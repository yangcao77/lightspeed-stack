"""Unit tests for the /streaming-query REST API endpoint."""

# pylint: disable=too-many-lines,too-many-function-args
import json
from typing import Any

import pytest
from pydantic import AnyUrl
from pytest_mock import MockerFixture

from app.endpoints.streaming_query import (
    LLM_TOKEN_EVENT,
    LLM_TOOL_CALL_EVENT,
    LLM_TOOL_RESULT_EVENT,
    generic_llm_error,
    prompt_too_long_error,
    stream_end_event,
    stream_event,
)
from configuration import AppConfig
from constants import MEDIA_TYPE_JSON, MEDIA_TYPE_TEXT
from models.requests import QueryRequest
from models.responses import ReferencedDocument
from utils.token_counter import TokenCounter

# Note: content_delta module doesn't exist in llama-stack-client 0.3.x
# These are mock classes for backward compatibility with Agent API tests
# pylint: disable=too-few-public-methods,redefined-builtin


class TextDelta:
    """Mock TextDelta for Agent API tests."""

    def __init__(self, text: str, type: str = "text"):  # noqa: A002
        """
        Initialize the object with textual content and a chunk type.

        Parameters:
            text (str): The textual content for this instance.
            type (str): The content type or category (for example, "text"). Defaults to "text".
        """
        self.text = text
        self.type = type


class ToolCallDelta:
    """Mock ToolCallDelta for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


# Note: Agent API types don't exist in llama-stack-client 0.3.x
# These are mock classes for backward compatibility with Agent API tests


class TurnResponseEvent:
    """Mock TurnResponseEvent for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseStreamChunk:
    """Mock AgentTurnResponseStreamChunk for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseStepCompletePayload:
    """Mock AgentTurnResponseStepCompletePayload for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseStepProgressPayload:
    """Mock AgentTurnResponseStepProgressPayload for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseTurnAwaitingInputPayload:
    """Mock AgentTurnResponseTurnAwaitingInputPayload for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseTurnCompletePayload:
    """Mock AgentTurnResponseTurnCompletePayload for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class AgentTurnResponseTurnStartPayload:
    """Mock AgentTurnResponseTurnStartPayload for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class ToolExecutionStep:
    """Mock ToolExecutionStep for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


class ToolResponse:
    """Mock ToolResponse for Agent API tests."""

    def __init__(self, **kwargs: Any):
        """
        Initialize the instance by setting attributes from the provided keyword arguments.

        Parameters:
            **kwargs: Any
                Attribute names and values to assign to the instance. Each key in
                `kwargs` becomes an attribute on the created object with the
                corresponding value.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


# pylint: enable=too-few-public-methods,redefined-builtin

MOCK_AUTH = (
    "017adfa4-7cc6-46e4-b663-3653e1ae69df",
    "mock_username",
    False,
    "mock_token",
)


def mock_database_operations(mocker: MockerFixture) -> None:
    """Helper function to mock database operations for streaming query endpoints.

    Configure test mocks for conversation ownership validation and post-stream
    cleanup used by streaming-query tests.

    Parameters:
        mocker (MockerFixture): Pytest-mock fixture used to patch functions.
        After calling this helper, `validate_conversation_ownership` is patched
        to return `True` and `cleanup_after_streaming` is patched to an async
        no-op.
    """
    mocker.patch(
        "app.endpoints.streaming_query.validate_conversation_ownership",
        return_value=True,
    )
    # Mock the cleanup function that handles all post-streaming database/cache work
    mocker.patch(
        "app.endpoints.streaming_query.cleanup_after_streaming",
        mocker.AsyncMock(return_value=None),
    )


def mock_metrics(mocker: MockerFixture) -> None:
    """Helper function to mock metrics operations for streaming query endpoints."""
    # Mock the metrics that are used in the streaming query endpoints
    mocker.patch("metrics.llm_token_sent_total")
    mocker.patch("metrics.llm_token_received_total")
    mocker.patch("metrics.llm_calls_total")


