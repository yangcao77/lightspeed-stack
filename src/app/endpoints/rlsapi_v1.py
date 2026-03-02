"""Handler for RHEL Lightspeed rlsapi v1 REST API endpoints.

This module provides the /infer endpoint for stateless inference requests
from the RHEL Lightspeed Command Line Assistant (CLA).
"""

import time
from typing import Annotated, Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from llama_stack_api.openai_responses import OpenAIResponseObject
from llama_stack_client import APIConnectionError, APIStatusError, RateLimitError
from openai._exceptions import APIStatusError as OpenAIAPIStatusError

import constants
import metrics
from authentication import get_auth_dependency
from authentication.interface import AuthTuple
from authentication.rh_identity import RHIdentityData
from authorization.middleware import authorize
from client import AsyncLlamaStackClientHolder
from configuration import configuration
from models.config import Action
from models.responses import (
    ForbiddenResponse,
    InternalServerErrorResponse,
    PromptTooLongResponse,
    QuotaExceededResponse,
    ServiceUnavailableResponse,
    UnauthorizedResponse,
    UnprocessableEntityResponse,
)
from models.rlsapi.requests import RlsapiV1InferRequest, RlsapiV1SystemInfo
from models.rlsapi.responses import RlsapiV1InferData, RlsapiV1InferResponse
from observability import InferenceEventData, build_inference_event, send_splunk_event
from utils.query import (
    extract_provider_and_model_from_model_id,
    handle_known_apistatus_errors,
)
from utils.responses import (
    extract_text_from_response_items,
    extract_token_usage,
    get_mcp_tools,
)
from utils.suid import get_suid
from log import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["rlsapi-v1"])

# Default values when RH Identity auth is not configured
AUTH_DISABLED = "auth_disabled"


def _get_rh_identity_context(request: Request) -> tuple[str, str]:
    """Extract org_id and system_id from RH Identity request state.

    When RH Identity authentication is configured, the auth dependency stores
    the RHIdentityData object in request.state.rh_identity_data. This function
    extracts the org_id and system_id for telemetry purposes.

    Args:
        request: The FastAPI request object.

    Returns:
        Tuple of (org_id, system_id). Returns ("auth_disabled", "auth_disabled")
        when RH Identity auth is not configured or data is unavailable.
    """
    rh_identity: RHIdentityData | None = getattr(
        request.state, "rh_identity_data", None
    )
    if rh_identity is None:
        return AUTH_DISABLED, AUTH_DISABLED

    org_id = rh_identity.get_org_id() or AUTH_DISABLED
    system_id = rh_identity.get_user_id() or AUTH_DISABLED
    return org_id, system_id


infer_responses: dict[int | str, dict[str, Any]] = {
    200: RlsapiV1InferResponse.openapi_response(),
    401: UnauthorizedResponse.openapi_response(
        examples=["missing header", "missing token"]
    ),
    403: ForbiddenResponse.openapi_response(examples=["endpoint"]),
    413: PromptTooLongResponse.openapi_response(),
    422: UnprocessableEntityResponse.openapi_response(),
    429: QuotaExceededResponse.openapi_response(),
    500: InternalServerErrorResponse.openapi_response(examples=["generic"]),
    503: ServiceUnavailableResponse.openapi_response(),
}


def _build_instructions(systeminfo: RlsapiV1SystemInfo) -> str:
    """Build LLM instructions incorporating system context when available.

    Enhances the default system prompt with RHEL system information to provide
    the LLM with relevant context about the user's environment.

    Args:
        systeminfo: System information from the client (OS, version, arch).

    Returns:
        Instructions string for the LLM, with system context if available.
    """
    base_prompt = _get_base_prompt()

    context_parts = []
    if systeminfo.os:
        context_parts.append(f"OS: {systeminfo.os}")
    if systeminfo.version:
        context_parts.append(f"Version: {systeminfo.version}")
    if systeminfo.arch:
        context_parts.append(f"Architecture: {systeminfo.arch}")

    if not context_parts:
        return base_prompt

    system_context = ", ".join(context_parts)
    return f"{base_prompt}\n\nUser's system: {system_context}"


def _get_base_prompt() -> str:
    """Get the base system prompt with configuration fallback."""
    if (
        configuration.customization is not None
        and configuration.customization.system_prompt is not None
    ):
        return configuration.customization.system_prompt
    return constants.DEFAULT_SYSTEM_PROMPT


