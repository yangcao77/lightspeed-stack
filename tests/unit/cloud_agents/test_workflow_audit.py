"""Unit tests for the workflow audit emitter (issue #51, Phase 2, T5)."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

import pytest

from models.config import PolicyRule, WorkflowPolicy
from workflow.audit import (
    FIXED_POINTER_KEYS,
    AuditEvent,
    AuditReason,
    json_pointer,
    record_authorized,
    record_denied,
    record_start_failed,
)
from workflow.catalog import ResolvedProvider
from workflow.effective import EffectivePlanError, build_effective_plan
from workflow.policy import Principal, authorize_workflow_submission

CANARY = "sk-canary-9f3a"


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return audit records captured so far."""
    return [r for r in caplog.records if r.name.endswith("workflow.audit")]


def _payload(record: logging.LogRecord) -> dict[str, Any]:
    """Decode the JSON audit message."""
    return json.loads(record.getMessage())


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    """Capture everything at DEBUG."""
    caplog.set_level(logging.DEBUG)


def test_enums_cover_required_values() -> None:
    """Event and reason enums contain the spec'd members."""
    assert {e.value for e in AuditEvent} == {
        "workflow_authorized",
        "workflow_denied",
        "workflow_start_failed",
    }
    required = {
        "payload_too_large",
        "forbidden_field",
        "count_cap",
        "shape_invalid",
        "provider_unknown",
        "model_not_allowed",
        "credential_not_allowed",
        "policy_denied",
        "service_account_conflict",
        "executor_validation_failed",
        "start_failed",
    }
    assert required <= {r.value for r in AuditReason}


def test_json_pointer_ints_and_fixed_keys() -> None:
    """Pointers are built from ints and known keys."""
    assert json_pointer() == ""
    assert json_pointer("steps", 2, "agent") == "/steps/2/agent"


@pytest.mark.parametrize("bad", [CANARY, "", "a/b", True, -1, 1.5, None, b"x"])
def test_json_pointer_unknown_part_becomes_placeholder(bad: Any) -> None:
    """Caller-controlled parts never reach the pointer."""
    pointer = json_pointer("steps", bad)
    assert pointer == "/steps/*"
    assert CANARY not in pointer


def test_record_denied_one_record_with_typed_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Denied emits exactly one structured record."""
    record_denied(
        user_id="u1",
        request_id="r1",
        status=403,
        reasons=[AuditReason.POLICY_DENIED, AuditReason.MODEL_NOT_ALLOWED],
        paths=[json_pointer("steps", 0, "model")],
        provider="openai",
    )
    recs = _records(caplog)
    assert len(recs) == 1
    body = _payload(recs[0])
    assert body == {
        "event": "workflow_denied",
        "status": 403,
        "reasons": ["policy_denied", "model_not_allowed"],
        "paths": ["/steps/0/model"],
        "user_id": "u1",
        "request_id": "r1",
        "provider": "openai",
    }
    assert recs[0].audit == body  # type: ignore[attr-defined]


def test_record_denied_optional_provider_omitted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Provider is null when unresolved."""
    record_denied(
        user_id="u",
        request_id="r",
        status=413,
        reasons=[AuditReason.PAYLOAD_TOO_LARGE],
    )
    body = _payload(_records(caplog)[0])
    assert body["provider"] is None
    assert body["paths"] == []


