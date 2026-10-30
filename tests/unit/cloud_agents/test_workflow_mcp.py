"""Unit tests for operator-catalog MCP references (issue #51, Phase 3, T2).

Covers reference validation over every raw ``mcp_servers`` occurrence, the
effective per-step lists (step, else spec; ``[]`` is explicitly empty), the
``workflow_input["mcp_servers"]`` builder and executor contract tests that run
the built catalog through the real cloud-agents normalizer and resolver.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Optional

import pytest
from cloud_agents.workflow.core.execution import (
    build_step_input,
    normalize_workflow_step,
    workflow_defaults_from_definition,
)
from cloud_agents.workflow.core.mcp_resolver import resolve_mcp_servers
from cloud_agents.workflow.core.models import MCPServerConfig

from models.config import ModelContextProtocolServer
from workflow.audit import AuditReason
from workflow.catalog import ResolvedProvider
from workflow.effective import EffectivePlan, build_effective_plan
from workflow.mcp import (
    MCP_NAME_CONFLICT_MESSAGE,
    MCP_UNKNOWN_MESSAGE,
    McpAuditSummary,
    McpReferenceError,
    StepMcpServers,
    build_workflow_mcp_servers,
    effective_mcp_servers,
    mcp_audit_summary,
    step_mcp_servers,
    validate_mcp_references,
)

STEPS = "/definition/spec/steps"
SPEC_MCP = "/definition/spec/mcp_servers"
CANARY = "CANARY-tok-9f3b2c1d"

CATALOG: tuple[ModelContextProtocolServer, ...] = (
    ModelContextProtocolServer(
        name="kb", url="http://kb.internal:8080/mcp", workflow_enabled=True
    ),
    ModelContextProtocolServer(
        name="pods", url="https://pods.internal/mcp", workflow_enabled=True
    ),
    ModelContextProtocolServer(
        name="unused", url="https://unused.internal/mcp", workflow_enabled=True
    ),
    ModelContextProtocolServer(name="disabled", url="https://disabled.internal/mcp"),
)

RUN_PROVIDER = {"name": "openai", "model": "gpt-4o"}


def _step(index: int, **extra: Any) -> dict[str, Any]:
    """Build a multi-step-safe agent step."""
    step: dict[str, Any] = {
        "name": f"s{index}",
        "type": "agent",
        "prompt": "Do it",
        "output_key": f"o{index}",
    }
    step.update(extra)
    return step


def _definition(
    steps: list[dict[str, Any]], spec_mcp: Optional[list[Any]] = None
) -> dict[str, Any]:
    """Build a definition, optionally with a spec-level mcp_servers list."""
    spec: dict[str, Any] = {"steps": steps}
    if spec_mcp is not None:
        spec["mcp_servers"] = spec_mcp
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "wf"},
        "spec": spec,
    }


def _plan(definition: dict[str, Any]) -> EffectivePlan:
    """Build the effective plan with the real builder."""
    resolved = ResolvedProvider(
        catalog_name="corp-openai",
        executor_type="openai",
        model="gpt-4o",
        credential_ref=None,
        provider=dict(RUN_PROVIDER),
    )
    return build_effective_plan(
        definition, resolved, run_sandbox_image=None, spawner_default_image=None
    )


def _inject(definition: dict[str, Any]) -> list[dict[str, str]]:
    """Run the stack's injection path for a definition."""
    return build_workflow_mcp_servers(effective_mcp_servers(_plan(definition)), CATALOG)


def _reference_error(definition: dict[str, Any]) -> McpReferenceError:
    """Return the reference error a definition raises."""
    with pytest.raises(McpReferenceError) as exc_info:
        validate_mcp_references(definition, CATALOG)
    return exc_info.value


# --------------------------------------------------------------------------
# Reference validation
# --------------------------------------------------------------------------


def test_valid_names_in_spec_and_steps_pass() -> None:
    """Enabled catalog names pass at spec and step level, mixed with inline."""
    definition = _definition(
        [
            _step(0),
            _step(1, mcp_servers=["pods", {"name": "inl", "url": "https://i/mcp"}]),
        ],
        spec_mcp=["kb"],
    )
    validate_mcp_references(definition, CATALOG)


def test_no_mcp_anywhere_passes() -> None:
    """A definition without mcp_servers has nothing to validate."""
    validate_mcp_references(_definition([_step(0)]), CATALOG)
    validate_mcp_references(_definition([_step(0, mcp_servers=[])], []), CATALOG)


