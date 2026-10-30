"""Structured audit emitter for workflow submissions.

Exactly one record is emitted per call. The API accepts only typed, structured
arguments: enums for events and reasons, integers for status, JSON pointers
built from indices and fixed keys, and identifiers supplied by the auth layer
or the operator catalog. There is no free-text or exception parameter, so step
names, header values, prompts, models and URLs cannot be logged through it.
"""

import json
import re
from collections.abc import Sequence
from enum import Enum
from typing import Any, Final, Optional

from log import get_logger

logger = get_logger(__name__)

PLACEHOLDER: Final[str] = "*"
MAX_IDENTIFIER_LENGTH: Final[int] = 128
START_FAILED_STATUS: Final[int] = 500

# Object keys of the workflow definition that may appear in a pointer. Anything
# else is caller-controlled and is replaced by PLACEHOLDER.
FIXED_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "steps",
        "agent",
        "prompt",
        "model",
        "provider",
        "image",
        "timeout",
        "retries",
        "service_account",
        "permissions",
        "max_tokens",
        "spawn_config",
        "spawn_mode",
        "skills",
        "mcp_servers",
        "secret_headers",
        "headers",
        "url",
        "policy",
        "depends_on",
        "defaults",
        "spec",
        # Request body and workflow definition keys used by the submission
        # pipeline (submission_guard, catalog, effective plan, policy).
        "definition",
        "metadata",
        "type",
        "output_key",
        "advisory",
        "sandbox_image",
        "spawn",
        "timeout_seconds",
        "max_retries",
        "tools",
        "allowed_skills",
        "target_namespaces",
        "inference_provider",
        "credentials_secret",
        "credential_ref",
    }
)

_POINTER_SEGMENT: Final[re.Pattern[str]] = re.compile(
    r"^(?:\d+|\*|" + "|".join(sorted(FIXED_POINTER_KEYS)) + r")$"
)


class AuditEvent(str, Enum):
    """Audit event types."""

    AUTHORIZED = "workflow_authorized"
    DENIED = "workflow_denied"
    START_FAILED = "workflow_start_failed"


class AuditReason(str, Enum):
    """Reason codes for audit records."""

    PAYLOAD_TOO_LARGE = "payload_too_large"
    FORBIDDEN_FIELD = "forbidden_field"
    COUNT_CAP = "count_cap"
    SHAPE_INVALID = "shape_invalid"
    PROVIDER_UNKNOWN = "provider_unknown"
    MODEL_NOT_ALLOWED = "model_not_allowed"
    CREDENTIAL_NOT_ALLOWED = "credential_not_allowed"
    MCP_NOT_ALLOWED = "mcp_not_allowed"
    IMAGE_NOT_ALLOWED = "image_not_allowed"
    SPAWN_MODE_NOT_ALLOWED = "spawn_mode_not_allowed"
    LIMIT_EXCEEDED = "limit_exceeded"
    TOOLS_NOT_ENFORCEABLE = "tools_not_enforceable"
    POLICY_DENIED = "policy_denied"
    SERVICE_ACCOUNT_CONFLICT = "service_account_conflict"
    EXECUTOR_VALIDATION_FAILED = "executor_validation_failed"
    START_FAILED = "start_failed"


def json_pointer(*parts: int | str) -> str:
    """Build an RFC 6901 pointer from indices and fixed keys only.

    Parameters:
        *parts: Non-negative ints (not bool) or members of FIXED_POINTER_KEYS.
            Any other value is replaced by the placeholder.

    Returns:
        The pointer string, empty for no parts.
    """
    segments: list[str] = []
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool) and part >= 0:
            segments.append(str(part))
        elif isinstance(part, str) and part in FIXED_POINTER_KEYS:
            segments.append(part)
        else:
            segments.append(PLACEHOLDER)
    return "".join(f"/{s}" for s in segments)


def _clean_pointer(path: object) -> str:
    """Re-validate a pointer, replacing any non-fixed segment.

    Parameters:
        path: A pointer string, normally from json_pointer.

    Returns:
        A pointer containing only indices, fixed keys, or the placeholder.
    """
    if not isinstance(path, str):
        return "/" + PLACEHOLDER
    if path == "":
        return ""
    segments = path.split("/")[1:] if path.startswith("/") else [path]
    return "".join(
        f"/{s if _POINTER_SEGMENT.match(s) else PLACEHOLDER}" for s in segments
    )


def _identifier(value: object, name: str) -> str:
    """Validate and bound an identifier supplied by the auth layer or catalog.

    Parameters:
        value: The identifier.
        name: Parameter name, used in the TypeError (never the value).

    Returns:
        The identifier truncated to MAX_IDENTIFIER_LENGTH.

    Raises:
        TypeError: If value is not a str.
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    return value[:MAX_IDENTIFIER_LENGTH]


def _status(value: object) -> int:
    """Validate an HTTP status code.

    Parameters:
        value: The status.

    Returns:
        The status as int.

    Raises:
        TypeError: If value is not an int.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("status must be int")
    return value


