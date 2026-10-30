"""Unit tests for the run-level workflow policy (issue #51, Phase 2, T3).

Plans are built with the real ``build_effective_plan`` so the policy is
exercised against the same pointers and executor defaults the endpoint uses.
"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import Any, Optional

import pytest

from models.config import PolicyLimits, PolicyRule, WorkflowPolicy
from workflow.audit import AuditReason
from workflow.catalog import ResolvedProvider
from workflow.effective import EffectivePlan, build_effective_plan
from workflow.policy import (
    WORKFLOW_ADVISORY_POINTER,
    PolicyDecision,
    Principal,
    authorize_workflow_submission,
)

DEFAULT_IMAGE = "lightspeed-agentic-sandbox:latest"
PROVIDER = "corp-openai"
STEPS = "/definition/spec/steps"
CANARY = "CANARY-tok-9f3b2c1d"

ADMIN = Principal(user_id="admin-1", is_admin=True, roles=frozenset({"*"}))
USER = Principal(user_id="user-1", is_admin=False, roles=frozenset({"*"}))

FULL_LIMITS = PolicyLimits(
    max_step_timeout_seconds=600,
    max_workflow_seconds=3600,
    max_retries=2,
    max_tokens=10_000,
)


def _rule(role: str = "*", **grants: Any) -> PolicyRule:
    """Build a rule granting provider, ephemeral spawn, wildcard tools, limits.

    Ephemeral steps need an explicit wildcard ``tools`` grant (the sandbox
    does not enforce finite lists), so the baseline carries one. Pass
    ``tools=None`` to drop it.
    """
    base: dict[str, Any] = {
        "providers": [PROVIDER],
        "tools": ["*"],
        "spawn_modes": ["ephemeral"],
        "limits": FULL_LIMITS,
    }
    base.update(grants)
    return PolicyRule(role=role, **base)


def _policy(*rules: PolicyRule) -> WorkflowPolicy:
    """Build a policy from rules (one baseline wildcard rule by default)."""
    return WorkflowPolicy(rules=list(rules) if rules else [_rule()])


def _step(index: int = 0, **extra: Any) -> dict[str, Any]:
    """Build an agent step that passes the baseline policy."""
    step: dict[str, Any] = {
        "name": f"s{index}",
        "type": "agent",
        "prompt": "Do it",
        "output_key": f"o{index}",
        "timeout_seconds": 60,
        "permissions": {"max_tokens": 1000},
    }
    step.update(extra)
    return {k: v for k, v in step.items() if v is not None}


def _plan(
    steps: Optional[list[dict[str, Any]]] = None,
    *,
    provider: str = PROVIDER,
    run_image: Optional[str] = None,
    **spec_extra: Any,
) -> EffectivePlan:
    """Build an effective plan with the real builder."""
    definition = {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "wf"},
        "spec": {"steps": steps if steps is not None else [_step()], **spec_extra},
    }
    resolved = ResolvedProvider(
        catalog_name=provider,
        executor_type="openai",
        model="gpt-4o",
        credential_ref=None,
        provider={"name": "openai", "model": "gpt-4o"},
    )
    return build_effective_plan(
        definition,
        resolved,
        run_sandbox_image=run_image,
        spawner_default_image=DEFAULT_IMAGE,
    )


def _authorize(  # pylint: disable=too-many-arguments
    plan: EffectivePlan,
    principal: Principal,
    policy: Optional[WorkflowPolicy],
    *,
    spawner_configured: bool = True,
    advisory: bool = False,
    definition_skills_image: Optional[str] = None,
) -> PolicyDecision:
    """Call the policy with the test defaults."""
    return authorize_workflow_submission(
        plan,
        principal,
        policy,
        spawner_configured=spawner_configured,
        default_sandbox_image=DEFAULT_IMAGE,
        advisory=advisory,
        definition_skills_image=definition_skills_image,
    )


def _not_enforceable(path: str) -> tuple[AuditReason, str]:
    """The (reason, path) pair of a tools_not_enforceable denial."""
    return (AuditReason.TOOLS_NOT_ENFORCEABLE, path)


def _pairs(decision: PolicyDecision) -> set[tuple[AuditReason, str]]:
    """Return the (reason, path) pairs of a decision."""
    return {(d.reason, d.path) for d in decision.denials}


def _allowed(decision: PolicyDecision) -> bool:
    """Whether the decision allows, checking it is consistent."""
    assert decision.allowed is (not decision.denials)
    return decision.allowed


# --------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------


def test_principal_always_includes_wildcard_role() -> None:
    """A principal built without '*' still matches wildcard rules."""
    principal = Principal(user_id="u", is_admin=False, roles=frozenset({"dev"}))
    assert "*" in principal.roles


# --------------------------------------------------------------------------
# Hard rule: ephemeral without a spawner
# --------------------------------------------------------------------------


@pytest.mark.parametrize("principal", [ADMIN, USER])
@pytest.mark.parametrize("with_policy", [False, True])
def test_ephemeral_without_spawner_denied_everywhere(
    principal: Principal, with_policy: bool
) -> None:
    """Ephemeral steps need a spawner in every mode, for every caller."""
    decision = _authorize(
        _plan(),
        principal,
        _policy() if with_policy else None,
        spawner_configured=False,
    )
    assert not _allowed(decision)
    assert (AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0") in _pairs(decision)


def test_ephemeral_without_spawner_uses_spawn_pointer_when_set() -> None:
    """An explicit spawn mode is named by its own pointer."""
    decision = _authorize(
        _plan([_step(spawn="ephemeral")]), ADMIN, None, spawner_configured=False
    )
    assert _pairs(decision) == {
        (AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0/spawn")
    }


def test_non_ephemeral_without_spawner_not_hit_by_hard_rule() -> None:
    """Spawn none needs no spawner (admin, no policy)."""
    decision = _authorize(
        _plan([_step(spawn="none")]), ADMIN, None, spawner_configured=False
    )
    assert _allowed(decision)


# --------------------------------------------------------------------------
# No policy (Phase 0a kept, plus inline MCP tightening)
# --------------------------------------------------------------------------


def test_no_policy_baseline_allowed_for_both() -> None:
    """A plain ephemeral step on the default image passes for everyone."""
    for principal in (ADMIN, USER):
        assert _allowed(_authorize(_plan(), principal, None))


def test_no_policy_ignores_provider_skills_tools_sa_namespaces_limits() -> None:
    """Without a policy, grants and limits are not checked at all."""
    step = _step(
        allowed_skills=["skill-x"],
        tools=["tool-x"],
        service_account="sa-x",
        target_namespaces=["ns-x"],
        timeout_seconds=3000,
        max_retries=9,
        permissions=None,
    )
    decision = _authorize(_plan([step], provider="other"), USER, None)
    assert _allowed(decision)


@pytest.mark.parametrize("mode", ["none", "local"])
def test_no_policy_privileged_spawn(mode: str) -> None:
    """Spawn none/local: admin allowed, non-admin denied."""
    plan = _plan([_step(spawn=mode)])
    assert _allowed(_authorize(plan, ADMIN, None))
    decision = _authorize(plan, USER, None)
    assert _pairs(decision) == {
        (AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0/spawn")
    }


def test_no_policy_spec_level_spawn_denied_once() -> None:
    """A spec-level mode inherited by two steps is reported once."""
    plan = _plan([_step(0), _step(1)], spawn="local")
    decision = _authorize(plan, USER, None)
    assert [d.path for d in decision.denials] == ["/definition/spec/spawn"]


def test_no_policy_custom_images() -> None:
    """Custom images: admin allowed (legacy override), non-admin denied."""
    plan = _plan(
        [_step(spawn_config={"sandbox_image": "custom:1"})],
        run_image="custom:2",
    )
    assert _allowed(_authorize(plan, ADMIN, None, definition_skills_image="custom:3"))
    decision = _authorize(plan, USER, None, definition_skills_image="custom:3")
    assert _pairs(decision) == {
        (AuditReason.IMAGE_NOT_ALLOWED, f"{STEPS}/0/spawn_config/sandbox_image"),
        (AuditReason.IMAGE_NOT_ALLOWED, "/sandbox_image"),
        (AuditReason.IMAGE_NOT_ALLOWED, "/definition/skills/image"),
    }


def test_no_policy_default_image_named_explicitly_is_fine() -> None:
    """Naming the default image is not a custom image."""
    plan = _plan(
        [_step(spawn_config={"sandbox_image": DEFAULT_IMAGE})], run_image=DEFAULT_IMAGE
    )
    assert _allowed(_authorize(plan, USER, None))


def test_no_policy_advisory() -> None:
    """Advisory: admin allowed, non-admin denied."""
    assert _allowed(_authorize(_plan(), ADMIN, None, advisory=True))
    decision = _authorize(_plan(), USER, None, advisory=True)
    assert _pairs(decision) == {(AuditReason.POLICY_DENIED, WORKFLOW_ADVISORY_POINTER)}


def test_no_policy_inline_mcp_denied_for_non_admin_only() -> None:
    """Inline MCP is the one tightening: non-admin 403, admin passes through."""
    inline = {"name": "srv", "url": "https://mcp.example", "secret_headers": {}}
    plan = _plan([_step(mcp_servers=["named-srv", inline])])
    assert _allowed(_authorize(plan, ADMIN, None))
    decision = _authorize(plan, USER, None)
    assert _pairs(decision) == {
        (AuditReason.MCP_NOT_ALLOWED, f"{STEPS}/0/mcp_servers/1")
    }


def test_no_policy_spec_inline_mcp_denied_for_non_admin() -> None:
    """Inline MCP inherited from the spec is denied at the spec pointer."""
    plan = _plan([_step()], mcp_servers=[{"name": "srv", "url": "https://x"}])
    decision = _authorize(plan, USER, None)
    assert _pairs(decision) == {
        (AuditReason.MCP_NOT_ALLOWED, "/definition/spec/mcp_servers/0")
    }


def test_no_policy_named_mcp_unchanged() -> None:
    """Named MCP is not checked without a policy."""
    plan = _plan([_step(mcp_servers=["named-srv"])])
    assert _allowed(_authorize(plan, USER, None))


def test_no_policy_non_admin_all_reasons_together() -> None:
    """Every Phase 0a reason is returned in one decision."""
    plan = _plan(
        [
            _step(
                spawn="local",
                spawn_config={"sandbox_image": "custom:1"},
                mcp_servers=[{"name": "srv", "url": "https://x"}],
            )
        ]
    )
    decision = _authorize(plan, USER, None, advisory=True)
    assert {d.reason for d in decision.denials} == {
        AuditReason.SPAWN_MODE_NOT_ALLOWED,
        AuditReason.IMAGE_NOT_ALLOWED,
        AuditReason.POLICY_DENIED,
        AuditReason.MCP_NOT_ALLOWED,
    }


# --------------------------------------------------------------------------
# Policy mode: baseline and deny-by-default
# --------------------------------------------------------------------------


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_policy_baseline_allowed(principal: Principal) -> None:
    """A step inside every grant passes for admin and non-admin."""
    assert _allowed(_authorize(_plan(), principal, _policy()))


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_policy_empty_denies_everything(principal: Principal) -> None:
    """An empty policy denies even admins (no admin exemption)."""
    decision = _authorize(_plan(), principal, WorkflowPolicy(rules=[]))
    reasons = {d.reason for d in decision.denials}
    assert not _allowed(decision)
    assert AuditReason.POLICY_DENIED in reasons  # provider
    assert AuditReason.SPAWN_MODE_NOT_ALLOWED in reasons  # ephemeral not granted
    assert AuditReason.LIMIT_EXCEEDED in reasons


def test_policy_rule_for_other_role_grants_nothing() -> None:
    """Rules for roles the caller lacks do not apply."""
    policy = _policy(_rule(role="ops"))
    assert not _allowed(_authorize(_plan(), ADMIN, policy))


# --------------------------------------------------------------------------
# Policy mode: spawn modes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["none", "local"])
def test_policy_privileged_spawn_admin_needs_grant(mode: str) -> None:
    """Admin spawn none/local needs a grant."""
    plan = _plan([_step(spawn=mode)])
    denied = _authorize(plan, ADMIN, _policy())
    assert _pairs(denied) == {(AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0/spawn")}
    granted = _policy(_rule(spawn_modes=["ephemeral", mode]))
    assert _allowed(_authorize(plan, ADMIN, granted))


@pytest.mark.parametrize("grant", [["none", "local"], ["*"]])
@pytest.mark.parametrize("mode", ["none", "local"])
def test_policy_privileged_spawn_non_admin_denied_even_if_granted(
    mode: str, grant: list[str]
) -> None:
    """A grant of none/local never lets a non-admin through."""
    plan = _plan([_step(spawn=mode)])
    decision = _authorize(plan, USER, _policy(_rule(spawn_modes=grant)))
    assert _pairs(decision) == {
        (AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0/spawn")
    }
    assert "admin" in decision.denials[0].message


def test_policy_ephemeral_needs_grant() -> None:
    """Ephemeral is not implicit; it must be granted."""
    decision = _authorize(_plan(), USER, _policy(_rule(spawn_modes=None)))
    assert _pairs(decision) == {(AuditReason.SPAWN_MODE_NOT_ALLOWED, f"{STEPS}/0")}


# --------------------------------------------------------------------------
# Policy mode: images
# --------------------------------------------------------------------------


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_policy_custom_image_needs_grant(principal: Principal) -> None:
    """The legacy admin image override is broken on purpose."""
    plan = _plan([_step(spawn_config={"sandbox_image": "custom:1"})])
    decision = _authorize(plan, principal, _policy())
    assert _pairs(decision) == {
        (AuditReason.IMAGE_NOT_ALLOWED, f"{STEPS}/0/spawn_config/sandbox_image")
    }
    assert _allowed(_authorize(plan, principal, _policy(_rule(images=["custom:1"]))))
    assert _allowed(_authorize(plan, principal, _policy(_rule(images=["*"]))))


def test_policy_default_image_is_implicit() -> None:
    """The spawner default image needs no rule, even when named."""
    plan = _plan(
        [_step(spawn_config={"sandbox_image": DEFAULT_IMAGE})], run_image=DEFAULT_IMAGE
    )
    assert _allowed(_authorize(plan, USER, _policy()))


def test_policy_run_and_skills_images_need_grant() -> None:
    """Request and skills images are checked like step images."""
    plan = _plan(run_image="custom:2")
    decision = _authorize(plan, USER, _policy(), definition_skills_image="custom:3")
    assert _pairs(decision) == {
        (AuditReason.IMAGE_NOT_ALLOWED, "/sandbox_image"),
        (AuditReason.IMAGE_NOT_ALLOWED, "/definition/skills/image"),
    }
    granted = _policy(_rule(images=["custom:2", "custom:3"]))
    assert _allowed(_authorize(plan, USER, granted, definition_skills_image="custom:3"))


# --------------------------------------------------------------------------
# Policy mode: advisory, MCP, provider
# --------------------------------------------------------------------------


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_policy_advisory_needs_grant(principal: Principal) -> None:
    """Advisory needs a rule with advisory: true."""
    decision = _authorize(_plan(), principal, _policy(), advisory=True)
    assert _pairs(decision) == {(AuditReason.POLICY_DENIED, WORKFLOW_ADVISORY_POINTER)}
    granted = _policy(_rule(), PolicyRule(role="*", advisory=True))
    assert _allowed(_authorize(_plan(), principal, granted, advisory=True))


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_policy_all_mcp_denied(principal: Principal) -> None:
    """Named and inline MCP fail closed in policy mode for everyone."""
    plan = _plan(
        [_step(mcp_servers=["named-srv", {"name": "srv", "url": "https://x"}])]
    )
    decision = _authorize(plan, principal, _policy())
    assert _pairs(decision) == {
        (AuditReason.MCP_NOT_ALLOWED, f"{STEPS}/0/mcp_servers/0"),
        (AuditReason.MCP_NOT_ALLOWED, f"{STEPS}/0/mcp_servers/1"),
    }


def test_policy_empty_mcp_list_is_fine() -> None:
    """An explicit empty MCP list asks for nothing."""
    assert _allowed(_authorize(_plan([_step(mcp_servers=[])]), USER, _policy()))


def test_policy_provider_needs_grant() -> None:
    """The run provider (catalog name) must be granted."""
    decision = _authorize(_plan(provider="other"), USER, _policy())
    assert _pairs(decision) == {(AuditReason.POLICY_DENIED, "/provider")}
    wildcard = _policy(_rule(providers=["*"]))
    assert _allowed(_authorize(_plan(provider="other"), USER, wildcard))


# --------------------------------------------------------------------------
# Policy mode: skills, tools, service accounts, namespaces
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step_key", "grant_key", "value"),
    [
        ("allowed_skills", "skills", "skill-a"),
        ("tools", "tools", "tool-a"),
        ("target_namespaces", "namespaces", "ns-a"),
    ],
)
def test_policy_list_grants(step_key: str, grant_key: str, value: str) -> None:
    """Each named entry needs a grant; '*' grants any; [] and None grant none."""
    step_values: dict[str, Any] = {step_key: ["ok", value]}
    plan = _plan([_step(**step_values)])
    path = f"{STEPS}/0/{step_key}/1"
    for grant in (None, [], ["ok"]):
        grants: dict[str, Any] = {grant_key: grant}
        decision = _authorize(plan, USER, _policy(_rule(**grants)))
        expected = {(AuditReason.POLICY_DENIED, f"{STEPS}/0/{step_key}/0")}
        if grant == ["ok"]:
            expected = set()
        if grant_key == "tools":
            expected.add(_not_enforceable(f"{STEPS}/0/permissions"))
        assert _pairs(decision) == expected | {(AuditReason.POLICY_DENIED, path)}
    for grant in (["*"], ["ok", value]):
        grants = {grant_key: grant}
        decision = _authorize(plan, USER, _policy(_rule(**grants)))
        if grant_key == "tools" and grant != ["*"]:
            # Named tools cover the names, not the missing enforcement.
            assert _pairs(decision) == {_not_enforceable(f"{STEPS}/0/permissions")}
        else:
            assert _allowed(decision)


def _tool_step(allowed: list[str], **extra: Any) -> dict[str, Any]:
    """Build a step whose permissions carry allowed_tools."""
    return _step(permissions={"max_tokens": 100, "allowed_tools": allowed}, **extra)


def test_policy_allowed_tools_without_grant_denied() -> None:
    """Ephemeral steps send permissions.allowed_tools to the sandbox: gated."""
    plan = _plan([_tool_step(["Bash", "Write"])])
    for grant in (None, [], ["Bash"]):
        grants: dict[str, Any] = {"tools": grant}
        decision = _authorize(plan, USER, _policy(_rule(**grants)))
        expected = {
            (AuditReason.POLICY_DENIED, f"{STEPS}/0/permissions/allowed_tools/1")
        }
        if grant != ["Bash"]:
            expected.add(
                (AuditReason.POLICY_DENIED, f"{STEPS}/0/permissions/allowed_tools/0")
            )
        expected.add(_not_enforceable(f"{STEPS}/0/permissions"))
        assert _pairs(decision) == expected


def test_policy_allowed_tools_granted_and_wildcard_allowed() -> None:
    """A named or wildcard tools grant allows allowed_tools."""
    plan = _plan([_tool_step(["Bash", "Write"])])
    assert _allowed(_authorize(plan, USER, _policy(_rule(tools=["*"]))))
    # A finite grant covers the names but not the missing enforcement.
    decision = _authorize(plan, USER, _policy(_rule(tools=["Bash", "Write"])))
    assert _pairs(decision) == {_not_enforceable(f"{STEPS}/0/permissions")}


def test_policy_allowed_tools_empty_needs_no_grant() -> None:
    """Empty or absent allowed_tools needs no grant."""
    plan = _plan([_tool_step([])])
    assert _allowed(_authorize(plan, USER, _policy()))


def test_policy_step_tools_still_checked_alongside_allowed_tools() -> None:
    """step.tools and permissions.allowed_tools are both checked."""
    plan = _plan([_tool_step(["Bash"], tools=["tool-a"])])
    decision = _authorize(plan, USER, _policy(_rule(tools=["Bash"])))
    assert _pairs(decision) == {
        (AuditReason.POLICY_DENIED, f"{STEPS}/0/tools/0"),
        _not_enforceable(f"{STEPS}/0/permissions"),
    }


def test_policy_allowed_tools_whole_object_permissions_replace_spec() -> None:
    """Step permissions replace spec permissions, including allowed_tools."""
    plan = _plan(
        [_step(permissions={"max_tokens": 100}), _step(1, permissions=None)],
        permissions={"max_tokens": 100, "allowed_tools": ["Bash"]},
    )
    decision = _authorize(plan, USER, _policy(_rule(tools=None)))
    assert _pairs(decision) == {
        (AuditReason.POLICY_DENIED, "/definition/spec/permissions/allowed_tools/0"),
        _not_enforceable(f"{STEPS}/0/permissions"),
        _not_enforceable("/definition/spec/permissions"),
    }


def test_policy_denied_tools_is_restrictive_and_needs_no_grant() -> None:
    """denied_tools only restricts, so it needs no tools grant."""
    plan = _plan([_step(permissions={"max_tokens": 100, "denied_tools": ["Bash"]})])
    assert _allowed(_authorize(plan, USER, _policy()))


def test_limits_distinct_denials_sharing_a_path_are_all_returned() -> None:
    """Timeout and max_tokens denials that fall back to one path both show."""
    policy = _limits_policy(
        PolicyLimits(
            max_step_timeout_seconds=300, max_workflow_seconds=10_000, max_tokens=10
        )
    )
    plan = _plan([_step(timeout_seconds=None, permissions=None)])
    decision = _authorize(plan, USER, policy)
    messages = [d.message for d in decision.denials if d.path == f"{STEPS}/0"]
    assert any("timeout_seconds" in m for m in messages)
    assert any("max_tokens" in m for m in messages)


@pytest.mark.parametrize("step_key", ["allowed_skills", "tools", "target_namespaces"])
def test_policy_list_values_unset_or_empty_need_nothing(step_key: str) -> None:
    """A step that names nothing needs no grant (no implicit grants either)."""
    empty: dict[str, Any] = {step_key: []}
    assert _allowed(_authorize(_plan([_step(**empty)]), USER, _policy()))
    assert _allowed(_authorize(_plan([_step()]), USER, _policy()))


def test_policy_service_account_needs_grant() -> None:
    """A named service account needs a grant."""
    plan = _plan([_step(service_account="sa-a")])
    decision = _authorize(plan, USER, _policy())
    assert _pairs(decision) == {
        (AuditReason.POLICY_DENIED, f"{STEPS}/0/service_account")
    }
    assert _allowed(_authorize(plan, USER, _policy(_rule(service_accounts=["sa-a"]))))


def test_policy_permissions_service_account_needs_grant() -> None:
    """A service account in permissions is named by its pointer."""
    plan = _plan([_step(permissions={"max_tokens": 10, "service_account": "sa-b"})])
    decision = _authorize(plan, USER, _policy())
    assert _pairs(decision) == {
        (AuditReason.POLICY_DENIED, f"{STEPS}/0/permissions/service_account")
    }


@pytest.mark.parametrize("value", [None, ""])
def test_policy_default_service_account_is_implicit(value: Optional[str]) -> None:
    """Unset and empty-string service accounts get the implicit default grant."""
    plan = _plan([_step(service_account=value)])
    assert _allowed(_authorize(plan, USER, _policy()))
    plan = _plan([_step(permissions={"max_tokens": 10, "service_account": value})])
    assert _allowed(_authorize(plan, USER, _policy()))


def test_policy_configured_default_service_account_is_implicit() -> None:
    """A spawner default service account named explicitly needs no rule."""
    plan = _plan([_step(service_account="default-sa")])
    decision = authorize_workflow_submission(
        plan,
        USER,
        _policy(),
        spawner_configured=True,
        default_sandbox_image=DEFAULT_IMAGE,
        default_service_account="default-sa",
    )
    assert _allowed(decision)


# --------------------------------------------------------------------------
# Policy mode: tools are not enforceable on ephemeral steps
#
# The sandbox consumer has no allowedTools/deniedTools fields, always passes
# its default tool list and runs with bypassPermissions, so a finite tools
# grant cannot be honoured. Only an explicit wildcard grant authorizes
# ephemeral execution (see examples/workflows/README.md).
# --------------------------------------------------------------------------

REQUESTED: dict[str, Any] = {
    "omitted": {"max_tokens": 1000},
    "null": {"max_tokens": 1000, "allowed_tools": None},
    "empty": {"max_tokens": 1000, "allowed_tools": []},
    "named": {"max_tokens": 1000, "allowed_tools": ["Bash"]},
}
GRANTS: dict[str, Any] = {
    "missing": None,
    "empty": [],
    "finite": ["Bash"],
    "wildcard": ["*"],
}


@pytest.mark.parametrize("grant_id", list(GRANTS))
@pytest.mark.parametrize("requested_id", list(REQUESTED))
def test_ephemeral_tools_matrix(requested_id: str, grant_id: str) -> None:
    """Ephemeral steps pass only on a wildcard grant, whatever is requested."""
    plan = _plan([_step(permissions=REQUESTED[requested_id])])
    policy = _policy(_rule(tools=GRANTS[grant_id]))
    decision = _authorize(plan, USER, policy)
    if grant_id == "wildcard":
        assert _allowed(decision)
        return
    expected = {_not_enforceable(f"{STEPS}/0/permissions")}
    if requested_id == "named" and grant_id != "finite":
        expected.add(
            (AuditReason.POLICY_DENIED, f"{STEPS}/0/permissions/allowed_tools/0")
        )
    assert _pairs(decision) == expected
    message = next(
        d.message
        for d in decision.denials
        if d.reason is AuditReason.TOOLS_NOT_ENFORCEABLE
    )
    assert "wildcard" in message and "does not promise" in message


def test_ephemeral_finite_grant_is_never_promoted_to_wildcard() -> None:
    """A finite grant that covers every requested name is still denied."""
    plan = _plan([_step(tools=["a"], permissions=REQUESTED["named"])])
    decision = _authorize(plan, USER, _policy(_rule(tools=["a", "Bash"])))
    assert not _allowed(decision)
    assert _pairs(decision) == {_not_enforceable(f"{STEPS}/0/permissions")}
    # An unrelated name stays denied, so the grant did not become '*'.
    other = _plan([_step(tools=["zzz"], permissions=REQUESTED["named"])])
    assert (
        AuditReason.POLICY_DENIED,
        f"{STEPS}/0/tools/0",
    ) in _pairs(_authorize(other, USER, _policy(_rule(tools=["a", "Bash"]))))


def test_ephemeral_tools_denial_points_at_step_when_permissions_defaulted() -> None:
    """With no permissions object anywhere the denial points at the step."""
    plan = _plan([_step(permissions=None)])
    decision = _authorize(plan, USER, _policy(_rule(tools=None)))
    assert _not_enforceable(f"{STEPS}/0") in _pairs(decision)


def test_ephemeral_tools_denial_points_at_spec_permissions_when_inherited() -> None:
    """Spec-level permissions are taken whole, so the denial names them."""
    plan = _plan([_step(permissions=None)], permissions={"max_tokens": 1000})
    decision = _authorize(plan, USER, _policy(_rule(tools=["Bash"])))
    assert _pairs(decision) == {_not_enforceable("/definition/spec/permissions")}


def test_ephemeral_tools_denial_reported_once_per_step_with_others() -> None:
    """Two steps each get a denial and other violations are returned too."""
    plan = _plan(
        [_step(0), _step(1, permissions={"max_tokens": 1000, "allowed_tools": ["x"]})],
        provider=PROVIDER,
    )
    policy = _policy(_rule(tools=None, providers=["other"]))
    decision = _authorize(plan, USER, policy, advisory=True)
    pairs = _pairs(decision)
    assert _not_enforceable(f"{STEPS}/0/permissions") in pairs
    assert _not_enforceable(f"{STEPS}/1/permissions") in pairs
    assert (AuditReason.POLICY_DENIED, "/provider") in pairs
    assert (AuditReason.POLICY_DENIED, WORKFLOW_ADVISORY_POINTER) in pairs
    assert (
        AuditReason.POLICY_DENIED,
        f"{STEPS}/1/permissions/allowed_tools/0",
    ) in pairs


def test_ephemeral_tools_denial_for_admin_too() -> None:
    """Admins get no exemption: there is no enforcement to rely on."""
    plan = _plan()
    decision = _authorize(plan, ADMIN, _policy(_rule(tools=["Bash"])))
    assert _pairs(decision) == {_not_enforceable(f"{STEPS}/0/permissions")}


def test_ephemeral_wildcard_covers_finite_requests_without_promising_them() -> None:
    """Wildcard passes even a finite allowed_tools (it is not enforced)."""
    plan = _plan([_step(permissions={"max_tokens": 1, "allowed_tools": ["Bash"]})])
    assert _allowed(_authorize(plan, USER, _policy(_rule(tools=["*"]))))


def test_wildcard_from_any_unioned_rule_authorizes() -> None:
    """The union closure decides: a wildcard in an inherited rule is enough."""
    policy = _policy(
        _rule(tools=None),
        PolicyRule(role="dev", inherit=["ops"]),
        PolicyRule(role="ops", tools=["*"]),
    )
    dev = Principal(user_id="d", is_admin=False, roles=frozenset({"dev"}))
    assert _allowed(_authorize(_plan(), dev, policy))
    assert not _allowed(_authorize(_plan(), USER, policy))


@pytest.mark.parametrize("mode", ["none", "local"])
@pytest.mark.parametrize("grant_id", ["missing", "finite", "wildcard"])
def test_non_ephemeral_steps_keep_the_step_tools_checks(
    mode: str, grant_id: str
) -> None:
    """spawn none/local never gets the new denial; step.tools is checked."""
    plan = _plan([_step(spawn=mode, tools=["tool-a"])])
    policy = _policy(_rule(tools=GRANTS[grant_id], spawn_modes=[mode]))
    decision = _authorize(plan, ADMIN, policy)
    assert AuditReason.TOOLS_NOT_ENFORCEABLE not in decision.reasons
    expected = (
        set()
        if grant_id == "wildcard"
        else {(AuditReason.POLICY_DENIED, f"{STEPS}/0/tools/0")}
    )
    assert _pairs(decision) == expected


def test_non_ephemeral_without_any_tools_grant_is_allowed() -> None:
    """Omitted step.tools on none/local means no tools: nothing to grant."""
    plan = _plan([_step(spawn="local")])
    policy = _policy(_rule(tools=None, spawn_modes=["local"]))
    assert _allowed(_authorize(plan, ADMIN, policy))


def test_mixed_spawn_modes_only_ephemeral_steps_are_denied() -> None:
    """Only the ephemeral step of a mixed workflow gets the denial."""
    plan = _plan([_step(0, spawn="local"), _step(1)])
    policy = _policy(_rule(tools=None, spawn_modes=["local", "ephemeral"]))
    decision = _authorize(plan, ADMIN, policy)
    assert _pairs(decision) == {_not_enforceable(f"{STEPS}/1/permissions")}


@pytest.mark.parametrize("principal", [ADMIN, USER])
def test_no_policy_never_adds_tools_not_enforceable(principal: Principal) -> None:
    """No-policy mode is unchanged: tools are not checked at all."""
    plan = _plan([_step(tools=["x"], permissions=REQUESTED["named"])])
    assert _allowed(_authorize(plan, principal, None))


# --------------------------------------------------------------------------
# Policy mode: grant union, inherit closure, user isolation
# --------------------------------------------------------------------------


def test_policy_union_across_rules_and_roles() -> None:
    """Grants from all matching rules are unioned; bools OR."""
    policy = _policy(
        _rule(),
        PolicyRule(role="dev", skills=["skill-a"]),
        PolicyRule(role="*", skills=["skill-b"]),
        PolicyRule(role="dev", advisory=True),
    )
    dev = Principal(user_id="d", is_admin=False, roles=frozenset({"dev"}))
    plan = _plan([_step(allowed_skills=["skill-a", "skill-b"])])
    assert _allowed(_authorize(plan, dev, policy, advisory=True))
    assert _pairs(_authorize(plan, USER, policy, advisory=True)) == {
        (AuditReason.POLICY_DENIED, f"{STEPS}/0/allowed_skills/0"),
        (AuditReason.POLICY_DENIED, WORKFLOW_ADVISORY_POINTER),
    }


def test_policy_inherit_closure() -> None:
    """A role gets everything its inherit closure grants, transitively."""
    policy = _policy(
        PolicyRule(role="base", providers=[PROVIDER], spawn_modes=["ephemeral"]),
        PolicyRule(role="mid", inherit=["base"], limits=FULL_LIMITS),
        PolicyRule(role="top", inherit=["mid"], tools=["*"]),
    )
    top = Principal(user_id="t", is_admin=False, roles=frozenset({"top"}))
    mid = Principal(user_id="m", is_admin=False, roles=frozenset({"mid"}))
    plan = _plan([_step(tools=["tool-a"])])
    assert _allowed(_authorize(plan, top, policy))
    assert _pairs(_authorize(plan, mid, policy)) == {
        (AuditReason.POLICY_DENIED, f"{STEPS}/0/tools/0"),
        _not_enforceable(f"{STEPS}/0/permissions"),
    }


def test_policy_user_isolation() -> None:
    """Two principals on different roles never share grants."""
    policy = _policy(
        _rule(role="team-a", images=["img-a"]),
        _rule(role="team-b", images=["img-b"]),
    )
    user_a = Principal(user_id="a", is_admin=False, roles=frozenset({"team-a"}))
    user_b = Principal(user_id="b", is_admin=False, roles=frozenset({"team-b"}))
    plan_a = _plan([_step(spawn_config={"sandbox_image": "img-a"})])
    plan_b = _plan([_step(spawn_config={"sandbox_image": "img-b"})])
    assert _allowed(_authorize(plan_a, user_a, policy))
    assert _allowed(_authorize(plan_b, user_b, policy))
    assert not _allowed(_authorize(plan_b, user_a, policy))
    assert not _allowed(_authorize(plan_a, user_b, policy))
    # Order of evaluation does not leak state between calls.
    assert _allowed(_authorize(plan_a, user_a, policy))


# --------------------------------------------------------------------------
# Policy mode: numeric limits
# --------------------------------------------------------------------------


def _limits_policy(*limits: PolicyLimits) -> WorkflowPolicy:
    """Policy with the baseline grants and the given limit rules only."""
    rules = [_rule(limits=PolicyLimits())] + [
        PolicyRule(role="*", limits=lim) for lim in limits
    ]
    return WorkflowPolicy(rules=rules)


def _limit_paths(decision: PolicyDecision) -> set[str]:
    """Paths of limit denials."""
    return {d.path for d in decision.denials if d.reason is AuditReason.LIMIT_EXCEEDED}


def test_limits_absent_deny_every_agent_step() -> None:
    """No limit grants means every agent step is denied (absent = 0)."""
    decision = _authorize(_plan(), USER, _limits_policy())
    assert _limit_paths(decision) == {
        f"{STEPS}/0/timeout_seconds",
        f"{STEPS}/0/permissions",  # permissions.timeout_seconds defaults to 600
        f"{STEPS}/0/permissions/max_tokens",
        STEPS,  # declared workflow budget
    }


def test_limits_approval_only_workflow_needs_no_limits() -> None:
    """Approval steps are excluded from step limits and the budget."""
    plan = _plan([{"name": "gate", "type": "human-approval", "output_key": "g"}])
    assert _allowed(_authorize(plan, USER, _limits_policy()))


def test_limit_step_timeout_max_over_rules() -> None:
    """Effective step timeout is the max over rules."""
    policy = _limits_policy(
        PolicyLimits(max_step_timeout_seconds=30),
        PolicyLimits(
            max_step_timeout_seconds=600, max_workflow_seconds=3600, max_tokens=10_000
        ),
    )
    assert _allowed(_authorize(_plan([_step(timeout_seconds=600)]), USER, policy))
    decision = _authorize(_plan([_step(timeout_seconds=601)]), USER, policy)
    assert _limit_paths(decision) == {f"{STEPS}/0/timeout_seconds"}


def test_limit_step_timeout_omitted_checks_600() -> None:
    """Omitted step and permissions timeouts are checked as 600."""
    policy = _limits_policy(
        PolicyLimits(
            max_step_timeout_seconds=599, max_workflow_seconds=3600, max_tokens=10_000
        )
    )
    plan = _plan([_step(timeout_seconds=None, permissions={"max_tokens": 10})])
    assert _limit_paths(_authorize(plan, USER, policy)) == {
        f"{STEPS}/0",
        f"{STEPS}/0/permissions",
    }


def test_limit_permissions_timeout_checked() -> None:
    """permissions.timeout_seconds is checked against the step limit."""
    policy = _limits_policy(
        PolicyLimits(
            max_step_timeout_seconds=300, max_workflow_seconds=3600, max_tokens=10_000
        )
    )
    ok = _plan([_step(permissions={"max_tokens": 10, "timeout_seconds": 300})])
    assert _allowed(_authorize(ok, USER, policy))
    bad = _plan([_step(permissions={"max_tokens": 10, "timeout_seconds": 301})])
    assert _limit_paths(_authorize(bad, USER, policy)) == {
        f"{STEPS}/0/permissions/timeout_seconds"
    }


def test_limit_step_timeout_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The effective step timeout never exceeds the hard cap."""
    monkeypatch.setattr("workflow.policy.MAX_POLICY_STEP_TIMEOUT_SECONDS", 100)
    plan = _plan([_step(permissions={"max_tokens": 10, "timeout_seconds": 100})])
    assert _allowed(_authorize(plan, USER, _policy()))
    plan = _plan(
        [
            _step(
                timeout_seconds=101,
                permissions={"max_tokens": 10, "timeout_seconds": 1},
            )
        ]
    )
    assert _limit_paths(_authorize(plan, USER, _policy())) == {
        f"{STEPS}/0/timeout_seconds"
    }


