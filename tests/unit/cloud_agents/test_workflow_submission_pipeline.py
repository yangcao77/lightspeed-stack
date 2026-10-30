"""Endpoint tests for the POST /v1/workflows/run submission pipeline (#51 Phase 2).

These go through the real ``@authorize`` decorator with a real starlette
``Request``: only the role resolver is faked, so ``request.state.user_roles``
and ``is_admin`` come from the production code path. They pin the pipeline
order, the error hygiene, the single audit record per outcome and the canary
rule (caller strings never reach logs or audit records).
"""

# pylint: disable=protected-access,redefined-outer-name,too-many-lines

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable, Generator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from cloud_agents.workflow.core.execution import (
    normalize_workflow_step,
    workflow_defaults_from_definition,
)
from fastapi import HTTPException
from pytest_mock import MockerFixture
from starlette.requests import Request

import app.endpoints.workflows as wf_mod
from app.endpoints.workflows import start_workflow_handler
from authorization.resolvers import GenericAccessResolver
from models.api.requests.agents import RunWorkflowRequest
from models.config import AccessRule, Action, WorkflowEngineConfiguration
from workflow.catalog import normalize_definition, resolve_run_provider
from workflow.limits import MAX_DEFINITION_BYTES, MAX_WORKFLOW_STEPS

CANARY = "sk-CANARY-3f9a7c2e1b5d"
DEFAULT_IMAGE = "default-sandbox:v1"
ADMIN_ROLE = "agent-admin"
AUTH = ("user-1", "alice", False, "token")

ACCESS = GenericAccessResolver(
    [
        AccessRule(role="*", actions=[Action.WORKFLOW_START]),
        AccessRule(role=ADMIN_ROLE, actions=[Action.ADMIN]),
    ]
)


class _Roles:  # pylint: disable=too-few-public-methods
    """Roles resolver returning fixed roles (stands in for JwtRolesResolver)."""

    def __init__(self, roles: set[str]) -> None:
        """Store the roles."""
        self._roles = roles

    async def resolve_roles(self, auth: Any) -> set[str]:
        """Return the fixed roles."""
        _ = auth
        return set(self._roles)


@dataclass
class Outcome:
    """Result of one POST through the decorated handler."""

    status: int
    detail: Any
    audits: list[dict[str, Any]]
    log_text: str


@dataclass
class Env:
    """Test environment: patched config, executor and runner."""

    cfg: Any
    executor: Any
    run: Callable[..., Any]