def test_record_authorized_requires_workflow_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Authorized carries workflow_id and cannot omit it."""
    with pytest.raises(TypeError):
        record_authorized(  # type: ignore[call-arg]  # pylint: disable=missing-kwoa
            user_id="u", request_id="r", status=202
        )
    assert not _records(caplog)
    record_authorized(
        user_id="u", request_id="r", status=202, workflow_id="wf-1", provider="p"
    )
    recs = _records(caplog)
    assert len(recs) == 1
    body = _payload(recs[0])
    assert body["event"] == "workflow_authorized"
    assert body["workflow_id"] == "wf-1"
    assert body["status"] == 202


def test_record_start_failed(caplog: pytest.LogCaptureFixture) -> None:
    """Start failure emits one record with fixed reason."""
    record_start_failed(user_id="u", request_id="r", provider="p")
    recs = _records(caplog)
    assert len(recs) == 1
    body = _payload(recs[0])
    assert body["event"] == "workflow_start_failed"
    assert body["status"] == 500
    assert body["reasons"] == ["start_failed"]


def test_api_rejects_strings_and_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Free text, exceptions, and strings are refused with no record."""
    bad: Any = CANARY
    exc: Any = ValueError(CANARY)
    with pytest.raises(TypeError):
        record_denied(user_id="u", request_id="r", status=400, reasons=[bad])
    with pytest.raises(TypeError):
        record_denied(user_id="u", request_id="r", status=400, reasons=[exc])
    with pytest.raises(TypeError):
        record_denied(user_id="u", request_id="r", status=bad, reasons=[])
    with pytest.raises(TypeError):
        record_denied(user_id=exc, request_id="r", status=400, reasons=[])
    with pytest.raises(TypeError):
        record_denied(user_id="u", request_id="r", status=400, reasons=bad)
    with pytest.raises(TypeError):
        record_authorized(user_id="u", request_id="r", status=202, workflow_id=exc)
    assert not _records(caplog)
    assert CANARY not in caplog.text


def test_signatures_have_no_free_text_parameter() -> None:
    """No message/detail/error/exc parameter exists on any recorder."""
    banned = {"message", "msg", "detail", "error", "exc", "exception", "text"}
    for fn in (record_denied, record_authorized, record_start_failed):
        assert not banned & set(inspect.signature(fn).parameters)


def test_canary_in_paths_is_replaced(caplog: pytest.LogCaptureFixture) -> None:
    """A raw string smuggled in as a path is replaced, not logged."""
    record_denied(
        user_id="u",
        request_id="r",
        status=422,
        reasons=[AuditReason.SHAPE_INVALID],
        paths=[f"/steps/0/{CANARY}", CANARY, "/steps/0/model"],
    )
    assert CANARY not in caplog.text
    body = _payload(_records(caplog)[0])
    assert body["paths"] == ["/steps/0/*", "/*", "/steps/0/model"]


def test_canary_in_json_pointer_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Pointers built with a canary key log the placeholder."""
    record_denied(
        user_id="u",
        request_id="r",
        status=400,
        reasons=[AuditReason.FORBIDDEN_FIELD],
        paths=[json_pointer("steps", 1, CANARY)],
    )
    assert CANARY not in caplog.text
    assert _payload(_records(caplog)[0])["paths"] == ["/steps/1/*"]


@pytest.mark.parametrize("field", ["provider", "request_id", "user_id"])
def test_canary_identifier_only_in_its_own_field(
    caplog: pytest.LogCaptureFixture, field: str
) -> None:
    """Identifier fields carry the value only in their own slot."""
    kwargs: dict[str, Any] = {"user_id": "u", "request_id": "r", "provider": "p"}
    kwargs[field] = CANARY
    record_denied(status=403, reasons=[AuditReason.POLICY_DENIED], **kwargs)
    body = _payload(_records(caplog)[0])
    assert body[field] == CANARY
    assert [k for k, v in body.items() if CANARY in str(v)] == [field]


def test_canary_not_in_other_fields_across_all_recorders(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With canary-free identifiers nothing else can leak the canary."""
    record_denied(
        user_id="u",
        request_id="r",
        status=400,
        reasons=[AuditReason.FORBIDDEN_FIELD],
        paths=[f"/{CANARY}"],
    )
    record_start_failed(user_id="u", request_id="r")
    record_authorized(user_id="u", request_id="r", status=202, workflow_id="w")
    assert len(_records(caplog)) == 3
    assert CANARY not in caplog.text


def test_oversized_identifier_is_truncated(caplog: pytest.LogCaptureFixture) -> None:
    """Identifiers are bounded in length."""
    record_start_failed(user_id="u" * 5000, request_id="r")
    assert len(_payload(_records(caplog)[0])["user_id"]) <= 128


def test_fixed_pointer_keys_cover_plan_and_request_keys() -> None:
    """The keys the effective plan, policy and guard use are all fixed keys."""
    assert {
        "definition",
        "timeout_seconds",
        "max_retries",
        "spawn",
        "tools",
        "allowed_skills",
        "target_namespaces",
        "sandbox_image",
        "advisory",
        "credentials_secret",
        "credential_ref",
        "inference_provider",
        "type",
        "output_key",
    } <= FIXED_POINTER_KEYS


