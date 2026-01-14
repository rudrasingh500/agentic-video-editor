"""
Asset retrieval agent for finding timestamp-addressable content.

This module provides an agent that searches indexed asset metadata
to find video, audio, and image segments matching a natural language query.

Usage:
    from agent.asset_retrieval import find_assets

    result = find_assets(
        project_id="uuid-here",
        query="Find clips of John discussing quarterly results",
        db=db_session,
    )

    for candidate in result.candidates:
        print(f"{candidate.media_id}: {candidate.t0}ms - {candidate.t1}ms (score: {candidate.score})")
"""

from .agent import find_assets
from .types import AssetCandidate, RetrievalResult

__all__ = [
    "find_assets",
    "AssetCandidate",
    "RetrievalResult",
]