def _get_default_model_id() -> str:
    """Get the default model ID from configuration.

    Returns the model identifier in Llama Stack format (provider/model).

    Returns:
        The model identifier string.

    Raises:
        HTTPException: If no model can be determined from configuration.
    """
    if configuration.inference is None:
        msg = "No inference configuration available"
        logger.error(msg)
        error_response = ServiceUnavailableResponse(
            backend_name="inference service (configuration)",
            cause=msg,
        )
        raise HTTPException(**error_response.model_dump())

    model_id = configuration.inference.default_model
    provider_id = configuration.inference.default_provider

    if model_id and provider_id:
        return f"{provider_id}/{model_id}"

    msg = "No default model configured for rlsapi v1 inference"
    logger.error(msg)
    error_response = ServiceUnavailableResponse(
        backend_name="inference service (configuration)",
        cause=msg,
    )
    raise HTTPException(**error_response.model_dump())


async def retrieve_simple_response(
    question: str,
    instructions: str,
    tools: list[Any] | None = None,
    model_id: str | None = None,
) -> str:
    """Retrieve a simple response from the LLM for a stateless query.

    Uses the Responses API for simple stateless inference, consistent with
    other endpoints (query, streaming_query).

    Args:
        question: The combined user input (question + context).
        instructions: System instructions for the LLM.
        tools: Optional list of MCP tool definitions for the LLM.
        model_id: Fully qualified model identifier in provider/model format.
            When omitted, the configured default model is used.

    Returns:
        The LLM-generated response text.

    Raises:
        APIConnectionError: If the Llama Stack service is unreachable.
        HTTPException: 503 if no default model is configured.
    """
    client = AsyncLlamaStackClientHolder().get_client()
    resolved_model_id = model_id or _get_default_model_id()
    logger.debug("Using model %s for rlsapi v1 inference", resolved_model_id)

    response = await client.responses.create(
        input=question,
        model=resolved_model_id,
        instructions=instructions,
        tools=tools or [],
        stream=False,
        store=False,
    )
    response = cast(OpenAIResponseObject, response)
    extract_token_usage(response.usage, model_id)

    return extract_text_from_response_items(response.output)


def _get_cla_version(request: Request) -> str:
    """Extract CLA version from User-Agent header."""
    return request.headers.get("User-Agent", "")


def _get_configured_default_model_name() -> str:
    """Get configured default model name for telemetry payloads."""
    if configuration.inference is None:
        return ""
    return configuration.inference.default_model or ""


def _queue_splunk_event(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    background_tasks: BackgroundTasks,
    infer_request: RlsapiV1InferRequest,
    request: Request,
    request_id: str,
    response_text: str,
    inference_time: float,
    sourcetype: str,
) -> None:
    """Build and queue a Splunk telemetry event for background sending."""
    org_id, system_id = _get_rh_identity_context(request)
    systeminfo = infer_request.context.systeminfo

    event_data = InferenceEventData(
        question=infer_request.question,
        response=response_text,
        inference_time=inference_time,
        model=_get_configured_default_model_name(),
        org_id=org_id,
        system_id=system_id,
        request_id=request_id,
        cla_version=_get_cla_version(request),
        system_os=systeminfo.os,
        system_version=systeminfo.version,
        system_arch=systeminfo.arch,
    )

    event = build_inference_event(event_data)
    background_tasks.add_task(send_splunk_event, event, sourcetype)


def _record_inference_failure(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    background_tasks: BackgroundTasks,
    infer_request: RlsapiV1InferRequest,
    request: Request,
    request_id: str,
    error: Exception,
    start_time: float,
    model: str,
    provider: str,
) -> float:
    """Record metrics and queue Splunk event for an inference failure.

    Args:
        background_tasks: FastAPI background tasks for async event sending.
        infer_request: The original inference request.
        request: The FastAPI request object.
        request_id: Unique identifier for the request.
        error: The exception that caused the failure.
        start_time: Monotonic clock time when inference started.

    Returns:
        The total inference time in seconds.
    """
    inference_time = time.monotonic() - start_time
    metrics.llm_calls_failures_total.labels(provider, model).inc()
    _queue_splunk_event(
        background_tasks,
        infer_request,
        request,
        request_id,
        str(error),
        inference_time,
        "infer_error",
    )
    return inference_time


