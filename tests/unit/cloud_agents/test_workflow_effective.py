"""Unit tests for the effective workflow plan (issue #51, Phase 2, T2).

Wherever the installed cloud-agents executor exposes the function, the tests
run the real executor over the same fixture and compare it with
``EffectivePlan`` field by field, so the plan cannot drift from what the
runner will actually do.
"""

# pylint: disable=too-many-locals

from __future__ import annotations

import copy
from typing import Any, Optional

import pytest
from cloud_agents.workflow.core.execution import (
    build_step_input,
    normalize_workflow_step,
    workflow_defaults_from_definition,
)
from cloud_agents.workflow.core.execution import (
    normalize_definition as executor_normalize_definition,
)

from workflow.catalog import ResolvedProvider
from workflow.effective import (
    DEFAULT_STEP_TIMEOUT_SECONDS,
    EXECUTOR_DEFAULT_SANDBOX_IMAGE,
    REASON_INVALID_VALUE,
    REASON_SERVICE_ACCOUNT_CONFLICT,
    EffectivePlan,
    EffectivePlanError,
    ImageSource,
    build_effective_plan,
)

SPAWNER_IMAGE = "spawner-default:v1"
RUN_PROVIDER = ResolvedProvider(
    catalog_name="corp-openai",
    executor_type="openai",
    model="gpt-4o",
    credential_ref=None,
    provider={"name": "openai", "model": "gpt-4o"},
)
STEPS = "/definition/spec/steps"


def _step(name: str = "agent", **extra: Any) -> dict[str, Any]:
    """Build a minimal agent step."""
    return {
        "name": name,
        "type": "agent",
        "prompt": "Do it",
        "output_key": f"{name}_out",
        **extra,
    }


def _approval(name: str = "gate") -> dict[str, Any]:
    """Build a minimal human-approval step."""
    return {
        "name": name,
        "type": "human-approval",
        "message": "ok?",
        "output_key": f"{name}_out",
    }


def _definition(
    steps: Optional[list[dict[str, Any]]] = None, **spec: Any
) -> dict[str, Any]:
    """Build a definition; ``spec`` keys land under ``spec``."""
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "wf"},
        "spec": {"steps": steps if steps is not None else [_step()], **spec},
    }


def _plan(
    definition: dict[str, Any],
    run_sandbox_image: Optional[str] = None,
    spawner_default_image: Optional[str] = SPAWNER_IMAGE,
    run_skills_image: Optional[str] = None,
) -> EffectivePlan:
    """Build the plan with test defaults."""
    return build_effective_plan(
        definition,
        RUN_PROVIDER,
        run_sandbox_image=run_sandbox_image,
        spawner_default_image=spawner_default_image,
        run_skills_image=run_skills_image,
    )


def _run_context(
    run_image: Optional[str], skills_image: Optional[str] = None
) -> dict[str, Any]:
    """Build the run context the local runner hands to build_step_input."""
    return {
        "provider": {},
        "sandbox_image": run_image,
        "skills_image": skills_image,
    }


def _assert_matches_executor(
    definition: dict[str, Any],
    plan: EffectivePlan,
    run_image: Optional[str],
    skills_image: Optional[str] = None,
) -> None:
    """Compare every plan step with the real executor, field by field."""
    raw_steps = definition["spec"]["steps"]
    defaults = workflow_defaults_from_definition(definition)
    normalized_steps, _ = executor_normalize_definition(copy.deepcopy(definition))
    agent_indices = [
        i for i, s in enumerate(raw_steps) if s.get("type") != "human-approval"
    ]
    assert [s.index for s in plan.steps] == agent_indices
    assert len(normalized_steps) == len(plan.steps)
    for normalized, step_plan in zip(normalized_steps, plan.steps):
        raw = raw_steps[step_plan.index]
        step_input = build_step_input(
            copy.deepcopy(raw),
            _run_context(run_image, skills_image),
            workflow_defaults=defaults,
            step_count=len(raw_steps),
        )
        _, meta = normalize_workflow_step(
            copy.deepcopy(raw), workflow_defaults=defaults, step_count=len(raw_steps)
        )
        scope = normalized.permissions
        assert step_plan.spawn.value == normalized.spawn
        assert step_plan.sandbox_image.value == step_input.sandbox_image
        assert step_plan.timeout_seconds.value == step_input.timeout_seconds
        assert step_plan.service_account.value == (
            scope.service_account if scope else None
        )
        assert step_plan.permissions_timeout_seconds.value == (
            scope.timeout_seconds if scope else None
        )
        assert step_plan.max_tokens.value == (scope.max_tokens if scope else None)
        assert step_plan.max_retries.value == normalized.max_retries
        assert step_plan.tools.value == tuple(normalized.tools)
        expected_allowed = scope.allowed_tools if scope else None
        assert step_plan.allowed_tools.value == (
            None if expected_allowed is None else tuple(expected_allowed)
        )
        expected_skills = normalized.allowed_skills
        assert step_plan.allowed_skills.value == (
            None if expected_skills is None else tuple(expected_skills)
        )
        expected_ns = meta.get("target_namespaces")
        assert step_plan.target_namespaces.value == (
            None if expected_ns is None else tuple(expected_ns)
        )
        assert plan.skills_image.value == step_input.skills_image
        expected_spawn_config = (
            normalized.spawn_config.model_dump() if normalized.spawn_config else None
        )
        assert step_plan.spawn_config.value == expected_spawn_config