def test_limit_retries() -> None:
    """No retries grant: only 0 passes; otherwise the max over rules."""
    no_grant = _policy(
        _rule(limits=FULL_LIMITS.model_copy(update={"max_retries": None}))
    )
    assert _allowed(_authorize(_plan([_step(max_retries=0)]), USER, no_grant))
    decision = _authorize(_plan([_step(max_retries=1)]), USER, no_grant)
    assert _limit_paths(decision) == {f"{STEPS}/0/max_retries"}
    two = _policy(_rule(), PolicyRule(role="*", limits=PolicyLimits(max_retries=1)))
    assert _allowed(_authorize(_plan([_step(max_retries=2)]), USER, two))
    assert not _allowed(_authorize(_plan([_step(max_retries=3)]), USER, two))


def test_limit_retries_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The effective retry limit never exceeds the hard cap."""
    monkeypatch.setattr("workflow.policy.MAX_POLICY_RETRIES", 1)
    assert _allowed(_authorize(_plan([_step(max_retries=1)]), USER, _policy()))
    assert not _allowed(_authorize(_plan([_step(max_retries=2)]), USER, _policy()))


def test_limit_workflow_budget() -> None:
    """The declared budget sums timeout x (retries + 1) over agent steps."""
    policy = _policy(
        _rule(limits=FULL_LIMITS.model_copy(update={"max_workflow_seconds": 360}))
    )
    gate = {"name": "gate", "type": "human-approval", "output_key": "g"}
    # 60 x 3 + 60 x 3 = 360, approval excluded.
    ok = _plan([_step(0, max_retries=2), gate, _step(2, max_retries=2)])
    assert _allowed(_authorize(ok, USER, policy))
    bad = _plan(
        [_step(0, max_retries=2), gate, _step(2, timeout_seconds=61, max_retries=2)]
    )
    assert _limit_paths(_authorize(bad, USER, policy)) == {STEPS}


def test_limit_workflow_budget_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The effective workflow budget never exceeds the hard cap."""
    monkeypatch.setattr("workflow.policy.MAX_POLICY_WORKFLOW_SECONDS", 59)
    assert _limit_paths(_authorize(_plan(), USER, _policy())) == {STEPS}


