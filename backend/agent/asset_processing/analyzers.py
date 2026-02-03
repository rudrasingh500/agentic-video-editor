import base64
import base64
import json
import os

from openai import OpenAI

from .prompts import (
    AUDIO_ANALYSIS_PROMPT,
    IMAGE_ANALYSIS_PROMPT,
    VIDEO_ANALYSIS_PROMPT,
)

MODEL = "google/gemini-3-flash-preview"

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
    return json.loads(response.choices[0].message.content)


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
    return json.loads(response.choices[0].message.content)


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
    return json.loads(response.choices[0].message.content)