def _map_inference_error_to_http_exception(
    error: Exception, model_id: str, request_id: str
) -> HTTPException | None:
    """Map known inference errors to HTTPException.

    Returns None for RuntimeError values that are not context-length related,
    so callers can preserve existing re-raise behavior for unknown runtime
    errors.
    """
    if isinstance(error, RuntimeError):
        if "context_length" in str(error).lower():
            logger.error("Prompt too long for request %s: %s", request_id, error)
            error_response = PromptTooLongResponse(model=model_id)
            return HTTPException(**error_response.model_dump())
        logger.error("Unexpected RuntimeError for request %s: %s", request_id, error)
        return None

    if isinstance(error, APIConnectionError):
        logger.error(
            "Unable to connect to Llama Stack for request %s: %s", request_id, error
        )
        error_response = ServiceUnavailableResponse(
            backend_name="Llama Stack",
            cause="Unable to connect to the inference backend",
        )
        return HTTPException(**error_response.model_dump())

    if isinstance(error, RateLimitError):
        logger.error("Rate limit exceeded for request %s: %s", request_id, error)
        error_response = QuotaExceededResponse(
            response="The quota has been exceeded",
            cause="Rate limit exceeded, please try again later",
        )
        return HTTPException(**error_response.model_dump())

    if isinstance(error, (APIStatusError, OpenAIAPIStatusError)):
        logger.exception("API error for request %s: %s", request_id, error)
        error_response = handle_known_apistatus_errors(error, model_id)
        return HTTPException(**error_response.model_dump())

    return None


@router.post("/infer", responses=infer_responses)
@authorize(Action.RLSAPI_V1_INFER)
async def infer_endpoint(  # pylint: disable=R0914
    infer_request: RlsapiV1InferRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> RlsapiV1InferResponse:
    """Handle rlsapi v1 /infer requests for stateless inference.

    This endpoint serves requests from the RHEL Lightspeed Command Line Assistant (CLA).

    Accepts a question with optional context (stdin, attachments, terminal output,
    system info) and returns an LLM-generated response.

    Args:
        infer_request: The inference request containing question and context.
        request: The FastAPI request object for accessing headers and state.
        background_tasks: FastAPI background tasks for async Splunk event sending.
        auth: Authentication tuple from the configured auth provider.

    Returns:
        RlsapiV1InferResponse containing the generated response text and request ID.

    Raises:
        HTTPException: 503 if the LLM service is unavailable.
    """
    # Authentication enforced by get_auth_dependency(), authorization by @authorize decorator.
    _ = auth

    request_id = get_suid()

    logger.info("Processing rlsapi v1 /infer request %s", request_id)

    input_source = infer_request.get_input_source()
    instructions = _build_instructions(infer_request.context.systeminfo)
    model_id = _get_default_model_id()
    provider, model = extract_provider_and_model_from_model_id(model_id)
    mcp_tools = await get_mcp_tools(request_headers=request.headers)
    logger.debug(
        "Request %s: Combined input source length: %d", request_id, len(input_source)
    )

    start_time = time.monotonic()
    try:
        response_text = await retrieve_simple_response(
            input_source,
            instructions,
            tools=cast(list[Any], mcp_tools),
            model_id=model_id,
        )
        inference_time = time.monotonic() - start_time
    except (
        RuntimeError,
        APIConnectionError,
        RateLimitError,
        APIStatusError,
        OpenAIAPIStatusError,
    ) as error:
        _record_inference_failure(
            background_tasks,
            infer_request,
            request,
            request_id,
            error,
            start_time,
            model,
            provider,
        )
        mapped_error = _map_inference_error_to_http_exception(
            error,
            model_id,
            request_id,
        )
        if mapped_error is not None:
            raise mapped_error from error
        raise

    if not response_text:
        logger.warning("Empty response from LLM for request %s", request_id)
        response_text = constants.UNABLE_TO_PROCESS_RESPONSE

    _queue_splunk_event(
        background_tasks,
        infer_request,
        request,
        request_id,
        response_text,
        inference_time,
        "infer_with_llm",
    )

    logger.info("Completed rlsapi v1 /infer request %s", request_id)

    return RlsapiV1InferResponse(
        data=RlsapiV1InferData(
            text=response_text,
            request_id=request_id,
        )
    )