@pytest.mark.parametrize("name", ["nope", "disabled", CANARY, ""])
def test_unknown_and_disabled_names_identical(name: str) -> None:
    """Unknown and non-workflow_enabled names give the same reason and text."""
    error = _reference_error(_definition([_step(0, mcp_servers=["kb", name])]))
    assert error.status_code == 400
    assert error.reasons == (AuditReason.MCP_UNKNOWN,)
    assert error.paths == (f"{STEPS}/0/mcp_servers/1",)
    assert error.detail == f"{MCP_UNKNOWN_MESSAGE} ({STEPS}/0/mcp_servers/1)"
    assert name not in str(error.detail) or name == ""


def test_unknown_and_disabled_bodies_equal() -> None:
    """The full error for an unknown name equals the one for a disabled name."""
    unknown = _reference_error(_definition([_step(0, mcp_servers=["nope"])]))
    disabled = _reference_error(_definition([_step(0, mcp_servers=["disabled"])]))
    assert (unknown.status_code, unknown.detail, unknown.reasons, unknown.paths) == (
        disabled.status_code,
        disabled.detail,
        disabled.reasons,
        disabled.paths,
    )


def test_unknown_name_at_spec_level() -> None:
    """A spec-level unknown name is reported at the spec pointer."""
    error = _reference_error(_definition([_step(0)], spec_mcp=["nope"]))
    assert error.reasons == (AuditReason.MCP_UNKNOWN,)
    assert error.paths == (f"{SPEC_MCP}/0",)


def test_overridden_spec_list_still_validated() -> None:
    """Validation covers every raw occurrence, even a spec list no step uses."""
    error = _reference_error(_definition([_step(0, mcp_servers=[])], spec_mcp=["nope"]))
    assert error.paths == (f"{SPEC_MCP}/0",)


def test_approval_step_occurrence_validated() -> None:
    """Approval steps carry no agent spec, but their raw entries are still walked."""
    approval = {"name": "gate", "type": "human-approval", "mcp_servers": ["nope"]}
    error = _reference_error(_definition([_step(0), approval]))
    assert error.paths == (f"{STEPS}/1/mcp_servers/0",)


def test_all_problems_reported_together() -> None:
    """Every bad reference is reported in one error, in walk order."""
    definition = _definition(
        [
            _step(0, mcp_servers=["nope", "kb", "kb"]),
            _step(1, mcp_servers=[{"name": "pods", "url": "https://x/mcp"}]),
        ],
        spec_mcp=["disabled"],
    )
    error = _reference_error(definition)
    assert error.reasons == (AuditReason.MCP_UNKNOWN, AuditReason.MCP_NAME_CONFLICT)
    assert error.paths == (
        f"{SPEC_MCP}/0",
        f"{STEPS}/0/mcp_servers/0",
        f"{STEPS}/0/mcp_servers/2",
        f"{STEPS}/1/mcp_servers/0",
    )
    assert MCP_UNKNOWN_MESSAGE in error.detail
    assert MCP_NAME_CONFLICT_MESSAGE in error.detail


def test_inline_named_like_catalog_entry_conflicts() -> None:
    """An inline entry may not reuse an enabled catalog name."""
    error = _reference_error(
        _definition([_step(0, mcp_servers=[{"name": "kb", "url": "https://x/mcp"}])])
    )
    assert error.reasons == (AuditReason.MCP_NAME_CONFLICT,)
    assert error.paths == (f"{STEPS}/0/mcp_servers/0",)
    assert error.detail == f"{MCP_NAME_CONFLICT_MESSAGE} ({STEPS}/0/mcp_servers/0)"


def test_inline_named_like_disabled_entry_does_not_conflict() -> None:
    """Disabled entries are never injected, so they cannot collide (no probe)."""
    validate_mcp_references(
        _definition(
            [_step(0, mcp_servers=[{"name": "disabled", "url": "https://x/mcp"}])]
        ),
        CATALOG,
    )


@pytest.mark.parametrize(
    "servers",
    [
        ["kb", "kb"],
        [{"name": "inl", "url": "https://a/mcp"}, {"name": "inl", "url": "https://b"}],
    ],
)
def test_duplicate_names_within_one_list_conflict(servers: list[Any]) -> None:
    """A name used twice in one list is a conflict at the second occurrence."""
    error = _reference_error(_definition([_step(0, mcp_servers=servers)]))
    assert error.reasons == (AuditReason.MCP_NAME_CONFLICT,)
    assert error.paths == (f"{STEPS}/0/mcp_servers/1",)


def test_duplicate_in_spec_list_conflicts() -> None:
    """Duplicates in the spec default list are conflicts too."""
    error = _reference_error(_definition([_step(0)], spec_mcp=["kb", "kb"]))
    assert error.paths == (f"{SPEC_MCP}/1",)