def _reasons(values: object) -> list[str]:
    """Validate a sequence of AuditReason members.

    Parameters:
        values: The reason codes.

    Returns:
        Their string values.

    Raises:
        TypeError: If values is not a list/tuple of AuditReason.
    """
    if not isinstance(values, (list, tuple)) or not all(
        isinstance(v, AuditReason) for v in values
    ):
        raise TypeError("reasons must be a sequence of AuditReason")
    return [v.value for v in values]


def _emit(  # pylint: disable=too-many-arguments
    event: AuditEvent,
    *,
    status: int,
    reasons: list[str],
    paths: Sequence[str],
    user_id: str,
    request_id: str,
    provider: Optional[str],
    workflow_id: Optional[str] = None,
) -> None:
    """Emit one audit record as a JSON message, mirrored in ``extra``.

    Parameters:
        event: Event type.
        status: HTTP status.
        reasons: Validated reason code values.
        paths: Pointer paths.
        user_id: Authenticated user identifier.
        request_id: Request identifier.
        provider: Resolved catalog provider name, if any.
        workflow_id: Workflow identifier, authorized events only.
    """
    body: dict[str, Any] = {
        "event": event.value,
        "status": status,
        "reasons": reasons,
        "paths": [_clean_pointer(p) for p in paths],
        "user_id": user_id,
        "request_id": request_id,
        "provider": provider,
    }
    if workflow_id is not None:
        body["workflow_id"] = workflow_id
    logger.info("%s", json.dumps(body, sort_keys=False), extra={"audit": body})


def _optional_identifier(value: object, name: str) -> Optional[str]:
    """Validate an optional identifier.

    Parameters:
        value: The identifier or None.
        name: Parameter name for errors.

    Returns:
        The bounded identifier or None.
    """
    return None if value is None else _identifier(value, name)


def record_denied(  # pylint: disable=too-many-arguments
    *,
    user_id: str,
    request_id: str,
    status: int,
    reasons: Sequence[AuditReason],
    paths: Sequence[str] = (),
    provider: Optional[str] = None,
) -> None:
    """Record a denied submission (413, 400, 422, 403).

    Parameters:
        user_id: Identifier from the auth layer.
        request_id: Request identifier.
        status: HTTP status returned.
        reasons: Reason codes.
        paths: Pointers from json_pointer.
        provider: Resolved catalog provider name, if resolved.

    Raises:
        TypeError: If any argument has the wrong type; nothing is logged.
    """
    _emit(
        AuditEvent.DENIED,
        status=_status(status),
        reasons=_reasons(reasons),
        paths=paths,
        user_id=_identifier(user_id, "user_id"),
        request_id=_identifier(request_id, "request_id"),
        provider=_optional_identifier(provider, "provider"),
    )


def record_authorized(  # pylint: disable=too-many-arguments
    *,
    user_id: str,
    request_id: str,
    status: int,
    workflow_id: str,
    provider: Optional[str] = None,
) -> None:
    """Record an accepted submission; call only after ``start`` returned.

    Parameters:
        user_id: Identifier from the auth layer.
        request_id: Request identifier.
        status: HTTP status returned.
        workflow_id: Identifier returned by the executor.
        provider: Resolved catalog provider name, if any.

    Raises:
        TypeError: If any argument has the wrong type; nothing is logged.
    """
    _emit(
        AuditEvent.AUTHORIZED,
        status=_status(status),
        reasons=[],
        paths=(),
        user_id=_identifier(user_id, "user_id"),
        request_id=_identifier(request_id, "request_id"),
        provider=_optional_identifier(provider, "provider"),
        workflow_id=_identifier(workflow_id, "workflow_id"),
    )


def record_start_failed(
    *,
    user_id: str,
    request_id: str,
    provider: Optional[str] = None,
) -> None:
    """Record that ``executor.start`` raised; the exception is never logged.

    Parameters:
        user_id: Identifier from the auth layer.
        request_id: Request identifier.
        provider: Resolved catalog provider name, if any.

    Raises:
        TypeError: If any argument has the wrong type; nothing is logged.
    """
    _emit(
        AuditEvent.START_FAILED,
        status=START_FAILED_STATUS,
        reasons=[AuditReason.START_FAILED.value],
        paths=(),
        user_id=_identifier(user_id, "user_id"),
        request_id=_identifier(request_id, "request_id"),
        provider=_optional_identifier(provider, "provider"),
    )
