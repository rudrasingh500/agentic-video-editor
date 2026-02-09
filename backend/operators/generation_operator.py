from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from database.models import (
    AssetGeneration,
    Assets,
    CharacterModel,
    CharacterModelSnippetLink,
    Snippet,
    SnippetIdentity,
    SnippetIdentityLink,
)
from operators.asset_operator import upload_asset
from operators.snippet_operator import attach_generation_anchor
from utils.frame_editing import apply_frame_edit
from utils.gcs_utils import download_file, generate_signed_url
from utils.nano_banana_provider import (
    DEFAULT_MODEL as DEFAULT_NANO_BANANA_MODEL,
    generate_image,
)
from utils.veo_provider import DEFAULT_VEO_MODEL, generate_video


ASSET_BUCKET = "video-editor"


def create_generation(
    db: Session,
    project_id: UUID,
    prompt: str,
    mode: str,
    requestor: str,
    request_origin: str = "user",
    timeline_id: UUID | None = None,
    target_asset_id: UUID | None = None,
    frame_range: dict | None = None,
    frame_indices: list[int] | None = None,
    frame_repeat_count: int | None = None,
    reference_asset_id: UUID | None = None,
    reference_snippet_id: UUID | None = None,
    reference_identity_id: UUID | None = None,
    reference_character_model_id: UUID | None = None,
    model: str | None = None,
    parameters: dict | None = None,
    request_context: dict | None = None,
) -> AssetGeneration:
    normalized_mode = str(mode or "image").strip().lower()
    if normalized_mode not in {"image", "video", "insert_frames", "replace_frames"}:
        raise ValueError(f"Unsupported generation mode: {mode}")

    normalized_frame_range, normalized_frame_indices = _normalize_frame_inputs(
        mode=normalized_mode,
        frame_range=frame_range,
        frame_indices=frame_indices,
    )
    normalized_frame_repeat_count = _normalize_frame_repeat_count(
        mode=normalized_mode,
        frame_repeat_count=frame_repeat_count,
    )

    if normalized_mode in {"insert_frames", "replace_frames"} and not target_asset_id:
        raise ValueError("target_asset_id is required for frame operations")

    if normalized_mode in {"insert_frames", "replace_frames"} and target_asset_id:
        target_asset = _get_asset(db, project_id, target_asset_id)
        if not target_asset:
            raise ValueError("target_asset_id not found")
        if not str(target_asset.asset_type or "").startswith("video/"):
            raise ValueError("target_asset_id must reference a video asset")

    reference = _resolve_reference_image(
        db=db,
        project_id=project_id,
        reference_asset_id=reference_asset_id,
        reference_snippet_id=reference_snippet_id,
        reference_identity_id=reference_identity_id,
        reference_character_model_id=reference_character_model_id,
    )

    generation_parameters = dict(parameters or {})
    if normalized_frame_repeat_count is not None:
        generation_parameters["frame_repeat_count"] = normalized_frame_repeat_count

    if normalized_mode == "video":
        reference_hint = _build_reference_prompt_hint(reference)
        if reference_hint:
            generation_parameters["reference_prompt_hint"] = reference_hint

        try:
            generation_result = generate_video(
                prompt=prompt,
                reference_image_bytes=reference.get("image_bytes"),
                reference_content_type=reference.get("content_type"),
                model=model,
                parameters=generation_parameters,
            )
        except RuntimeError as exc:
            if not _is_veo_reference_unsupported_error(exc) or reference.get("image_bytes") is None:
                raise

            fallback_prompt = _augment_video_prompt_with_reference_hint(
                base_prompt=prompt,
                reference_hint=reference_hint,
            )
            generation_result = generate_video(
                prompt=fallback_prompt,
                reference_image_bytes=None,
                reference_content_type=None,
                model=model,
                parameters=generation_parameters,
            )
            generation_parameters["veo_reference_mode"] = "prompt_hint_fallback"

        generated_content = generation_result.video_bytes
        generated_content_type = generation_result.content_type
        resolved_model = generation_result.model or model or DEFAULT_VEO_MODEL
        provider = "google"

        metadata = dict(generation_parameters.get("veo_metadata") or {})
        metadata.update(generation_result.metadata or {})
        generation_parameters["veo_metadata"] = metadata
    else:
        generation_result = generate_image(
            prompt=prompt,
            reference_image_bytes=reference.get("image_bytes"),
            reference_content_type=reference.get("content_type"),
            model=model,
            parameters=generation_parameters,
        )
        generated_content = generation_result.image_bytes
        generated_content_type = generation_result.content_type
        resolved_model = generation_result.model or model or DEFAULT_NANO_BANANA_MODEL
        provider = "openrouter"

    generated_asset = upload_asset(
        db=db,
        project_id=project_id,
        asset_name=_build_generated_asset_name(normalized_mode, generated_content_type),
        content=generated_content,
        content_type=generated_content_type,
    )

    generation = AssetGeneration(
        project_id=project_id,
        timeline_id=timeline_id,
        request_origin=request_origin,
        requestor=requestor,
        provider=provider,
        model=resolved_model,
        mode=normalized_mode,
        status="pending",
        prompt=prompt,
        parameters=generation_parameters,
        reference_asset_id=reference.get("reference_asset_id"),
        reference_snippet_id=reference.get("reference_snippet_id"),
        reference_identity_id=reference.get("reference_identity_id"),
        reference_character_model_id=reference.get("reference_character_model_id"),
        target_asset_id=target_asset_id,
        frame_range=normalized_frame_range,
        frame_indices=normalized_frame_indices,
        generated_asset_id=generated_asset.asset_id,
        request_context=request_context or {},
    )
    db.add(generation)
    db.flush()

    _attach_snippet_anchor_if_needed(
        db=db,
        generation=generation,
        created_by=requestor,
    )

    db.commit()
    db.refresh(generation)
    return generation