def _audits(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Decode every audit record captured so far."""
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name.endswith("workflow.audit")
    ]


@pytest.fixture(name="env")
def env_fixture(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> Generator[Env, None, None]:
    """Legacy-mode config with a spawner, a mock executor and a runner."""
    caplog.set_level(logging.DEBUG)
    cfg = mocker.patch("app.endpoints.workflows.configuration")
    cfg.workflow_engine_configuration = WorkflowEngineConfiguration(enabled=True)
    cfg.inference = SimpleNamespace(default_provider="openai", default_model="gpt-4o")
    cfg.spawner_configuration = SimpleNamespace(sandbox_image=DEFAULT_IMAGE)
    mocker.patch("app.endpoints.workflows.check_configuration_loaded")
    executor = mocker.AsyncMock()
    executor.start.return_value = "wf-1"
    wf_mod._executor = executor

    async def run(body: dict[str, Any], roles: tuple[str, ...] = ()) -> Outcome:
        """POST a body as a caller with the given roles."""
        mocker.patch(
            "authorization.middleware.get_authorization_resolvers",
            return_value=(_Roles(set(roles) | {"*"}), ACCESS),
        )
        caplog.clear()
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/workflows/run",
                "headers": [(b"x-request-id", b"req-123")],
            }
        )
        try:
            result = await start_workflow_handler(
                request=request, body=RunWorkflowRequest(**body), auth=AUTH
            )
            status, detail = 202, result
        except HTTPException as exc:
            status, detail = exc.status_code, exc.detail
        return Outcome(status, detail, _audits(caplog), caplog.text)

    yield Env(cfg, executor, run)
    wf_mod._executor = None


def _step(name: str = "agent", **extra: Any) -> dict[str, Any]:
    """Build an agent step on the default (ephemeral) spawn."""
    return {
        "name": name,
        "type": "agent",
        "prompt": "Do it",
        "output_key": f"out_{name}",
        **extra,
    }


def _definition(*steps: dict[str, Any], **top: Any) -> dict[str, Any]:
    """Build a definition; ``spec`` in ``top`` is merged into the spec."""
    spec_extra = top.pop("spec", {})
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "wf"},
        "spec": {"steps": list(steps) or [_step()], **spec_extra},
        **top,
    }


def _body(definition: Optional[dict[str, Any]] = None, **extra: Any) -> dict:
    """Build a request body."""
    return {"definition": definition or _definition(), **extra}


def _governed(policy: Optional[dict[str, Any]] = None) -> WorkflowEngineConfiguration:
    """Governed catalog, optionally with a workflow policy."""
    data: dict[str, Any] = {
        "enabled": True,
        "providers": [
            {
                "name": "claude-prod",
                "executor_type": "anthropic",
                "credential": {"name": "inference/anthropic-prod"},
                "allowed_models": ["claude-sonnet-4-5", "claude-haiku-4-5"],
            },
        ],
        "default_provider": "claude-prod",
        "default_model": "claude-sonnet-4-5",
        "secrets": [
            {
                "name": "inference/anthropic-prod",
                "backend": "env",
                "env": "ANTHROPIC_API_KEY",
            }
        ],
    }
    if policy is not None:
        data["policy"] = policy
    return WorkflowEngineConfiguration.model_validate(data)


def _one(outcome: Outcome) -> dict[str, Any]:
    """Return the single audit record, failing unless there is exactly one."""
    assert len(outcome.audits) == 1, outcome.audits
    return outcome.audits[0]


def _reasons(outcome: Outcome) -> list[str]:
    """Return the reasons of the single audit record."""
    return _one(outcome)["reasons"]


# --------------------------------------------------------------------------
# Order
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forbidden_field_400_beats_extra_key_422(env: Env) -> None:
    """The raw-dict scan answers 400 before extra="forbid" can answer 422."""
    definition = _definition(
        provider={"name": "openai", "model": "m", "credentials_secret": "X"}
    )
    definition["unexpected"] = 1
    outcome = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert outcome.status == 400
    assert _reasons(outcome) == ["forbidden_field"]
    env.executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_shape_422_beats_catalog_400(env: Env) -> None:
    """A malformed definition is 422 even when the provider is unknown."""
    env.cfg.workflow_engine_configuration = _governed()
    definition = _definition(_step(unexpected=1))
    outcome = await env.run(
        _body(definition, provider={"name": "nope", "model": "m"}),
        roles=(ADMIN_ROLE,),
    )
    assert outcome.status == 422
    assert _reasons(outcome) == ["shape_invalid"]
    env.executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_count_cap_422_beats_shape_and_catalog(env: Env) -> None:
    """Count caps run before the typed parse and the catalog."""
    env.cfg.workflow_engine_configuration = _governed()
    steps = [_step(f"s{i}", unexpected=1) for i in range(MAX_WORKFLOW_STEPS + 1)]
    outcome = await env.run(
        _body(_definition(*steps), provider={"name": "nope"}), roles=(ADMIN_ROLE,)
    )
    assert outcome.status == 422
    assert _reasons(outcome) == ["count_cap"]
    assert _one(outcome)["paths"] == ["/definition/spec/steps"]


@pytest.mark.asyncio
async def test_catalog_400_beats_policy_403(env: Env) -> None:
    """An unknown provider is 400 even when the caller would also be denied."""
    env.cfg.workflow_engine_configuration = _governed()
    outcome = await env.run(
        _body(sandbox_image="evil:1", provider={"name": "nope", "model": "m"})
    )
    assert outcome.status == 400
    assert _reasons(outcome) == ["provider_unknown"]
    env.executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_policy_403_beats_executor_422(env: Env) -> None:
    """A non-admin is denied before the executor's own validation runs.

    Duplicate step names pass the typed parse and the effective plan but are
    rejected by ``validate_definition``; the custom image is a 403.
    """
    definition = _definition(_step("a"), _step("a", output_key="other"))
    admin = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert admin.status == 422
    assert _reasons(admin) == ["executor_validation_failed"]

    outcome = await env.run(_body(definition, sandbox_image="evil:1"))
    assert outcome.status == 403
    assert _reasons(outcome) == ["image_not_allowed"]
    env.executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_service_account_conflict_422_beats_policy_403(env: Env) -> None:
    """Step 5b runs before the 403 step."""
    definition = _definition(
        _step(service_account="sa-b"),
        spec={"permissions": {"service_account": "sa-a"}},
    )
    outcome = await env.run(_body(definition, sandbox_image="evil:1"))
    assert outcome.status == 422
    assert _reasons(outcome) == ["service_account_conflict"]


@pytest.mark.asyncio
async def test_start_raising_is_generic_500_without_authorized_event(
    env: Env,
) -> None:
    """start failing emits workflow_start_failed only and a generic 500."""
    env.executor.start.side_effect = RuntimeError(f"db down {CANARY}")
    outcome = await env.run(_body(), roles=(ADMIN_ROLE,))
    assert outcome.status == 500
    record = _one(outcome)
    assert record["event"] == "workflow_start_failed"
    assert CANARY not in json.dumps(outcome.detail)
    assert CANARY not in outcome.log_text
    assert "workflow_authorized" not in outcome.log_text


@pytest.mark.asyncio
async def test_authorized_event_only_after_start_with_workflow_id(env: Env) -> None:
    """A 202 emits exactly one workflow_authorized carrying the workflow id."""
    outcome = await env.run(_body(), roles=(ADMIN_ROLE,))
    assert outcome.status == 202
    record = _one(outcome)
    assert record["event"] == "workflow_authorized"
    assert record["workflow_id"] == "wf-1"
    assert record["user_id"] == "user-1"
    assert record["request_id"] == "req-123"
    assert record["provider"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True], ids=["202", "start-failed"])
async def test_legacy_mode_caller_provider_name_never_audited(
    env: Env, fails: bool
) -> None:
    """Legacy mode audits no provider: the name is caller-chosen input.

    The executor only accepts real provider types, so the caller picks a
    valid one that differs from the configured default.
    """
    if fails:
        env.executor.start.side_effect = RuntimeError("boom")
    outcome = await env.run(
        _body(provider={"name": "anthropic", "model": "m"}), roles=(ADMIN_ROLE,)
    )
    assert outcome.status == (500 if fails else 202)
    record = _one(outcome)
    assert record["provider"] is None
    assert "anthropic" not in json.dumps(record)


@pytest.mark.asyncio
async def test_governed_start_failed_records_catalog_name(policy_env: Env) -> None:
    """Governed mode keeps the resolved catalog name on start failure."""
    policy_env.executor.start.side_effect = RuntimeError("boom")
    outcome = await policy_env.run(_body(_definition(_policy_step())))
    assert outcome.status == 500
    record = _one(outcome)
    assert record["event"] == "workflow_start_failed"
    assert record["provider"] == "claude-prod"


# --------------------------------------------------------------------------
# Error hygiene
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_typed_parse_errors_are_loc_and_type_only(env: Env) -> None:
    """Pydantic errors become [{loc, type}] without input values or messages."""
    definition = _definition(_step(timeout_seconds=CANARY))
    outcome = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert outcome.status == 422
    errors = outcome.detail["validation_errors"]
    assert errors
    for error in errors:
        assert set(error) == {"loc", "type"}
        assert error["loc"][0] == "definition"
    assert CANARY not in json.dumps(outcome.detail)


@pytest.mark.asyncio
async def test_provider_validation_error_has_no_exception_text(env: Env) -> None:
    """An executor-unknown legacy provider is 422 without the exception text."""
    outcome = await env.run(
        _body(provider={"name": f"bogus-{CANARY}", "model": "m"}),
        roles=(ADMIN_ROLE,),
    )
    assert outcome.status == 422
    assert _reasons(outcome) == ["executor_validation_failed"]
    assert CANARY not in json.dumps(outcome.detail)
    assert CANARY not in outcome.log_text


@pytest.mark.asyncio
async def test_executor_rejection_is_logged_as_drift(env: Env) -> None:
    """validate_definition still rejecting after our checks is logged as drift."""
    definition = _definition(_step("a"), _step("a", output_key="other"))
    outcome = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert outcome.status == 422
    assert "drift" in outcome.log_text
    assert "Duplicate" not in outcome.log_text


@pytest.mark.asyncio
async def test_start_receives_normalized_definition_not_typed_copy(
    env: Env,
) -> None:
    """start gets exactly normalize_definition's output; the typed copy is dropped."""
    engine = _governed()
    env.cfg.workflow_engine_configuration = engine
    definition = _definition(
        _step(spawn="ephemeral"),
        provider={"name": "claude-prod", "model": "claude-haiku-4-5"},
    )
    body = _body(definition)
    outcome = await env.run(copy.deepcopy(body), roles=(ADMIN_ROLE,))
    assert outcome.status == 202
    resolved = resolve_run_provider(engine, env.cfg.inference, None)
    expected = normalize_definition(engine, definition, resolved)
    started = env.executor.start.call_args[0][0]["definition"]
    assert started == expected
    assert "advisory" not in started


# --------------------------------------------------------------------------
# Service account conflict
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sa_conflict_real_normalizer(env: Env) -> None:
    """A cross-layer conflict the executor rejects is a 422 before start."""
    sa_a, sa_b = f"sa-a-{CANARY}", f"sa-b-{CANARY}"
    definition = _definition(
        _step(spawn="none", service_account=sa_b),
        spec={"permissions": {"service_account": sa_a}},
    )
    with pytest.raises(ValueError):
        normalize_workflow_step(
            definition["spec"]["steps"][0],
            workflow_defaults_from_definition(definition),
            1,
        )

    outcome = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert outcome.status == 422
    assert outcome.detail == {
        "validation_errors": [
            {
                "loc": ["definition", "spec", "steps", 0, "service_account"],
                "type": "service_account_conflict",
            }
        ]
    }
    record = _one(outcome)
    assert record["reasons"] == ["service_account_conflict"]
    assert record["paths"] == [
        "/definition/spec/steps/0/service_account",
        "/definition/spec/permissions/service_account",
    ]
    assert "drift" not in outcome.log_text
    assert CANARY not in outcome.log_text
    env.executor.start.assert_not_called()


# --------------------------------------------------------------------------
# No-policy mode (Phase 0a rules through policy.py)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda d, b: b.update(sandbox_image="evil:1"), "image_not_allowed"),
        (lambda d, b: d.update(advisory=True), "policy_denied"),
        (
            lambda d, b: d["spec"]["steps"][0].update(spawn="local"),
            "spawn_mode_not_allowed",
        ),
        (
            lambda d, b: d["spec"]["steps"][0].update(spawn="none"),
            "spawn_mode_not_allowed",
        ),
        (lambda d, b: d.update(skills={"image": "evil:1"}), "image_not_allowed"),
        (
            lambda d, b: d["spec"]["steps"][0].update(
                spawn_config={"sandbox_image": "evil:1"}
            ),
            "image_not_allowed",
        ),
        (
            lambda d, b: d["spec"]["steps"][0].update(
                mcp_servers=[{"name": "x", "url": "https://mcp.example.com"}]
            ),
            "mcp_not_allowed",
        ),
    ],
    ids=[
        "sandbox-image",
        "advisory",
        "local",
        "none",
        "skills-image",
        "step-image",
        "inline-mcp",
    ],
)
async def test_no_policy_privileged_options_need_admin(
    env: Env, mutate: Any, reason: str
) -> None:
    """Non-admins get 403 with the reason; admins pass (legacy override kept)."""
    definition = _definition()
    extras: dict[str, Any] = {}
    mutate(definition, extras)
    outcome = await env.run(_body(definition, **extras))
    assert outcome.status == 403
    assert outcome.detail["denied"]
    assert _reasons(outcome) == [reason]
    env.executor.start.assert_not_called()

    admin = await env.run(_body(definition, **extras), roles=(ADMIN_ROLE,))
    assert admin.status == 202
    env.executor.start.assert_called_once()


