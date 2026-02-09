import base64
import json
import logging
import os
from typing import Any

from openai import APIStatusError, OpenAI
from utils.video_utils import get_video_duration

from .prompts import (
    AUDIO_ANALYSIS_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    VIDEO_ANALYSIS_PROMPT,
)

MODEL = "google/gemini-3-flash-preview"
logger = logging.getLogger(__name__)

MAX_INLINE_MEDIA_BYTES = int(os.getenv("OPENROUTER_MAX_INLINE_MEDIA_BYTES", "8000000"))

REASONING_CONFIG = {
    "reasoning": {
        "effort": "high",
    }
}

IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
}

VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
}

AUDIO_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "audio/mp4",
    "audio/aac",
    "audio/flac",
}


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


def extract_metadata(
    content: bytes,
    content_type: str,
    source_url: str | None = None,
) -> dict | None:
    if content_type in IMAGE_TYPES:
        return analyze_image(content, content_type, source_url=source_url)
    elif content_type in VIDEO_TYPES:
        return analyze_video(content, content_type, source_url=source_url)
    elif content_type in AUDIO_TYPES:
        return analyze_audio(content, content_type, source_url=source_url)
    return None


def analyze_image(content: bytes, content_type: str, source_url: str | None = None) -> dict:
    media_part = _build_media_part("image_url", content, content_type, source_url)
    if media_part is None:
        logger.warning(
            "Image analysis skipped: payload too large for inline upload and no source URL"
        )
        return _fallback_image_metadata()

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        media_part,
                        {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            extra_body=REASONING_CONFIG,
        )
    except Exception as exc:
        if _is_payload_too_large_error(exc):
            logger.warning(
                "Image analysis request exceeded gateway payload limit (413). "
                "Using fallback metadata."
            )
        else:
            logger.warning(
                "Image analysis failed (%s). Using fallback metadata.",
                f"{type(exc).__name__}: {exc}",
            )
        return _fallback_image_metadata()

    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Image analysis returned no JSON payload; using fallback metadata")
    return _fallback_image_metadata()


def analyze_video(content: bytes, content_type: str, source_url: str | None = None) -> dict:
    media_part = _build_media_part("video_url", content, content_type, source_url)
    if media_part is None:
        logger.warning(
            "Video analysis skipped: payload too large for inline upload and no source URL"
        )
        return _fallback_video_metadata(content, content_type)

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        media_part,
                        {"type": "text", "text": VIDEO_ANALYSIS_PROMPT},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            extra_body=REASONING_CONFIG,
        )
    except Exception as exc:
        if _is_payload_too_large_error(exc):
            logger.warning(
                "Video analysis request exceeded gateway payload limit (413). "
                "Using fallback metadata."
            )
        else:
            logger.warning(
                "Video analysis failed (%s). Using fallback metadata.",
                f"{type(exc).__name__}: {exc}",
            )
        return _fallback_video_metadata(content, content_type)

    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Video analysis returned no JSON payload; using fallback metadata")
    return _fallback_video_metadata(content, content_type)


def analyze_audio(content: bytes, content_type: str, source_url: str | None = None) -> dict:
    media_part = _build_media_part("audio_url", content, content_type, source_url)
    if media_part is None:
        logger.warning(
            "Audio analysis skipped: payload too large for inline upload and no source URL"
        )
        return _fallback_audio_metadata()

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        media_part,
                        {"type": "text", "text": AUDIO_ANALYSIS_PROMPT},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            extra_body=REASONING_CONFIG,
        )
    except Exception as exc:
        if _is_payload_too_large_error(exc):
            logger.warning(
                "Audio analysis request exceeded gateway payload limit (413). "
                "Using fallback metadata."
            )
        else:
            logger.warning(
                "Audio analysis failed (%s). Using fallback metadata.",
                f"{type(exc).__name__}: {exc}",
            )
        return _fallback_audio_metadata()

    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Audio analysis returned no JSON payload; using fallback metadata")
    return _fallback_audio_metadata()


def _build_media_part(
    media_field: str,
    content: bytes,
    content_type: str,
    source_url: str | None,
) -> dict[str, Any] | None:
    if source_url:
        return {
            "type": media_field,
            media_field: {"url": source_url},
        }

    if len(content) > MAX_INLINE_MEDIA_BYTES:
        return None

    b64 = base64.b64encode(content).decode("utf-8")
    return {
        "type": media_field,
        media_field: {"url": f"data:{content_type};base64,{b64}"},
    }


def _is_payload_too_large_error(exc: Exception) -> bool:
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        if status_code == 413:
            return True

    text = str(exc).lower()
    return "413" in text and "payload" in text and "large" in text


def _extract_response_json(response: Any) -> dict | None:
    if response is None:
        return None

    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        parsed = _parse_json_content(content)
        if parsed is not None:
            return parsed

    data: dict[str, Any] | None = None
    if hasattr(response, "model_dump"):
        maybe = response.model_dump()
        if isinstance(maybe, dict):
            data = maybe
    elif isinstance(response, dict):
        data = response

    if not data:
        return None

    raw_choices = data.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        return None

    message = raw_choices[0].get("message") if isinstance(raw_choices[0], dict) else None
    if not isinstance(message, dict):
        return None

    return _parse_json_content(message.get("content"))


def _parse_json_content(content: Any) -> dict | None:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                continue

            item_type = getattr(item, "type", None)
            item_text = getattr(item, "text", None)
            if item_type == "text" and isinstance(item_text, str):
                text_parts.append(item_text)

        if text_parts:
            text = "\n".join(part for part in text_parts if part).strip()
            if not text:
                return None
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return None

    return None


def _fallback_image_metadata() -> dict:
    return {
        "summary": "Image uploaded. Automated semantic analysis is temporarily unavailable.",
        "tags": ["image", "analysis-fallback"],
        "transcript": [],
        "events": [],
        "notable_shots": [],
        "faces": [],
        "objects": [],
        "scenes": [],
        "audio_features": {},
        "audio_structure": {},
        "colors": [],
        "technical": {"analysis_fallback": True},
    }


def _fallback_video_metadata(content: bytes, content_type: str) -> dict:
    duration_seconds = get_video_duration(content, content_type)
    return {
        "summary": "Video uploaded. Automated semantic analysis is temporarily unavailable.",
        "tags": ["video", "analysis-fallback"],
        "transcript": [],
        "events": [],
        "notable_shots": [],
        "faces": [],
        "objects": [],
        "scenes": [],
        "audio_features": {},
        "audio_structure": {},
        "colors": [],
        "technical": {
            "analysis_fallback": True,
            "duration_seconds": duration_seconds,
        },
    }


def _fallback_audio_metadata() -> dict:
    return {
        "summary": "Audio uploaded. Automated semantic analysis is temporarily unavailable.",
        "tags": ["audio", "analysis-fallback"],
        "transcript": [],
        "events": [],
        "notable_shots": [],
        "faces": [],
        "objects": [],
        "scenes": [],
        "audio_features": {},
        "audio_structure": {},
        "colors": [],
        "technical": {"analysis_fallback": True},
    }
