"""Edit Orchestrator Agent.

This agent coordinates video editing tasks by:
1. Understanding user intent from natural language
2. Analyzing timeline state
3. Retrieving relevant assets
4. Delegating to specialized sub-agents
5. Collecting and presenting proposed changes

Usage:
    from agent.edit_orchestrator import orchestrate_edit, EditRequest

    result = orchestrate_edit(
        project_id="...",
        user_id="...",
        request=EditRequest(message="Remove awkward pauses"),
        db=session,
    )
"""

from .agent import orchestrate_edit
from .types import (
    ApplyPatchesRequest,
    ApplyPatchesResult,
    EditPlan,
    EditRequest,
    EditSessionDetail,
    EditSessionStatus,
    EditSessionSummary,
    MessageRole,
    OrchestratorResult,
    PendingPatch,
    SessionMessage,
    SubAgentCall,
)
from .session import (
    SessionClosedError,
    SessionNotFoundError,
    add_message,
    add_pending_patches,
    clear_pending_patches,
    create_session,
    delete_session,
    get_session,
    get_session_by_project,
    list_sessions,
    update_session_status,
    update_session_title,
)
from .sub_agents import (
    AssetContext,
    EDLPatch,
    PreviewRequest,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
    TimelineOperation,
    TimelineSlice,
    dispatch_to_agent,
    get_registered_agents,
)
from .executor import (
    BatchExecutionResult,
    ExecutionResult,
    OperationExecutionError,
    execute_operation,
    execute_patch,
    get_supported_operations,
)


__all__ = [
    # Main entry point
    "orchestrate_edit",
    # Request/Response types
    "EditRequest",
    "EditPlan",
    "OrchestratorResult",
    "PendingPatch",
    "SubAgentCall",
    # Session types
    "EditSessionDetail",
    "EditSessionSummary",
    "EditSessionStatus",
    "SessionMessage",
    "MessageRole",
    # Session operations
    "create_session",
    "get_session",
    "get_session_by_project",
    "list_sessions",
    "add_message",
    "add_pending_patches",
    "clear_pending_patches",
    "update_session_status",
    "update_session_title",
    "delete_session",
    # Session errors
    "SessionNotFoundError",
    "SessionClosedError",
    # Apply patches
    "ApplyPatchesRequest",
    "ApplyPatchesResult",
    # Sub-agent types
    "SubAgentType",
    "SubAgentRequest",
    "SubAgentResponse",
    "EDLPatch",
    "TimelineSlice",
    "TimelineOperation",
    "PreviewRequest",
    "AssetContext",
    "dispatch_to_agent",
    "get_registered_agents",
    # Executor
    "execute_operation",
    "execute_patch",
    "ExecutionResult",
    "BatchExecutionResult",
    "OperationExecutionError",
    "get_supported_operations",
]