@pytest.mark.asyncio
async def test_no_policy_named_mcp_and_default_image_fine_for_non_admin(
    env: Env,
) -> None:
    """Named MCP is unchanged and the spawner image is implicit."""
    definition = _definition(_step(mcp_servers=["catalog-entry"]))
    outcome = await env.run(_body(definition, sandbox_image=DEFAULT_IMAGE))
    assert outcome.status == 202


@pytest.mark.asyncio
async def test_no_policy_ephemeral_without_spawner_denied_even_for_admin(
    env: Env,
) -> None:
    """The spawner hard rule applies to admins too; spawn none does not need one."""
    env.cfg.spawner_configuration = None
    outcome = await env.run(_body(), roles=(ADMIN_ROLE,))
    assert outcome.status == 403
    assert _reasons(outcome) == ["spawn_mode_not_allowed"]

    definition = _definition(
        _step(spawn="none"),
        {"name": "gate", "type": "human-approval", "output_key": "approval"},
    )
    ok = await env.run(_body(definition), roles=(ADMIN_ROLE,))
    assert ok.status == 202

    non_admin = await env.run(_body(definition))
    assert non_admin.status == 403


@pytest.mark.asyncio
async def test_no_policy_all_denials_returned_together(env: Env) -> None:
    """Every denial message reaches the caller in one response."""
    definition = _definition(_step(spawn="local"), advisory=True)
    outcome = await env.run(_body(definition, sandbox_image="evil:1"))
    assert outcome.status == 403
    assert len(outcome.detail["denied"]) == 3
    assert set(_reasons(outcome)) == {
        "spawn_mode_not_allowed",
        "policy_denied",
        "image_not_allowed",
    }


