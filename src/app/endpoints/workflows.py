"""Handler for REST API calls to manage workflow executions."""

# pylint: disable=import-outside-toplevel,global-statement,invalid-name

import copy
import re
import uuid
from typing import Annotated, Any, Final, Optional

from cloud_agents.workflow.core.definition import WorkflowDefinition
from cloud_agents.workflow.core.execution import (
    inference_spec_from_provider_config,
    validate_credential_reference,
)
from cloud_agents.workflow.core.validation import validate_definition
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from authentication import get_auth_dependency
from authentication.interface import AuthTuple
from authorization.middleware import authorize, is_admin
from configuration import configuration
from log import get_logger
from models.api.requests.agents import ApproveWorkflowRequest, RunWorkflowRequest
from models.api.responses.error import InternalServerErrorResponse
from models.config import Action
from utils.endpoints import check_configuration_loaded
from workflow.audit import (
    AuditReason,
    json_pointer,
    record_authorized,
    record_denied,
    record_start_failed,
)
from workflow.catalog import (
    LEGACY_DEPRECATION,
    LEGACY_SUNSET,
    ResolvedProvider,
    normalize_definition,
    resolve_run_provider,
)
from workflow.effective import (
    REASON_SERVICE_ACCOUNT_CONFLICT,
    EffectivePlan,
    EffectivePlanError,
    build_effective_plan,
)
from workflow.policy import Principal, authorize_workflow_submission
from workflow.spawner_factory import build_spawner
from workflow.submission_guard import (
    SubmissionRejected,
    reject_forbidden_caller_fields,
    reject_over_count_caps,
    reject_oversized_definition,
)

logger = get_logger(__name__)
router = APIRouter(tags=["workflows"])

# Request id header; only plain tokens are trusted for the audit record.
_REQUEST_ID_HEADER: Final[str] = "x-request-id"
_SAFE_REQUEST_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._:-]{1,128}")

_executor = None


def _get_executor() -> Any:
    """Get the workflow executor singleton.

    Returns:
        The workflow executor instance.

    Raises:
        HTTPException: If the workflow engine is not enabled.
    """
    global _executor
    if _executor is not None:
        return _executor

    if not configuration.workflow_engine_configuration.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow engine is not enabled. "
            "Set workflow_engine.enabled=true in configuration.",
        )

    from workflow.executor_factory import create_workflow_runner

    spawner_config = configuration.spawner_configuration
    spawner = build_spawner(spawner_config) if spawner_config else None
    _executor = create_workflow_runner(spawner=spawner)
    return _executor


def _pointer_loc(pointer: str) -> list[int | str]:
    """Turn a JSON pointer into a ``loc`` list (digit segments become ints).

    Parameters:
        pointer: JSON pointer built from indices and fixed keys.

    Returns:
        The pointer's segments.
    """
    return [int(s) if s.isdigit() else s for s in pointer.split("/")[1:]]


def _check_definition_shape(definition: dict[str, Any]) -> None:
    """Typed-parse a throwaway deep copy of the definition (422 on failure).

    The copy is discarded: neither it nor anything the parse fills in reaches
    the executor. Errors are reported as ``[{loc, type}]`` only, because the
    pydantic message and ``input`` echo caller values.

    Parameters:
        definition: Raw workflow definition from the request body.

    Raises:
        SubmissionRejected: 422 ``shape_invalid``.
    """
    errors: list[dict[str, Any]] = []
    try:
        WorkflowDefinition.model_validate(copy.deepcopy(definition))
    except ValidationError as exc:
        errors = [
            {"loc": ["definition", *err["loc"]], "type": err["type"]}
            for err in exc.errors(
                include_url=False, include_input=False, include_context=False
            )
        ]
    # Raised outside the except block so the pydantic text is not chained.
    if errors:
        raise SubmissionRejected(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"validation_errors": errors},
            reasons=(AuditReason.SHAPE_INVALID,),
            paths=[json_pointer(*e["loc"]) for e in errors],
        )


