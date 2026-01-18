"""FXAgent: Handles transitions, speed ramps, freeze frames, vignette, grain, and blur.

This is a STUB implementation. The actual agent will analyze the timeline
and apply creative effects.
"""

from .base import register_agent
from .types import (
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
)


@register_agent(SubAgentType.FX)
def fx_agent(request: SubAgentRequest) -> SubAgentResponse:
    """Process visual effects requests.

    Capabilities:
    - Create and customize transitions
    - Apply speed ramps and time remapping
    - Create freeze frames
    - Add vignette effects
    - Apply film grain
    - Create blur effects (gaussian, motion, radial)
    - Glow and bloom effects
    - Letterboxing and framing

    This is a STUB that returns a placeholder response.
    """

    return SubAgentResponse(
        request_id=request.request_id,
        success=True,
        agent_type=SubAgentType.FX,
        patch=EDLPatch(
            operations=[],
            preview_requests=[],
            metrics_needs=["clip_boundaries", "transition_points"],
            description=f"[STUB] FXAgent would process: {request.intent}",
            estimated_duration_change_ms=0,
        ),
        reasoning=(
            f"[STUB] FXAgent received request to: {request.intent}. "
            "Would analyze timeline for effect application points. "
            "This stub returns no operations - actual implementation pending."
        ),
        warnings=["This is a stub implementation - no actual edits will be made"],
    )