# --------------------------------------------------------------------------
# Policy mode
# --------------------------------------------------------------------------

LIMITS = {
    "max_step_timeout_seconds": 600,
    "max_workflow_seconds": 3600,
    "max_retries": 1,
    "max_tokens": 10_000,
}

POLICY = {
    "rules": [
        {
            "role": "*",
            "providers": ["claude-prod"],
            "spawn_modes": ["ephemeral"],
            "tools": ["*"],
            "limits": LIMITS,
        },
        {"role": "team-a", "images": ["team-a/sandbox:v2"], "skills": ["triage"]},
    ]
}


def _policy_step(**extra: Any) -> dict[str, Any]:
    """An agent step that passes the baseline policy."""
    return _step(timeout_seconds=120, permissions={"max_tokens": 1000}, **extra)


@pytest.fixture(name="policy_env")
def policy_env_fixture(env: Env) -> Env:
    """Governed config with the test policy."""
    env.cfg.workflow_engine_configuration = _governed(POLICY)
    return env


@pytest.mark.asyncio
async def test_policy_baseline_allowed_for_everyone(policy_env: Env) -> None:
    """A step within the wildcard grants is accepted."""
    outcome = await policy_env.run(_body(_definition(_policy_step())))
    assert outcome.status == 202
    assert _one(outcome)["provider"] == "claude-prod"