# --- service account -------------------------------------------------------


def test_sa_conflict_real_normalizer() -> None:
    """A cross-layer SA conflict fails in the executor and in the plan."""
    definition = _definition(
        [_step(service_account="sa-b")],
        permissions={"service_account": "sa-a"},
    )
    with pytest.raises(ValueError):
        executor_normalize_definition(copy.deepcopy(definition))

    with pytest.raises(EffectivePlanError) as exc_info:
        _plan(definition)
    exc = exc_info.value
    assert exc.reason == REASON_SERVICE_ACCOUNT_CONFLICT
    assert exc.path == f"{STEPS}/0/service_account"
    assert exc.conflicting_path == "/definition/spec/permissions/service_account"
    for text in (str(exc), repr(exc), str(exc.args)):
        assert "sa-a" not in text
        assert "sa-b" not in text
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_sa_conflict_same_layer_spec() -> None:
    """Spec-level permissions SA vs spec-level legacy SA also conflicts."""
    definition = _definition(
        [_step()],
        service_account="sa-b",
        permissions={"service_account": "sa-a"},
    )
    with pytest.raises(ValueError):
        executor_normalize_definition(copy.deepcopy(definition))
    with pytest.raises(EffectivePlanError) as exc_info:
        _plan(definition)
    assert exc_info.value.reason == REASON_SERVICE_ACCOUNT_CONFLICT
    assert exc_info.value.path == "/definition/spec/service_account"


def test_sa_conflict_empty_permissions_sa_matches_executor() -> None:
    """An empty permissions SA still conflicts with a legacy SA (executor rule)."""
    definition = _definition(
        [_step(service_account="sa-b", permissions={"service_account": ""})]
    )
    with pytest.raises(ValueError):
        executor_normalize_definition(copy.deepcopy(definition))
    with pytest.raises(EffectivePlanError) as exc_info:
        _plan(definition)
    assert exc_info.value.reason == REASON_SERVICE_ACCOUNT_CONFLICT


@pytest.mark.parametrize(
    ("steps", "spec", "expected_sa", "expected_path"),
    [
        pytest.param(
            [_step(service_account="sa-a")],
            {"permissions": {"service_account": "sa-a"}},
            "sa-a",
            "/definition/spec/permissions/service_account",
            id="equal-values",
        ),
        pytest.param(
            [_step(permissions={"max_tokens": 10})],
            {"service_account": "sa-spec"},
            "sa-spec",
            "/definition/spec/service_account",
            id="step-perms-without-sa-plus-spec-sa",
        ),
        pytest.param(
            [_step(permissions={"max_tokens": 10})],
            {"permissions": {"service_account": "sa-spec"}},
            None,
            None,
            id="step-perms-replace-spec-perms-with-sa",
        ),
        pytest.param(
            [_step(service_account="sa-b", permissions={"max_tokens": 10})],
            {"permissions": {"service_account": "sa-a"}},
            "sa-b",
            f"{STEPS}/0/service_account",
            id="step-perms-hide-spec-sa-so-no-conflict",
        ),
        pytest.param(
            [_step(service_account="")],
            {"service_account": "sa-spec"},
            None,
            None,
            id="empty-step-sa-shadows-spec-sa",
        ),
        pytest.param(
            [_step(service_account="", permissions={"service_account": "sa-p"})],
            {},
            "sa-p",
            f"{STEPS}/0/permissions/service_account",
            id="empty-legacy-sa-is-absent",
        ),
        pytest.param(
            [_step()],
            {},
            None,
            None,
            id="nothing-set",
        ),
    ],
)
def test_sa_no_conflict_matrix(
    steps: list[dict[str, Any]],
    spec: dict[str, Any],
    expected_sa: Optional[str],
    expected_path: Optional[str],
) -> None:
    """Non-conflicting combinations match the real normalizer."""
    definition = _definition(steps, **spec)
    plan = _plan(definition)
    assert plan.steps[0].service_account.value == expected_sa
    assert plan.steps[0].service_account.path == expected_path
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


