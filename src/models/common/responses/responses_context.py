"""Request-scoped context model for the responses endpoint pipeline."""

from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks
from llama_stack_client import AsyncLlamaStackClient
from pydantic import BaseModel, ConfigDict, Field

from utils.types import RAGContext, ShieldModerationResult


class ResponsesContext(BaseModel):
    """Shared request-scoped context for the /responses endpoint pipeline."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: AsyncLlamaStackClient = Field(description="The Llama Stack client")
    auth: tuple[str, str, bool, str] = Field(
        description="Authentication tuple (user_id, username, skip_userid_check, token)",
    )
    input_text: str = Field(description="Extracted user input text for the turn")
    started_at: datetime = Field(description="UTC timestamp when the request started")
    moderation_result: ShieldModerationResult = Field(
        description="Shield moderation outcome",
    )
    inline_rag_context: RAGContext = Field(
        description="Inline RAG context for the turn"
    )
    filter_server_tools: bool = Field(
        default=False,
        description="Whether to filter server-deployed MCP tool events from output",
    )
    background_tasks: Optional[BackgroundTasks] = Field(
        default=None,
        description="Background tasks for telemetry, if enabled",
    )
    rh_identity_context: tuple[str, str] = Field(
        default=("", ""),
        description="RH identity (org_id, system_id) for Splunk events",
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="User-Agent string from request headers",
    )
    endpoint_path: str = Field(
        ...,
        description="API endpoint path used for metric labeling",
    )
    generate_topic_summary: bool = Field(
        default=False,
        description="Whether to generate a topic summary for new conversations",
    )