def get_generation(
    db: Session,
    project_id: UUID,
    generation_id: UUID,
) -> AssetGeneration | None:
    return (
        db.query(AssetGeneration)
        .filter(
            AssetGeneration.project_id == project_id,
            AssetGeneration.generation_id == generation_id,
        )
        .first()
    )


def decide_generation(
    db: Session,
    project_id: UUID,
    generation_id: UUID,
    decision: str,
    decided_by: str,
    reason: str | None = None,
) -> AssetGeneration:
    generation = get_generation(db, project_id, generation_id)
    if not generation:
        raise ValueError("Generation not found")

    normalized_decision = str(decision).strip().lower()
    if normalized_decision not in {"approve", "deny"}:
        raise ValueError("decision must be either 'approve' or 'deny'")

    if generation.status in {"denied", "applied"}:
        return generation

    now = datetime.now(timezone.utc)
    generation.decision_reason = reason
    generation.decided_at = now
    decision_context = dict(generation.request_context or {})
    decision_context["decided_by"] = decided_by
    decision_context["decision"] = normalized_decision
    generation.request_context = decision_context

    if normalized_decision == "deny":
        generation.status = "denied"
        generation.updated_at = now
        db.commit()
        db.refresh(generation)
        return generation

    generation.status = "approved"
    generation.updated_at = now

    if generation.mode in {"insert_frames", "replace_frames"}:
        try:
            applied_asset = _apply_frame_generation(db, generation)
            generation.applied_asset_id = applied_asset.asset_id
            generation.applied_at = datetime.now(timezone.utc)
            generation.status = "applied"
        except Exception as exc:
            generation.status = "failed"
            generation.error_message = str(exc)

    db.commit()
    db.refresh(generation)
    return generation


def get_generation_assets(
    db: Session,
    generation: AssetGeneration,
) -> tuple[Assets | None, Assets | None]:
    generated_asset = None
    if generation.generated_asset_id:
        generated_asset = (
            db.query(Assets)
            .filter(
                Assets.project_id == generation.project_id,
                Assets.asset_id == generation.generated_asset_id,
            )
            .first()
        )

    applied_asset = None
    if generation.applied_asset_id:
        applied_asset = (
            db.query(Assets)
            .filter(
                Assets.project_id == generation.project_id,
                Assets.asset_id == generation.applied_asset_id,
            )
            .first()
        )

    return generated_asset, applied_asset


