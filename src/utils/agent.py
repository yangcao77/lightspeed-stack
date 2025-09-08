"""Utility functions for agent management."""

from contextlib import suppress
import logging

from fastapi import HTTPException, status
from llama_stack_client._client import AsyncLlamaStackClient
from llama_stack_client.lib.agents.agent import AsyncAgent

from utils.suid import get_suid
from utils.types import GraniteToolParser


logger = logging.getLogger("utils.agent")


# pylint: disable=R0913,R0917
async def get_agent(
    client: AsyncLlamaStackClient,
    model_id: str,
    system_prompt: str,
    available_input_shields: list[str],
    available_output_shields: list[str],
    conversation_id: str | None,
    no_tools: bool = False,
) -> tuple[AsyncAgent, str, str]:
    """Get existing agent or create a new one with session persistence."""
    existing_agent_id = None
    if conversation_id:
        with suppress(ValueError):
            agent_response = await client.agents.retrieve(agent_id=conversation_id)
            existing_agent_id = agent_response.agent_id

    logger.debug("Creating new agent")
    agent = AsyncAgent(
        client,  # type: ignore[arg-type]
        model=model_id,
        instructions=system_prompt,
        input_shields=available_input_shields if available_input_shields else [],
        output_shields=available_output_shields if available_output_shields else [],
        tool_parser=None if no_tools else GraniteToolParser.get_parser(model_id),
        enable_session_persistence=True,
    )
    await agent.initialize()

    if existing_agent_id and conversation_id:
        orphan_agent_id = agent.agent_id
        agent._agent_id = conversation_id  # type: ignore[assignment]  # pylint: disable=protected-access
        await client.agents.delete(agent_id=orphan_agent_id)
        sessions_response = await client.agents.session.list(agent_id=conversation_id)
        logger.info("session response: %s", sessions_response)
        try:
            session_id = str(sessions_response.data[0]["session_id"])
        except IndexError as e:
            logger.error("No sessions found for conversation %s", conversation_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "response": "Conversation not found",
                    "cause": f"Conversation {conversation_id} could not be retrieved.",
                },
            ) from e
    else:
        conversation_id = agent.agent_id
        session_id = await agent.create_session(get_suid())

    return agent, conversation_id, session_id


async def get_temp_agent(
    client: AsyncLlamaStackClient,
    model_id: str,
    system_prompt: str,
) -> tuple[AsyncAgent, str]:
    """Create a temporary agent with new agent_id and session_id.
    
    This function creates a new agent without persistence, shields, or tools.
    Useful for temporary operations or one-off queries, such as validating a question or generating a summary.
    
    Args:
        client: The AsyncLlamaStackClient to use for the request.
        model_id: The ID of the model to use.
        system_prompt: The system prompt/instructions for the agent.
        
    Returns:
        tuple[AsyncAgent, str]: A tuple containing the agent and session_id.
    """
    logger.debug("Creating temporary agent")
    agent = AsyncAgent(
        client,  # type: ignore[arg-type]
        model=model_id,
        instructions=system_prompt,
        enable_session_persistence=False,  # Temporary agent doesn't need persistence
    )
    await agent.initialize()
    
    # Generate new IDs for the temporary agent
    session_id = await agent.create_session(get_suid())
    
    return agent, session_id
