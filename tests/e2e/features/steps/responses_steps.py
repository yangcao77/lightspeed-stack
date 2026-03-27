"""Behave steps for POST /v1/responses (LCORE Responses API) multi-turn tests."""

from __future__ import annotations

from typing import Any

from behave import step  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context

from tests.e2e.utils.utils import http_response_json_or_responses_sse_terminal


def _successful_responses_result_object(context: Context) -> dict[str, Any]:
    """Return the LCORE responses payload for a successful call (JSON or SSE)."""
    assert context.response is not None
    assert context.response.status_code == 200, context.response.text
    data = http_response_json_or_responses_sse_terminal(context.response)
    assert "id" in data and "conversation" in data, data
    return data


@step("I store the first responses turn from the last response")
def store_first_responses_turn(context: Context) -> None:
    """Save response id and conversation from a successful responses call (JSON or SSE)."""
    assert context.response is not None, "Request needs to be performed first"
    data = _successful_responses_result_object(context)
    context.responses_first_response_id = data["id"]
    context.responses_conversation_id = data["conversation"]


@step("I store the multi-turn baseline from the last responses response")
def store_multi_turn_baseline(context: Context) -> None:
    """Save conversation id after a continuation turn (thread before an optional fork)."""
    assert context.response is not None, "Request needs to be performed first"
    data = _successful_responses_result_object(context)
    context.responses_multi_turn_baseline_conversation_id = data["conversation"]
    context.responses_second_response_id = data["id"]


@step("I store the forked responses conversation id from the last response")
def store_forked_responses_conversation_id(context: Context) -> None:
    """Save conversation id returned after branching from a non-latest ``previous_response_id``."""
    assert context.response is not None, "Request needs to be performed first"
    data = _successful_responses_result_object(context)
    context.responses_fork_conversation_id = data["conversation"]


@step("The responses conversation id is different from the multi-turn baseline")
def responses_conversation_differs_from_baseline(context: Context) -> None:
    """Assert fork applied: returned conversation is not the baseline thread id."""
    assert context.response is not None
    data = _successful_responses_result_object(context)
    baseline = context.responses_multi_turn_baseline_conversation_id
    current = data["conversation"]
    assert (
        current != baseline
    ), f"Expected a new conversation after fork, got same as baseline {baseline!r}"


@step("The responses conversation id matches the multi-turn baseline")
def responses_conversation_matches_baseline(context: Context) -> None:
    """Assert continuation on latest turn keeps the same normalized conversation id."""
    assert context.response is not None
    data = _successful_responses_result_object(context)
    baseline = context.responses_multi_turn_baseline_conversation_id
    current = data["conversation"]
    assert current == baseline, f"Expected conversation {baseline!r}, got {current!r}"


@step("The responses conversation id matches the first stored conversation")
def responses_conversation_matches_first_stored(context: Context) -> None:
    """Assert the response uses the same thread as ``I store the first responses turn``."""
    assert context.response is not None
    assert hasattr(
        context, "responses_conversation_id"
    ), "responses_conversation_id not set; run the first-store step first"
    data = _successful_responses_result_object(context)
    expected = context.responses_conversation_id
    current = data["conversation"]
    assert current == expected, f"Expected conversation {expected!r}, got {current!r}"
