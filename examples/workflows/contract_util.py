"""Helpers shared by verify.py and the contract test for cases.yaml."""

# pylint: disable=import-outside-toplevel,import-error,unused-argument,too-few-public-methods,too-many-locals

import copy
from pathlib import Path
from typing import Any

import yaml

WF_DIR = Path(__file__).resolve().parent


def load(name: str) -> Any:
    """Load one YAML document from this folder."""
    with open(WF_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_all(name: str) -> list[dict]:
    """Load a multi-document YAML file from this folder."""
    with open(WF_DIR / name, encoding="utf-8") as fh:
        return [d for d in yaml.safe_load_all(fh) if d]


def deep_merge(base: Any, over: Any) -> Any:
    """Maps merge; lists and scalars are replaced."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            out[key] = deep_merge(base[key], value) if key in base else value
        return out
    return copy.deepcopy(over)


def _key(container: Any, token: str) -> Any:
    """Resolve a path token: dict key, list index, or list item by name."""
    if isinstance(container, list):
        if token.isdigit():
            return int(token)
        for i, item in enumerate(container):
            if isinstance(item, dict) and item.get("name") == token:
                return i
        raise KeyError(token)
    return token


def patch(doc: Any, patches: dict[str, Any] | None) -> Any:
    """Return a copy of ``doc`` with dotted-path ``patches`` applied."""
    doc = copy.deepcopy(doc)
    for path, value in (patches or {}).items():
        tokens = path.split(".")
        cur = doc
        for tok in tokens[:-1]:
            k = _key(cur, tok)
            if isinstance(cur, dict) and k not in cur:
                cur[k] = {}
            cur = cur[k]
        cur[_key(cur, tokens[-1])] = value
    return doc


def generate(definition: dict, spec: dict[str, int]) -> dict:
    """Build oversized inputs for the limit cases."""
    steps = definition["spec"]["steps"]
    if "pad_bytes" in spec:
        definition["metadata"]["padding"] = "x" * spec["pad_bytes"]
    while len(steps) < spec.get("steps", 0):
        clone = copy.deepcopy(steps[0])
        clone["name"] = f"gen{len(steps)}"
        steps.append(clone)
    if "mcp_servers" in spec:
        definition["spec"]["mcp_servers"] = [
            f"srv{i}" for i in range(spec["mcp_servers"])
        ]
    if "secret_headers" in spec:
        server = steps[0]["mcp_servers"][0]
        server["secret_headers"] = {
            f"H{i}": {"name": "mcp/incidents"} for i in range(spec["secret_headers"])
        }
    return definition


def case_body(case: dict, definitions: dict, defaults: dict) -> dict:
    """Request body for a workflow case (definition, provider, overrides)."""
    dflt = defaults[case["workflow"]]
    definition = generate(
        patch(definitions[case["workflow"]], case.get("set")), case.get("generate", {})
    )
    return patch(
        {"definition": definition, "provider": copy.deepcopy(dflt["provider"])},
        case.get("body_set"),
    )


# ---------------------------------------------------------------------------
# Real-endpoint driver, shared by verify.py and the contract unit test.
# ---------------------------------------------------------------------------

# Highest #51 phase implemented in src/ (phase 0 is the Phase 0a hardening).
# Cases up to this phase run against the real endpoint and config.
IMPLEMENTED_PHASE = 2

# Named MCP servers are denied for every caller in policy mode until Phase 3,
# so cases for earlier phases run with the workflow-level names removed.
# Otherwise every one of them would be a 403 for that reason alone.
NAMED_MCP_PHASE = 3


def engine_config(stack: dict, pending: frozenset[str] | set[str] = frozenset()) -> Any:
    """Build the real WorkflowEngineConfiguration from an example stack config."""
    from models.config import WorkflowEngineConfiguration

    engine = {k: v for k, v in stack["workflow_engine"].items() if k not in pending}
    return WorkflowEngineConfiguration.model_validate(engine)


def without_named_mcp(definitions: dict) -> dict:
    """Copy of the definitions with workflow-level MCP server names removed."""
    out = copy.deepcopy(definitions)
    for definition in out.values():
        spec = definition["spec"]
        if "mcp_servers" in spec:
            spec["mcp_servers"] = []
    return out


class _StubRolesResolver:
    """Roles resolver that returns the roles of the case under test."""

    def __init__(self, roles: set[str]) -> None:
        """Remember the roles to return."""
        self._roles = roles

    async def resolve_roles(self, auth: Any) -> set[str]:
        """Return the case's roles whatever the auth tuple says."""
        return set(self._roles)


class _FakeExecutor:
    """Stands in for the workflow runner and records whether start was called."""

    def __init__(self) -> None:
        """Start with no call recorded."""
        self.started = False

    async def start(self, *args: Any, **kwargs: Any) -> str:
        """Record the call and return a workflow id."""
        self.started = True
        return "wf-contract"


async def run_real_case_detail(
    case: dict,
    stack: dict,
    definitions: dict,
    defaults: dict,
    pending: frozenset[str] | set[str] = frozenset(),
) -> tuple[int, bool, list[str]]:
    """POST the case to the real handler.

    Returns:
        ``(status, executor.start called, caller-facing denial messages)``.

    The request goes through the real ``@authorize`` decorator and access
    rules, so ``request.state.user_roles`` and ``is_admin`` come from the
    case's ``as`` roles; only the roles resolver is replaced.
    """
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException
    from starlette.requests import Request

    roles = set(case.get("as", defaults[case["workflow"]]["as"]))
    if case["phase"] < NAMED_MCP_PHASE:
        definitions = without_named_mcp(definitions)
    executor = _FakeExecutor()
    with pytest.MonkeyPatch.context() as mp:
        # The router reads the auth module from the loaded configuration at
        # import time; the case supplies the auth tuple itself, so any
        # dependency will do.
        mp.setattr("authentication.get_auth_dependency", lambda: lambda: None)
        import app.endpoints.workflows as wf_mod
        from authorization.resolvers import GenericAccessResolver
        from models.api.requests.agents import RunWorkflowRequest
        from models.config import AccessRule

        access = GenericAccessResolver(
            [AccessRule(**r) for r in stack["authorization"]["access_rules"]]
        )
        cfg = SimpleNamespace(
            workflow_engine_configuration=engine_config(stack, pending),
            inference=SimpleNamespace(default_provider=None, default_model=None),
            spawner_configuration=(
                SimpleNamespace(sandbox_image=stack["spawner"]["sandbox_image"])
                if case.get("spawner", True)
                else None
            ),
        )
        mp.setattr(wf_mod, "configuration", cfg)
        mp.setattr(wf_mod, "check_configuration_loaded", lambda _cfg: None)
        mp.setattr(wf_mod, "_executor", executor)
        mp.setattr(
            "authorization.middleware.get_authorization_resolvers",
            lambda: (_StubRolesResolver(roles), access),
        )
        body = RunWorkflowRequest(**case_body(case, definitions, defaults))
        request = Request(
            {"type": "http", "headers": [], "method": "POST", "path": "/"}
        )
        denied: list[str] = []
        try:
            await wf_mod.start_workflow_handler(
                request=request, body=body, auth=("uid", "user", False, "token")
            )
            status = 202
        except HTTPException as exc:
            status = exc.status_code
            if isinstance(exc.detail, dict):
                denied = [str(m) for m in exc.detail.get("denied", [])]
    return status, executor.started, denied


def current_schema_stack(stack: dict, files_dir: str) -> dict:
    """The example config minus the blocks that belong to Phase 3 and later.

    MCP ``secret_headers`` and ``workflow_enabled`` do not load yet. FilePath
    fields point at Secrets mounted in-cluster, so dummy files stand in.
    """
    out = copy.deepcopy(stack)
    for server in out["mcp_servers"]:
        server.pop("secret_headers", None)
        server.pop("workflow_enabled", None)
    tls_keys = ("openshell_tls_ca", "openshell_tls_cert", "openshell_tls_key")
    for section, keys in (
        (out["spawner"], tls_keys),
        (out["database"]["postgres"], ("ca_cert_path",)),
    ):
        for key in keys:
            path = Path(files_dir) / f"{key}.pem"
            path.write_text("placeholder", encoding="utf-8")
            section[key] = str(path)
    return out