SAMPLE_KNOWLEDGE_SEARCH_RESULTS = [
    """knowledge_search tool found 2 chunks:
BEGIN of knowledge_search tool results.
""",
    """Result 1
Content: ABC
Metadata: {'docs_url': 'https://example.com/doc1', 'title': 'Doc1', 'document_id': 'doc-1', \
'source': None}
""",
    """Result 2
Content: ABC
Metadata: {'docs_url': 'https://example.com/doc2', 'title': 'Doc2', 'document_id': 'doc-2', \
'source': None}
""",
    """END of knowledge_search tool results.
""",
    # Following metadata contains an intentionally incorrect keyword "Title" (instead of "title")
    # and it is not picked as a referenced document.
    """Result 3
Content: ABC
Metadata: {'docs_url': 'https://example.com/doc3', 'Title': 'Doc3', 'document_id': 'doc-3', \
'source': None}
""",
    """The above results were retrieved to help answer the user\'s query: "Sample Query".
Use them as supporting information only in answering this query.
""",
]


@pytest.fixture(autouse=True, name="setup_configuration")
def setup_configuration_fixture() -> AppConfig:
    """Set up configuration for tests.

    Create and initialize an AppConfig instance preconfigured for unit tests.

    The configuration uses a local service (localhost:8080), a test Llama Stack
    API key and URL, disables user transcript collection, and sets a noop
    conversation cache and empty MCP servers to avoid external dependencies.

    Returns:
        AppConfig: An initialized AppConfig populated with the test settings.
    """
    config_dict = {
        "name": "test",
        "service": {
            "host": "localhost",
            "port": 8080,
            "auth_enabled": False,
            "workers": 1,
            "color_log": True,
            "access_log": True,
        },
        "llama_stack": {
            "api_key": "test-key",
            "url": "http://test.com:1234",
            "use_as_library_client": False,
        },
        "user_data_collection": {
            "transcripts_enabled": False,
        },
        "mcp_servers": [],
        "conversation_cache": {
            "type": "noop",
        },
    }
    cfg = AppConfig()
    cfg.init_from_dict(config_dict)
    return cfg


# ============================================================================
# OLS Compatibility Tests
# ============================================================================


class TestOLSStreamEventFormatting:
    """Test the stream_event function for both media types (OLS compatibility)."""

    def test_stream_event_json_token(self) -> None:
        """Test token event formatting for JSON media type."""
        data = {"id": 0, "token": "Hello"}
        result = stream_event(data, LLM_TOKEN_EVENT, MEDIA_TYPE_JSON)

        expected = 'data: {"event": "token", "data": {"id": 0, "token": "Hello"}}\n\n'
        assert result == expected

    def test_stream_event_text_token(self) -> None:
        """Test token event formatting for text media type."""

        data = {"id": 0, "token": "Hello"}
        result = stream_event(data, LLM_TOKEN_EVENT, MEDIA_TYPE_TEXT)

        assert result == "Hello"

    def test_stream_event_json_tool_call(self) -> None:
        """Test tool call event formatting for JSON media type."""

        data = {
            "id": 0,
            "token": {"tool_name": "search", "arguments": {"query": "test"}},
        }
        result = stream_event(data, LLM_TOOL_CALL_EVENT, MEDIA_TYPE_JSON)

        expected = (
            'data: {"event": "tool_call", "data": {"id": 0, "token": '
            '{"tool_name": "search", "arguments": {"query": "test"}}}}\n\n'
        )
        assert result == expected

    def test_stream_event_text_tool_call(self) -> None:
        """Test tool call event formatting for text media type."""

        data = {
            "id": 0,
            "token": {"tool_name": "search", "arguments": {"query": "test"}},
        }
        result = stream_event(data, LLM_TOOL_CALL_EVENT, MEDIA_TYPE_TEXT)

        expected = (
            '\nTool call: {"id": 0, "token": '
            '{"tool_name": "search", "arguments": {"query": "test"}}}\n'
        )
        assert result == expected

    def test_stream_event_json_tool_result(self) -> None:
        """Test tool result event formatting for JSON media type."""

        data = {
            "id": 0,
            "token": {"tool_name": "search", "response": "Found results"},
        }
        result = stream_event(data, LLM_TOOL_RESULT_EVENT, MEDIA_TYPE_JSON)

        expected = (
            'data: {"event": "tool_result", "data": {"id": 0, "token": '
            '{"tool_name": "search", "response": "Found results"}}}\n\n'
        )
        assert result == expected

    def test_stream_event_text_tool_result(self) -> None:
        """Test tool result event formatting for text media type."""

        data = {
            "id": 0,
            "token": {"tool_name": "search", "response": "Found results"},
        }
        result = stream_event(data, LLM_TOOL_RESULT_EVENT, MEDIA_TYPE_TEXT)

        expected = (
            '\nTool result: {"id": 0, "token": '
            '{"tool_name": "search", "response": "Found results"}}\n'
        )
        assert result == expected

    def test_stream_event_unknown_type(self) -> None:
        """Test handling of unknown event types."""

        data = {"id": 0, "token": "test"}
        result = stream_event(data, "unknown_event", MEDIA_TYPE_TEXT)

        assert result == ""