def _build_plan(
    definition: dict[str, Any],
    resolved: ResolvedProvider,
    *,
    run_sandbox_image: Optional[str],
    default_sandbox_image: str,
) -> EffectivePlan:
    """Build the effective plan, turning executor-rejected values into 422.

    A service-account conflict is reported as ``service_account_conflict``
    with both pointers; the executor's message (which contains both values)
    is never produced or echoed, and this is not logged as drift.

    Parameters:
        definition: Normalized definition.
        resolved: Resolved run-level provider.
        run_sandbox_image: ``sandbox_image`` from the request body.
        default_sandbox_image: The spawner's default image.

    Returns:
        The effective plan.

    Raises:
        SubmissionRejected: 422 ``service_account_conflict`` or
            ``executor_validation_failed``.
    """
    error: Optional[EffectivePlanError] = None
    try:
        return build_effective_plan(
            definition,
            resolved,
            run_sandbox_image=run_sandbox_image,
            spawner_default_image=default_sandbox_image,
        )
    except EffectivePlanError as exc:
        error = exc
    conflict = error.reason == REASON_SERVICE_ACCOUNT_CONFLICT
    paths = [error.path]
    if error.conflicting_path is not None:
        paths.append(error.conflicting_path)
    raise SubmissionRejected(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {
            "validation_errors": [
                {"loc": _pointer_loc(error.path), "type": error.reason}
            ]
        },
        reasons=[
            (
                AuditReason.SERVICE_ACCOUNT_CONFLICT
                if conflict
                else AuditReason.EXECUTOR_VALIDATION_FAILED
            )
        ],
        paths=paths,
    )


def _authorize_plan(
    plan: EffectivePlan,
    definition: dict[str, Any],
    *,
    principal: Principal,
    default_sandbox_image: str,
    spawner_configured: bool,
) -> None:
    """Apply the run-level policy (or the Phase 0a rules without one).

    Parameters:
        plan: Effective plan.
        definition: Normalized definition (typed-parse checked).
        principal: The caller.
        default_sandbox_image: The spawner's default image (implicit grant).
        spawner_configured: Whether a spawner_configuration exists.

    Raises:
        SubmissionRejected: 403 with every denial message for the caller;
            only reason codes and pointers are audited.
    """
    skills = definition.get("skills")
    skills_image = skills.get("image") if isinstance(skills, dict) else None
    decision = authorize_workflow_submission(
        plan,
        principal,
        configuration.workflow_engine_configuration.policy,  # pylint: disable=no-member
        spawner_configured=spawner_configured,
        default_sandbox_image=default_sandbox_image,
        advisory=bool(definition.get("advisory")),
        definition_skills_image=skills_image if isinstance(skills_image, str) else None,
    )
    if not decision.allowed:
        raise SubmissionRejected(
            status.HTTP_403_FORBIDDEN,
            {"denied": [d.message for d in decision.denials]},
            reasons=decision.reasons,
            paths=decision.paths,
        )


def _executor_errors(
    definition: dict[str, Any], provider: dict[str, Any]
) -> tuple[list[Any], list[str]]:
    """Run the executor's own submission checks on what will be started.

    Parameters:
        definition: Normalized definition.
        provider: Run-level provider dict built by the stack.

    Returns:
        Caller-facing errors and their pointers; both empty when valid.
        ``validate_definition`` messages are returned as-is (they name the
        caller's own steps); provider errors are ``{loc, type}`` only.
    """
    definition_errors = validate_definition(definition)
    if definition_errors:
        return list(definition_errors), ["/definition"]
    provider_error: Optional[str] = None
    try:
        inference_spec_from_provider_config(provider)
        if provider.get("credentials_secret") is not None:
            validate_credential_reference(provider["credentials_secret"])
    except ValueError:
        provider_error = "invalid_provider"
    if provider_error is not None:
        return [{"loc": ["provider"], "type": provider_error}], ["/provider"]
    return [], []


