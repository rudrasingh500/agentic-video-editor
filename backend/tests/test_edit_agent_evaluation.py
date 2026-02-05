"""Evaluation scaffolding for the edit agent.

These tests are intentionally lightweight to avoid calling external services.
Use this file as a starting point for integration tests that exercise the agent
end-to-end with mocked tool results.
"""

from __future__ import annotations

import pytest


EVALUATION_CASES = [
    {
        "id": "simple_trim",
        "input": "Remove the first 5 seconds from the first clip",
        "expected_tools": ["get_timeline_snapshot", "skills_registry", "edit_timeline"],
        "expected_operation_types": ["trim_clip"],
    },
    {
        "id": "add_transition",
        "input": "Add a crossfade between the first and second clips",
        "expected_tools": ["get_timeline_snapshot", "skills_registry", "edit_timeline"],
        "expected_operation_types": ["add_transition"],
    },
    {
        "id": "search_and_edit",
        "input": "Find the interview clip and add it to the timeline",
        "expected_tools": ["list_assets_summaries", "edit_timeline"],
        "expected_operation_types": ["add_clip"],
    },
    {
        "id": "info_only",
        "input": "What clips are currently on the timeline?",
        "expected_tools": ["get_timeline_snapshot"],
        "expected_operation_types": [],
    },
]


def test_evaluation_case_structure() -> None:
    for case in EVALUATION_CASES:
        assert "id" in case
        assert "input" in case
        assert "expected_tools" in case
        assert "expected_operation_types" in case


@pytest.mark.skip(reason="Integration test scaffold; requires OpenAI + DB setup")
def test_agent_integration_placeholder() -> None:
    """Placeholder for integration evaluation.

    Replace this test with a fully mocked run of orchestrate_edit that validates:
    - tool call trajectory
    - operation types emitted
    - verification steps (render + view)
    """
    assert True
