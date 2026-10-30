"""Unit tests for the workflow submission guard (issue #51, Phases 0a and 2).

The guard keeps the pre-parse checks: the byte cap (413), forbidden caller
fields (400) and count caps (422). The privileged-option rules (403) moved to
``workflow.policy`` in Phase 2 and are tested there and at the endpoint.
"""

# pylint: disable=too-few-public-methods

from __future__ import annotations

import copy
from typing import Any, Optional

import pytest

from workflow.audit import AuditReason, json_pointer
from workflow.limits import (
    MAX_DEFINITION_BYTES,
    MAX_MCP_SERVERS_PER_STEP,
    MAX_SECRET_HEADERS_PER_SERVER,
    MAX_WORKFLOW_STEPS,
)
from workflow.submission_guard import (
    SubmissionRejected,
    reject_forbidden_caller_fields,
    reject_over_count_caps,
    reject_oversized_definition,
)

CANARY = "sk-CANARY-guard-5e1d"


def _step(name: str = "agent", **extra: Any) -> dict[str, Any]:
    """Build a minimal agent step."""
    return {
        "name": name,
        "type": "agent",
        "prompt": "Do it",
        "output_key": "result",
        **extra,
    }


def _definition(steps: Optional[list[dict[str, Any]]] = None, **top: Any) -> dict:
    """Build a minimal definition; ``top`` keys land at top level."""
    spec_extra = top.pop("spec", {})
    return {
        "apiVersion": "v1",
        "kind": "AgentWorkflow",
        "metadata": {"name": "t"},
        "spec": {"steps": steps or [_step(spawn="ephemeral")], **spec_extra},
        **top,
    }


def _rejection(call: Any) -> Optional[SubmissionRejected]:
    """Return the SubmissionRejected a call raises, or None."""
    try:
        call()
    except SubmissionRejected as exc:
        return exc
    return None


LOGICAL = frozenset({"inference/anthropic-prod"})


def _forbidden(
    definition: dict[str, Any],
    provider: Optional[dict[str, Any]] = None,
    governed: bool = False,
) -> Optional[SubmissionRejected]:
    """Run the forbidden-field check (governed uses the LOGICAL catalog names)."""
    return _rejection(
        lambda: reject_forbidden_caller_fields(
            definition,
            provider or {"name": "openai"},
            logical_credentials=LOGICAL if governed else None,
        )
    )


def _counts(definition: dict[str, Any]) -> Optional[SubmissionRejected]:
    """Run the count-cap check."""
    return _rejection(lambda: reject_over_count_caps(definition))


class TestCredentialRoutes:
    """G1/G2: callers cannot choose the credential env var."""

    @pytest.mark.parametrize("value", ["DATABASE_URL", None, ""])
    def test_run_provider_credentials_secret_rejected(self, value: Any) -> None:
        """Run-level credentials_secret is 400 whatever its value (legacy mode)."""
        provider = {"name": "openai", "model": "m", "credentials_secret": value}
        exc = _forbidden(_definition(), provider)
        assert exc is not None and exc.status_code == 400
        assert exc.reasons == (AuditReason.FORBIDDEN_FIELD,)
        assert exc.paths == ("/provider/credentials_secret",)

    def test_run_provider_logical_name_left_to_catalog_when_governed(
        self,
    ) -> None:
        """Governed mode: a logical credential name is left to the catalog."""
        provider = {"name": "claude-prod", "credentials_secret": next(iter(LOGICAL))}
        assert _forbidden(_definition(), provider, governed=True) is None

    @pytest.mark.parametrize("value", ["ANTHROPIC_API_KEY", None, {"x": 1}])
    def test_run_provider_physical_name_rejected_when_governed(
        self, value: Any
    ) -> None:
        """Governed mode: anything but a logical credential name is 400 up front."""
        provider = {"name": "claude-prod", "credentials_secret": value}
        exc = _forbidden(_definition(), provider, governed=True)
        assert exc is not None and exc.status_code == 400
        assert exc.paths == ("/provider/credentials_secret",)

    @pytest.mark.parametrize("governed", [True, False])
    def test_definition_provider_credentials_secret_rejected(
        self, governed: bool
    ) -> None:
        """definition.provider.credentials_secret is 400 in every mode."""
        definition = _definition(
            provider={"name": "bedrock", "model": "m", "credentials_secret": "X_KEY"}
        )
        exc = _forbidden(definition, governed=governed)
        assert exc is not None and exc.status_code == 400
        assert exc.paths == ("/definition/provider/credentials_secret",)

    def test_definition_provider_without_credentials_accepted(self) -> None:
        """A definition provider with no credentials_secret passes."""
        definition = _definition(provider={"name": "openai", "model": "m"})
        assert _forbidden(definition) is None

    def test_scanned_on_raw_dict_even_with_unknown_keys(self) -> None:
        """The scan works on raw input, so unknown keys do not hide it."""
        definition = _definition(
            provider={"name": "x", "credentials_secret": "Y", CANARY: 1}
        )
        definition[CANARY] = True
        exc = _forbidden(definition)
        assert exc is not None and exc.status_code == 400

    def test_message_does_not_echo_the_value(self) -> None:
        """The response never repeats the caller's credential value."""
        provider = {"name": "openai", "credentials_secret": CANARY}
        exc = _forbidden(_definition(), provider)
        assert exc is not None
        assert CANARY not in str(exc.detail)