def _validate_with_executor(
    definition: dict[str, Any], provider: dict[str, Any]
) -> None:
    """Reject input the executor would still refuse after the stack's checks.

    LocalWorkflowRunner.start persists the raw definition and provider before
    normalization runs (issue #55), so this must answer 422 before start.
    Reaching it means the stack's own checks missed something, so it is
    logged as drift, with the reason code and pointers only.

    Parameters:
        definition: Normalized definition.
        provider: Run-level provider dict built by the stack.

    Raises:
        SubmissionRejected: 422 ``executor_validation_failed``.
    """
    errors, paths = _executor_errors(definition, provider)
    if errors:
        logger.warning(
            "Workflow submission drift: executor validation rejected input "
            "that passed the stack's checks (reason=%s, paths=%s)",
            AuditReason.EXECUTOR_VALIDATION_FAILED.value,
            paths,
        )
        raise SubmissionRejected(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"validation_errors": errors},
            reasons=(AuditReason.EXECUTOR_VALIDATION_FAILED,),
            paths=paths,
        )


def _prepare_submission(
    body: RunWorkflowRequest,
    *,
    principal: Principal,
    default_sandbox_image: str,
    spawner_configured: bool,
) -> tuple[ResolvedProvider, dict[str, Any]]:
    """Run the submission pipeline and return what the workflow will run with.

    Order (issue #51 Phase 2): 1. 413 byte cap; 2. 400 forbidden caller
    fields on the raw dict; 3. 422 count caps; 4. 422 typed parse of a
    throwaway copy; 5. 400 catalog resolution and normalization; 5b. 422
    effective plan (service-account conflict, executor-rejected values);
    6. 403 policy, every denial at once; 7. 422 executor validation, logged
    as drift. Nothing has been persisted when this raises.

    Parameters:
        body: Request body as sent by the caller.
        principal: The caller.
        default_sandbox_image: The spawner's configured sandbox image.
        spawner_configured: Whether a spawner_configuration exists.

    Returns:
        The resolved run-level provider and the normalized definition, which
        is exactly what ``executor.start`` receives.

    Raises:
        SubmissionRejected: 413, 400, 422 or 403 with audit reasons and
            pointers; ``provider`` is set once it is safe to audit.
    """
    engine = configuration.workflow_engine_configuration
    reject_oversized_definition(body.definition)
    reject_forbidden_caller_fields(
        body.definition,
        body.provider,
        logical_credentials=(
            frozenset(p.credential.name for p in engine.providers if p.credential)
            if engine.governed
            else None
        ),
    )
    reject_over_count_caps(body.definition)
    _check_definition_shape(body.definition)
    resolved = resolve_run_provider(engine, configuration.inference, body.provider)
    definition = normalize_definition(engine, body.definition, resolved)

    # In legacy mode the provider name is caller-chosen until the executor
    # has accepted it, so it is only audited once a catalog resolved it.
    audit_provider = resolved.catalog_name if engine.governed else None
    try:
        plan = _build_plan(
            definition,
            resolved,
            run_sandbox_image=body.sandbox_image,
            default_sandbox_image=default_sandbox_image,
        )
        _authorize_plan(
            plan,
            definition,
            principal=principal,
            default_sandbox_image=default_sandbox_image,
            spawner_configured=spawner_configured,
        )
        _validate_with_executor(definition, resolved.provider)
    except SubmissionRejected as exc:
        raise SubmissionRejected(
            exc.status_code,
            exc.detail,
            reasons=exc.reasons,
            paths=exc.paths,
            provider=audit_provider,
        ) from None
    return resolved, definition


def _request_id(request: Request) -> str:
    """Return the caller's request id when it is a plain token, else a new one.

    Parameters:
        request: The incoming request.

    Returns:
        A request id that is safe to audit.
    """
    value = request.headers.get(_REQUEST_ID_HEADER)
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return uuid.uuid4().hex


