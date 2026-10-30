"""Pre-parse checks for POST /v1/workflows/run (issue #51, Phases 0a and 2).

These run on the raw request before any typed parse: the byte cap (413),
caller fields that would choose a credential (400), MCP fields callers may
never set (400: a run-level ``mcp_servers`` and raw physical Secret refs in
inline header values, Phase 3) and count caps (422).
The privileged-option rules (403) live in ``workflow.policy``.

Every rejection is a ``SubmissionRejected`` carrying audit reason codes and
JSON pointers built from indices and fixed keys, so the handler can write
the structured audit record (``workflow.audit``) without caller values.
Details never echo caller strings such as step names or credential values.
Pure checks: nothing here mutates its inputs or logs.
"""

import json
from collections.abc import Collection, Sequence
from typing import Any, Final, Optional

from fastapi import HTTPException, status

from workflow.audit import AuditReason, json_pointer
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
        mcp_servers: Enabled catalog MCP names in use, or None before the
            effective plan exists.
        mcp_inline_count: Number of inline MCP entries in use, or None
            before the effective plan exists.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        status_code: int,
        detail: Any,
        *,
        reasons: Sequence[AuditReason],
        paths: Sequence[str] = (),
        provider: Optional[str] = None,
        mcp_servers: Optional[Sequence[str]] = None,
        mcp_inline_count: Optional[int] = None,
    ) -> None:
        """Initialize the rejection.

        Parameters:
            status_code: HTTP status returned to the caller.
            detail: Caller-facing detail; may name denied values but must
                never be logged.
            reasons: Audit reason codes.
            paths: JSON pointers of the offending fields.
            provider: Catalog provider name to audit, if any.
            mcp_servers: Catalog MCP names to audit, if known.
            mcp_inline_count: Inline MCP entry count to audit, if known.
        """
        super().__init__(status_code=status_code, detail=detail)
        self.reasons: tuple[AuditReason, ...] = tuple(reasons)
        self.paths: tuple[str, ...] = tuple(paths)
        self.provider = provider
        self.mcp_servers: Optional[tuple[str, ...]] = (
            None if mcp_servers is None else tuple(mcp_servers)
        )
        self.mcp_inline_count = mcp_inline_count


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


FORBIDDEN_MCP_MESSAGE: Final[str] = (
    "Run-level mcp_servers cannot be set by callers; name workflow-enabled "
    "catalog servers in the step or spec mcp_servers instead. MCP header "
    "values cannot name a Secret (secret_name/key)."
)

# Inline MCP entry fields whose values are header maps.
_HEADER_FIELDS: Final[tuple[str, ...]] = ("headers", "secret_headers")
# Keys that name a physical Secret in a raw executor header reference.
_PHYSICAL_REF_KEYS: Final[frozenset[str]] = frozenset({"secret_name", "key"})


def _mcp_lists(definition: dict[str, Any]) -> list[tuple[list[Any], list[int | str]]]:
    """Return every raw ``mcp_servers`` list with its pointer parts.

    Malformed containers are skipped; the typed parse answers those.

    Parameters:
        definition: Raw workflow definition.

    Returns:
        ``(entries, parts)`` for the spec list and each step list.
    """
    spec = _as_dict(definition.get("spec"))
    found: list[tuple[list[Any], list[int | str]]] = []
    if isinstance(spec.get("mcp_servers"), list):
        found.append((spec["mcp_servers"], ["definition", "spec", "mcp_servers"]))
    steps = spec.get("steps")
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        servers = _as_dict(step).get("mcp_servers")
        if isinstance(servers, list):
            found.append(
                (servers, ["definition", "spec", "steps", index, "mcp_servers"])
            )
    return found


def _names_physical_secret(headers: Any) -> bool:
    """Tell whether any header value names a physical Secret or key.

    Parameters:
        headers: A raw ``headers`` / ``secret_headers`` value.

    Returns:
        True when some value is a mapping with ``secret_name`` or ``key``.
    """
    return any(
        isinstance(value, dict) and bool(_PHYSICAL_REF_KEYS & set(value))
        for value in _as_dict(headers).values()
    )


def reject_forbidden_mcp_fields(
    definition: dict[str, Any], *, run_mcp_servers_sent: bool
) -> None:
    """Reject MCP fields callers may never set (issue #51 Phase 3).

    Runs on the raw request in every mode, admins included, before the
    count caps and the typed parse. Forbidden: a run-level ``mcp_servers``
    (the stack builds that list from the catalog), and any inline header
    value naming a physical Secret (``secret_name`` or ``key``), in every
    ``mcp_servers`` list of the definition. Other unsupported header shapes
    are left to the typed parse, which rejects them (422).

    Parameters:
        definition: Raw workflow definition from the request body.
        run_mcp_servers_sent: Whether the caller sent a run-level
            ``mcp_servers`` field (any value, null included).

    Raises:
        SubmissionRejected: 400 ``forbidden_field`` naming each field by
            pointer; the detail is fixed text.
    """
    paths: list[str] = ["/mcp_servers"] if run_mcp_servers_sent else []
    for entries, parts in _mcp_lists(definition):
        for index, entry in enumerate(entries):
            server = _as_dict(entry)
            paths += [
                json_pointer(*parts, index, field)
                for field in _HEADER_FIELDS
                if _names_physical_secret(server.get(field))
            ]
    if paths:
        raise SubmissionRejected(
            status.HTTP_400_BAD_REQUEST,
            FORBIDDEN_MCP_MESSAGE,
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
