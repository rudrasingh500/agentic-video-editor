from __future__ import annotations

import base64
import logging
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = os.getenv("NANO_BANANA_MODEL", "google/gemini-3-pro-image-preview")


@dataclass
class NanoBananaImageResult:
    image_bytes: bytes
    content_type: str
    model: str
    prompt: str
    response_text: str | None = None


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def generate_image(
    prompt: str,
    reference_image_bytes: bytes | None = None,
    reference_content_type: str | None = None,
    reference_images: list[dict[str, Any]] | None = None,
    model: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> NanoBananaImageResult:
    if not prompt.strip():
        raise ValueError("Prompt is required")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt.strip()}]

    normalized_reference_images: list[tuple[bytes, str]] = []
    if reference_images:
        for entry in reference_images:
            if not isinstance(entry, dict):
                continue
            image_bytes = entry.get("image_bytes")
            if not isinstance(image_bytes, (bytes, bytearray)):
                continue
            mime = str(entry.get("content_type") or "image/png")
            normalized_reference_images.append((bytes(image_bytes), mime))

    if not normalized_reference_images and reference_image_bytes:
        normalized_reference_images.append(
            (reference_image_bytes, reference_content_type or "image/png")
        )

    for image_bytes, mime in normalized_reference_images:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
            }
        )

    request_payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "stream": False,
    }

    params = parameters or {}
    extra_body_payload: dict[str, Any] = {}

    image_config = params.get("image_config")
    if isinstance(image_config, dict) and image_config:
        extra_body_payload["image_config"] = image_config

    extra_body = params.get("extra_body")
    if isinstance(extra_body, dict) and extra_body:
        extra_body_payload.update(extra_body)

    if extra_body_payload:
        request_payload["extra_body"] = extra_body_payload

    client = _get_client()
    response = client.chat.completions.create(**request_payload)

    image_url = _extract_generated_image_url(response)
    if not image_url:
        raise RuntimeError("Nano Banana response did not include an image")

    image_bytes, content_type = _decode_image_payload(image_url)
    response_text = _extract_response_text(response)
    return NanoBananaImageResult(
        image_bytes=image_bytes,
        content_type=content_type,
        model=request_payload["model"],
        prompt=prompt.strip(),
        response_text=response_text,
    )


def _extract_generated_image_url(response: Any) -> str | None:
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        images = getattr(message, "images", None)
        if images:
            url = _extract_url_from_images(images)
            if url:
                return url

    if hasattr(response, "model_dump"):
        data = response.model_dump()
    elif isinstance(response, dict):
        data = response
    else:
        data = {}

    raw_choices = data.get("choices") or []
    if not raw_choices:
        return None
    message = raw_choices[0].get("message") or {}
    return _extract_url_from_images(message.get("images") or [])


def _extract_url_from_images(images: list[Any]) -> str | None:
    for image in images:
        if isinstance(image, dict):
            image_url = image.get("image_url") or image.get("imageUrl") or {}
            url = image_url.get("url")
            if url:
                return str(url)
            if image.get("url"):
                return str(image["url"])
            continue

        image_url_obj = getattr(image, "image_url", None) or getattr(image, "imageUrl", None)
        if image_url_obj is not None:
            maybe_url = getattr(image_url_obj, "url", None)
            if maybe_url:
                return str(maybe_url)

        maybe_url = getattr(image, "url", None)
        if maybe_url:
            return str(maybe_url)

    return None


def _extract_response_text(response: Any) -> str | None:
    choices = getattr(response, "choices", None)
    if choices:
        content = getattr(choices[0].message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = "\n".join([p for p in parts if p]).strip()
            return text or None
    return None


def _decode_image_payload(image_url: str) -> tuple[bytes, str]:
    if image_url.startswith("data:"):
        header, _, data = image_url.partition(",")
        if not data:
            raise RuntimeError("Invalid data URL from Nano Banana")
        content_type = "image/png"
        if ";" in header:
            content_type = header[5:].split(";", 1)[0] or content_type
        return base64.b64decode(data), content_type

    if image_url.startswith("http://") or image_url.startswith("https://"):
        with urllib.request.urlopen(image_url, timeout=90) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type", "image/png")
            return payload, content_type

    raise RuntimeError("Unsupported Nano Banana image payload format")