def test_same_name_in_different_lists_is_fine() -> None:
    """Step and spec lists are separate effective lists; reuse across them is fine."""
    validate_mcp_references(
        _definition([_step(0, mcp_servers=["kb"]), _step(1)], spec_mcp=["kb"]),
        CATALOG,
    )


def test_malformed_containers_left_to_shape_validation() -> None:
    """Non-list containers and non-str/dict entries are the typed parse's job."""
    validate_mcp_references({"spec": "x"}, CATALOG)
    validate_mcp_references({"spec": {"steps": "x", "mcp_servers": "kb"}}, CATALOG)
    validate_mcp_references(
        _definition(["x", _step(1, mcp_servers=[3, None, {"url": "https://x"}])]),
        CATALOG,
    )


def test_validation_does_not_modify_definition() -> None:
    """The walk is read-only."""
    definition = _definition(
        [_step(0, mcp_servers=["kb", {"name": "inl", "url": "https://i"}])],
        spec_mcp=["pods"],
    )
    before = copy.deepcopy(definition)
    validate_mcp_references(definition, CATALOG)
    assert definition == before


def test_error_carries_no_caller_strings() -> None:
    """Detail, reasons and paths never echo a caller-sent name or URL."""
    definition = _definition(
        [
            _step(
                0,
                mcp_servers=[
                    CANARY,
                    {"name": "kb", "url": f"https://{CANARY}/mcp"},
                    {"name": CANARY, "url": "https://x", "headers": {CANARY: "v"}},
                    {"name": CANARY, "url": "https://y"},
                ],
            )
        ]
    )
    error = _reference_error(definition)
    blob = repr((error.detail, error.reasons, error.paths, str(error)))
    assert CANARY not in blob


# --------------------------------------------------------------------------
# Effective per-step lists and audit-facing helpers
# --------------------------------------------------------------------------


def test_effective_lists_inherit_override_and_mix() -> None:
    """Step list, else spec list; [] is explicitly empty; inline counted."""
    definition = _definition(
        [
            _step(0),
            _step(1, mcp_servers=[]),
            _step(2, mcp_servers=["pods", {"name": "inl", "url": "https://i/mcp"}]),
        ],
        spec_mcp=["kb"],
    )
    steps = effective_mcp_servers(_plan(definition))
    assert [s.step_index for s in steps] == [0, 1, 2]
    assert [s.step_path for s in steps] == [f"{STEPS}/0", f"{STEPS}/1", f"{STEPS}/2"]
    assert [s.names for s in steps] == [("kb",), (), ("pods",)]
    assert [s.inline_count for s in steps] == [0, 0, 1]
    assert steps[0].named[0].path == f"{SPEC_MCP}/0"
    assert steps[2].named[0].path == f"{STEPS}/2/mcp_servers/0"
    assert steps[2].inline_paths == (f"{STEPS}/2/mcp_servers/1",)


def test_step_mcp_servers_matches_plan_helper() -> None:
    """The per-step helper and the plan helper agree."""
    plan = _plan(_definition([_step(0, mcp_servers=["kb"])]))
    assert effective_mcp_servers(plan) == (step_mcp_servers(plan.steps[0]),)


def test_approval_steps_have_no_effective_servers() -> None:
    """Approval steps run no agent, so they get no servers."""
    approval = {"name": "gate", "type": "human-approval"}
    steps = effective_mcp_servers(_plan(_definition([_step(0), approval], ["kb"])))
    assert [s.step_index for s in steps] == [0]


def test_audit_summary_names_and_inline_count() -> None:
    """Audit carries deduplicated catalog names and a distinct inline count."""
    definition = _definition(
        [
            _step(0),
            _step(1),
            _step(2, mcp_servers=["pods", "kb", {"name": "inl", "url": "https://i"}]),
        ],
        spec_mcp=["kb", {"name": "shared", "url": "https://s"}],
    )
    summary = mcp_audit_summary(effective_mcp_servers(_plan(definition)), CATALOG)
    assert summary == McpAuditSummary(catalog_names=("kb", "pods"), inline_count=2)


def test_audit_summary_overridden_spec_counts_nothing() -> None:
    """A spec list every step overrides with [] contributes nothing."""
    definition = _definition(
        [_step(0, mcp_servers=[])],
        spec_mcp=["kb", {"name": "inl", "url": "https://i"}],
    )
    summary = mcp_audit_summary(effective_mcp_servers(_plan(definition)), CATALOG)
    assert summary == McpAuditSummary(catalog_names=(), inline_count=0)


