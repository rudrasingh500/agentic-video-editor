"""MotionAgent: Handles stabilization, reframe autofollow, and crop/scale/position keyframes.

This is a STUB implementation. The actual agent will analyze footage motion
and apply appropriate corrections and reframing.
"""

from .base import register_agent
from .types import (
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
)


@register_agent(SubAgentType.MOTION)
def motion_agent(request: SubAgentRequest) -> SubAgentResponse:
    """Process motion and reframing requests.

    Capabilities:
    - Stabilize shaky footage
    - Auto-reframe for different aspect ratios
    - Track subjects and auto-follow
    - Create crop/scale/position keyframes
    - Smooth camera movements
    - Ken Burns effects on stills
    - Pan and scan automation

    This is a STUB that returns a placeholder response.
    """

    return SubAgentResponse(
        request_id=request.request_id,
        success=True,
        agent_type=SubAgentType.MOTION,
        patch=EDLPatch(
            operations=[],
            preview_requests=[],
            metrics_needs=["motion_vectors", "face_detection", "subject_tracking"],
            description=f"[STUB] MotionAgent would process: {request.intent}",
            estimated_duration_change_ms=0,
        ),
        reasoning=(
            f"[STUB] MotionAgent received request to: {request.intent}. "
            "Would analyze footage for motion and stabilization needs. "
            "This stub returns no operations - actual implementation pending."
        ),
        warnings=["This is a stub implementation - no actual edits will be made"],
    )