def get_asset_preview_url(asset: Assets | None) -> str | None:
    if not asset or not asset.asset_url:
        return None
    return generate_signed_url(_asset_bucket(), asset.asset_url)


def _apply_frame_generation(db: Session, generation: AssetGeneration) -> Assets:
    if not generation.target_asset_id:
        raise ValueError("Generation target asset is missing")
    if not generation.generated_asset_id:
        raise ValueError("Generation output asset is missing")

    target_asset = (
        db.query(Assets)
        .filter(
            Assets.project_id == generation.project_id,
            Assets.asset_id == generation.target_asset_id,
        )
        .first()
    )
    if not target_asset:
        raise ValueError("Target video asset not found")

    generated_asset = (
        db.query(Assets)
        .filter(
            Assets.project_id == generation.project_id,
            Assets.asset_id == generation.generated_asset_id,
        )
        .first()
    )
    if not generated_asset:
        raise ValueError("Generated frame asset not found")

    target_bytes = download_file(_asset_bucket(), target_asset.asset_url)
    if not target_bytes:
        raise RuntimeError("Failed to load target video bytes")
    generated_bytes = download_file(_asset_bucket(), generated_asset.asset_url)
    if not generated_bytes:
        raise RuntimeError("Failed to load generated frame bytes")

    edited_bytes, edited_content_type, metadata = apply_frame_edit(
        target_video_bytes=target_bytes,
        target_content_type=target_asset.asset_type,
        generated_frame_bytes=generated_bytes,
        mode=str(generation.mode),
        frame_range=generation.frame_range,
        frame_indices=generation.frame_indices,
        frame_repeat_count=_extract_frame_repeat_count(generation.parameters),
    )

    applied_asset_name = _build_applied_video_asset_name(
        target_asset.asset_name,
        str(generation.mode),
    )
    applied_asset = upload_asset(
        db=db,
        project_id=generation.project_id,
        asset_name=applied_asset_name,
        content=edited_bytes,
        content_type=edited_content_type,
    )

    params = dict(generation.parameters or {})
    params["frame_edit_result"] = metadata
    generation.parameters = params
    return applied_asset


def _normalize_frame_inputs(
    mode: str,
    frame_range: dict | None,
    frame_indices: list[int] | None,
) -> tuple[dict | None, list[int] | None]:
    if mode in {"image", "video"}:
        return None, None

    normalized_range = None
    if frame_range is not None:
        start = int(frame_range.get("start_frame", 0))
        end = int(frame_range.get("end_frame", start))
        if start < 0 or end < 0:
            raise ValueError("frame_range values must be >= 0")
        if end < start:
            start, end = end, start
        normalized_range = {"start_frame": start, "end_frame": end}

    normalized_indices = None
    if frame_indices:
        cleaned = sorted({int(value) for value in frame_indices if int(value) >= 0})
        normalized_indices = cleaned or None

    if normalized_range is None and normalized_indices is None:
        raise ValueError("Frame operations require frame_range or frame_indices")

    return normalized_range, normalized_indices


def _normalize_frame_repeat_count(
    mode: str,
    frame_repeat_count: int | None,
) -> int | None:
    if mode in {"image", "video"}:
        return None

    if frame_repeat_count is None:
        return 1

    normalized = int(frame_repeat_count)
    if normalized < 1:
        raise ValueError("frame_repeat_count must be >= 1")
    if normalized > 600:
        raise ValueError("frame_repeat_count is too large")
    return normalized


def _extract_frame_repeat_count(parameters: dict | None) -> int:
    if not parameters:
        return 1
    value = parameters.get("frame_repeat_count")
    if value is None:
        return 1
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return parsed if parsed >= 1 else 1


def _is_veo_reference_unsupported_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "inlinedata" in message and "isn't supported" in message
    ) or (
        "referenceimages" in message and "isn't supported" in message
    )


def _build_reference_prompt_hint(reference: dict) -> str | None:
    value = reference.get("prompt_hint")
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _augment_video_prompt_with_reference_hint(
    base_prompt: str,
    reference_hint: str | None,
) -> str:
    base = base_prompt.strip()
    if not reference_hint:
        return base
    return (
        f"{base}\n\n"
        "Match the same primary subject identity as the selected reference snippet.\n"
        f"Reference details: {reference_hint}"
    )


