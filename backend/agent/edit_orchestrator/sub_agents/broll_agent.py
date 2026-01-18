"""BrollAgent: Places b-roll, PiP, masks, and blur while maintaining dialogue continuity.

This is a STUB implementation. The actual agent will analyze the timeline
and assets to intelligently place supplementary footage.
"""

from .base import register_agent
from .types import (
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
)


@register_agent(SubAgentType.BROLL)
def broll_agent(request: SubAgentRequest) -> SubAgentResponse:
    """Process b-roll and overlay placement requests.

    Capabilities:
    - Place b-roll footage over primary content
    - Create picture-in-picture compositions
    - Apply masks and blur effects
    - Maintain dialogue/speaker continuity
    - Match b-roll to content context (semantic matching)
    - Handle cutaway timing for natural flow

    This is a STUB that returns a placeholder response.
    """

    return SubAgentResponse(
        request_id=request.request_id,
        success=True,
        agent_type=SubAgentType.BROLL,
        patch=EDLPatch(
            operations=[],
            preview_requests=[],
            metrics_needs=["scene_boundaries", "speaker_segments"],
            description=f"[STUB] BrollAgent would process: {request.intent}",
            estimated_duration_change_ms=0,
        ),
        reasoning=(
            f"[STUB] BrollAgent received request to: {request.intent}. "
            f"Has {len(request.assets)} asset candidates for b-roll placement. "
            "Would analyze timeline for appropriate cutaway points. "
            "This stub returns no operations - actual implementation pending."
        ),
        warnings=["This is a stub implementation - no actual edits will be made"],
    )