# --- image and spawn -------------------------------------------------------


def test_image_spec_inherited_with_partial_step_spawn_config() -> None:
    """A spec image is used when the step's spawn_config has no image."""
    definition = _definition(
        [_step(spawn_config={"cpu_limit": "1"})],
        spawn_config={"sandbox_image": "image-a:1", "memory_limit": "1Gi"},
    )
    plan = _plan(definition, run_sandbox_image="run-image:1")
    step = plan.steps[0]
    assert step.sandbox_image.value == "image-a:1"
    assert step.sandbox_image.path == "/definition/spec/spawn_config/sandbox_image"
    assert step.sandbox_image_source == ImageSource.SPEC
    # Whole-object rule for the other fields: the spec memory_limit is NOT
    # merged into the step's spawn_config.
    assert step.spawn_config.path == f"{STEPS}/0/spawn_config"
    assert step.spawn_config.value is not None
    assert step.spawn_config.value["memory_limit"] == "512Mi"
    assert step.spawn_config.value["cpu_limit"] == "1"
    _assert_matches_executor(definition, plan, "run-image:1")


def test_image_step_wins() -> None:
    """A step image outranks the spec and run images."""
    definition = _definition(
        [_step(spawn_config={"sandbox_image": "step-img"})],
        spawn_config={"sandbox_image": "image-a:1"},
    )
    plan = _plan(definition, run_sandbox_image="run-image:1")
    assert plan.steps[0].sandbox_image.value == "step-img"
    assert plan.steps[0].sandbox_image.path == f"{STEPS}/0/spawn_config/sandbox_image"
    assert plan.steps[0].sandbox_image_source == ImageSource.STEP
    _assert_matches_executor(definition, plan, "run-image:1")


def test_image_spec_only_spawn_config_inherited_whole() -> None:
    """With no step spawn_config the spec object is inherited whole."""
    definition = _definition(
        [_step()], spawn_config={"sandbox_image": "image-a:1", "cpu_limit": "2"}
    )
    plan = _plan(definition)
    step = plan.steps[0]
    assert step.sandbox_image.value == "image-a:1"
    assert step.sandbox_image_source == ImageSource.SPEC
    assert step.spawn_config.path == "/definition/spec/spawn_config"
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_image_fallbacks_build_step_input() -> None:
    """No definition images gives the run image; no run image gives sandbox:latest."""
    definition = _definition([_step(spawn_config={"sandbox_image": ""})])

    plan = _plan(definition, run_sandbox_image="run-image:1")
    assert plan.steps[0].sandbox_image.value == "run-image:1"
    assert plan.steps[0].sandbox_image.path == "/sandbox_image"
    assert plan.steps[0].sandbox_image_source == ImageSource.REQUEST
    _assert_matches_executor(definition, plan, "run-image:1")

    plan = _plan(definition)
    assert plan.steps[0].sandbox_image.value == SPAWNER_IMAGE
    assert plan.steps[0].sandbox_image.path is None
    assert plan.steps[0].sandbox_image_source == ImageSource.SPAWNER_DEFAULT
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)

    plan = _plan(definition, spawner_default_image=None)
    assert plan.steps[0].sandbox_image.value == EXECUTOR_DEFAULT_SANDBOX_IMAGE
    assert EXECUTOR_DEFAULT_SANDBOX_IMAGE == "sandbox:latest"
    assert plan.steps[0].sandbox_image.path is None
    assert plan.steps[0].sandbox_image_source == ImageSource.EXECUTOR_DEFAULT
    _assert_matches_executor(definition, plan, None)
    assert plan.run_sandbox_image is None


