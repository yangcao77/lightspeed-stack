"""Request models for workflow endpoints.

POST /v1/workflows/run is the only agent execution endpoint: a one-shot
agent invocation is submitted as a one-step workflow definition (see the
``RunWorkflowRequest.definition`` schema and the one-step ``agent`` /
``result`` naming convention in cloud-agents).
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema


class RunWorkflowRequest(BaseModel):
    """Request body for POST /v1/workflows/run.

    A one-shot agent invocation is a one-step workflow: a definition with a
    single agent step using the ``agent`` / ``result`` naming convention.
    One-step workflows take exactly the same path as multi-step workflows
    (normalization, executor selection, status, cancellation, transcripts,
    persistence).

    Attributes:
        definition: Workflow definition (same schema as cloud-agents YAML).
        provider: Default LLM provider config for all steps.
        sandbox_image: Default sandbox image for ephemeral steps.
        approval_policy: Optional approval policy.
        session_id: Optional caller-provided ID grouping related workflow runs.
    """

    definition: dict[str, Any] = Field(
        ...,
        description="Workflow definition with apiVersion, kind, metadata, spec. "
        "A one-step workflow uses a single agent step named 'agent' with "
        "output_key 'result'.",
    )

    provider: Optional[dict[str, Any]] = Field(
        None,
        description="Default provider config: {name, model}. The stack chooses the credential; credentials_secret is rejected.",
    )

    sandbox_image: Optional[str] = Field(
        None,
        description="Default sandbox image for ephemeral steps.",
    )

    approval_policy: Optional[dict[str, Any]] = Field(
        None,
        description="Approval policy for human-approval steps.",
    )

    session_id: Optional[str] = Field(
        None,
        description="Caller-provided ID grouping related workflow runs.",
    )

    # Not part of the API (so not in the docstring, which becomes the schema
    # description). Captured only so the handler can answer a caller-sent
    # run-level field with a 400 (issue #51 Phase 3) instead of pydantic
    # silently dropping it: the field name in model_fields_set means the
    # caller sent it. SkipJsonSchema keeps it out of OpenAPI and exclude
    # keeps the value out of every dump; the handler never reads the value.
    mcp_servers: SkipJsonSchema[Any] = Field(default=None, exclude=True)

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: Optional[str]) -> Optional[str]:
        """Treat an empty string session_id the same as omitted.

        Parameters:
            value: Raw session_id from the request; may be None or empty.

        Returns:
            None if the value is empty, otherwise the original value.
        """
        return value or None


class ApproveWorkflowRequest(BaseModel):
    """Request body for POST /v1/workflows/{id}/approve.

    Attributes:
        step_name: Name of the approval step.
        decision: Approval decision.
        approver: Identity of the approver.
    """

    step_name: str = Field(
        ...,
        description="Name of the approval step to approve.",
    )

    decision: Literal["approved", "rejected"] = Field(
        ...,
        description="Approval decision.",
    )

    approver: str = Field(
        "",
        description="Identity of the approver.",
    )
