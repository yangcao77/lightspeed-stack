"""Unit tests for agent utility functions."""

import pytest

from configuration import AppConfig

from utils.agent import get_agent, get_temp_agent


@pytest.fixture(name="setup_configuration")
def setup_configuration_fixture():
    """Set up configuration for tests."""
    test_config_dict = {
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
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config_dict)
    return cfg


@pytest.mark.asyncio
async def test_get_agent_with_conversation_id(prepare_agent_mocks, mocker):
    """Test get_agent function when agent exists in llama stack."""
    mock_client, mock_agent = prepare_agent_mocks
    conversation_id = "test_conversation_id"

    # Mock existing agent retrieval
    mock_agent_response = mocker.Mock()
    mock_agent_response.agent_id = conversation_id
    mock_client.agents.retrieve.return_value = mock_agent_response

    mock_client.agents.session.list.return_value = mocker.Mock(
        data=[{"session_id": "test_session_id"}]
    )

    # Mock Agent class
    mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=conversation_id,
    )

    # Assert the same agent is returned and conversation_id is preserved
    assert result_agent == mock_agent
    assert result_conversation_id == conversation_id
    assert result_session_id == "test_session_id"


@pytest.mark.asyncio
async def test_get_agent_with_conversation_id_and_no_agent_in_llama_stack(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function when conversation_id is provided."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_client.agents.retrieve.side_effect = ValueError(
        "fake not finding existing agent"
    )
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)
    conversation_id = "non_existent_conversation_id"
    # Call function with conversation_id
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=conversation_id,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert conversation_id != result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with correct parameters
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1"],
        output_shields=["output_shield2"],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_no_conversation_id(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function when conversation_id is None."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function with None conversation_id
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=None,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with correct parameters
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1"],
        output_shields=["output_shield2"],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_empty_shields(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function with empty shields list."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function with empty shields list
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=[],
        available_output_shields=[],
        conversation_id=None,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with empty shields
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=[],
        output_shields=[],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_multiple_mcp_servers(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function with multiple MCP servers."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration with multiple MCP servers
    mock_mcp_server1 = mocker.Mock()
    mock_mcp_server1.name = "mcp_server_1"
    mock_mcp_server2 = mocker.Mock()
    mock_mcp_server2.name = "mcp_server_2"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server1, mock_mcp_server2],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1", "shield2"],
        available_output_shields=["output_shield3", "output_shield4"],
        conversation_id=None,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with tools from both MCP servers
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1", "shield2"],
        output_shields=["output_shield3", "output_shield4"],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_session_persistence_enabled(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function ensures session persistence is enabled."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function
    await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=None,
    )

    # Verify Agent was created with session persistence enabled
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1"],
        output_shields=["output_shield2"],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_no_tools_no_parser(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function sets tool_parser=None when no_tools=True."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function with no_tools=True
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=None,
        no_tools=True,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with tool_parser=None
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1"],
        output_shields=["output_shield2"],
        tool_parser=None,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_agent_no_tools_false_preserves_parser(
    setup_configuration, prepare_agent_mocks, mocker
):
    """Test get_agent function preserves tool_parser when no_tools=False."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "new_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="new_session_id")

    # Mock GraniteToolParser
    mock_parser = mocker.Mock()
    mock_granite_parser = mocker.patch("utils.agent.GraniteToolParser")
    mock_granite_parser.get_parser.return_value = mock_parser

    # Mock configuration
    mock_mcp_server = mocker.Mock()
    mock_mcp_server.name = "mcp_server_1"
    mocker.patch.object(
        type(setup_configuration),
        "mcp_servers",
        new_callable=mocker.PropertyMock,
        return_value=[mock_mcp_server],
    )
    mocker.patch("configuration.configuration", setup_configuration)

    # Call function with no_tools=False
    result_agent, result_conversation_id, result_session_id = await get_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
        available_input_shields=["shield1"],
        available_output_shields=["output_shield2"],
        conversation_id=None,
        no_tools=False,
    )

    # Assert new agent is created
    assert result_agent == mock_agent
    assert result_conversation_id == result_agent.agent_id
    assert result_session_id == "new_session_id"

    # Verify Agent was created with the proper tool_parser
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        input_shields=["shield1"],
        output_shields=["output_shield2"],
        tool_parser=mock_parser,
        enable_session_persistence=True,
    )


@pytest.mark.asyncio
async def test_get_temp_agent_basic_functionality(prepare_agent_mocks, mocker):
    """Test get_temp_agent function creates agent with correct parameters."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "temp_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="temp_session_id")

    # Call function
    result_agent, result_session_id, result_conversation_id = await get_temp_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
    )

    # Assert agent, session_id, and conversation_id are created and returned
    assert result_agent == mock_agent
    assert result_session_id == "temp_session_id"
    assert result_conversation_id == mock_agent.agent_id

    # Verify Agent was created with correct parameters for temporary agent
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        enable_session_persistence=False,  # Key difference: no persistence
    )

    # Verify agent was initialized and session was created
    mock_agent.initialize.assert_called_once()
    mock_agent.create_session.assert_called_once_with("temp_session_id")


@pytest.mark.asyncio
async def test_get_temp_agent_returns_valid_ids(prepare_agent_mocks, mocker):
    """Test get_temp_agent function returns valid agent_id and session_id."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.agent_id = "generated_agent_id"
    mock_agent.create_session.return_value = "generated_session_id"

    # Mock Agent class
    mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="generated_session_id")

    # Call function
    result_agent, result_session_id, result_conversation_id = await get_temp_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
    )

    # Assert all three values are returned and are not None/empty
    assert result_agent is not None
    assert result_session_id is not None
    assert result_conversation_id is not None

    # Assert they are strings
    assert isinstance(result_session_id, str)
    assert isinstance(result_conversation_id, str)

    # Assert conversation_id matches agent_id
    assert result_conversation_id == result_agent.agent_id


@pytest.mark.asyncio
async def test_get_temp_agent_no_persistence(prepare_agent_mocks, mocker):
    """Test get_temp_agent function creates agent without session persistence."""
    mock_client, mock_agent = prepare_agent_mocks
    mock_agent.create_session.return_value = "temp_session_id"

    # Mock Agent class
    mock_agent_class = mocker.patch("utils.agent.AsyncAgent", return_value=mock_agent)

    # Mock get_suid
    mocker.patch("utils.agent.get_suid", return_value="temp_session_id")

    # Call function
    await get_temp_agent(
        client=mock_client,
        model_id="test_model",
        system_prompt="test_prompt",
    )

    # Verify Agent was created with session persistence disabled
    mock_agent_class.assert_called_once_with(
        mock_client,
        model="test_model",
        instructions="test_prompt",
        enable_session_persistence=False,
    )
