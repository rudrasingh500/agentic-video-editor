import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


def get_embedding(text: str) -> list[float] | None:
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
    return get_embedding(query)


def build_embedding_text(summary: str, tags: list[str] | None) -> str:
    parts = []

    if summary:
        parts.append(f"Summary: {summary}")

    if tags:
        tags_str = ", ".join(tags)
        parts.append(f"Tags: {tags_str}")

    return "\n".join(parts)
