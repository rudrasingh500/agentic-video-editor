import base64
import base64
import json
import logging
import os
from typing import Any

from openai import OpenAI
from utils.video_utils import get_video_duration

from .prompts import (
    AUDIO_ANALYSIS_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    VIDEO_ANALYSIS_PROMPT,
)

MODEL = "google/gemini-3-flash-preview"
logger = logging.getLogger(__name__)

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


def extract_metadata(content: bytes, content_type: str) -> dict | None:
    if content_type in IMAGE_TYPES:
        return analyze_image(content, content_type)
    elif content_type in VIDEO_TYPES:
        return analyze_video(content, content_type)
    elif content_type in AUDIO_TYPES:
        return analyze_audio(content, content_type)
    return None


def analyze_image(content: bytes, content_type: str) -> dict:
    b64 = base64.b64encode(content).decode("utf-8")

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{b64}"},
                    },
                    {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                ],
            }
        ],
        response_format={"type": "json_object"},
        extra_body=REASONING_CONFIG,
    )
    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Image analysis returned no JSON payload; using fallback metadata")
    return _fallback_image_metadata()


def analyze_video(content: bytes, content_type: str) -> dict:
    b64 = base64.b64encode(content).decode("utf-8")

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": f"data:{content_type};base64,{b64}"},
                    },
                    {"type": "text", "text": VIDEO_ANALYSIS_PROMPT},
                ],
            }
        ],
        response_format={"type": "json_object"},
        extra_body=REASONING_CONFIG,
    )
    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Video analysis returned no JSON payload; using fallback metadata")
    return _fallback_video_metadata(content, content_type)


def analyze_audio(content: bytes, content_type: str) -> dict:
    b64 = base64.b64encode(content).decode("utf-8")

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "audio_url",
                        "audio_url": {"url": f"data:{content_type};base64,{b64}"},
                    },
                    {"type": "text", "text": AUDIO_ANALYSIS_PROMPT},
                ],
            }
        ],
        response_format={"type": "json_object"},
        extra_body=REASONING_CONFIG,
    )
    parsed = _extract_response_json(response)
    if parsed is not None:
        return parsed
    logger.warning("Audio analysis returned no JSON payload; using fallback metadata")
    return _fallback_audio_metadata()


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