@pytest.mark.parametrize(
    ("step_spawn", "spec_spawn", "expected", "expected_path"),
    [
        ("none", "local", "none", f"{STEPS}/0/spawn"),
        (None, "local", "local", "/definition/spec/spawn"),
        (None, None, "ephemeral", None),
    ],
)
def test_spawn_mode_precedence(
    step_spawn: Optional[str],
    spec_spawn: Optional[str],
    expected: str,
    expected_path: Optional[str],
) -> None:
    """Spawn mode: step, else spec, else ephemeral."""
    step = _step() if step_spawn is None else _step(spawn=step_spawn)
    spec = {} if spec_spawn is None else {"spawn": spec_spawn}
    definition = _definition([step], **spec)
    plan = _plan(definition)
    assert plan.steps[0].spawn.value == expected
    assert plan.steps[0].spawn.path == expected_path
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_skills_image_run_only() -> None:
    """The skills image comes from the run context only, never the definition."""
    definition = _definition()
    definition["skills"] = {"image": "def-skills:1", "paths": ["/a"]}

    plan = _plan(definition)
    assert plan.skills_image.value is None
    assert plan.skills_image.path is None
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)

    plan = _plan(definition, run_skills_image="run-skills:1")
    assert plan.skills_image.value == "run-skills:1"
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE, "run-skills:1")


# --- timeouts, retries, budget ---------------------------------------------