def test_audit_facing_outputs_never_carry_inline_values() -> None:
    """Inline names, URLs and header names never reach audit-facing outputs.

    Unvalidated (non-catalog) names are also kept out of the summary, so a
    canary that slipped past validation still cannot reach an audit record.
    """
    inline = {
        "name": f"{CANARY}-name",
        "url": f"https://{CANARY}.example/mcp",
        "headers": {f"X-{CANARY}": "value"},
        "secret_headers": {f"X-{CANARY}-s": {"name": "ref"}},
    }
    definition = _definition(
        [_step(0, mcp_servers=["kb", inline, f"{CANARY}-unknown"])],
        spec_mcp=[inline],
    )
    steps = effective_mcp_servers(_plan(definition))
    summary = mcp_audit_summary(steps, CATALOG)
    assert summary.catalog_names == ("kb",)
    assert summary.inline_count == 1
    audit_facing = repr(
        (
            summary,
            [
                (s.step_index, s.step_path, s.inline_paths, s.inline_count)
                for s in steps
            ],
        )
    )
    assert CANARY not in audit_facing
    assert all(CANARY not in repr(path) for s in steps for path in s.inline_paths)


# --------------------------------------------------------------------------
# workflow_input["mcp_servers"] builder
# --------------------------------------------------------------------------


def test_injection_is_name_and_url_only() -> None:
    """Each entry is exactly {name, url} from the catalog."""
    injected = _inject(_definition([_step(0, mcp_servers=["kb", "pods"])]))
    assert injected == [
        {"name": "kb", "url": "http://kb.internal:8080/mcp"},
        {"name": "pods", "url": "https://pods.internal/mcp"},
    ]
    assert all(set(entry) == {"name", "url"} for entry in injected)


def test_injection_spec_overridden_by_empty_injects_nothing() -> None:
    """A spec entry every step overrides with [] is never injected."""
    assert not _inject(_definition([_step(0, mcp_servers=[])], spec_mcp=["kb"]))


def test_injection_union_of_referenced_servers_deduplicated() -> None:
    """The run list is the deduplicated union of servers steps reference."""
    definition = _definition(
        [
            _step(0),
            _step(1, mcp_servers=["pods", "kb"]),
            _step(2, mcp_servers=[]),
            _step(3, mcp_servers=[{"name": "inl", "url": "https://i"}]),
        ],
        spec_mcp=["kb"],
    )
    assert [e["name"] for e in _inject(definition)] == ["kb", "pods"]


def test_unreferenced_catalog_server_never_injected() -> None:
    """Enabled servers no step references are not injected."""
    names = {e["name"] for e in _inject(_definition([_step(0, mcp_servers=["kb"])]))}
    assert names == {"kb"}


def test_inline_only_injects_nothing() -> None:
    """Inline entries stay in the definition; nothing is added to the catalog."""
    definition = _definition(
        [_step(0, mcp_servers=[{"name": "inl", "url": "https://i"}])]
    )
    assert not _inject(definition)


def test_injection_refuses_unvalidated_names() -> None:
    """The builder fails closed on a name that is not an enabled entry."""
    for name in ("nope", "disabled"):
        steps = effective_mcp_servers(
            _plan(_definition([_step(0, mcp_servers=[name])]))
        )
        with pytest.raises(McpReferenceError) as exc_info:
            build_workflow_mcp_servers(steps, CATALOG)
        assert exc_info.value.reasons == (AuditReason.MCP_UNKNOWN,)


def test_injection_entries_are_fresh_dicts() -> None:
    """Callers may mutate the result without touching the catalog."""
    first = _inject(_definition([_step(0, mcp_servers=["kb"])]))
    first[0]["url"] = "changed"
    assert CATALOG[0].url == "http://kb.internal:8080/mcp"


def test_step_mcp_servers_dataclass_is_frozen() -> None:
    """Helper outputs are immutable."""
    steps = effective_mcp_servers(_plan(_definition([_step(0, mcp_servers=["kb"])])))
    assert isinstance(steps[0], StepMcpServers)
    with pytest.raises(AttributeError):
        steps[0].step_index = 9  # type: ignore[misc]


# --------------------------------------------------------------------------
# Executor contract: the real normalizer and resolver
# --------------------------------------------------------------------------


def _mixed_definition() -> dict[str, Any]:
    """Spec default, [] override, a mixed step and an unreferenced server."""
    return _definition(
        [
            _step(0),
            _step(1, mcp_servers=[]),
            _step(2, mcp_servers=["pods", {"name": "inl", "url": "https://i/mcp"}]),
            _step(3, mcp_servers=["kb", "pods"]),
        ],
        spec_mcp=["kb"],
    )