@pytest.mark.asyncio
async def test_policy_grant_by_role(policy_env: Env) -> None:
    """A non-admin needs the role that grants the image and skill."""
    definition = _definition(_policy_step(allowed_skills=["triage"]))
    body = _body(definition, sandbox_image="team-a/sandbox:v2")

    denied = await policy_env.run(body)
    assert denied.status == 403
    assert any("team-a/sandbox:v2" in m for m in denied.detail["denied"])
    assert set(_reasons(denied)) == {"image_not_allowed", "policy_denied"}
    assert "team-a/sandbox:v2" not in denied.log_text

    granted = await policy_env.run(body, roles=("team-a",))
    assert granted.status == 202


@pytest.mark.asyncio
async def test_policy_admin_is_deny_by_default(policy_env: Env) -> None:
    """Admins lose the legacy image override and need a grant for spawn none."""
    image = await policy_env.run(
        _body(_definition(_policy_step()), sandbox_image="evil:1"),
        roles=(ADMIN_ROLE,),
    )
    assert image.status == 403
    assert _reasons(image) == ["image_not_allowed"]

    none = await policy_env.run(
        _body(_definition(_policy_step(spawn="none"))), roles=(ADMIN_ROLE,)
    )
    assert none.status == 403
    assert _reasons(none) == ["spawn_mode_not_allowed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "servers",
    [["catalog-entry"], [{"name": "x", "url": "https://mcp.example.com"}]],
    ids=["named", "inline"],
)
async def test_policy_mcp_denied_for_everyone(
    policy_env: Env, servers: list[Any]
) -> None:
    """Named and inline MCP are 403 under a policy, admins included."""
    definition = _definition(_policy_step(mcp_servers=servers))
    for roles in ((), (ADMIN_ROLE,)):
        outcome = await policy_env.run(_body(definition), roles=roles)
        assert outcome.status == 403
        assert _reasons(outcome) == ["mcp_not_allowed"]
        assert _one(outcome)["paths"] == ["/definition/spec/steps/0/mcp_servers/0"]
    policy_env.executor.start.assert_not_called()


