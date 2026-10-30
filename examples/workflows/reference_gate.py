"""Reference model of the inline-MCP part of the #51 submission gate (Phase 4+).

This is an executable spec, not the implementation. Phases 0-3 are real code
and ``cases.yaml`` runs them against the real endpoint: caller credentials,
provider catalog, run-level policy, spawn/image/advisory gates, limits, audit,
and secretless operator-catalog MCP (named servers and the policy ``mcp``
grant).

What is left here is what the stack does not implement yet and that stays
tagged ``phase: 4`` in ``cases.yaml``: inline MCP servers with host grants and
registry secret refs (``inline_mcp``, ``inline_mcp_hosts``, ``mcp_secrets``).
Those policy fields are reserved in the real schema and fail config load, so
they live in ``PHASE4_GRANTS`` instead of the example config. Secret delivery,
SSRF confinement and ``MCP_ALLOWED_SECRETS`` generation are deferred further
and have no model here; see README.md. The post-cloud-agents#269 credential
check is also modelled here. When Phase 4 lands, run its cases against the
real endpoint and delete this file.

Stages: ``pre269`` (env-bound inference credentials) and ``post269``
(credential leases, any backend).
"""

# pylint: disable=too-many-locals,too-many-branches,import-error

import json
from typing import Any
from urllib.parse import urlsplit

from cloud_agents.workflow.core.definition import WorkflowDefinition
from pydantic import ValidationError

# Phase 4 policy grants per role (reserved fields of the real policy schema).
PHASE4_GRANTS: dict[str, dict[str, Any]] = {
    "agent-admin": {
        "inline_mcp": True,
        "mcp_secrets": ["mcp/incidents"],
        "inline_mcp_hosts": ["mcp.internal.example.com"],
    },
}

# Registry refs the inline cases use. The example config no longer binds MCP
# secrets (catalog MCP is secretless), so the model carries its own.
PHASE4_SECRET_REFS = {"mcp/incidents"}


class Denied(Exception):
    """A gate rejection with its status code and reasons."""

    def __init__(self, status: int, *reasons: str) -> None:
        super().__init__(status, reasons)
        self.status = status
        self.reasons = list(reasons)


# ----------------------------------------------------------------- load time
def load_errors(stack: dict, stage: str = "pre269") -> list[str]:
    """Return the post-#269 config-load failures the plan requires.

    Earlier checks (catalog, defaults, policy, MCP catalog) are the real
    configuration's job and are covered by the unit test.
    """
    we = stack["workflow_engine"]
    secrets = {s["name"]: s for s in we.get("secrets", [])}
    errors: list[str] = []
    if stage == "post269":
        # The real config only knows the pre-269 rule (env-bound credentials).
        for p in we.get("providers") or []:
            ref = (p.get("credential") or {}).get("name")
            if ref is not None and ref not in secrets:
                errors.append(f"{p['name']}: credential {ref} has no secrets binding")
    return errors


# -------------------------------------------------------------------- grants
def grants(roles: set[str]) -> dict[str, Any]:
    """Union of the Phase 4 grants of the roles."""
    out: dict[str, Any] = {}
    for role in roles:
        for key, value in PHASE4_GRANTS.get(role, {}).items():
            if isinstance(value, list):
                out[key] = sorted(set(out.get(key, [])) | set(value))
            else:
                out[key] = out.get(key, False) or value
    return out


# ---------------------------------------------------------------- submission
def _agent_steps(definition: dict) -> list[dict]:
    return [s for s in definition["spec"]["steps"] if s.get("type", "agent") == "agent"]


def _shape_copy(definition: dict) -> dict:
    """Copy for the cloud-agents shape check with inline registry refs rewritten.

    cloud-agents' MCPServerConfig only accepts ``{secret_name, key}``, so a
    registry ref ``{name: ...}`` would fail the typed parse (the real endpoint
    answers 422 for it today). Phase 4 would validate registry refs itself and
    rewrite them to the executor form; this models that rewrite.
    """
    shaped = json.loads(json.dumps(definition))
    spec = shaped.get("spec", {})
    for scope in [spec, *spec.get("steps", [])]:
        for srv in scope.get("mcp_servers") or []:
            if not isinstance(srv, dict):
                continue
            for header, ref in list((srv.get("secret_headers") or {}).items()):
                if isinstance(ref, dict) and set(ref) == {"name"}:
                    srv["secret_headers"][header] = {
                        "secret_name": ref["name"],
                        "key": "value",
                    }
    return shaped


def executor_form(stack: dict, definition: dict) -> dict:
    """Definition as cloud-agents' own validator sees it after the stack's rewrite.

    Logical provider names become executor types and inline registry refs the
    executor's ``{secret_name, key}`` form.
    """
    out = _shape_copy(definition)
    catalog = {
        p["name"]: p["executor_type"] for p in stack["workflow_engine"]["providers"]
    }
    scopes = [out] + [s for s in out["spec"]["steps"] if s.get("inference_provider")]
    for scope in scopes:
        key = "provider" if scope is out else "inference_provider"
        if scope.get(key):
            scope[key]["name"] = catalog.get(scope[key]["name"], scope[key]["name"])
    return out


def submit(body: dict, roles: set[str]) -> None:
    """Model the inline-MCP checks of POST /v1/workflows/run (Phase 4).

    Returns when it would be 202; raises Denied(status, reasons) otherwise.
    Named catalog servers and everything that is not inline MCP are the real
    endpoint's job and are not modelled.
    """
    definition = body["definition"]
    spec = definition["spec"]
    try:
        WorkflowDefinition.model_validate(_shape_copy(definition))
    except ValidationError as exc:
        raise Denied(422, f"shape: {exc.error_count()} errors") from exc

    # 400: unknown to the deployment.
    for scope in [spec, *_agent_steps(definition)]:
        for srv in scope.get("mcp_servers") or []:
            if not isinstance(srv, dict):
                continue
            for ref in (srv.get("secret_headers") or {}).values():
                if (
                    not isinstance(ref, dict)
                    or ref.get("name") not in PHASE4_SECRET_REFS
                ):
                    raise Denied(400, "inline secret_headers must be registry refs")

    # 403: exists, not for this caller.
    g = grants(roles)
    why: list[str] = []
    for step in _agent_steps(definition):
        s = step["name"]
        servers = (
            step["mcp_servers"]
            if step.get("mcp_servers") is not None
            else spec.get("mcp_servers") or []
        )
        for srv in servers:
            if not isinstance(srv, dict):
                continue
            if not g.get("inline_mcp"):
                why.append(f"{s}: inline MCP not granted")
            parts = urlsplit(srv.get("url", ""))
            if parts.scheme != "https" or parts.username or parts.password:
                why.append(f"{s}: inline MCP must be https without userinfo")
            if srv.get("headers"):
                why.append(f"{s}: inline MCP literal header values are not allowed")
            if parts.hostname not in g.get("inline_mcp_hosts", []):
                why.append(f"{s}: inline MCP host '{parts.hostname}' not allowed")
            for ref in (srv.get("secret_headers") or {}).values():
                if ref["name"] not in g.get("mcp_secrets", []):
                    why.append(f"{s}: inline MCP secret '{ref['name']}' not granted")
    if why:
        raise Denied(403, *why)
