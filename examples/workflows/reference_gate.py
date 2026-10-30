"""Reference model of the MCP part of the #51 submission gate (Phases 3-5).

This is an executable spec, not the implementation. Phases 0-2 (caller
credentials, provider catalog, run-level policy, spawn/image/advisory gates,
limits, audit) are real code now and ``cases.yaml`` runs them against the real
endpoint. What is left here is what the stack does not implement yet: named and
inline MCP servers, MCP secret refs, ``MCP_ALLOWED_SECRETS`` generation and the
post-cloud-agents#269 stage. When Phase 3 lands, run those cases against the
real endpoint too and delete this file.

The MCP grants the policy will carry in Phase 3 (``mcp``, ``mcp_secrets``,
``inline_mcp``, ``inline_mcp_hosts``) are reserved in the real schema and fail
config load, so they live in ``PHASE3_GRANTS`` instead of the example config.

Stages: ``pre269`` (names only, env-bound inference credentials) and
``post269`` (credential leases, any backend).
"""

# pylint: disable=too-many-locals,too-many-branches,import-error

import json
from typing import Any
from urllib.parse import urlsplit

from cloud_agents.workflow.core.definition import WorkflowDefinition
from pydantic import ValidationError

from workflow.limits import MAX_SECRET_HEADERS_PER_SERVER

REQUEST_BOUND = {"client", "oauth", "kubernetes"}

# Phase 3 policy grants per role (reserved fields of the real policy schema).
PHASE3_GRANTS: dict[str, dict[str, Any]] = {
    "agent-user": {
        "mcp_servers": ["github-readonly"],
        "mcp_secrets": ["mcp/github-readonly"],
    },
    "agent-support": {
        "mcp_servers": ["kb-search"],
        "mcp_secrets": ["mcp/kb-search"],
    },
    "agent-admin": {
        "inherit": ["agent-user", "agent-support"],
        "inline_mcp": True,
        "mcp_secrets": ["mcp/incidents"],
        "inline_mcp_hosts": ["mcp.internal.example.com"],
    },
}


class Denied(Exception):
    """A gate rejection with its status code and reasons."""

    def __init__(self, status: int, *reasons: str) -> None:
        super().__init__(status, reasons)
        self.status = status
        self.reasons = list(reasons)


# ----------------------------------------------------------------- load time
def _phase3_refs(roles: list[str] | None = None) -> set[str]:
    """MCP secret refs the Phase 3 policy grants (all roles by default)."""
    return {
        ref
        for role, rule in PHASE3_GRANTS.items()
        if roles is None or role in roles
        for ref in rule.get("mcp_secrets", [])
    }


def generated_mcp_allowed_secrets(stack: dict) -> str:
    """Value the stack writes to MCP_ALLOWED_SECRETS at startup."""
    secrets = {s["name"]: s for s in stack["workflow_engine"]["secrets"]}
    refs = {
        ref["name"]
        for server in stack["mcp_servers"]
        if server.get("workflow_enabled")
        for ref in (server.get("secret_headers") or {}).values()
    }
    # Inline MCP refs granted by policy are mounted too, so the runtime
    # guardrail must allow them as well.
    refs |= _phase3_refs()
    names = {
        secrets[ref]["secret_name"]
        for ref in refs
        if secrets.get(ref, {}).get("backend") == "k8s"
    }
    return ",".join(sorted(names))