def test_limit_max_tokens() -> None:
    """max_tokens must be declared and within the max over rules."""
    policy = _policy(
        _rule(limits=FULL_LIMITS.model_copy(update={"max_tokens": 100})),
        PolicyRule(role="*", limits=PolicyLimits(max_tokens=500)),
    )
    ok = _plan([_step(permissions={"max_tokens": 500})])
    assert _allowed(_authorize(ok, USER, policy))
    bad = _plan([_step(permissions={"max_tokens": 501})])
    assert _limit_paths(_authorize(bad, USER, policy)) == {
        f"{STEPS}/0/permissions/max_tokens"
    }


def test_limit_max_tokens_omitted_denied() -> None:
    """Omitted max_tokens asks for unlimited and is always denied."""
    plan = _plan([_step(permissions=None)])
    decision = _authorize(plan, ADMIN, _policy())
    assert _limit_paths(decision) == {f"{STEPS}/0"}
    plan = _plan([_step(permissions={"timeout_seconds": 60})])
    assert _limit_paths(_authorize(plan, ADMIN, _policy())) == {
        f"{STEPS}/0/permissions"
    }


def test_limit_max_tokens_no_grant_denied() -> None:
    """No max_tokens grant denies any declared value."""
    policy = _policy(_rule(limits=FULL_LIMITS.model_copy(update={"max_tokens": None})))
    decision = _authorize(_plan([_step(permissions={"max_tokens": 1})]), USER, policy)
    assert _limit_paths(decision) == {f"{STEPS}/0/permissions/max_tokens"}


