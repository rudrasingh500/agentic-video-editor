"""Sub-agents for the Edit Orchestrator.

Each sub-agent is a specialized stateless function that receives an EDL slice
and returns a patch (diff) to apply to the timeline.

Sub-agents are automatically registered via the @register_agent decorator.
Import this module to ensure all agents are registered.
"""

from .types import (
    AssetContext,
    EDLPatch,
    PreviewRequest,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
    TimelineOperation,
    TimelineSlice,
)
from .base import dispatch_to_agent, get_registered_agents, is_agent_registered

# Import all agent modules to trigger registration
from . import cut_agent
from . import silence_agent
from . import broll_agent
from . import captions_agent
from . import mix_agent
from . import color_agent
from . import motion_agent
from . import fx_agent


__all__ = [
    # Types
    "AssetContext",
    "EDLPatch",
    "PreviewRequest",
    "SubAgentRequest",
    "SubAgentResponse",
    "SubAgentType",
    "TimelineOperation",
    "TimelineSlice",
    # Functions
    "dispatch_to_agent",
    "get_registered_agents",
    "is_agent_registered",
]
