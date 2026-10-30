"""What the real cloud-agents step runner puts on the wire for tool lists.

These tests run the producer's own request-building code
(``cloud_agents.workflow.core.step_runner.run_step``) against a stub
transport and record the body it POSTs to the sandbox. They document the
PRODUCER only. They are NOT proof that the sandbox enforces anything.

Consumer evidence (read from lightspeed-agentic-sandbox at detached HEAD
619fb0c under ``src/lightspeed_agentic/``; the deployed image
``quay.io/jameswong/lightspeed-agentic-sandbox:latest`` is a floating tag
whose build could not be verified):

* ``routes/models.py``: ``RunRequest`` has no ``allowedTools`` or
  ``deniedTools`` field, so the values below are not even parsed.
* ``routes/query.py:163`` and ``tools.py:5``: the run always passes
  ``DEFAULT_ALLOWED_TOOLS`` = Bash, Read, Glob, Grep, Skill.
* ``providers/claude.py:95-97``: the Claude provider runs with
  ``permission_mode=bypassPermissions``, and the SDK treats ``allowed_tools``
  as an auto-approve list, not a restriction.

So a captured ``allowedTools`` field must not be read as enforcement. That is
why the workflow policy requires an explicit wildcard tools grant for
ephemeral steps (see examples/workflows/README.md).

Producer lines: ``step_runner.py:399-402`` and
``executor/temporal/activities.py:619-622`` add ``allowedTools`` and
``deniedTools`` only when the list is truthy, so omitted, None and [] are
identical on the wire (nothing is sent).
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import pytest
from cloud_agents.workflow.core import step_runner


class _FakeSpawner:
    """Minimal spawner: always ready, records nothing about tools."""

    async def spawn(self, *_args: Any, **_kwargs: Any) -> str:
        """Return a fake endpoint."""
        return "http://sandbox.invalid"

    async def wait_ready(self, *_args: Any, **_kwargs: Any) -> bool:
        """Report the sandbox as ready."""
        return True

    async def destroy(self, *_args: Any, **_kwargs: Any) -> None:
        """Accept the teardown."""


@pytest.fixture(name="wire")
def wire_fixture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every body posted to /v1/agent/run by the real step runner."""
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "output": {}})
        return httpx.Response(404)

    monkeypatch.setattr(
        step_runner,
        "build_query_client_kwargs",
        lambda *_a, **_k: {"transport": httpx.MockTransport(handler)},
    )
    monkeypatch.delenv("SANDBOX_AUTH_ENABLED", raising=False)
    return bodies


async def _run(permissions: Optional[dict[str, Any]]) -> None:
    """Run one ephemeral step with the given permissions through run_step."""
    step: dict[str, Any] = {"name": "s", "type": "agent", "prompt": "Do it"}
    if permissions is not None:
        step["permissions"] = permissions
    result = await step_runner.run_step(
        {
            "step": step,
            "workflow_id": "wf-1",
            "provider": {"name": "anthropic", "model": "m"},
            "sandbox_image": "img:1",
        },
        spawner=_FakeSpawner(),
    )
    assert result["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "permissions",
    [
        pytest.param(None, id="no-permissions"),
        pytest.param({"max_tokens": 1000}, id="omitted"),
        pytest.param({"max_tokens": 1000, "allowed_tools": None}, id="null"),
        pytest.param({"max_tokens": 1000, "allowed_tools": []}, id="empty"),
    ],
)
async def test_omitted_null_and_empty_allowed_tools_send_nothing(
    wire: list[dict[str, Any]], permissions: Optional[dict[str, Any]]
) -> None:
    """Omitted, None and [] are identical on the wire: no tool fields at all."""
    await _run(permissions)
    assert len(wire) == 1
    assert "allowedTools" not in wire[0]
    assert "deniedTools" not in wire[0]


@pytest.mark.asyncio
async def test_non_empty_tool_lists_are_sent(wire: list[dict[str, Any]]) -> None:
    """Non-empty lists are sent (which does not mean the sandbox enforces them)."""
    await _run({"max_tokens": 1, "allowed_tools": ["Bash"], "denied_tools": ["Write"]})
    assert wire[0]["allowedTools"] == ["Bash"]
    assert wire[0]["deniedTools"] == ["Write"]


@pytest.mark.asyncio
async def test_empty_denied_tools_is_not_deny_all(wire: list[dict[str, Any]]) -> None:
    """An empty list never reaches the sandbox, so [] cannot mean deny-all."""
    await _run({"max_tokens": 1, "allowed_tools": [], "denied_tools": []})
    assert not {"allowedTools", "deniedTools"} & wire[0].keys()
