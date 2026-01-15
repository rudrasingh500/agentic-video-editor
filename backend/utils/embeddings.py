"""
Embedding generation utilities for semantic search.

Uses OpenAI's text-embedding-3-small model via OpenRouter
to generate 1536-dimensional embeddings for asset content.
"""

import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def _get_client() -> OpenAI:
    """Get OpenAI client configured for OpenRouter."""
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


def get_embedding(text: str) -> list[float] | None:
    """
    Generate embedding vector for the given text.

    Args:
        text: The text to embed (max ~8000 tokens)

    Returns:
        List of 1536 floats representing the embedding vector,
        or None if embedding generation fails.
    """
    if not text or not text.strip():
        logger.warning("Empty text provided for embedding generation")
        return None

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set, skipping embedding generation")
        return None

    try:
        client = _get_client()
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text.strip(),
        )
        embedding = response.data[0].embedding

        if len(embedding) != EMBEDDING_DIMENSIONS:
            logger.warning(
                f"Unexpected embedding dimensions: {len(embedding)}, expected {EMBEDDING_DIMENSIONS}"
            )

        return embedding

    except Exception as e:
        logger.error(f"Failed to generate embedding: {type(e).__name__}: {e}")
        return None


def get_query_embedding(query: str) -> list[float] | None:
    """
    Generate embedding for a search query.

    This is a convenience wrapper around get_embedding for search queries.
    Uses the same model to ensure consistency between indexed content
    and search queries.

    Args:
        query: The natural language search query

    Returns:
        Embedding vector or None if generation fails.
    """
    return get_embedding(query)


def build_embedding_text(summary: str, tags: list[str] | None) -> str:
    """
    Build the text representation to embed for an asset.

    Combines the asset summary and tags into a single text string
    optimized for semantic search.

    Args:
        summary: The asset summary description
        tags: List of tags associated with the asset

    Returns:
        Formatted text string for embedding
    """
    parts = []

    if summary:
        parts.append(f"Summary: {summary}")

    if tags:
        tags_str = ", ".join(tags)
        parts.append(f"Tags: {tags_str}")

    return "\n".join(parts)