def _segments(pointer: str) -> list[int | str]:
    """Split a pointer into json_pointer parts (digits become ints)."""
    return [int(p) if p.isdigit() else p for p in pointer.split("/")[1:]]


def _rich_definition() -> dict[str, Any]:
    """A definition that sets every field the effective plan reads."""
    full_step = {
        "name": CANARY,
        "type": "agent",
        "prompt": CANARY,
        "output_key": "o0",
        "spawn": "local",
        "spawn_config": {"sandbox_image": CANARY},
        "service_account": "sa-step",
        "permissions": {
            "service_account": "sa-step",
            "timeout_seconds": 9000,
            "max_tokens": 9_000_000,
        },
        "timeout_seconds": 9000,
        "max_retries": 9,
        "allowed_skills": [CANARY],
        "tools": [CANARY],
        "target_namespaces": [CANARY],
        "mcp_servers": [CANARY, {"name": CANARY, "url": "https://x.example"}],
    }
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": CANARY},
        "advisory": True,
        "skills": {"image": CANARY},
        "spec": {
            "spawn": "none",
            "spawn_config": {"sandbox_image": CANARY},
            "service_account": "sa-spec",
            "permissions": {"service_account": "sa-spec", "timeout_seconds": 9000},
            "timeout_seconds": 9000,
            "allowed_skills": [CANARY],
            "mcp_servers": [{"name": CANARY, "url": "https://y.example"}],
            "steps": [
                full_step,
                {"name": "s1", "type": "agent", "prompt": "p", "output_key": "o1"},
                {"name": "gate", "type": "human-approval"},
                {
                    "name": "s3",
                    "type": "agent",
                    "prompt": "p",
                    "output_key": "o3",
                    "spawn": "ephemeral",
                    "spawn_config": {"cpu": "1"},
                },
            ],
        },
    }


def _plan_pointers(plan: Any) -> set[str]:
    """Collect every pointer a plan carries."""
    pointers: set[str] = set()
    for step in plan.steps:
        pointers.add(step.path)
        if step.permissions_path:
            pointers.add(step.permissions_path)
        for value in vars(step).values():
            path = getattr(value, "path", None)
            if isinstance(path, str):
                pointers.add(path)
    return pointers


RESOLVED = ResolvedProvider(
    catalog_name="p",
    executor_type="openai",
    model="m",
    credential_ref=None,
    provider={"name": "openai", "model": "m"},
)


def _policy_pointers(plan: Any) -> set[str]:
    """Collect every denial pointer across modes, admin and non-admin."""
    pointers: set[str] = set()
    policies = [
        None,
        WorkflowPolicy(rules=[]),
        WorkflowPolicy(rules=[PolicyRule(role="*", spawn_modes=["none"])]),
    ]
    for policy in policies:
        for admin in (True, False):
            decision = authorize_workflow_submission(
                plan,
                Principal(user_id="u", is_admin=admin),
                policy,
                spawner_configured=False,
                default_sandbox_image="default:v1",
                advisory=True,
                definition_skills_image=CANARY,
            )
            pointers.update(decision.paths)
    return pointers


def _conflict_pointers() -> set[str]:
    """Collect the pointers of a service-account conflict."""
    conflict = _rich_definition()
    conflict["spec"]["steps"][1]["service_account"] = "sa-other"
    with pytest.raises(EffectivePlanError) as exc_info:
        build_effective_plan(
            conflict, RESOLVED, run_sandbox_image=None, spawner_default_image=None
        )
    return {exc_info.value.path, str(exc_info.value.conflicting_path)}


def test_plan_and_policy_pointers_survive_json_pointer() -> None:
    """No pointer from the plan or the policy loses a segment to the placeholder."""
    plan = build_effective_plan(
        _rich_definition(),
        RESOLVED,
        run_sandbox_image=CANARY,
        spawner_default_image="default:v1",
    )
    pointers = _plan_pointers(plan) | _policy_pointers(plan) | _conflict_pointers()

    assert len(pointers) > 30
    for pointer in sorted(pointers):
        assert CANARY not in pointer
        assert json_pointer(*_segments(pointer)) == pointer, pointer