def test_timeout_inherited_only() -> None:
    """The spec timeout is the per-step default."""
    definition = _definition([_step()], timeout_seconds=120)
    plan = _plan(definition)
    assert plan.steps[0].timeout_seconds.value == 120
    assert plan.steps[0].timeout_seconds.path == "/definition/spec/timeout_seconds"
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_timeout_step_override() -> None:
    """A step timeout outranks the spec timeout."""
    definition = _definition([_step(timeout_seconds=30)], timeout_seconds=120)
    plan = _plan(definition)
    assert plan.steps[0].timeout_seconds.value == 30
    assert plan.steps[0].timeout_seconds.path == f"{STEPS}/0/timeout_seconds"
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_timeout_both_omitted_gives_600() -> None:
    """With no timeout anywhere, the runner default 600 is filled in."""
    definition = _definition()
    plan = _plan(definition)
    assert DEFAULT_STEP_TIMEOUT_SECONDS == 600
    assert plan.steps[0].timeout_seconds.value == 600
    assert plan.steps[0].timeout_seconds.path is None
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_permissions_replaced_whole() -> None:
    """Step permissions replace spec permissions as a whole object."""
    definition = _definition(
        [_step(permissions={"max_tokens": 50}), _step("b")],
        permissions={"timeout_seconds": 300, "max_tokens": 1000},
    )
    plan = _plan(definition)
    first, second = plan.steps
    assert first.permissions_timeout_seconds.value is None
    assert first.permissions_timeout_seconds.path is None
    assert first.max_tokens.value == 50
    assert first.max_tokens.path == f"{STEPS}/0/permissions/max_tokens"
    assert first.permissions_path == f"{STEPS}/0/permissions"
    assert second.permissions_timeout_seconds.value == 300
    assert second.permissions_timeout_seconds.path == (
        "/definition/spec/permissions/timeout_seconds"
    )
    assert second.max_tokens.value == 1000
    assert second.permissions_path == "/definition/spec/permissions"
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_allowed_tools_whole_object_semantics_and_paths() -> None:
    """permissions.allowed_tools follows the whole-object permissions rule."""
    definition = _definition(
        [
            _step(permissions={"max_tokens": 50}),
            _step("b"),
            _step("c", permissions={"allowed_tools": ["Bash", "Write"]}),
            _step("d", permissions={"allowed_tools": []}),
        ],
        permissions={"allowed_tools": ["Read"], "max_tokens": 1000},
    )
    plan = _plan(definition)
    first, second, third, fourth = plan.steps
    assert first.allowed_tools.value is None
    assert first.allowed_tools.path is None
    assert second.allowed_tools.value == ("Read",)
    assert second.allowed_tools.path == "/definition/spec/permissions/allowed_tools"
    assert third.allowed_tools.value == ("Bash", "Write")
    assert third.allowed_tools.path == f"{STEPS}/2/permissions/allowed_tools"
    assert fourth.allowed_tools.value == ()
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_allowed_tools_none_stays_distinct_from_empty() -> None:
    """Omitted and null allowed_tools stay None; only an explicit [] is ().

    The producer sends nothing for either, but the plan keeps what the
    caller wrote so policy and audit can tell them apart.
    """
    definition = _definition(
        [
            _step("a", permissions=None),
            _step("b", permissions={"max_tokens": 1}),
            _step("c", permissions={"max_tokens": 1, "allowed_tools": None}),
            _step("d", permissions={"max_tokens": 1, "allowed_tools": []}),
            _step("e", permissions={"max_tokens": 1, "allowed_tools": ["Bash"]}),
        ]
    )
    plan = _plan(definition)
    values = [step.allowed_tools.value for step in plan.steps]
    assert values == [None, None, None, (), ("Bash",)]
    assert values[2] is None and values[3] is not None
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_omitted_max_tokens_is_unlimited() -> None:
    """An omitted max_tokens is represented explicitly as None (unlimited)."""
    definition = _definition()
    plan = _plan(definition)
    assert plan.steps[0].max_tokens.value is None
    assert plan.steps[0].max_tokens.path is None
    assert plan.steps[0].permissions_path is None
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_retries() -> None:
    """max_retries is step-only and defaults to 0."""
    definition = _definition([_step(max_retries=2), _step("b")])
    plan = _plan(definition)
    assert plan.steps[0].max_retries.value == 2
    assert plan.steps[0].max_retries.path == f"{STEPS}/0/max_retries"
    assert plan.steps[1].max_retries.value == 0
    assert plan.steps[1].max_retries.path is None
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_workflow_declared_budget_sum() -> None:
    """Declared budget = sum of step_timeout x (max_retries+1), approvals excluded."""
    definition = _definition(
        [
            _step("a", timeout_seconds=100, max_retries=2),
            _approval("gate"),
            _step("b"),
            _step("c", max_retries=1),
        ],
        timeout_seconds=50,
    )
    plan = _plan(definition)
    assert [s.index for s in plan.steps] == [0, 2, 3]
    assert plan.approval_step_indices == (1,)
    assert [s.declared_budget_seconds for s in plan.steps] == [300, 50, 100]
    assert plan.declared_workflow_budget_seconds == 450
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_budget_docstrings_say_declared_not_deadline() -> None:
    """The budget is documented as a declared budget, not a deadline."""
    doc = (EffectivePlan.__doc__ or "").lower()
    assert "declared" in doc
    assert "not a deadline" in doc


# --- list-ish fields --------------------------------------------------------


def test_list_fields_none_vs_empty() -> None:
    """None inherits/means unset; an explicit [] is kept as an empty tuple."""
    definition = _definition(
        [
            _step("a"),
            _step("b", allowed_skills=[], target_namespaces=[], tools=[]),
            _step(
                "c",
                allowed_skills=["s1"],
                target_namespaces=["ns1"],
                tools=["t1"],
            ),
        ],
        allowed_skills=["spec-skill"],
    )
    plan = _plan(definition)
    a, b, c = plan.steps
    assert a.allowed_skills.value == ("spec-skill",)
    assert a.allowed_skills.path == "/definition/spec/allowed_skills"
    assert a.target_namespaces.value is None
    assert a.target_namespaces.path is None
    assert a.tools.value == ()
    assert a.tools.path is None
    assert b.allowed_skills.value == ()
    assert b.allowed_skills.path == f"{STEPS}/1/allowed_skills"
    assert b.target_namespaces.value == ()
    assert b.tools.value == ()
    assert b.tools.path == f"{STEPS}/1/tools"
    assert c.allowed_skills.value == ("s1",)
    assert c.target_namespaces.value == ("ns1",)
    assert c.target_namespaces.path == f"{STEPS}/2/target_namespaces"
    assert c.tools.value == ("t1",)
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


