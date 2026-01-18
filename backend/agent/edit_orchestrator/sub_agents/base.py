"""Base sub-agent dispatcher and registry.

Each sub-agent is a stateless function that receives a SubAgentRequest
and returns a SubAgentResponse with an EDL patch.
"""

from __future__ import annotations

import logging
from typing import Callable

from .types import SubAgentRequest, SubAgentResponse, SubAgentType

logger = logging.getLogger(__name__)

# Type alias for sub-agent functions
SubAgentFunc = Callable[[SubAgentRequest], SubAgentResponse]

# Registry of sub-agent implementations
_AGENT_REGISTRY: dict[SubAgentType, SubAgentFunc] = {}


def register_agent(agent_type: SubAgentType) -> Callable[[SubAgentFunc], SubAgentFunc]:
    """Decorator to register a sub-agent implementation."""

    def decorator(func: SubAgentFunc) -> SubAgentFunc:
        _AGENT_REGISTRY[agent_type] = func
        logger.debug(f"Registered sub-agent: {agent_type.value}")
        return func

    return decorator


def dispatch_to_agent(
    agent_type: SubAgentType,
    request: SubAgentRequest,
) -> SubAgentResponse:
    """Dispatch a request to the appropriate sub-agent.

    Args:
        agent_type: Type of sub-agent to invoke
        request: The request to send to the sub-agent

    Returns:
        SubAgentResponse with EDL patch or error

    Raises:
        ValueError: If the agent type is not registered
    """
    if agent_type not in _AGENT_REGISTRY:
        logger.error(f"Unknown agent type: {agent_type}")
        return SubAgentResponse(
            request_id=request.request_id,
            success=False,
            agent_type=agent_type,
            patch=None,
            reasoning="",
            error=f"Agent type '{agent_type.value}' is not implemented",
        )

    agent_func = _AGENT_REGISTRY[agent_type]
    logger.info(f"Dispatching to {agent_type.value} agent: {request.intent[:100]}...")

    try:
        response = agent_func(request)
        logger.debug(
            f"Agent {agent_type.value} completed: success={response.success}"
        )
        return response
    except Exception as e:
        logger.exception(f"Agent {agent_type.value} failed with exception")
        return SubAgentResponse(
            request_id=request.request_id,
            success=False,
            agent_type=agent_type,
            patch=None,
            reasoning="",
            error=f"Agent execution failed: {type(e).__name__}: {str(e)}",
        )


def get_registered_agents() -> list[SubAgentType]:
    """Return list of registered agent types."""
    return list(_AGENT_REGISTRY.keys())


def is_agent_registered(agent_type: SubAgentType) -> bool:
    """Check if an agent type is registered."""
    return agent_type in _AGENT_REGISTRY
