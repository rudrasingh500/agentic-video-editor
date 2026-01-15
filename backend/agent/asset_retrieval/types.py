"""
Type definitions for the asset retrieval agent.

Defines the output schema for asset candidates returned by the agent.
"""

from pydantic import BaseModel, Field


class AssetCandidate(BaseModel):
    """A single asset candidate with timestamp information and relevance scoring."""

    media_id: str = Field(description="UUID of the asset")
    t0: int = Field(description="Start timestamp in milliseconds")
    t1: int = Field(description="End timestamp in milliseconds")
    score: int = Field(ge=0, le=100, description="Relevance score (0-100)")
    reasons: list[str] = Field(description="Reasons why this asset matched the query")
    tags: list[str] = Field(
        default_factory=list, description="Relevant tags from the asset"
    )
    transcript_snippet: str | None = Field(
        default=None, description="Relevant transcript excerpt if applicable"
    )
    face_ids: list[str] = Field(
        default_factory=list, description="IDs of matched faces in this segment"
    )
    speaker_ids: list[str] = Field(
        default_factory=list, description="IDs of matched speakers in this segment"
    )


class RetrievalResult(BaseModel):
    """Result from the asset retrieval agent."""

    candidates: list[AssetCandidate] = Field(
        default_factory=list,
        description="Up to 10 asset candidates ordered by relevance",
    )
    trace: list[dict] = Field(
        default_factory=list,
        description="Tool call history for debugging and observability",
    )
