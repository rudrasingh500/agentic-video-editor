"""
Asset processing module for extracting metadata from media files.

This module provides background job processing for analyzing uploaded
media assets (images, videos, audio) using Gemini 3 Flash via OpenRouter.

Usage:
    from agent.asset_processing import process_asset

    # Enqueue the job
    rq_queue.enqueue(process_asset, asset_id, project_id)
"""

from .processor import process_asset
from .analyzers import (
    extract_metadata,
    analyze_image,
    analyze_video,
    analyze_audio,
    IMAGE_TYPES,
    VIDEO_TYPES,
    AUDIO_TYPES,
)
from .prompts import (
    IMAGE_ANALYSIS_PROMPT,
    VIDEO_ANALYSIS_PROMPT,
    AUDIO_ANALYSIS_PROMPT,
)

__all__ = [
    # Main job function
    "process_asset",
    # Analyzers
    "extract_metadata",
    "analyze_image",
    "analyze_video",
    "analyze_audio",
    # MIME type sets
    "IMAGE_TYPES",
    "VIDEO_TYPES",
    "AUDIO_TYPES",
    # Prompts (for customization/testing)
    "IMAGE_ANALYSIS_PROMPT",
    "VIDEO_ANALYSIS_PROMPT",
    "AUDIO_ANALYSIS_PROMPT",
]
