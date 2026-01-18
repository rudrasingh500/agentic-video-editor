"""CaptionsAgent: Creates captions, lower-thirds, and text overlays tied to transcript.

This is a STUB implementation. The actual agent will analyze transcripts
and generate appropriate text elements.
"""

from .base import register_agent
from .types import (
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
)


@register_agent(SubAgentType.CAPTIONS)
def captions_agent(request: SubAgentRequest) -> SubAgentResponse:
    """Process caption and text overlay requests.

    Capabilities:
    - Generate captions from transcript
    - Create lower-thirds for speakers
    - Add text overlays and titles
    - Handle caption timing and line breaks
    - Apply style presets and formatting
    - Support multiple caption tracks

    This is a STUB that returns a placeholder response.
    """

    return SubAgentResponse(
        request_id=request.request_id,
        success=True,
        agent_type=SubAgentType.CAPTIONS,
        patch=EDLPatch(
            operations=[],
            preview_requests=[],
            metrics_needs=["transcript_segments", "speaker_ids"],
            description=f"[STUB] CaptionsAgent would process: {request.intent}",
            estimated_duration_change_ms=0,
        ),
        reasoning=(
            f"[STUB] CaptionsAgent received request to: {request.intent}. "
            "Would analyze transcript for caption generation. "
            "This stub returns no operations - actual implementation pending."
        ),
        warnings=["This is a stub implementation - no actual edits will be made"],
    )
