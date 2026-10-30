"""Run examples/workflows/cases.yaml against the real handler and config (issue #51).

The cases are the acceptance contract for the #51 phases. Each case carries the
phase that makes it real; cases for later phases are skipped, so raising
``IMPLEMENTED_PHASE`` (and removing the matching part of the example's
``reference_gate.py``) is how a phase is declared done.

The request goes through the real ``@authorize`` decorator: the example's
access rules decide ``workflow_start`` and admin, and the decorator itself sets
``request.state.user_roles`` from the case's ``as`` roles. Only the roles
resolver is replaced (verify.py covers the JWT role mapping). The driver lives
in ``contract_util.run_real_case_detail`` so verify.py runs the same code.

Only the HTTP status is compared here: the reference gate's ``reason`` strings
are specific to the reference implementation.
"""

# pyright: reportMissingImports=false
# pylint: disable=import-outside-toplevel,redefined-outer-name,wrong-import-position,import-error

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "workflows"
sys.path.insert(0, str(EXAMPLES))

from contract_util import (  # IMPLEMENTED_PHASE = 2: phases 0-2 run for real
    IMPLEMENTED_PHASE,
    current_schema_stack,
    engine_config,
    load,
    patch,
    run_real_case_detail,
)

from models.config import Configuration

# workflow_engine keys of the example config whose phase is not built yet.
PENDING_ENGINE_KEYS: set[str] = set()

CASES = load("cases.yaml")
STACK = load("lightspeed-stack.yaml")
DEFINITIONS = {
    name: load(f"{name}.yaml")
    for name in ("triage-github-issue", "kb-answer-with-approval", "admin-inline-mcp")
}


def _params(section: str) -> list[Any]:
    """Parametrize over a cases.yaml section, skipping later phases."""
    out = []
    for case in CASES[section]:
        marks = []
        if case["phase"] > IMPLEMENTED_PHASE:
            marks.append(pytest.mark.skip(reason=f"phase {case['phase']} not built"))
        out.append(pytest.param(case, id=case["name"], marks=marks))
    return out


def _expected(case: dict[str, Any]) -> int:
    """Expected status before cloud-agents#269."""
    exp = case["expect"]
    return exp["pre269"] if isinstance(exp, dict) else exp


@pytest.mark.parametrize("case", _params("workflow_cases"))
@pytest.mark.asyncio
async def test_workflow_case(case: dict[str, Any]) -> None:
    """The real POST /v1/workflows/run handler gives the contract's status."""
    status, started, denied = await run_real_case_detail(
        case, STACK, DEFINITIONS, CASES["defaults"], PENDING_ENGINE_KEYS
    )
    assert status == _expected(case)
    assert started == (status == 202)
    if "denied_contains" in case:
        assert any(case["denied_contains"] in message for message in denied), denied


@pytest.mark.parametrize("case", _params("config_cases"))
def test_config_case(case: dict[str, Any]) -> None:
    """The real WorkflowEngineConfiguration fails to load as the contract says."""
    stack = patch(STACK, case["set"])
    with pytest.raises(ValidationError) as exc_info:
        engine_config(stack, PENDING_ENGINE_KEYS)
    assert case["error"].lower() in str(exc_info.value).lower()


def test_phase_tags_are_valid() -> None:
    """Every case is tagged with a known phase, so none is silently never run."""
    for section in ("workflow_cases", "config_cases"):
        for case in CASES[section]:
            assert case["phase"] in (0, 1, 2, 3), case["name"]


def test_example_config_loads_without_pending_blocks() -> None:
    """The example's implemented blocks load as a real WorkflowEngineConfiguration."""
    cfg = engine_config(STACK, PENDING_ENGINE_KEYS)
    assert cfg.governed
    assert cfg.default_provider == "claude-prod"


def test_example_policy_block_loads() -> None:
    """The example policy is valid under the real schema (fails on schema drift)."""
    cfg = engine_config(STACK, PENDING_ENGINE_KEYS)
    assert cfg.policy is not None
    roles = {rule.role for rule in cfg.policy.rules}
    assert roles == {
        "*",
        "agent-user",
        "agent-support",
        "agent-restricted",
        "agent-admin",
    }
    # The admin rule inherits both flows' grants.
    admin = cfg.policy.rules_for({"agent-admin"})
    assert {r.role for r in admin} == roles - {"*", "agent-restricted"}


def test_example_ephemeral_roles_grant_wildcard_and_restricted_is_finite() -> None:
    """Roles that run ephemeral flows grant ["*"]; agent-restricted stays finite."""
    cfg = engine_config(STACK, PENDING_ENGINE_KEYS)
    assert cfg.policy is not None
    by_role = {rule.role: rule for rule in cfg.policy.rules}
    for role in ("agent-user", "agent-support"):
        assert by_role[role].tools == ["*"]
    assert by_role["agent-restricted"].tools == ["github.read"]


def test_example_policy_rejects_unknown_fields() -> None:
    """A misspelt or retired policy key fails the load instead of being ignored."""
    stack = patch(STACK, {"workflow_engine.policy.rules.1.roles": ["agent-user"]})
    with pytest.raises(ValidationError):
        engine_config(stack)
    stack = patch(STACK, {"workflow_engine.policy.rules.1.limits.max_timeout": 1})
    with pytest.raises(ValidationError):
        engine_config(stack)


def test_example_config_validates_as_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The example (minus Phase 3 MCP blocks) loads as a full Configuration.

    This runs the cross-field checks too: with a policy that grants to
    non-wildcard roles, auth must be jwk-token with role and access rules.
    """
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only")
    stack = current_schema_stack(STACK, str(tmp_path))
    config = Configuration.model_validate(stack)
    assert config.workflow_engine.policy is not None

    stack["authentication"] = {"module": "noop"}
    with pytest.raises(ValidationError):
        Configuration.model_validate(stack)


def test_readme_states_which_limits_are_enforced() -> None:
    """The policy docs say what is enforced at runtime and what is declared only."""
    text = " ".join((EXAMPLES / "README.md").read_text(encoding="utf-8").split())
    assert "max_retries" in text and "enforced at runtime" in text
    for declared in (
        "step `timeout_seconds` for `none` and `ephemeral`",
        "`permissions.timeout_seconds`",
        "`permissions.max_tokens`",
        "workflow seconds",
    ):
        assert declared in text, declared
    assert "declared budgets" in text
    assert "not security boundaries" in text


def test_readme_states_tools_enforcement_wording_and_consumer_evidence() -> None:
    """The README says what a wildcard tools grant means and why, with evidence."""
    text = " ".join((EXAMPLES / "README.md").read_text(encoding="utf-8").split())
    for needle in (
        "tools_not_enforceable",
        "explicit wildcard",
        "does not promise",
        "not enforced",
        "upstream assumption",
        "step_runner.py:399-402",
        "activities.py:619-622",
        "routes/models.py",
        "routes/query.py:163",
        "providers/claude.py:95-97",
        "bypassPermissions",
        "DEFAULT_ALLOWED_TOOLS",
        "floating tag",
        "negative execution tests",
        "disallowed_tools",
        "fail closed",
    ):
        assert needle in text, needle
    assert "does not enforce `permissions.allowed_tools`" in text
    assert "`denied_tools`" in text