def test_limit_max_tokens_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The effective token limit never exceeds the hard cap."""
    monkeypatch.setattr("workflow.policy.MAX_POLICY_TOKENS", 999)
    assert not _allowed(
        _authorize(_plan([_step(permissions={"max_tokens": 1000})]), USER, _policy())
    )


def test_limits_spec_level_inherited_timeout_reported_once() -> None:
    """A spec timeout inherited by two steps is one denial at the spec pointer."""
    policy = _policy(
        _rule(
            limits=FULL_LIMITS.model_copy(update={"max_step_timeout_seconds": 100}),
        )
    )
    steps = [
        _step(
            0, timeout_seconds=None, permissions={"max_tokens": 1, "timeout_seconds": 1}
        ),
        _step(
            1, timeout_seconds=None, permissions={"max_tokens": 1, "timeout_seconds": 1}
        ),
    ]
    decision = _authorize(_plan(steps, timeout_seconds=200), USER, policy)
    assert [d.path for d in decision.denials] == ["/definition/spec/timeout_seconds"]


# --------------------------------------------------------------------------
# All reasons together; audit-safe fields
# --------------------------------------------------------------------------


def _canary_plan() -> EffectivePlan:
    """A plan that puts the canary into every caller-controlled value."""
    step = _step(
        name=CANARY,
        output_key=CANARY,
        prompt=CANARY,
        spawn="local",
        allowed_skills=[CANARY],
        tools=[CANARY],
        target_namespaces=[CANARY],
        service_account=CANARY,
        spawn_config={"sandbox_image": CANARY},
        mcp_servers=[CANARY, {"name": CANARY, "url": f"https://{CANARY}"}],
        timeout_seconds=99_999,
        max_retries=99,
        permissions=None,
    )
    return _plan([step], provider=CANARY, run_image=CANARY)


def test_policy_returns_all_reasons_together() -> None:
    """Every failing check appears in one decision."""
    decision = _authorize(
        _canary_plan(),
        USER,
        WorkflowPolicy(rules=[]),
        advisory=True,
        definition_skills_image=CANARY,
    )
    assert {d.reason for d in decision.denials} == {
        AuditReason.POLICY_DENIED,
        AuditReason.SPAWN_MODE_NOT_ALLOWED,
        AuditReason.IMAGE_NOT_ALLOWED,
        AuditReason.MCP_NOT_ALLOWED,
        AuditReason.LIMIT_EXCEEDED,
    }
    assert {d.path for d in decision.denials} == {
        "/provider",
        WORKFLOW_ADVISORY_POINTER,
        "/sandbox_image",
        "/definition/skills/image",
        STEPS,
        f"{STEPS}/0",
        f"{STEPS}/0/spawn",
        f"{STEPS}/0/spawn_config/sandbox_image",
        f"{STEPS}/0/service_account",
        f"{STEPS}/0/allowed_skills/0",
        f"{STEPS}/0/tools/0",
        f"{STEPS}/0/target_namespaces/0",
        f"{STEPS}/0/mcp_servers/0",
        f"{STEPS}/0/mcp_servers/1",
        f"{STEPS}/0/timeout_seconds",
        f"{STEPS}/0/max_retries",
    }
    assert decision.reasons == tuple(dict.fromkeys(d.reason for d in decision.denials))
    assert decision.paths == tuple(d.path for d in decision.denials)


@pytest.mark.parametrize(
    ("principal", "policy"),
    [(ADMIN, None), (USER, None), (ADMIN, "empty"), (USER, "empty")],
)
def test_audit_safe_fields_never_carry_caller_strings(
    principal: Principal, policy: Optional[str]
) -> None:
    """Reasons and paths come from enums and plan pointers, never caller input."""
    decision = _authorize(
        _canary_plan(),
        principal,
        WorkflowPolicy(rules=[]) if policy else None,
        spawner_configured=False,
        advisory=True,
        definition_skills_image=CANARY,
    )
    for denial in decision.denials:
        assert isinstance(denial.reason, AuditReason)
        assert CANARY not in denial.path
        assert denial.path.startswith("/")
    assert all(CANARY not in p for p in decision.paths)
    assert all(CANARY not in r.value for r in decision.reasons)


def test_messages_may_name_denied_values() -> None:
    """The caller-facing message may name the denied value."""
    plan = _plan([_step(spawn_config={"sandbox_image": "custom:1"})])
    decision = _authorize(plan, USER, _policy())
    assert "custom:1" in decision.denials[0].message