class TestOLSStreamEndEvent:
    """Test the stream_end_event function for both media types (OLS compatibility)."""

    def test_stream_end_event_json(self) -> None:
        """Test end event formatting for JSON media type."""

        metadata_map = {
            "doc1": {"title": "Test Doc 1", "docs_url": "https://example.com/doc1"},
            "doc2": {"title": "Test Doc 2", "docs_url": "https://example.com/doc2"},
        }
        # Create mock objects for the test
        mock_token_usage = TokenCounter(input_tokens=100, output_tokens=50)
        available_quotas: dict[str, int] = {}
        referenced_documents = [
            ReferencedDocument(
                doc_url=AnyUrl("https://example.com/doc1"), doc_title="Test Doc 1"
            ),
            ReferencedDocument(
                doc_url=AnyUrl("https://example.com/doc2"), doc_title="Test Doc 2"
            ),
        ]
        result = stream_end_event(
            metadata_map,
            mock_token_usage,
            available_quotas,
            referenced_documents,
            MEDIA_TYPE_JSON,
        )

        # Parse the result to verify structure
        data_part = result.replace("data: ", "").strip()
        parsed = json.loads(data_part)

        assert parsed["event"] == "end"
        assert "referenced_documents" in parsed["data"]
        assert len(parsed["data"]["referenced_documents"]) == 2
        assert parsed["data"]["referenced_documents"][0]["doc_title"] == "Test Doc 1"
        assert (
            parsed["data"]["referenced_documents"][0]["doc_url"]
            == "https://example.com/doc1"
        )
        assert "available_quotas" in parsed

    def test_stream_end_event_text(self) -> None:
        """Test end event formatting for text media type."""

        metadata_map = {
            "doc1": {"title": "Test Doc 1", "docs_url": "https://example.com/doc1"},
            "doc2": {"title": "Test Doc 2", "docs_url": "https://example.com/doc2"},
        }
        # Create mock objects for the test
        mock_token_usage = TokenCounter(input_tokens=100, output_tokens=50)
        available_quotas: dict[str, int] = {}
        referenced_documents = [
            ReferencedDocument(
                doc_url=AnyUrl("https://example.com/doc1"), doc_title="Test Doc 1"
            ),
            ReferencedDocument(
                doc_url=AnyUrl("https://example.com/doc2"), doc_title="Test Doc 2"
            ),
        ]
        result = stream_end_event(
            metadata_map,
            mock_token_usage,
            available_quotas,
            referenced_documents,
            MEDIA_TYPE_TEXT,
        )

        expected = (
            "\n\n---\n\nTest Doc 1: https://example.com/doc1\n"
            "Test Doc 2: https://example.com/doc2"
        )
        assert result == expected

    def test_stream_end_event_text_no_docs(self) -> None:
        """Test end event formatting for text media type with no documents."""

        metadata_map: dict = {}
        # Create mock objects for the test
        mock_token_usage = TokenCounter(input_tokens=100, output_tokens=50)
        available_quotas: dict[str, int] = {}
        referenced_documents: list[ReferencedDocument] = []
        result = stream_end_event(
            metadata_map,
            mock_token_usage,
            available_quotas,
            referenced_documents,
            MEDIA_TYPE_TEXT,
        )

        assert result == ""