def test_no_skills_anywhere_is_none() -> None:
    """No allowed_skills at any layer stays None."""
    plan = _plan(_definition())
    assert plan.steps[0].allowed_skills.value is None
    assert plan.steps[0].allowed_skills.path is None


def test_mcp_servers_inherited_with_path() -> None:
    """mcp_servers follows step, else spec, with a path for T3 to deny on."""
    definition = _definition(
        [_step("a"), _step("b", mcp_servers=[])], mcp_servers=["named"]
    )
    plan = _plan(definition)
    assert plan.steps[0].mcp_servers.value == ("named",)
    assert plan.steps[0].mcp_servers.path == "/definition/spec/mcp_servers"
    assert plan.steps[1].mcp_servers.value == ()
    assert plan.steps[1].mcp_servers.path == f"{STEPS}/1/mcp_servers"


# --- run-level fields, purity and invalid input -----------------------------


def test_run_level_fields() -> None:
    """The plan records the run provider and run image."""
    plan = _plan(_definition(), run_sandbox_image="run-image:1")
    assert plan.provider == "corp-openai"
    assert plan.run_sandbox_image == "run-image:1"
    assert plan.spawner_default_image == SPAWNER_IMAGE


def test_input_not_modified() -> None:
    """The function is pure: the definition is not modified."""
    definition = _definition(
        [_step(permissions={"max_tokens": 5}, spawn_config={"cpu_limit": "1"})],
        spawn_config={"sandbox_image": "a"},
        allowed_skills=["x"],
    )
    before = copy.deepcopy(definition)
    _plan(definition)
    assert definition == before


def test_single_step_without_name_uses_one_step_defaults() -> None:
    """A one-step definition may omit name/output_key like the executor."""
    definition = _definition([{"prompt": "hi", "timeout_seconds": 10}])
    plan = _plan(definition)
    assert plan.steps[0].timeout_seconds.value == 10
    _assert_matches_executor(definition, plan, SPAWNER_IMAGE)


@pytest.mark.parametrize(
    ("step_extra", "spec_extra", "expected_path"),
    [
        ({"timeout_seconds": 0}, {}, f"{STEPS}/0/timeout_seconds"),
        ({"timeout_seconds": True}, {}, f"{STEPS}/0/timeout_seconds"),
        ({"timeout_seconds": "60"}, {}, f"{STEPS}/0/timeout_seconds"),
        ({}, {"timeout_seconds": -1}, "/definition/spec/timeout_seconds"),
        ({"max_retries": -1}, {}, f"{STEPS}/0/max_retries"),
        ({"permissions": {"max_tokens": 0}}, {}, f"{STEPS}/0/permissions"),
        ({"permissions": "nope"}, {}, f"{STEPS}/0/permissions"),
        ({"spawn_config": {"cpu_limit": "99"}}, {}, f"{STEPS}/0/spawn_config"),
        ({"tools": "bash"}, {}, f"{STEPS}/0/tools"),
        ({"type": "weird"}, {}, f"{STEPS}/0/type"),
    ],
)
def test_invalid_values_raise_without_echo(
    step_extra: dict[str, Any], spec_extra: dict[str, Any], expected_path: str
) -> None:
    """Values the executor would reject raise invalid_value, never echoing input."""
    definition = _definition([_step(**step_extra)], **spec_extra)
    with pytest.raises(ValueError):
        executor_normalize_definition(copy.deepcopy(definition))
    with pytest.raises(EffectivePlanError) as exc_info:
        _plan(definition)
    exc = exc_info.value
    assert exc.reason == REASON_INVALID_VALUE
    assert exc.path == expected_path
    assert exc.__cause__ is None
    assert exc.__context__ is None
    for value in ("bash", "weird", "nope", "99"):
        assert value not in str(exc)
        assert value not in repr(exc)


def test_malformed_structure_raises_invalid_value() -> None:
    """Non-mapping spec/steps raise invalid_value with a fixed path."""
    with pytest.raises(EffectivePlanError) as exc_info:
        _plan({"spec": {"steps": ["x"]}})
    assert exc_info.value.path == f"{STEPS}/0"
    with pytest.raises(EffectivePlanError) as exc_info:
        _plan({"spec": "x"})
    assert exc_info.value.path == "/definition/spec"
