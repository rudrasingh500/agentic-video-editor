"""
Asset retrieval agent for finding timestamp-addressable content.

Uses z-ai/glm-4.7 via OpenRouter with tool calling to search across
indexed asset metadata and return scored candidates.
"""

import json
import logging
import os
import re
from uuid import uuid4

from openai import OpenAI
from sqlalchemy.orm import Session

from database.models import AgentRun

from .prompts import SYSTEM_PROMPT
from .tools import TOOLS, execute_tool
from .types import AssetCandidate, RetrievalResult

logger = logging.getLogger(__name__)

MODEL = "z-ai/glm-4.7"
MAX_ITERATIONS = 25


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


def find_assets(
    project_id: str,
    query: str,
    db: Session,
) -> RetrievalResult:
    client = _get_client()
    trace: list[dict] = []

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Project ID: {project_id}\n\nQuery: {query}"},
    ]

    final_content = ""

    for iteration in range(MAX_ITERATIONS):
        logger.debug(f"Asset retrieval iteration {iteration + 1}/{MAX_ITERATIONS}")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return RetrievalResult(
                candidates=[],
                trace=trace + [{"error": str(e), "iteration": iteration}],
            )

        message = response.choices[0].message
        final_content = message.content or ""

        assistant_msg: dict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_msg)

        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                trace_entry = {
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": tool_args,
                }

                logger.debug(f"Executing tool: {tool_name} with args: {tool_args}")

                result = execute_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    project_id=project_id,
                    db=db,
                )

                trace_entry["result"] = result
                trace.append(trace_entry)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

            remaining = MAX_ITERATIONS - iteration - 1
            iteration_context = (
                f"[System: Iteration {iteration + 1}/{MAX_ITERATIONS} complete. "
                f"{remaining} iterations remaining. "
            )
            if remaining <= 5:
                iteration_context += (
                    "You are running low on iterations. "
                    "Consider finalizing your search and returning candidates soon."
                )
            elif remaining <= 2:
                iteration_context += (
                    "URGENT: Very few iterations left. "
                    "You MUST return your candidates JSON in the next response."
                )
            iteration_context += "]"

            messages.append({
                "role": "user",
                "content": iteration_context,
            })

        if response.choices[0].finish_reason == "stop" and not message.tool_calls:
            logger.debug("Agent finished - parsing candidates")
            break
    else:
        logger.warning(
            f"Asset retrieval reached max iterations ({MAX_ITERATIONS}) for query: {query}"
        )
        trace.append({
            "warning": "Max iterations reached",
            "iteration": MAX_ITERATIONS,
        })

    candidates = _parse_candidates(final_content)

    _log_run(db, project_id, query, trace, candidates)

    return RetrievalResult(candidates=candidates, trace=trace)


def _parse_candidates(content: str) -> list[AssetCandidate]:
    if not content:
        return []

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.warning(f"No JSON found in response: {content[:200]}...")
            return []

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse candidates JSON: {e}")
        return []

    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return []

    candidates = []
    for raw in raw_candidates:
        try:
            candidate = AssetCandidate(
                media_id=raw.get("media_id", ""),
                t0=raw.get("t0", 0),
                t1=raw.get("t1", 0),
                score=max(0, min(100, raw.get("score", 0))),
                reasons=raw.get("reasons", []),
                tags=raw.get("tags", []),
                transcript_snippet=raw.get("transcript_snippet"),
                face_ids=raw.get("face_ids", []),
                speaker_ids=raw.get("speaker_ids", []),
            )
            candidates.append(candidate)
        except Exception as e:
            logger.warning(f"Failed to parse candidate: {e}")
            continue

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:10]


def _log_run(
    db: Session,
    project_id: str,
    query: str,
    trace: list[dict],
    candidates: list[AssetCandidate],
) -> None:
    try:
        run = AgentRun(
            run_id=uuid4(),
            project_id=project_id,
            trace={
                "agent": "asset_retrieval",
                "query": query,
                "iterations": len(set(t.get("iteration", 0) for t in trace if "iteration" in t)),
                "tool_calls": trace,
            },
            analysis_segments=[c.model_dump() for c in candidates],
        )
        db.add(run)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log agent run: {e}")
        db.rollback()
