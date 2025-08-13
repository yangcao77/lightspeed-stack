"""Unit tests for the /conversations REST API endpoints."""

import pytest
from fastapi import HTTPException, status
from llama_stack_client import APIConnectionError, NotFoundError

from app.endpoints.conversations import (
    get_conversation_endpoint_handler,
    delete_conversation_endpoint_handler,
    get_conversations_list_endpoint_handler,
    simplify_session_data,
)
from models.responses import (
    ConversationResponse,
    ConversationDeleteResponse,
    ConversationsListResponse,
)
from configuration import AppConfig

MOCK_AUTH = ("mock_user_id", "mock_username", "mock_token")
VALID_CONVERSATION_ID = "123e4567-e89b-12d3-a456-426614174000"
INVALID_CONVERSATION_ID = "invalid-id"


def create_mock_conversation(
    mocker,
    conversation_id,
    created_at,
    last_message_at,
    message_count,
    last_used_model,
    last_used_provider,
):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Helper function to create a mock conversation object with all required attributes."""
    mock_conversation = mocker.Mock()
    mock_conversation.id = conversation_id
    mock_conversation.created_at = mocker.Mock()
    mock_conversation.created_at.isoformat.return_value = created_at
    mock_conversation.last_message_at = mocker.Mock()
    mock_conversation.last_message_at.isoformat.return_value = last_message_at
    mock_conversation.message_count = message_count
    mock_conversation.last_used_model = last_used_model
    mock_conversation.last_used_provider = last_used_provider
    return mock_conversation


def mock_database_session(mocker, query_result=None):
    """Helper function to mock get_session with proper context manager support."""
    mock_session = mocker.Mock()
    if query_result is not None:
        mock_session.query.return_value.filter_by.return_value.all.return_value = (
            query_result
        )

    # Mock get_session to return a context manager
    mock_session_context = mocker.MagicMock()
    mock_session_context.__enter__.return_value = mock_session
    mock_session_context.__exit__.return_value = None
    mocker.patch(
        "app.endpoints.conversations.get_session", return_value=mock_session_context
    )
    return mock_session


@pytest.fixture(name="setup_configuration")
def setup_configuration_fixture():
    """Set up configuration for tests."""
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
        "customization": None,
    }
    cfg = AppConfig()
    cfg.init_from_dict(config_dict)
    return cfg


@pytest.fixture(name="mock_session_data")
def mock_session_data_fixture():
    """Create mock session data for testing."""
    return {
        "session_id": VALID_CONVERSATION_ID,
        "session_name": "test-session",
        "started_at": "2024-01-01T00:00:00Z",
        "turns": [
            {
                "turn_id": "turn-1",
                "input_messages": [
                    {"content": "Hello", "role": "user", "context": None}
                ],
                "output_message": {
                    "content": "Hi there!",
                    "role": "assistant",
                    "stop_reason": "end_of_turn",
                    "tool_calls": [],
                },
                "started_at": "2024-01-01T00:01:00Z",
                "completed_at": "2024-01-01T00:01:05Z",
                "steps": [],  # Detailed steps that should be filtered out
            },
            {
                "turn_id": "turn-2",
                "input_messages": [
                    {"content": "How are you?", "role": "user", "context": None}
                ],
                "output_message": {
                    "content": "I'm doing well, thanks!",
                    "role": "assistant",
                    "stop_reason": "end_of_turn",
                    "tool_calls": [],
                },
                "started_at": "2024-01-01T00:02:00Z",
                "completed_at": "2024-01-01T00:02:03Z",
                "steps": [],  # Detailed steps that should be filtered out
            },
        ],
    }


@pytest.fixture(name="expected_chat_history")
def expected_chat_history_fixture():
    """Create expected simplified chat history for testing."""
    return [
        {
            "messages": [
                {"content": "Hello", "type": "user"},
                {"content": "Hi there!", "type": "assistant"},
            ],
            "started_at": "2024-01-01T00:01:00Z",
            "completed_at": "2024-01-01T00:01:05Z",
            "model_id": "test-model",
            "provider_id": "test-provider",
        },
        {
            "messages": [
                {"content": "How are you?", "type": "user"},
                {"content": "I'm doing well, thanks!", "type": "assistant"},
            ],
            "started_at": "2024-01-01T00:02:00Z",
            "completed_at": "2024-01-01T00:02:03Z",
            "model_id": "test-model",
            "provider_id": "test-provider",
        },
    ]


class TestSimplifySessionData:
    """Test cases for the simplify_session_data function."""

    @pytest.mark.asyncio
    async def test_simplify_session_data_with_model_dump(
        self, mock_session_data, expected_chat_history
    ):
        """Test simplify_session_data with session data."""
        result = simplify_session_data(mock_session_data, "test-model", "test-provider")

        assert result == expected_chat_history

    @pytest.mark.asyncio
    async def test_simplify_session_data_empty_turns(self):
        """Test simplify_session_data with empty turns."""
        session_data = {
            "session_id": VALID_CONVERSATION_ID,
            "started_at": "2024-01-01T00:00:00Z",
            "turns": [],
        }

        result = simplify_session_data(session_data, "test-model", "test-provider")

        assert not result

    @pytest.mark.asyncio
    async def test_simplify_session_data_filters_unwanted_fields(self):
        """Test that simplify_session_data properly filters out unwanted fields."""
        session_data = {
            "session_id": VALID_CONVERSATION_ID,
            "turns": [
                {
                    "turn_id": "turn-1",
                    "input_messages": [
                        {
                            "content": "Test message",
                            "role": "user",
                            "context": {"some": "context"},  # Should be filtered out
                            "metadata": {"extra": "data"},  # Should be filtered out
                        }
                    ],
                    "output_message": {
                        "content": "Test response",
                        "role": "assistant",
                        "stop_reason": "end_of_turn",  # Should be filtered out
                        "tool_calls": ["tool1", "tool2"],  # Should be filtered out
                    },
                    "started_at": "2024-01-01T00:01:00Z",
                    "completed_at": "2024-01-01T00:01:05Z",
                    "steps": ["step1", "step2"],  # Should be filtered out
                }
            ],
        }

        result = simplify_session_data(session_data, "test-model", "test-provider")

        expected = [
            {
                "messages": [
                    {"content": "Test message", "type": "user"},
                    {"content": "Test response", "type": "assistant"},
                ],
                "started_at": "2024-01-01T00:01:00Z",
                "completed_at": "2024-01-01T00:01:05Z",
                "model_id": "test-model",
                "provider_id": "test-provider",
            }
        ]

        assert result == expected


class TestGetConversationEndpoint:
    """Test cases for the GET /conversations/{conversation_id} endpoint."""

    @pytest.mark.asyncio
    async def test_configuration_not_loaded(self, mocker):
        """Test the endpoint when configuration is not loaded."""
        mocker.patch("app.endpoints.conversations.configuration", None)

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Configuration is not loaded" in exc_info.value.detail["response"]

    @pytest.mark.asyncio
    async def test_invalid_conversation_id_format(self, mocker, setup_configuration):
        """Test the endpoint with an invalid conversation ID format."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_endpoint_handler(
                INVALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid conversation ID format" in exc_info.value.detail["response"]
        assert INVALID_CONVERSATION_ID in exc_info.value.detail["cause"]

    @pytest.mark.asyncio
    async def test_llama_stack_connection_error(self, mocker, setup_configuration):
        """Test the endpoint when LlamaStack connection fails."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise APIConnectionError
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.list.side_effect = APIConnectionError(request=None)
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        # simulate situation when it is not possible to connect to Llama Stack
        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Unable to connect to Llama Stack" in exc_info.value.detail["response"]

    @pytest.mark.asyncio
    async def test_llama_stack_not_found_error(self, mocker, setup_configuration):
        """Test the endpoint when LlamaStack returns NotFoundError."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise NotFoundError
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.list.side_effect = NotFoundError(
            message="Session not found", response=mocker.Mock(request=None), body=None
        )
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "Conversation not found" in exc_info.value.detail["response"]
        assert "could not be retrieved" in exc_info.value.detail["cause"]
        assert VALID_CONVERSATION_ID in exc_info.value.detail["cause"]

    @pytest.mark.asyncio
    async def test_session_retrieve_exception(self, mocker, setup_configuration):
        """Test the endpoint when session retrieval raises an exception."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise a general exception
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.list.side_effect = Exception("Failed to get session")
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Unknown error" in exc_info.value.detail["response"]
        assert (
            "Unknown error while getting conversation" in exc_info.value.detail["cause"]
        )

    @pytest.mark.asyncio
    async def test_successful_conversation_retrieval(
        self, mocker, setup_configuration, mock_session_data, expected_chat_history
    ):
        """Test successful conversation retrieval with simplified response structure."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.list.return_value = mocker.Mock(
            data=[mock_session_data]
        )

        # Mock session.retrieve to return an object with model_dump() method
        mock_session_retrieve_result = mocker.Mock()
        mock_session_retrieve_result.model_dump.return_value = mock_session_data
        mock_client.agents.session.retrieve.return_value = mock_session_retrieve_result

        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        response = await get_conversation_endpoint_handler(
            VALID_CONVERSATION_ID, auth=MOCK_AUTH
        )

        assert isinstance(response, ConversationResponse)
        assert response.conversation_id == VALID_CONVERSATION_ID
        assert response.chat_history == expected_chat_history
        mock_client.agents.session.list.assert_called_once_with(
            agent_id=VALID_CONVERSATION_ID
        )