def _user_roles(request: Request) -> frozenset[str]:
    """Return the roles ``@authorize`` stored on the request.

    Parameters:
        request: Request that passed through ``@authorize``.

    Returns:
        The caller's roles; empty when none were resolved.
    """
    roles = getattr(request.state, "user_roles", None)
    if not isinstance(roles, (set, frozenset, list, tuple)):
        return frozenset()
    return frozenset(r for r in roles if isinstance(r, str))


async def _start_audited(
    executor: Any,
    workflow_input: dict[str, Any],
    *,
    user_id: str,
    request_id: str,
    provider: str,
) -> str:
    """Start the workflow and write its single audit record.

    ``workflow_authorized`` is recorded only after ``start`` returned. When
    ``start`` raises, ``workflow_start_failed`` is recorded and a generic 500
    is raised; the exception text may echo the definition, so it is neither
    logged, chained nor returned.

    Parameters:
        executor: The workflow executor.
        workflow_input: Input handed to ``executor.start``.
        user_id: Identifier from the auth layer.
        request_id: Audit-safe request identifier.
        provider: Resolved provider name (validated by the executor).

    Returns:
        The workflow identifier.

    Raises:
        HTTPException: Generic 500 when ``executor.start`` raises.
    """
    try:
        workflow_id = str(await executor.start(workflow_input))
    except Exception:  # pylint: disable=broad-exception-caught
        record_start_failed(user_id=user_id, request_id=request_id, provider=provider)
        logger.error(
            "Workflow start failed: user=%s, request_id=%s", user_id, request_id
        )
        raise HTTPException(
            **InternalServerErrorResponse.generic().model_dump()
        ) from None
    record_authorized(
        user_id=user_id,
        request_id=request_id,
        status=status.HTTP_202_ACCEPTED,
        workflow_id=workflow_id,
        provider=provider,
    )
    return workflow_id