def _resolve_reference_image(
    db: Session,
    project_id: UUID,
    reference_asset_id: UUID | None,
    reference_snippet_id: UUID | None,
    reference_identity_id: UUID | None,
    reference_character_model_id: UUID | None,
) -> dict:
    selectors = [
        reference_asset_id,
        reference_snippet_id,
        reference_identity_id,
        reference_character_model_id,
    ]
    selector_count = len([value for value in selectors if value is not None])
    if selector_count > 1:
        raise ValueError(
            "Provide only one reference input: asset, snippet, identity, or character model"
        )

    if reference_snippet_id:
        snippet = _get_snippet(db, project_id, reference_snippet_id)
        if not snippet:
            raise ValueError("reference_snippet_id not found")
        image_bytes, image_content_type = _download_snippet_preview(snippet)
        if image_bytes is None:
            raise ValueError("Snippet has no preview image")
        return {
            "image_bytes": image_bytes,
            "content_type": image_content_type,
            "reference_snippet_id": snippet.snippet_id,
            "prompt_hint": _snippet_to_prompt_hint(snippet),
        }

    if reference_identity_id:
        identity = _get_identity(db, project_id, reference_identity_id)
        if not identity:
            raise ValueError("reference_identity_id not found")
        snippet = _resolve_identity_snippet(db, project_id, identity)
        if not snippet:
            raise ValueError("No snippet available for reference identity")
        image_bytes, image_content_type = _download_snippet_preview(snippet)
        if image_bytes is None:
            raise ValueError("Identity snippet has no preview image")
        return {
            "image_bytes": image_bytes,
            "content_type": image_content_type,
            "reference_snippet_id": snippet.snippet_id,
            "reference_identity_id": identity.identity_id,
            "prompt_hint": _snippet_to_prompt_hint(snippet),
        }

    if reference_character_model_id:
        character_model = _get_character_model(db, project_id, reference_character_model_id)
        if not character_model:
            raise ValueError("reference_character_model_id not found")
        snippet = _resolve_character_model_snippet(db, project_id, character_model)
        if not snippet:
            raise ValueError("No snippet available for reference character model")
        image_bytes, image_content_type = _download_snippet_preview(snippet)
        if image_bytes is None:
            raise ValueError("Character model snippet has no preview image")
        return {
            "image_bytes": image_bytes,
            "content_type": image_content_type,
            "reference_snippet_id": snippet.snippet_id,
            "reference_character_model_id": character_model.character_model_id,
            "prompt_hint": _snippet_to_prompt_hint(snippet),
        }

    if reference_asset_id:
        asset = _get_asset(db, project_id, reference_asset_id)
        if not asset:
            raise ValueError("reference_asset_id not found")
        if not str(asset.asset_type or "").startswith("image/"):
            raise ValueError("reference_asset_id must point to an image asset")
        image_bytes = download_file(_asset_bucket(), asset.asset_url)
        if image_bytes is None:
            raise RuntimeError("Failed to read reference asset")
        return {
            "image_bytes": image_bytes,
            "content_type": asset.asset_type,
            "reference_asset_id": asset.asset_id,
            "prompt_hint": None,
        }

    return {
        "image_bytes": None,
        "content_type": None,
        "prompt_hint": None,
    }


def _snippet_to_prompt_hint(snippet: Snippet) -> str | None:
    parts: list[str] = []
    if snippet.descriptor:
        text = str(snippet.descriptor).strip()
        if text:
            parts.append(text)
    if snippet.notes:
        text = str(snippet.notes).strip()
        if text:
            parts.append(text)
    if isinstance(snippet.tags, list) and snippet.tags:
        tags = [str(tag).strip() for tag in snippet.tags if str(tag).strip()]
        if tags:
            parts.append(f"tags: {', '.join(tags[:8])}")

    if not parts:
        return None
    return "; ".join(parts)


def _download_snippet_preview(snippet: Snippet) -> tuple[bytes | None, str]:
    blob = snippet.preview_blob_path or snippet.crop_blob_path
    if not blob:
        return None, "image/jpeg"
    payload = download_file(_asset_bucket(), blob)
    if payload is None:
        return None, "image/jpeg"
    guessed = mimetypes.guess_type(blob)[0] or "image/jpeg"
    return payload, guessed