EXPECTED_PER_STEP: tuple[Optional[list[str]], ...] = (
    ["kb"],
    None,
    ["pods", "inl"],
    ["kb", "pods"],
)


def _resolved_names(resolved: Optional[list[dict[str, Any]]]) -> Optional[list[str]]:
    """Names of resolved servers, keeping the executor's None."""
    return None if resolved is None else [s["name"] for s in resolved]


def test_contract_catalog_entries_validate_as_mcp_server_config() -> None:
    """Every injected entry validates against the executor's extra=forbid model."""
    for entry in _inject(_mixed_definition()):
        config = MCPServerConfig.model_validate(entry)
        assert config.headers is None
        assert config.secret_headers is None


def test_contract_normalize_and_resolve_per_step() -> None:
    """Each step resolves exactly its own servers from the run-level union."""
    definition = _mixed_definition()
    workflow_input = {"mcp_servers": _inject(definition)}
    defaults = workflow_defaults_from_definition(definition)
    steps = definition["spec"]["steps"]
    for index, step in enumerate(steps):
        normalized, _ = normalize_workflow_step(step, defaults, len(steps))
        resolved = resolve_mcp_servers(
            normalized.mcp_servers, workflow_input["mcp_servers"]
        )
        assert _resolved_names(resolved) == EXPECTED_PER_STEP[index], index
        for server in resolved or []:
            if server["name"] != "inl":
                MCPServerConfig.model_validate(server)
                assert set(server) == {"name", "url"}


def test_contract_build_step_input_and_step_runner_path() -> None:
    """build_step_input and the runner's re-resolution over raw_step agree."""
    definition = _mixed_definition()
    workflow_input = {"mcp_servers": _inject(definition)}
    defaults = workflow_defaults_from_definition(definition)
    steps = definition["spec"]["steps"]
    run_context = {"provider": dict(RUN_PROVIDER), **workflow_input}
    for index, step in enumerate(steps):
        step_input = build_step_input(step, run_context, defaults, len(steps))
        assert _resolved_names(step_input.mcp_servers) == EXPECTED_PER_STEP[index]
        rerun = resolve_mcp_servers(
            step_input.raw_step.get("mcp_servers"), workflow_input["mcp_servers"]
        )
        assert _resolved_names(rerun) == EXPECTED_PER_STEP[index]


def test_contract_stack_effective_lists_match_executor() -> None:
    """The stack's effective named lists equal what the executor normalizes."""
    definition = _mixed_definition()
    defaults = workflow_defaults_from_definition(definition)
    steps = definition["spec"]["steps"]
    ours = effective_mcp_servers(_plan(definition))
    for index, step in enumerate(steps):
        normalized, _ = normalize_workflow_step(step, defaults, len(steps))
        theirs = tuple(e for e in normalized.mcp_servers or () if isinstance(e, str))
        assert ours[index].names == theirs
        inline = [e for e in normalized.mcp_servers or () if not isinstance(e, str)]
        assert ours[index].inline_count == len(inline)


def test_contract_unknown_name_silently_dropped_by_executor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The executor drops names missing from the catalog with only a warning.

    That is why the stack answers ``mcp_unknown`` with a 400 before start: the
    executor would otherwise run the step without the server it asked for.
    """
    definition = _definition([_step(0, mcp_servers=["kb", "nope"])])
    with caplog.at_level(logging.WARNING):
        resolved = resolve_mcp_servers(
            ["kb", "nope"], [{"name": "kb", "url": "http://kb.internal:8080/mcp"}]
        )
        only_missing = resolve_mcp_servers(["nope"], [])
    assert _resolved_names(resolved) == ["kb"]
    assert only_missing is None
    error = _reference_error(definition)
    assert error.reasons == (AuditReason.MCP_UNKNOWN,)


def test_contract_union_does_not_leak_to_other_steps() -> None:
    """A step naming only 'kb' never receives 'pods' though both are injected."""
    definition = _definition(
        [_step(0, mcp_servers=["kb"]), _step(1, mcp_servers=["pods"])]
    )
    workflow_input = {"mcp_servers": _inject(definition)}
    assert [e["name"] for e in workflow_input["mcp_servers"]] == ["kb", "pods"]
    defaults = workflow_defaults_from_definition(definition)
    steps = definition["spec"]["steps"]
    got = [
        _resolved_names(
            resolve_mcp_servers(
                normalize_workflow_step(step, defaults, len(steps))[0].mcp_servers,
                workflow_input["mcp_servers"],
            )
        )
        for step in steps
    ]
    assert got == [["kb"], ["pods"]]