class TestOLSErrorHandling:
    """Test error handling functions (OLS compatibility)."""

    def test_prompt_too_long_error_json(self) -> None:
        """Test prompt too long error for JSON media type."""

        error = Exception("Prompt exceeds maximum length")
        result = prompt_too_long_error(error, MEDIA_TYPE_JSON)

        data_part = result.replace("data: ", "").strip()
        parsed = json.loads(data_part)
        assert parsed["event"] == "error"
        assert parsed["data"]["status_code"] == 413
        assert parsed["data"]["response"] == "Prompt is too long"
        assert parsed["data"]["cause"] == "Prompt exceeds maximum length"

    def test_prompt_too_long_error_text(self) -> None:
        """Test prompt too long error for text media type."""

        error = Exception("Prompt exceeds maximum length")
        result = prompt_too_long_error(error, MEDIA_TYPE_TEXT)

        assert result == "Prompt is too long: Prompt exceeds maximum length"

    def test_generic_llm_error_json(self) -> None:
        """Test generic LLM error for JSON media type."""

        error = Exception("Connection failed")
        result = generic_llm_error(error, MEDIA_TYPE_JSON)

        data_part = result.replace("data: ", "").strip()
        parsed = json.loads(data_part)
        assert parsed["event"] == "error"
        assert parsed["data"]["response"] == "Internal server error"
        assert parsed["data"]["cause"] == "Connection failed"

    def test_generic_llm_error_text(self) -> None:
        """Test generic LLM error for text media type."""

        error = Exception("Connection failed")
        result = generic_llm_error(error, MEDIA_TYPE_TEXT)

        assert result == "Error: Connection failed"


class TestOLSCompatibilityIntegration:
    """Integration tests for OLS compatibility."""

    def test_media_type_validation(self) -> None:
        """Test that media type validation works correctly."""

        # Valid media types
        valid_request = QueryRequest(query="test", media_type="application/json")
        assert valid_request.media_type == "application/json"

        valid_request = QueryRequest(query="test", media_type="text/plain")
        assert valid_request.media_type == "text/plain"

        # Invalid media type should raise error
        with pytest.raises(ValueError, match="media_type must be either"):
            QueryRequest(query="test", media_type="invalid/type")

    def test_ols_event_structure(self) -> None:
        """Test that events follow OLS structure."""

        # Test token event structure
        token_data = {"id": 0, "token": "Hello"}
        token_event = stream_event(token_data, LLM_TOKEN_EVENT, MEDIA_TYPE_JSON)

        data_part = token_event.replace("data: ", "").strip()
        parsed = json.loads(data_part)

        assert parsed["event"] == "token"
        assert "id" in parsed["data"]
        assert "token" in parsed["data"]
        assert "role" not in parsed["data"]  # Role field is not included

        # Test tool call event structure
        tool_data = {
            "id": 0,
            "token": {"tool_name": "search", "arguments": {"query": "test"}},
        }
        tool_event = stream_event(tool_data, LLM_TOOL_CALL_EVENT, MEDIA_TYPE_JSON)

        data_part = tool_event.replace("data: ", "").strip()
        parsed = json.loads(data_part)

        assert parsed["event"] == "tool_call"
        assert "id" in parsed["data"]
        assert "role" not in parsed["data"]
        assert "token" in parsed["data"]

        # Test tool result event structure
        result_data = {
            "id": 0,
            "token": {"tool_name": "search", "response": "Found results"},
        }
        result_event = stream_event(result_data, LLM_TOOL_RESULT_EVENT, MEDIA_TYPE_JSON)

        data_part = result_event.replace("data: ", "").strip()
        parsed = json.loads(data_part)

        assert parsed["event"] == "tool_result"
        assert "id" in parsed["data"]
        assert "role" not in parsed["data"]
        assert "token" in parsed["data"]

    def test_ols_end_event_structure(self) -> None:
        """Test that end event follows OLS structure."""

        metadata_map = {
            "doc1": {"title": "Test Doc", "docs_url": "https://example.com/doc"}
        }
        # Create mock objects for the test
        mock_token_usage = TokenCounter(input_tokens=100, output_tokens=50)
        available_quotas: dict[str, int] = {}
        referenced_documents = [
            ReferencedDocument(
                doc_url=AnyUrl("https://example.com/doc"), doc_title="Test Doc"
            ),
        ]
        end_event = stream_end_event(
            metadata_map,
            mock_token_usage,
            available_quotas,
            referenced_documents,
            MEDIA_TYPE_JSON,
        )
        data_part = end_event.replace("data: ", "").strip()
        parsed = json.loads(data_part)

        assert parsed["event"] == "end"
        assert "referenced_documents" in parsed["data"]
        assert "truncated" in parsed["data"]
        assert "input_tokens" in parsed["data"]
        assert "output_tokens" in parsed["data"]
        assert "available_quotas" in parsed  # At root level, not inside data
