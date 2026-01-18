"""ColorAgent: Applies LUT/grade/curves/WB with global look spec and local offsets.

This is a STUB implementation. The actual agent will analyze footage
and apply color correction and grading.
"""

from .base import register_agent
from .types import (
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
)


@register_agent(SubAgentType.COLOR)
def color_agent(request: SubAgentRequest) -> SubAgentResponse:
    """Process color grading requests.

    Capabilities:
    - Apply LUTs (Look-Up Tables)
    - Create color grades and looks
    - Adjust curves (RGB, luma)
    - White balance correction
    - Match colors across clips
    - Apply global look with local offsets
    - Handle HDR/SDR conversions

    This is a STUB that returns a placeholder response.
    """

    return SubAgentResponse(
        request_id=request.request_id,
        success=True,
        agent_type=SubAgentType.COLOR,
        patch=EDLPatch(
            operations=[],
            preview_requests=[],
            metrics_needs=["color_histogram", "white_point", "exposure_values"],
            description=f"[STUB] ColorAgent would process: {request.intent}",
            estimated_duration_change_ms=0,
        ),
        reasoning=(
            f"[STUB] ColorAgent received request to: {request.intent}. "
            "Would analyze footage for color correction needs. "
            "This stub returns no operations - actual implementation pending."
        ),
        warnings=["This is a stub implementation - no actual edits will be made"],
    )