@router.post(
    "/workflows/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
@authorize(Action.WORKFLOW_START)
async def start_workflow_handler(
    request: Request,
    body: RunWorkflowRequest,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> dict[str, Any] | JSONResponse:
    """Start a new workflow execution.

    Parameters:
        request: FastAPI request (used by middleware).
        body: Workflow definition and configuration.
        auth: Authentication tuple (used by middleware).

    Returns:
        Workflow ID and initial status. A response carrying ``Deprecation`` and
        ``Sunset`` headers when the caller used the deprecated
        ``credentials_secret`` field.
    """
    user_id, username, _, _ = auth

    check_configuration_loaded(configuration)
    executor = _get_executor()

    spawner_config = configuration.spawner_configuration
    default_sandbox_image = (
        spawner_config.sandbox_image  # pylint: disable=no-member
        if spawner_config
        else "lightspeed-agentic-sandbox:latest"
    )

    # Exactly one audit record per request from here on (issue #51 Phase 2):
    # workflow_denied for any pipeline rejection, workflow_start_failed when
    # start raises, workflow_authorized only after start returned.
    request_id = _request_id(request)
    try:
        resolved, definition = _prepare_submission(
            body,
            principal=Principal(
                user_id=user_id, is_admin=is_admin(request), roles=_user_roles(request)
            ),
            default_sandbox_image=default_sandbox_image,
            spawner_configured=spawner_config is not None,
        )
    except SubmissionRejected as exc:
        record_denied(
            user_id=user_id,
            request_id=request_id,
            status=exc.status_code,
            reasons=exc.reasons,
            paths=exc.paths,
            provider=exc.provider,
        )
        raise

    workflow_input = {
        "definition": definition,
        "provider": resolved.provider,
        "sandbox_image": body.sandbox_image or default_sandbox_image,
        "approval_policy": body.approval_policy,
        "session_id": body.session_id,
        "user_id": user_id,
        "authz_context": {
            "user_id": user_id,
            "username": username,
            "provider": resolved.catalog_name,
            "credential_ref": resolved.credential_ref,
        },
    }
    workflow_id = await _start_audited(
        executor,
        workflow_input,
        user_id=user_id,
        request_id=request_id,
        provider=resolved.catalog_name,
    )

    logger.info(
        "Workflow started: id=%s, user=%s",
        workflow_id,
        username,
    )

    result = {
        "workflow_id": workflow_id,
        "status": "running",
    }
    if resolved.legacy_credentials_secret:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=result,
            headers={"Deprecation": LEGACY_DEPRECATION, "Sunset": LEGACY_SUNSET},
        )
    return result


@router.get("/workflows/{workflow_id}")
@authorize(Action.WORKFLOW_VIEW)
async def get_workflow_handler(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> dict[str, Any]:
    """Get the current status of a workflow execution.

    Parameters:
        request: FastAPI request (used by middleware).
        workflow_id: Target workflow execution ID.
        auth: Authentication tuple (used by middleware).

    Returns:
        Workflow status including step results and events.
    """
    _ = auth
    _ = request

    check_configuration_loaded(configuration)
    executor = _get_executor()

    try:
        wf_status = await executor.get_status(workflow_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found.",
        ) from exc

    return {
        "workflow_id": wf_status.workflow_id,
        "status": wf_status.status,
        "steps": wf_status.steps,
        "events": wf_status.events,
        "is_terminal": wf_status.is_terminal,
    }


@router.post("/workflows/{workflow_id}/approve")
@authorize(Action.WORKFLOW_APPROVE)
async def approve_workflow_handler(
    request: Request,
    workflow_id: str,
    body: ApproveWorkflowRequest,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> dict[str, str]:
    """Send an approval signal to a paused workflow.

    Parameters:
        request: FastAPI request (used by middleware).
        workflow_id: Target workflow execution ID.
        body: Approval decision.
        auth: Authentication tuple (used by middleware).

    Returns:
        Acknowledgement message.
    """
    _ = request
    _, username, _, _ = auth

    check_configuration_loaded(configuration)
    executor = _get_executor()

    from cloud_agents.workflow.executor.base import ApprovalDecision

    decision = ApprovalDecision(
        step_name=body.step_name,
        decision=body.decision,
        approver=body.approver or username,
    )

    try:
        await executor.approve(workflow_id, decision)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    logger.info(
        "Workflow %s: step '%s' %s by %s",
        workflow_id,
        body.step_name,
        body.decision,
        decision.approver,
    )

    return {"message": f"Step '{body.step_name}' {body.decision}."}


@router.post("/workflows/{workflow_id}/cancel")
@authorize(Action.WORKFLOW_CANCEL)
async def cancel_workflow_handler(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> dict[str, str]:
    """Cancel a running workflow.

    Parameters:
        request: FastAPI request (used by middleware).
        workflow_id: Target workflow execution ID.
        auth: Authentication tuple (used by middleware).

    Returns:
        Acknowledgement message.
    """
    _ = auth
    _ = request

    check_configuration_loaded(configuration)
    executor = _get_executor()

    try:
        await executor.cancel(workflow_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found.",
        ) from exc

    logger.info("Workflow %s cancelled", workflow_id)

    return {"message": f"Workflow '{workflow_id}' cancelled."}


@router.get("/workflows/{workflow_id}/transcripts")
@authorize(Action.WORKFLOW_VIEW)
async def get_transcripts_handler(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> dict[str, Any]:
    """Get step transcripts for a workflow.

    Parameters:
        request: FastAPI request (used by middleware).
        workflow_id: Target workflow execution ID.
        auth: Authentication tuple (used by middleware).

    Returns:
        Transcripts keyed by step name.
    """
    _ = auth
    _ = request

    check_configuration_loaded(configuration)
    executor = _get_executor()

    try:
        transcripts = await executor.get_step_transcripts(workflow_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found.",
        ) from exc

    return {"workflow_id": workflow_id, "transcripts": transcripts}