NO_TOOLS_POLICY = {
    "rules": [
        {
            "role": "*",
            "providers": ["claude-prod"],
            "spawn_modes": ["ephemeral"],
            "limits": LIMITS,
        }
    ]
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allowed_tools",
    [
        pytest.param({}, id="omitted"),
        pytest.param({"allowed_tools": None}, id="null"),
        pytest.param({"allowed_tools": []}, id="empty"),
    ],
)
@pytest.mark.parametrize("roles", [(), (ADMIN_ROLE,)], ids=["user", "admin"])
async def test_policy_ephemeral_without_tools_grant_is_403(
    env: Env, allowed_tools: dict[str, Any], roles: tuple[str, ...]
) -> None:
    """A policy granting provider, ephemeral and budgets but no tools is 403.

    This is the reviewer's repro: omitted, null and [] allowed_tools all send
    nothing to the sandbox, which then runs with its default tools, so the
    grant must be an explicit wildcard.
    """
    env.cfg.workflow_engine_configuration = _governed(NO_TOOLS_POLICY)
    step = _step(timeout_seconds=120, permissions={"max_tokens": 1000, **allowed_tools})
    outcome = await env.run(_body(_definition(step)), roles=roles)
    assert outcome.status == 403
    assert _reasons(outcome) == ["tools_not_enforceable"]
    assert _one(outcome)["paths"] == ["/definition/spec/steps/0/permissions"]
    assert any("wildcard" in m for m in outcome.detail["denied"])
    env.executor.start.assert_not_called()


