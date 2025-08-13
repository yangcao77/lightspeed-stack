"""Handler for REST API calls to manage conversation history."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from llama_stack_client import APIConnectionError, NotFoundError

from fastapi import APIRouter, HTTPException, status, Depends

from client import AsyncLlamaStackClientHolder
from configuration import configuration
from models.responses import (
    ConversationResponse,
    ConversationDeleteResponse,
    ConversationsListResponse,
    ConversationDetails,
)
from models.database.conversations import UserConversation
from auth import get_auth_dependency
from app.database import get_session
from utils.endpoints import check_configuration_loaded, validate_conversation_ownership
from utils.suid import check_suid

logger = logging.getLogger("app.endpoints.handlers")
router = APIRouter(tags=["conversations"])
auth_dependency = get_auth_dependency()

conversation_responses: dict[int | str, dict[str, Any]] = {
    200: {
        "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
        "chat_history": [
            {
                "messages": [
                    {"content": "Hi", "type": "user"},
                    {"content": "Hello!", "type": "assistant"},
                ],
                "started_at": "2024-01-01T00:00:00Z",
                "completed_at": "2024-01-01T00:00:05Z",
                "model_id": "gemini-1.5-flash",
                "provider_id": "gemini",
            }
        ],
    },
    404: {
        "detail": {
            "response": "Conversation not found",
            "cause": "The specified conversation ID does not exist.",
        }
    },
    503: {
        "detail": {
            "response": "Unable to connect to Llama Stack",
            "cause": "Connection error.",
        }
    },
}

conversation_delete_responses: dict[int | str, dict[str, Any]] = {
    200: {
        "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
        "success": True,
        "message": "Conversation deleted successfully",
    },
    404: {
        "detail": {
            "response": "Conversation not found",
            "cause": "The specified conversation ID does not exist.",
        }
    },
    503: {
        "detail": {
            "response": "Unable to connect to Llama Stack",
            "cause": "Connection error.",
        }
    },
}

conversations_list_responses: dict[int | str, dict[str, Any]] = {
    200: {
        "conversations": [
            {
                "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
                "created_at": "2024-01-01T00:00:00Z",
                "last_message_at": "2024-01-01T00:05:00Z",
                "last_used_model": "gemini/gemini-1.5-flash",
                "last_used_provider": "gemini",
                "message_count": 5,
            },
            {
                "conversation_id": "456e7890-e12b-34d5-a678-901234567890",
                "created_at": "2024-01-01T01:00:00Z",
                "last_message_at": "2024-01-01T01:02:00Z",
                "last_used_model": "gemini/gemini-2.0-flash",
                "last_used_provider": "gemini",
                "message_count": 2,
            },
        ]
    },
    503: {
        "detail": {
            "response": "Unable to connect to Llama Stack",
            "cause": "Connection error.",
        }
    },
}


def simplify_session_data(session_data: dict, model_id: str, provider_id: str) -> list[dict[str, Any]]:
    """Simplify session data to include only essential conversation information.

    Args:
        session_data: The full session data dict from llama-stack

    Returns:
        Simplified session data with only input_messages and output_message per turn
    """
    # Create simplified structure
    chat_history = []

    # Extract only essential data from each turn
    for turn in session_data.get("turns", []):
        # Clean up input messages
        cleaned_messages = []
        for msg in turn.get("input_messages", []):
            cleaned_msg = {
                "content": msg.get("content"),
                "type": msg.get("role"),  # Rename role to type
            }
            cleaned_messages.append(cleaned_msg)

        # Clean up output message
        output_msg = turn.get("output_message", {})
        cleaned_messages.append(
            {
                "content": output_msg.get("content"),
                "type": output_msg.get("role"),  # Rename role to type
            }
        )

        simplified_turn = {
            "messages": cleaned_messages,
            "started_at": turn.get("started_at"),
            "completed_at": turn.get("completed_at"),
            "model_id": model_id,
            "provider_id": provider_id,
        }
        chat_history.append(simplified_turn)

    return chat_history


@router.get("/conversations", responses=conversations_list_responses)
def get_conversations_list_endpoint_handler(
    auth: Any = Depends(auth_dependency),
) -> ConversationsListResponse:
    """Handle request to retrieve all conversations for the authenticated user."""
    check_configuration_loaded(configuration)

    user_id, _, _ = auth

    logger.info("Retrieving conversations for user %s", user_id)

    with get_session() as session:
        try:
            # Get all conversations for this user
            user_conversations = (
                session.query(UserConversation).filter_by(user_id=user_id).all()
            )

            # Return conversation summaries with metadata
            conversations = [
                ConversationDetails(
                    conversation_id=conv.id,
                    created_at=conv.created_at.isoformat() if conv.created_at else None,
                    last_message_at=(
                        conv.last_message_at.isoformat()
                        if conv.last_message_at
                        else None
                    ),
                    message_count=conv.message_count,
                    last_used_model=conv.last_used_model,
                    last_used_provider=conv.last_used_provider,
                )
                for conv in user_conversations
            ]

            logger.info(
                "Found %d conversations for user %s", len(conversations), user_id
            )

            return ConversationsListResponse(conversations=conversations)

        except Exception as e:
            logger.exception(
                "Error retrieving conversations for user %s: %s", user_id, e
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "response": "Unknown error",
                    "cause": f"Unknown error while getting conversations for user {user_id}",
                },
            ) from e


@router.get("/conversations/{conversation_id}", responses=conversation_responses)
async def get_conversation_endpoint_handler(
    conversation_id: str,
    auth: Any = Depends(auth_dependency),
) -> ConversationResponse:
    """Handle request to retrieve a conversation by ID."""
    check_configuration_loaded(configuration)

    # Validate conversation ID format
    if not check_suid(conversation_id):
        logger.error("Invalid conversation ID format: %s", conversation_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "response": "Invalid conversation ID format",
                "cause": f"Conversation ID {conversation_id} is not a valid UUID",
            },
        )

    user_id, _, _ = auth

    validate_conversation_ownership(
        user_id=user_id,
        conversation_id=conversation_id,
    )

    agent_id = conversation_id
    logger.info("Retrieving conversation %s", conversation_id)

    try:
        client = AsyncLlamaStackClientHolder().get_client()

        # Get agent information to extract model and provider details
        agent_response = await client.agents.retrieve(agent_id=agent_id)
        agent_data = agent_response.model_dump()
        
        # Extract model_id and provider_id from agent_config.model
        agent_model = (
            agent_data.get("agent_config", {}).get("model")
            if isinstance(agent_data, dict)
            else None
        ) or ""
        if "/" in agent_model:
            provider_id, model_id = agent_model.split("/", 1)
        else:
            # Fallback if format is unexpected
            model_id = agent_model
            provider_id = "unknown"

        agent_sessions = (await client.agents.session.list(agent_id=agent_id)).data
        session_id = str(agent_sessions[0].get("session_id"))

        session_response = await client.agents.session.retrieve(
            agent_id=agent_id, session_id=session_id
        )
        session_data = session_response.model_dump()

        logger.info("Successfully retrieved conversation %s", conversation_id)

        # Simplify the session data to include only essential conversation information
        chat_history = simplify_session_data(session_data, model_id, provider_id)

        return ConversationResponse(
            conversation_id=conversation_id,
            chat_history=chat_history,
        )

    except APIConnectionError as e:
        logger.error("Unable to connect to Llama Stack: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "response": "Unable to connect to Llama Stack",
                "cause": str(e),
            },
        ) from e
    except NotFoundError as e:
        logger.error("Conversation not found: %s", e)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "response": "Conversation not found",
                "cause": f"Conversation {conversation_id} could not be retrieved: {str(e)}",
            },
        ) from e
    except Exception as e:
        # Handle case where session doesn't exist or other errors
        logger.exception("Error retrieving conversation %s: %s", conversation_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unknown error",
                "cause": f"Unknown error while getting conversation {conversation_id} : {str(e)}",
            },
        ) from e


@router.delete(
    "/conversations/{conversation_id}", responses=conversation_delete_responses
)
async def delete_conversation_endpoint_handler(
    conversation_id: str,
    auth: Any = Depends(auth_dependency),
) -> ConversationDeleteResponse:
    """Handle request to delete a conversation by ID."""
    check_configuration_loaded(configuration)

    # Validate conversation ID format
    if not check_suid(conversation_id):
        logger.error("Invalid conversation ID format: %s", conversation_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "response": "Invalid conversation ID format",
                "cause": f"Conversation ID {conversation_id} is not a valid UUID",
            },
        )

    user_id, _, _ = auth

    validate_conversation_ownership(
        user_id=user_id,
        conversation_id=conversation_id,
    )

    agent_id = conversation_id
    logger.info("Deleting conversation %s", conversation_id)

    try:
        # Get Llama Stack client
        client = AsyncLlamaStackClientHolder().get_client()
        # Delete session using the conversation_id as session_id
        # In this implementation, conversation_id and session_id are the same
        await client.agents.session.delete(
            agent_id=agent_id, session_id=conversation_id
        )

        logger.info("Successfully deleted conversation %s", conversation_id)

        return ConversationDeleteResponse(
            conversation_id=conversation_id,
            success=True,
            response="Conversation deleted successfully",
        )

    except APIConnectionError as e:
        logger.error("Unable to connect to Llama Stack: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "response": "Unable to connect to Llama Stack",
                "cause": str(e),
            },
        ) from e
    except NotFoundError as e:
        logger.error("Conversation not found: %s", e)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "response": "Conversation not found",
                "cause": f"Conversation {conversation_id} could not be deleted: {str(e)}",
            },
        ) from e
    except Exception as e:
        # Handle case where session doesn't exist or other errors
        logger.exception("Error deleting conversation %s: %s", conversation_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unknown error",
                "cause": f"Unknown error while deleting conversation {conversation_id} : {str(e)}",
            },
        ) from e
