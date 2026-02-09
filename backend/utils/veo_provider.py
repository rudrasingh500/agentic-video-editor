from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


GOOGLE_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_VEO_MODEL = os.getenv("VEO_MODEL", "veo-3.1-generate-preview")
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("VEO_GENERATION_TIMEOUT_SECONDS", "900"))
DEFAULT_POLL_INTERVAL_SECONDS = float(os.getenv("VEO_POLL_INTERVAL_SECONDS", "10"))


@dataclass
class VeoVideoResult:
    video_bytes: bytes
    content_type: str
    model: str
    prompt: str
    operation_name: str
    source_uri: str
    metadata: dict[str, Any]


def generate_video(
    prompt: str,
    reference_image_bytes: bytes | None = None,
    reference_content_type: str | None = None,
    model: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> VeoVideoResult:
    if not prompt.strip():
        raise ValueError("Prompt is required")

    selected_model = _normalize_model_name(model or DEFAULT_VEO_MODEL)
    params = dict(parameters or {})

    request_parameters = _build_request_parameters(params)
    timeout_seconds = _coerce_positive_int(
        params.get("timeout_seconds"),
        default_value=DEFAULT_TIMEOUT_SECONDS,
    )
    poll_interval_seconds = _coerce_positive_float(
        params.get("poll_interval_seconds"),
        default_value=DEFAULT_POLL_INTERVAL_SECONDS,
    )

    instance: dict[str, Any] = {
        "prompt": prompt.strip(),
    }
    if reference_image_bytes is not None:
        mime_type = reference_content_type or "image/png"
        instance["image"] = {
            "inlineData": {
                "mimeType": mime_type,
                "data": base64.b64encode(reference_image_bytes).decode("utf-8"),
            }
        }

    request_body: dict[str, Any] = {
        "instances": [instance],
    }
    if request_parameters:
        request_body["parameters"] = request_parameters

    operation = _request_json(
        method="POST",
        url=f"{GOOGLE_API_BASE_URL}/models/{selected_model}:predictLongRunning",
        payload=request_body,
    )
    operation_name = str(operation.get("name") or "")
    if not operation_name:
        raise RuntimeError("Veo did not return a long-running operation name")

    operation_result = _poll_operation(
        operation_name=operation_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    if operation_result.get("error"):
        raise RuntimeError(_format_google_error(operation_result["error"]))

    video_uri = _extract_video_uri(operation_result)
    if not video_uri:
        raise RuntimeError("Veo completed but did not return a generated video URI")

    video_bytes, content_type = _download_generated_video(video_uri)
    metadata = {
        "operation_name": operation_name,
        "source_uri": video_uri,
        "poll_interval_seconds": poll_interval_seconds,
        "timeout_seconds": timeout_seconds,
    }
    if request_parameters:
        metadata["request_parameters"] = request_parameters

    return VeoVideoResult(
        video_bytes=video_bytes,
        content_type=content_type,
        model=selected_model,
        prompt=prompt.strip(),
        operation_name=operation_name,
        source_uri=video_uri,
        metadata=metadata,
    )


def _poll_operation(
    operation_name: str,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    started_at = time.monotonic()
    operation_path = urllib.parse.quote(operation_name, safe="/")
    operation_url = f"{GOOGLE_API_BASE_URL}/{operation_path}"

    while True:
        operation_result = _request_json(method="GET", url=operation_url)
        if operation_result.get("done"):
            return operation_result

        if time.monotonic() - started_at >= timeout_seconds:
            raise TimeoutError(
                f"Timed out waiting for Veo generation after {timeout_seconds}s"
            )

        time.sleep(poll_interval_seconds)


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url=url, data=data, method=method.upper())
    request.add_header("x-goog-api-key", _google_api_key())
    if payload is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
            raise RuntimeError("Unexpected non-object response from Veo API")
    except urllib.error.HTTPError as exc:
        details = ""
        try:
            details = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            details = ""
        raise RuntimeError(
            f"Veo request failed ({exc.code}): {details[:500]}"
        ) from exc


def _download_generated_video(video_uri: str) -> tuple[bytes, str]:
    request = urllib.request.Request(video_uri, method="GET")
    request.add_header("x-goog-api-key", _google_api_key())
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "video/mp4")
        return payload, content_type.split(";", 1)[0].strip() or "video/mp4"


def _extract_video_uri(operation_result: dict[str, Any]) -> str | None:
    response = operation_result.get("response") or {}
    if not isinstance(response, dict):
        return None

    uri = _dig_first_uri(response, ["generateVideoResponse", "generatedSamples", 0, "video", "uri"])
    if uri:
        return uri

    uri = _dig_first_uri(response, ["generatedVideos", 0, "video", "uri"])
    if uri:
        return uri

    uri = _dig_first_uri(response, ["generated_videos", 0, "video", "uri"])
    if uri:
        return uri

    return None


def _dig_first_uri(payload: Any, path: list[Any]) -> str | None:
    current = payload
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(current, list) or len(current) <= segment:
                return None
            current = current[segment]
            continue

        if not isinstance(current, dict):
            return None
        current = current.get(segment)

    if isinstance(current, str) and current:
        return current
    return None


def _build_request_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "aspect_ratio": "aspectRatio",
        "resolution": "resolution",
        "negative_prompt": "negativePrompt",
        "number_of_videos": "numberOfVideos",
        "person_generation": "personGeneration",
    }

    result: dict[str, Any] = {}
    for source_key, target_key in mapping.items():
        value = parameters.get(source_key)
        if value is None:
            value = parameters.get(target_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        result[target_key] = value

    if "numberOfVideos" in result:
        try:
            number_of_videos = int(result["numberOfVideos"])
        except (TypeError, ValueError):
            raise ValueError("number_of_videos must be an integer")
        if number_of_videos < 1:
            raise ValueError("number_of_videos must be >= 1")
        result["numberOfVideos"] = number_of_videos

    return result


def _google_api_key() -> str:
    raw_key = os.getenv("GOOGLE_API_KEY", "")
    key = raw_key.strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    return key


def _normalize_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if normalized.startswith("models/"):
        normalized = normalized.split("/", 1)[1]
    if not normalized:
        raise ValueError("Veo model name is required")
    return normalized


def _coerce_positive_int(value: Any, default_value: int) -> int:
    if value is None:
        return default_value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default_value
    if parsed <= 0:
        return default_value
    return parsed


def _coerce_positive_float(value: Any, default_value: float) -> float:
    if value is None:
        return default_value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default_value
    if parsed <= 0:
        return default_value
    return parsed


def _format_google_error(error_payload: Any) -> str:
    if not isinstance(error_payload, dict):
        return "Veo generation failed"
    message = error_payload.get("message")
    status = error_payload.get("status")
    code = error_payload.get("code")
    if message and status and code is not None:
        return f"Veo generation failed ({status} {code}): {message}"
    if message:
        return f"Veo generation failed: {message}"
    return "Veo generation failed"