@pytest.mark.asyncio
async def test_policy_ephemeral_tools_denial_points_at_step_without_permissions(
    env: Env,
) -> None:
    """With permissions defaulted the denial points at the step."""
    env.cfg.workflow_engine_configuration = _governed(NO_TOOLS_POLICY)
    outcome = await env.run(_body(_definition(_step(timeout_seconds=120))))
    assert outcome.status == 403
    assert "tools_not_enforceable" in _reasons(outcome)
    assert "/definition/spec/steps/0" in _one(outcome)["paths"]


@pytest.mark.asyncio
async def test_policy_finite_tools_grant_is_still_403(env: Env) -> None:
    """A finite grant covering the requested tools is not enough."""
    policy = {"rules": [{**NO_TOOLS_POLICY["rules"][0], "tools": ["Bash"]}]}
    env.cfg.workflow_engine_configuration = _governed(policy)
    step = _step(
        timeout_seconds=120,
        permissions={"max_tokens": 1000, "allowed_tools": ["Bash"]},
    )
    outcome = await env.run(_body(_definition(step)))
    assert outcome.status == 403
    assert _reasons(outcome) == ["tools_not_enforceable"]


@pytest.mark.asyncio
async def test_policy_wildcard_tools_grant_is_202(env: Env) -> None:
    """A wildcard grant accepts ephemeral steps, even with a finite request."""
    policy = {"rules": [{**NO_TOOLS_POLICY["rules"][0], "tools": ["*"]}]}
    env.cfg.workflow_engine_configuration = _governed(policy)
    step = _step(
        timeout_seconds=120,
        permissions={"max_tokens": 1000, "allowed_tools": ["Bash"]},
    )
    outcome = await env.run(_body(_definition(step)))
    assert outcome.status == 202


@pytest.mark.asyncio
async def test_policy_limits_checked(policy_env: Env) -> None:
    """Omitted max_tokens and an over-limit timeout are denied."""
    definition = _definition(_step(timeout_seconds=9000))
    outcome = await policy_env.run(_body(definition))
    assert outcome.status == 403
    assert _reasons(outcome) == ["limit_exceeded"]


# --------------------------------------------------------------------------
# Exactly one audit record per outcome
# --------------------------------------------------------------------------


def _oversized() -> dict[str, Any]:
    """A body over the byte cap."""
    return _body(_definition(_step(prompt="x" * (MAX_DEFINITION_BYTES + 1))))


OUTCOMES: list[tuple[str, Callable[[], dict[str, Any]], tuple[str, ...], int, str]] = [
    ("413", _oversized, (ADMIN_ROLE,), 413, "payload_too_large"),
    (
        "400",
        lambda: _body(_definition(provider={"name": "o", "credentials_secret": "x"})),
        (ADMIN_ROLE,),
        400,
        "forbidden_field",
    ),
    (
        "422-shape",
        lambda: _body(_definition(_step(bogus=1))),
        (ADMIN_ROLE,),
        422,
        "shape_invalid",
    ),
    (
        "422-executor",
        lambda: _body(_definition(_step("a"), _step("a", output_key="b"))),
        (ADMIN_ROLE,),
        422,
        "executor_validation_failed",
    ),
    ("403", lambda: _body(sandbox_image="evil:1"), (), 403, "image_not_allowed"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "roles", "status", "reason"),
    [pytest.param(*o[1:], id=o[0]) for o in OUTCOMES],
)
async def test_exactly_one_denied_record(
    env: Env,
    body: Callable[[], dict[str, Any]],
    roles: tuple[str, ...],
    status: int,
    reason: str,
) -> None:
    """Each denial emits one workflow_denied record and never starts anything."""
    outcome = await env.run(body(), roles=roles)
    assert outcome.status == status
    record = _one(outcome)
    assert record["event"] == "workflow_denied"
    assert record["status"] == status
    assert reason in record["reasons"]
    assert record["user_id"] == "user-1"
    env.executor.start.assert_not_called()


# --------------------------------------------------------------------------
# Canaries: caller strings never reach logs or audit records
# --------------------------------------------------------------------------