class TestLimits:
    """G9: byte and count caps."""

    def test_oversized_definition_413(self) -> None:
        """A definition over MAX_DEFINITION_BYTES is 413."""
        big = _definition([_step(prompt="x" * (MAX_DEFINITION_BYTES + 1))])
        exc = _rejection(lambda: reject_oversized_definition(big))
        assert exc is not None and exc.status_code == 413
        assert exc.reasons == (AuditReason.PAYLOAD_TOO_LARGE,)
        assert exc.paths == ("/definition",)

    def test_small_definition_passes_size_check(self) -> None:
        """A normal definition passes the size check."""
        reject_oversized_definition(_definition())

    def test_too_many_steps_422(self) -> None:
        """More than MAX_WORKFLOW_STEPS steps is 422."""
        steps = [
            _step(f"s{i}", spawn="ephemeral") for i in range(MAX_WORKFLOW_STEPS + 1)
        ]
        exc = _counts(_definition(steps))
        assert exc is not None and exc.status_code == 422
        assert exc.reasons == (AuditReason.COUNT_CAP,)
        assert exc.paths == ("/definition/spec/steps",)

    def test_max_steps_accepted(self) -> None:
        """Exactly MAX_WORKFLOW_STEPS steps passes."""
        steps = [_step(f"s{i}", spawn="ephemeral") for i in range(MAX_WORKFLOW_STEPS)]
        assert _counts(_definition(steps)) is None

    def test_too_many_mcp_servers_on_step_422(self) -> None:
        """More than MAX_MCP_SERVERS_PER_STEP servers on a step is 422."""
        names = [f"srv{i}" for i in range(MAX_MCP_SERVERS_PER_STEP + 1)]
        definition = _definition([_step(spawn="ephemeral", mcp_servers=names)])
        exc = _counts(definition)
        assert exc is not None and exc.status_code == 422
        assert exc.paths == ("/definition/spec/steps/0/mcp_servers",)

    def test_too_many_workflow_level_mcp_servers_422(self) -> None:
        """Workflow-level defaults are counted too."""
        names = [f"srv{i}" for i in range(MAX_MCP_SERVERS_PER_STEP + 1)]
        definition = _definition(spec={"mcp_servers": names})
        exc = _counts(definition)
        assert exc is not None and exc.status_code == 422
        assert exc.paths == ("/definition/spec/mcp_servers",)

    def test_too_many_secret_headers_422(self) -> None:
        """An inline MCP entry with too many secret_headers is 422."""
        headers = {
            f"h{i}": {"secret_name": "s", "key": "k"}
            for i in range(MAX_SECRET_HEADERS_PER_SERVER + 1)
        }
        server = {
            "name": "x",
            "url": "https://m.example.com",
            "secret_headers": headers,
        }
        definition = _definition([_step(spawn="ephemeral", mcp_servers=[server])])
        exc = _counts(definition)
        assert exc is not None and exc.status_code == 422
        assert exc.paths == ("/definition/spec/steps/0/mcp_servers/0/secret_headers",)

    def test_count_errors_never_name_steps(self) -> None:
        """Count-cap details use pointers, never caller step names."""
        names = [f"srv{i}" for i in range(MAX_MCP_SERVERS_PER_STEP + 1)]
        definition = _definition([_step(CANARY, mcp_servers=names)])
        exc = _counts(definition)
        assert exc is not None
        assert CANARY not in str(exc.detail)

    @pytest.mark.parametrize(
        "definition",
        [
            {"spec": None},
            {"spec": []},
            {"spec": {"steps": "nope"}},
            {"spec": {"steps": [1, None]}},
        ],
    )
    def test_malformed_shapes_are_left_for_the_typed_parse(
        self, definition: dict[str, Any]
    ) -> None:
        """Count caps never crash on malformed containers."""
        assert _counts(definition) is None


def test_rejection_paths_survive_json_pointer() -> None:
    """Every pointer the guard emits is made of fixed keys and indices."""
    names = [f"srv{i}" for i in range(MAX_MCP_SERVERS_PER_STEP + 1)]
    for exc in (
        _counts(_definition([_step(mcp_servers=names)])),
        _counts(_definition(spec={"mcp_servers": names})),
        _forbidden(_definition(provider={"name": "x", "credentials_secret": "y"})),
        _forbidden(_definition(), {"credentials_secret": "y"}),
    ):
        assert exc is not None
        for path in exc.paths:
            parts = [int(p) if p.isdigit() else p for p in path.split("/")[1:]]
            assert json_pointer(*parts) == path


def test_guard_does_not_mutate_inputs() -> None:
    """The guard is a pure check."""
    definition = _definition(advisory=False)
    before = copy.deepcopy(definition)
    reject_oversized_definition(definition)
    reject_forbidden_caller_fields(definition, {}, logical_credentials=None)
    reject_over_count_caps(definition)
    assert definition == before