def _resolve_identity_snippet(
    db: Session,
    project_id: UUID,
    identity: SnippetIdentity,
) -> Snippet | None:
    if identity.canonical_snippet_id:
        return _get_snippet(db, project_id, identity.canonical_snippet_id)

    link = (
        db.query(SnippetIdentityLink)
        .filter(
            SnippetIdentityLink.project_id == project_id,
            SnippetIdentityLink.identity_id == identity.identity_id,
            SnippetIdentityLink.status == "active",
        )
        .order_by(SnippetIdentityLink.is_primary.desc(), SnippetIdentityLink.confidence.desc().nullslast())
        .first()
    )
    if not link:
        return None
    return _get_snippet(db, project_id, link.snippet_id)


def _resolve_character_model_snippet(
    db: Session,
    project_id: UUID,
    character_model: CharacterModel,
) -> Snippet | None:
    if character_model.canonical_snippet_id:
        return _get_snippet(db, project_id, character_model.canonical_snippet_id)

    link = (
        db.query(CharacterModelSnippetLink)
        .filter(CharacterModelSnippetLink.character_model_id == character_model.character_model_id)
        .order_by(CharacterModelSnippetLink.created_at.asc())
        .first()
    )
    if not link:
        return None
    return _get_snippet(db, project_id, link.snippet_id)


def _attach_snippet_anchor_if_needed(
    db: Session,
    generation: AssetGeneration,
    created_by: str,
) -> None:
    anchor_type = None
    snippet_id = None
    identity_id = None
    character_model_id = None

    if generation.reference_snippet_id:
        anchor_type = "snippet"
        snippet_id = generation.reference_snippet_id
    elif generation.reference_identity_id:
        anchor_type = "identity"
        identity_id = generation.reference_identity_id
    elif generation.reference_character_model_id:
        anchor_type = "character_model"
        character_model_id = generation.reference_character_model_id

    if not anchor_type:
        return

    request_context = {
        "generation_id": str(generation.generation_id),
        "mode": generation.mode,
        "prompt": generation.prompt,
        "provider": generation.provider,
        "model": generation.model,
    }
    attach_generation_anchor(
        db=db,
        project_id=generation.project_id,
        timeline_id=generation.timeline_id,
        anchor_type=anchor_type,
        snippet_id=snippet_id,
        identity_id=identity_id,
        character_model_id=character_model_id,
        request_context=request_context,
        created_by=created_by,
    )


def _build_generated_asset_name(mode: str, content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type or "") or ".png"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"generated_{mode}_{timestamp}{extension}"


def _build_applied_video_asset_name(target_name: str, mode: str) -> str:
    stem = target_name.rsplit(".", 1)[0] if "." in target_name else target_name
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{mode}_{timestamp}.mp4"


def _get_asset(db: Session, project_id: UUID, asset_id: UUID) -> Assets | None:
    return (
        db.query(Assets)
        .filter(
            Assets.project_id == project_id,
            Assets.asset_id == asset_id,
        )
        .first()
    )


def _get_snippet(db: Session, project_id: UUID, snippet_id: UUID) -> Snippet | None:
    return (
        db.query(Snippet)
        .filter(
            Snippet.project_id == project_id,
            Snippet.snippet_id == snippet_id,
        )
        .first()
    )


def _get_identity(
    db: Session,
    project_id: UUID,
    identity_id: UUID,
) -> SnippetIdentity | None:
    return (
        db.query(SnippetIdentity)
        .filter(
            SnippetIdentity.project_id == project_id,
            SnippetIdentity.identity_id == identity_id,
        )
        .first()
    )


def _get_character_model(
    db: Session,
    project_id: UUID,
    character_model_id: UUID,
) -> CharacterModel | None:
    return (
        db.query(CharacterModel)
        .filter(
            CharacterModel.project_id == project_id,
            CharacterModel.character_model_id == character_model_id,
        )
        .first()
    )


def _asset_bucket() -> str:
    from os import getenv

    return getenv("GCS_BUCKET", ASSET_BUCKET)