def _canary_step(**extra: Any) -> dict[str, Any]:
    """A step carrying the canary in its name, prompt and secret_headers."""
    step = _step(
        CANARY,
        prompt=f"Summarize {CANARY}",
        output_key="out",
        mcp_servers=[
            {
                "name": "srv",
                "url": "https://mcp.example.com",
                "secret_headers": {
                    "Authorization": {"secret_name": CANARY, "key": CANARY}
                },
            }
        ],
    )
    step.update(extra)
    return step


def _canary_body(**overrides: Any) -> dict[str, Any]:
    """A body with the canary in the step name, headers, prompt, model and image."""
    definition = overrides.pop("definition", None) or _definition(_canary_step())
    body = {
        "definition": definition,
        "provider": {"name": "openai", "model": f"gpt-{CANARY}"},
        "sandbox_image": f"registry/{CANARY}:1",
    }
    body.update(overrides)
    return body


def _canary_unknown_key() -> dict[str, Any]:
    """The canary body plus a canary-named unknown key."""
    definition = _definition(_canary_step(**{CANARY: CANARY}))
    return _canary_body(definition=definition)


def _canary_413() -> dict[str, Any]:
    """The canary body over the byte cap."""
    return _canary_body(
        definition=_definition(
            _canary_step(prompt=CANARY * (MAX_DEFINITION_BYTES // len(CANARY) + 1))
        )
    )


def _canary_400() -> dict[str, Any]:
    """The canary body with a caller-chosen credential."""
    definition = _definition(
        _canary_step(),
        provider={"name": "openai", "model": CANARY, "credentials_secret": CANARY},
    )
    return _canary_body(definition=definition)


def _canary_422_executor() -> dict[str, Any]:
    """The canary body with a credentialed MCP URL (executor rejects it)."""
    definition = _definition(
        _canary_step(
            mcp_servers=[{"name": CANARY, "url": f"https://u:{CANARY}@mcp.example"}]
        )
    )
    return _canary_body(definition=definition)


CANARY_CASES: list[tuple[str, Callable[[], dict[str, Any]], tuple[str, ...], int]] = [
    ("413", _canary_413, (ADMIN_ROLE,), 413),
    ("400", _canary_400, (ADMIN_ROLE,), 400),
    ("422-shape", _canary_unknown_key, (ADMIN_ROLE,), 422),
    ("422-executor", _canary_422_executor, (ADMIN_ROLE,), 422),
    ("403", _canary_body, (), 403),
    ("500", _canary_body, (ADMIN_ROLE,), 500),
    ("202", _canary_body, (ADMIN_ROLE,), 202),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "roles", "status"),
    [pytest.param(*c[1:], id=c[0]) for c in CANARY_CASES],
)
async def test_canary_never_logged_or_audited(
    env: Env,
    body: Callable[[], dict[str, Any]],
    roles: tuple[str, ...],
    status: int,
) -> None:
    """For every outcome the canary is in neither caplog nor the audit records."""
    if status == 500:
        env.executor.start.side_effect = RuntimeError(CANARY)
    outcome = await env.run(body(), roles=roles)
    assert outcome.status == status
    assert len(outcome.audits) == 1
    assert CANARY not in json.dumps(outcome.audits)
    assert CANARY not in outcome.log_text


@pytest.mark.asyncio
@pytest.mark.usefixtures("env")
async def test_canary_request_id_header_is_not_audited(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A caller-controlled request id that is not a plain token is replaced."""
    mocker.patch(
        "authorization.middleware.get_authorization_resolvers",
        return_value=(_Roles({"*", ADMIN_ROLE}), ACCESS),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/workflows/run",
            "headers": [(b"x-request-id", f"{CANARY} {CANARY}".encode())],
        }
    )
    await start_workflow_handler(
        request=request, body=RunWorkflowRequest(**_body()), auth=AUTH
    )
    records = _audits(caplog)
    assert len(records) == 1
    assert CANARY not in json.dumps(records)
    assert records[0]["request_id"]