def load_errors(stack: dict, stage: str = "pre269") -> list[str]:
    """Return the Phase 3 and post-#269 config-load failures the plan requires.

    Earlier checks (catalog, defaults, policy) are the real
    ``WorkflowEngineConfiguration``'s job and are covered by the unit test.
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
    for server in stack.get("mcp_servers", []):
        name = server["name"]
        for ref in (server.get("secret_headers") or {}).values():
            if ref["name"] not in secrets:
                errors.append(f"mcp {name}: ref {ref['name']} has no secrets binding")
        if server.get("workflow_enabled"):
            bad = REQUEST_BOUND & set((server.get("authorization_headers") or {}).values())
            if bad:
                errors.append(f"mcp {name}: workflow_enabled with {sorted(bad)}")
            if server.get("headers"):
                errors.append(f"mcp {name}: workflow_enabled with propagated headers")
    for ref in sorted(_phase3_refs() - set(secrets)):
        errors.append(f"policy: unknown mcp_secret {ref}")
    return errors


# -------------------------------------------------------------------- grants
def grants(roles: set[str]) -> dict[str, Any]:
    """Union of the Phase 3 grants of the roles (inherit resolved)."""
    out: dict[str, Any] = {}

    def add(role: str) -> None:
        rule = PHASE3_GRANTS.get(role, {})
        for parent in rule.get("inherit", []):
            add(parent)
        for key, value in rule.items():
            if key == "inherit":
                continue
            if isinstance(value, list):
                out[key] = sorted(set(out.get(key, [])) | set(value))
            else:
                out[key] = out.get(key, False) or value

    for role in roles:
        add(role)
    return out


# ---------------------------------------------------------------- submission
def _agent_steps(definition: dict) -> list[dict]:
    return [s for s in definition["spec"]["steps"] if s.get("type", "agent") == "agent"]


def _shape_copy(definition: dict) -> dict:
    """Copy for the cloud-agents shape check with inline registry refs rewritten.

    cloud-agents' MCPServerConfig only accepts ``{secret_name, key}``, so a
    registry ref ``{name: ...}`` would fail the typed parse. The stack
    validates registry refs itself, then rewrites them to the executor form;
    this models that rewrite for the shape check.
    """
    shaped = json.loads(json.dumps(definition))
    spec = shaped.get("spec", {})
    for scope in [spec, *spec.get("steps", [])]:
        for srv in scope.get("mcp_servers") or []:
            if not isinstance(srv, dict):
                continue
            for header, ref in list((srv.get("secret_headers") or {}).items()):
                if isinstance(ref, dict) and set(ref) == {"name"}:
                    srv["secret_headers"][header] = {"secret_name": ref["name"], "key": "value"}
    return shaped


def executor_form(stack: dict, definition: dict) -> dict:
    """Definition as cloud-agents' own validator sees it after the stack's rewrite.

    Logical provider names become executor types and inline registry refs the
    executor's ``{secret_name, key}`` form.
    """
    out = _shape_copy(definition)
    catalog = {p["name"]: p["executor_type"] for p in stack["workflow_engine"]["providers"]}
    scopes = [out] + [s for s in out["spec"]["steps"] if s.get("inference_provider")]
    for scope in scopes:
        key = "provider" if scope is out else "inference_provider"
        if scope.get(key):
            scope[key]["name"] = catalog.get(scope[key]["name"], scope[key]["name"])
    return out


def submit(
    stack: dict,
    body: dict,
    roles: set[str],
    stage: str = "pre269",
) -> None:
    """Model the MCP checks of POST /v1/workflows/run; return when it would be 202.

    Raises Denied(status, reasons) otherwise. Everything that is not about MCP
    is the real endpoint's job and is not modelled.
    """
    definition = body["definition"]
    spec = definition["spec"]
    try:
        WorkflowDefinition.model_validate(_shape_copy(definition))
    except ValidationError as exc:
        raise Denied(422, f"shape: {exc.error_count()} errors") from exc
    for scope in [spec, *_agent_steps(definition)]:
        for srv in scope.get("mcp_servers") or []:
            if isinstance(srv, dict) and (
                len(srv.get("secret_headers") or {}) > MAX_SECRET_HEADERS_PER_SERVER
            ):
                raise Denied(422, "too many secret_headers")

    # 400: unknown to the deployment.
    mcp = {m["name"]: m for m in stack["mcp_servers"]}
    refs = {s["name"] for s in stack["workflow_engine"]["secrets"]}
    for scope in [spec, *_agent_steps(definition)]:
        for srv in scope.get("mcp_servers") or []:
            if isinstance(srv, str):
                if srv not in mcp or not mcp[srv].get("workflow_enabled"):
                    raise Denied(400, f"unknown MCP server '{srv}'")
                continue
            for ref in (srv.get("secret_headers") or {}).values():
                if not isinstance(ref, dict) or ref.get("name") not in refs:
                    raise Denied(400, "inline secret_headers must be registry refs")

    # 403: exists, not for this caller.
    g = grants(roles)
    why: list[str] = []
    for step in _agent_steps(definition):
        s = step["name"]
        spawn = step.get("spawn") or spec.get("spawn") or "ephemeral"
        servers = (
            step["mcp_servers"]
            if step.get("mcp_servers") is not None
            else spec.get("mcp_servers") or []
        )
        for srv in servers:
            if isinstance(srv, str):
                if srv not in g.get("mcp_servers", []):
                    why.append(f"{s}: MCP '{srv}' not granted")
                secret_headers = mcp[srv].get("secret_headers") or {}
                for ref in secret_headers.values():
                    if ref["name"] not in g.get("mcp_secrets", []):
                        why.append(f"{s}: MCP secret '{ref['name']}' not granted for '{srv}'")
                if secret_headers and spawn != "ephemeral" and stage == "pre269":
                    why.append(f"{s}: secret_headers need ephemeral before cloud-agents#269")
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