class TestDeleteConversationEndpoint:
    """Test cases for the DELETE /conversations/{conversation_id} endpoint."""

    @pytest.mark.asyncio
    async def test_configuration_not_loaded(self, mocker):
        """Test the endpoint when configuration is not loaded."""
        mocker.patch("app.endpoints.conversations.configuration", None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Configuration is not loaded" in exc_info.value.detail["response"]

    @pytest.mark.asyncio
    async def test_invalid_conversation_id_format(self, mocker, setup_configuration):
        """Test the endpoint with an invalid conversation ID format."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint_handler(
                INVALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid conversation ID format" in exc_info.value.detail["response"]
        assert INVALID_CONVERSATION_ID in exc_info.value.detail["cause"]

    @pytest.mark.asyncio
    async def test_llama_stack_connection_error(self, mocker, setup_configuration):
        """Test the endpoint when LlamaStack connection fails."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise APIConnectionError
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.delete.side_effect = APIConnectionError(request=None)
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Unable to connect to Llama Stack" in exc_info.value.detail["response"]

    @pytest.mark.asyncio
    async def test_llama_stack_not_found_error(self, mocker, setup_configuration):
        """Test the endpoint when LlamaStack returns NotFoundError."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise NotFoundError
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.delete.side_effect = NotFoundError(
            message="Session not found", response=mocker.Mock(request=None), body=None
        )
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "Conversation not found" in exc_info.value.detail["response"]
        assert "could not be deleted" in exc_info.value.detail["cause"]
        assert VALID_CONVERSATION_ID in exc_info.value.detail["cause"]

    @pytest.mark.asyncio
    async def test_session_deletion_exception(self, mocker, setup_configuration):
        """Test the endpoint when session deletion raises an exception."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder to raise a general exception
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.delete.side_effect = Exception(
            "Session deletion failed"
        )
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation_endpoint_handler(
                VALID_CONVERSATION_ID, auth=MOCK_AUTH
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Unknown error" in exc_info.value.detail["response"]
        assert (
            "Unknown error while deleting conversation"
            in exc_info.value.detail["cause"]
        )

    @pytest.mark.asyncio
    async def test_successful_conversation_deletion(self, mocker, setup_configuration):
        """Test successful conversation deletion."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)
        mocker.patch("app.endpoints.conversations.check_suid", return_value=True)
        mocker.patch("app.endpoints.conversations.validate_conversation_ownership")

        # Mock AsyncLlamaStackClientHolder
        mock_client = mocker.AsyncMock()
        mock_client.agents.session.delete.return_value = None  # Successful deletion
        mock_client_holder = mocker.patch(
            "app.endpoints.conversations.AsyncLlamaStackClientHolder"
        )
        mock_client_holder.return_value.get_client.return_value = mock_client

        response = await delete_conversation_endpoint_handler(
            VALID_CONVERSATION_ID, auth=MOCK_AUTH
        )

        assert isinstance(response, ConversationDeleteResponse)
        assert response.conversation_id == VALID_CONVERSATION_ID
        assert response.success is True
        assert response.response == "Conversation deleted successfully"
        mock_client.agents.session.delete.assert_called_once_with(
            agent_id=VALID_CONVERSATION_ID, session_id=VALID_CONVERSATION_ID
        )


# Generated entirely by AI, no human review, so read with that in mind.
class TestGetConversationsListEndpoint:
    """Test cases for the GET /conversations endpoint."""

    def test_configuration_not_loaded(self, mocker):
        """Test the endpoint when configuration is not loaded."""
        mocker.patch("app.endpoints.conversations.configuration", None)

        with pytest.raises(HTTPException) as exc_info:
            get_conversations_list_endpoint_handler(auth=MOCK_AUTH)

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Configuration is not loaded" in exc_info.value.detail["response"]

    def test_successful_conversations_list_retrieval(self, mocker, setup_configuration):
        """Test successful retrieval of conversations list."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)

        # Mock database session and query results
        mock_conversations = [
            create_mock_conversation(
                mocker,
                "123e4567-e89b-12d3-a456-426614174000",
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:05:00Z",
                5,
                "gemini/gemini-2.0-flash",
                "gemini",
            ),
            create_mock_conversation(
                mocker,
                "456e7890-e12b-34d5-a678-901234567890",
                "2024-01-01T01:00:00Z",
                "2024-01-01T01:02:00Z",
                2,
                "gemini/gemini-2.5-flash",
                "gemini",
            ),
        ]
        mock_database_session(mocker, mock_conversations)

        response = get_conversations_list_endpoint_handler(auth=MOCK_AUTH)

        assert isinstance(response, ConversationsListResponse)
        assert len(response.conversations) == 2
        assert (
            response.conversations[0].conversation_id
            == "123e4567-e89b-12d3-a456-426614174000"
        )
        assert (
            response.conversations[1].conversation_id
            == "456e7890-e12b-34d5-a678-901234567890"
        )

    def test_empty_conversations_list(self, mocker, setup_configuration):
        """Test when user has no conversations."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)

        # Mock database session with no results
        mock_database_session(mocker, [])

        response = get_conversations_list_endpoint_handler(auth=MOCK_AUTH)

        assert isinstance(response, ConversationsListResponse)
        assert len(response.conversations) == 0
        assert response.conversations == []

    def test_database_exception(self, mocker, setup_configuration):
        """Test when database query raises an exception."""
        mocker.patch("app.endpoints.conversations.configuration", setup_configuration)

        # Mock database session to raise exception
        mock_session = mock_database_session(mocker)
        mock_session.query.side_effect = Exception("Database error")

        with pytest.raises(HTTPException) as exc_info:
            get_conversations_list_endpoint_handler(auth=MOCK_AUTH)

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Unknown error" in exc_info.value.detail["response"]
        assert (
            "Unknown error while getting conversations for user"
            in exc_info.value.detail["cause"]
        )
