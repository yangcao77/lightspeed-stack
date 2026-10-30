"""Pre-parse checks for POST /v1/workflows/run (issue #51, Phases 0a and 2).

These run on the raw request before any typed parse: the byte cap (413),
caller fields that would choose a credential (400) and count caps (422).
The privileged-option rules (403) live in ``workflow.policy``.

Every rejection is a ``SubmissionRejected`` carrying audit reason codes and
JSON pointers built from indices and fixed keys, so the handler can write
the structured audit record (``workflow.audit``) without caller values.
Details never echo caller strings such as step names or credential values.
Pure checks: nothing here mutates its inputs or logs.
"""

import json
from collections.abc import Collection, Sequence
from typing import Any, Optional

from fastapi import HTTPException, status

from workflow.audit import AuditReason
from workflow.limits import (
    MAX_DEFINITION_BYTES,
    MAX_MCP_SERVERS_PER_STEP,
    MAX_SECRET_HEADERS_PER_SERVER,
    MAX_WORKFLOW_STEPS,
)


class SubmissionRejected(HTTPException):
    """A submission rejection that carries audit-safe reasons and pointers.

    Attributes:
        reasons: Audit reason codes.
        paths: JSON pointers into the request body (indices and fixed keys).
        provider: Operator catalog name to audit, or None when it is not
            known or not safe to record.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        status_code: int,
        detail: Any,
        *,
        reasons: Sequence[AuditReason],
        paths: Sequence[str] = (),
        provider: Optional[str] = None,
    ) -> None:
        """Initialize the rejection.

        Parameters:
            status_code: HTTP status returned to the caller.
            detail: Caller-facing detail; may name denied values but must
                never be logged.
            reasons: Audit reason codes.
            paths: JSON pointers of the offending fields.
            provider: Catalog provider name to audit, if any.
        """
        super().__init__(status_code=status_code, detail=detail)
        self.reasons: tuple[AuditReason, ...] = tuple(reasons)
        self.paths: tuple[str, ...] = tuple(paths)
        self.provider = provider


def reject_oversized_definition(definition: dict[str, Any]) -> None:
    """Reject a definition whose JSON encoding exceeds the byte cap.

    Parameters:
        definition: Raw workflow definition from the request body.

    Raises:
        SubmissionRejected: 413 when the definition is over
            MAX_DEFINITION_BYTES.
    """
    size = len(json.dumps(definition).encode("utf-8"))
    if size > MAX_DEFINITION_BYTES:
        raise SubmissionRejected(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Workflow definition exceeds {MAX_DEFINITION_BYTES} bytes.",
            reasons=(AuditReason.PAYLOAD_TOO_LARGE,),
            paths=("/definition",),
        )


def _as_dict(value: Any) -> dict[str, Any]:
    """Return value when it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def reject_forbidden_caller_fields(
    definition: dict[str, Any],
    provider: Optional[dict[str, Any]],
    *,
    logical_credentials: Optional[Collection[str]],
) -> None:
    """Reject caller fields that would choose a credential (G1/G2).

    Runs on the raw request before the typed parse, so a forbidden field is
    answered 400 even when the definition also has keys the parse would
    reject with 422. In governed mode the run provider's deprecated
    ``credentials_secret`` may name a logical credential of the catalog; the
    catalog then checks it is the selected entry's own credential.

    Parameters:
        definition: Raw workflow definition from the request body.
        provider: Run-level provider as sent by the caller, or None.
        logical_credentials: Logical credential names of the catalog, or
            None in legacy mode (no catalog, so the field is always
            forbidden).

    Raises:
        SubmissionRejected: 400 naming the forbidden field by pointer.
    """
    paths: list[str] = []
    run_provider = _as_dict(provider)
    run_secret = run_provider.get("credentials_secret")
    if "credentials_secret" in run_provider and (
        logical_credentials is None
        or not isinstance(run_secret, str)
        or run_secret not in logical_credentials
    ):
        paths.append("/provider/credentials_secret")
    if "credentials_secret" in _as_dict(definition.get("provider")):
        paths.append("/definition/provider/credentials_secret")
    if paths:
        raise SubmissionRejected(
            status.HTTP_400_BAD_REQUEST,
            "credentials_secret cannot be set by callers; the stack "
            "chooses the credential for the provider.",
            reasons=(AuditReason.FORBIDDEN_FIELD,),
            paths=paths,
        )


def _count_errors(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Return count-cap violations as ``(pointer, message)`` pairs.

    Malformed containers are skipped; the typed parse answers those.

    Parameters:
        spec: Raw spec mapping.

    Returns:
        The violations; messages name pointers, never caller strings.
    """
    raw_steps = spec.get("steps")
    steps: list[Any] = raw_steps if isinstance(raw_steps, list) else []
    errors: list[tuple[str, str]] = []
    if len(steps) > MAX_WORKFLOW_STEPS:
        pointer = "/definition/spec/steps"
        errors.append(
            (pointer, f"{pointer} has {len(steps)} steps (max {MAX_WORKFLOW_STEPS})")
        )
    scopes = [("/definition/spec", spec)] + [
        (f"/definition/spec/steps/{i}", _as_dict(s)) for i, s in enumerate(steps)
    ]
    for base, scope in scopes:
        servers = scope.get("mcp_servers") or []
        if not isinstance(servers, list):
            continue
        pointer = f"{base}/mcp_servers"
        if len(servers) > MAX_MCP_SERVERS_PER_STEP:
            errors.append(
                (
                    pointer,
                    f"{pointer} has {len(servers)} entries "
                    f"(max {MAX_MCP_SERVERS_PER_STEP})",
                )
            )
        for index, server in enumerate(servers):
            headers = _as_dict(_as_dict(server).get("secret_headers"))
            if len(headers) > MAX_SECRET_HEADERS_PER_SERVER:
                header_pointer = f"{pointer}/{index}/secret_headers"
                errors.append(
                    (
                        header_pointer,
                        f"{header_pointer} has {len(headers)} entries "
                        f"(max {MAX_SECRET_HEADERS_PER_SERVER})",
                    )
                )
    return errors


def reject_over_count_caps(definition: dict[str, Any]) -> None:
    """Reject definitions over the step, MCP server or secret header caps.

    Parameters:
        definition: Raw workflow definition from the request body.

    Raises:
        SubmissionRejected: 422 listing every exceeded cap by pointer.
    """
    errors = _count_errors(_as_dict(definition.get("spec")))
    if errors:
        raise SubmissionRejected(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"validation_errors": [message for _, message in errors]},
            reasons=(AuditReason.COUNT_CAP,),
            paths=[pointer for pointer, _ in errors],
        )
