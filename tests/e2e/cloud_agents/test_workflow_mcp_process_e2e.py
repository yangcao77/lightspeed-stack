"""Process-boundary test for operator-catalog MCP (issue #51, Phase 3).

Starts the demo MCP server as a real subprocess, points a ``workflow_enabled``
catalog entry at it, runs a definition that references the entry by name
through the stack's own functions and the real executor resolver, then
connects with the executor's own MCP client (``MCPToolset`` over
``StreamableHttpTransport``, as in cloud-agents ``direct.py``) and calls
``get_pod_status``. Nothing about the MCP transport is mocked.

Needs no LLM, no PostgreSQL and no gateway, so it is not skipped under
``LIGHTSPEED_E2E_USE_MOCK_LLM``. Proves the catalog URL and the executor
contract line up over a real socket; it does not prove a model chooses to
call the tool (see ``test_workflows_http_e2e.py`` for that).
"""

from __future__ import annotations

from typing import Any

import pytest
from cloud_agents.workflow.core.execution import (
    normalize_workflow_step,
    workflow_defaults_from_definition,
)
from cloud_agents.workflow.core.mcp_resolver import resolve_mcp_servers
from cloud_agents.workflow.core.models import MCPServerConfig
from pydantic_ai.mcp import MCPToolset, StreamableHttpTransport

from models.config import ModelContextProtocolServer
from workflow.catalog import ResolvedProvider
from workflow.effective import build_effective_plan
from workflow.mcp import (
    McpReferenceError,
    build_workflow_mcp_servers,
    effective_mcp_servers,
    validate_mcp_references,
)

POD_STATUS_ANSWER = "memoryLimit=347Mi"


def _definition(mcp_servers: list[Any]) -> dict[str, Any]:
    """Build a one-step definition referencing the given MCP servers."""
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "mcp-process-boundary"},
        "spec": {
            "steps": [
                {
                    "name": "check",
                    "type": "agent",
                    "prompt": "Look up the pod",
                    "output_key": "check_result",
                    "spawn": "none",
                    "mcp_servers": mcp_servers,
                }
            ]
        },
    }


def _resolve_through_stack(
    definition: dict[str, Any], catalog: list[ModelContextProtocolServer]
) -> list[dict[str, Any]]:
    """Run the stack's reference path and the executor's resolver.

    Parameters:
        definition: Workflow definition with one agent step.
        catalog: Operator catalog entries.

    Returns:
        The servers the executor would hand to step 0.
    """
    validate_mcp_references(definition, catalog)
    resolved = ResolvedProvider(
        catalog_name="corp-openai",
        executor_type="openai",
        model="gpt-4o",
        credential_ref=None,
        provider={"name": "openai", "model": "gpt-4o"},
    )
    plan = build_effective_plan(
        definition, resolved, run_sandbox_image=None, spawner_default_image=None
    )
    injected = build_workflow_mcp_servers(effective_mcp_servers(plan), catalog)
    step = definition["spec"]["steps"][0]
    defaults = workflow_defaults_from_definition(definition)
    normalized, _ = normalize_workflow_step(step, defaults, 1)
    servers = resolve_mcp_servers(normalized.mcp_servers, injected)
    assert servers is not None
    for server in servers:
        MCPServerConfig.model_validate(server)
    return servers


async def _call_get_pod_status(url: str) -> str:
    """Call get_pod_status with the executor's own MCP client.

    Parameters:
        url: Streamable-http MCP endpoint.

    Returns:
        The tool's text result.
    """
    async with MCPToolset(StreamableHttpTransport(url=url)) as toolset:
        result = await toolset.client.call_tool(
            "get_pod_status", {"pod_name": "checkout-7f9"}
        )
    return "".join(getattr(block, "text", "") for block in result.content)


async def test_catalog_name_reaches_real_mcp_server(demo_mcp_url: str) -> None:
    """A catalog name resolves to the live server and its tool answers."""
    catalog = [
        ModelContextProtocolServer(
            name="pod-status", url=demo_mcp_url, workflow_enabled=True
        )
    ]
    servers = _resolve_through_stack(_definition(["pod-status"]), catalog)

    assert servers == [{"name": "pod-status", "url": demo_mcp_url}]
    answer = await _call_get_pod_status(servers[0]["url"])
    assert "checkout-7f9" in answer
    assert POD_STATUS_ANSWER in answer


def test_disabled_catalog_entry_is_not_resolvable(demo_mcp_url: str) -> None:
    """A catalog entry without workflow_enabled is a 400, never injected."""
    catalog = [ModelContextProtocolServer(name="pod-status", url=demo_mcp_url)]
    with pytest.raises(McpReferenceError):
        _resolve_through_stack(_definition(["pod-status"]), catalog)
