"""Unit tests for ModelContextProtocolServer model."""

import pytest

from pydantic import ValidationError

from models.config import (
    ModelContextProtocolServer,
    LlamaStackConfiguration,
    UserDataCollection,
    Configuration,
    ServiceConfiguration,
)


def test_model_context_protocol_server_constructor() -> None:
    """Test the ModelContextProtocolServer constructor."""
    mcp = ModelContextProtocolServer(name="test-server", url="http://localhost:8080")
    assert mcp is not None
    assert mcp.name == "test-server"
    assert mcp.provider_id == "model-context-protocol"
    assert mcp.url == "http://localhost:8080"


def test_model_context_protocol_server_custom_provider() -> None:
    """Test the ModelContextProtocolServer constructor with custom provider."""
    mcp = ModelContextProtocolServer(
        name="custom-server",
        provider_id="custom-provider",
        url="https://api.example.com",
    )
    assert mcp is not None
    assert mcp.name == "custom-server"
    assert mcp.provider_id == "custom-provider"
    assert mcp.url == "https://api.example.com"


def test_model_context_protocol_server_required_fields() -> None:
    """Test that ModelContextProtocolServer requires name and url."""

    with pytest.raises(ValidationError):
        ModelContextProtocolServer()  # pyright: ignore

    with pytest.raises(ValidationError):
        ModelContextProtocolServer(name="test-server")  # pyright: ignore

    with pytest.raises(ValidationError):
        ModelContextProtocolServer(url="http://localhost:8080")  # pyright: ignore


def test_configuration_empty_mcp_servers() -> None:
    """
    Test that a Configuration object can be created with an empty
    list of MCP servers.

    Verifies that the Configuration instance is constructed
    successfully and that the mcp_servers attribute is empty.
    """
    cfg = Configuration(
        name="test_name",
        service=ServiceConfiguration(),
        llama_stack=LlamaStackConfiguration(
            use_as_library_client=True,
            library_client_config_path="tests/configuration/run.yaml",
        ),
        user_data_collection=UserDataCollection(
            feedback_enabled=False, feedback_storage=None
        ),
        mcp_servers=[],
        customization=None,
    )
    assert cfg is not None
    assert not cfg.mcp_servers


def test_configuration_single_mcp_server() -> None:
    """
    Test that a Configuration object can be created with a single
    MCP server and verifies its properties.
    """
    mcp_server = ModelContextProtocolServer(
        name="test-server", url="http://localhost:8080"
    )
    cfg = Configuration(
        name="test_name",
        service=ServiceConfiguration(),
        llama_stack=LlamaStackConfiguration(
            use_as_library_client=True,
            library_client_config_path="tests/configuration/run.yaml",
        ),
        user_data_collection=UserDataCollection(
            feedback_enabled=False, feedback_storage=None
        ),
        mcp_servers=[mcp_server],
        customization=None,
    )
    assert cfg is not None
    assert len(cfg.mcp_servers) == 1
    assert cfg.mcp_servers[0].name == "test-server"
    assert cfg.mcp_servers[0].url == "http://localhost:8080"


def test_configuration_multiple_mcp_servers() -> None:
    """
    Verify that the Configuration object correctly handles multiple
    ModelContextProtocolServer instances in its mcp_servers list,
    including custom provider IDs.
    """
    mcp_servers = [
        ModelContextProtocolServer(name="server1", url="http://localhost:8080"),
        ModelContextProtocolServer(
            name="server2", url="http://localhost:8081", provider_id="custom-provider"
        ),
        ModelContextProtocolServer(name="server3", url="https://api.example.com"),
    ]
    cfg = Configuration(
        name="test_name",
        service=ServiceConfiguration(),
        llama_stack=LlamaStackConfiguration(
            use_as_library_client=True,
            library_client_config_path="tests/configuration/run.yaml",
        ),
        user_data_collection=UserDataCollection(
            feedback_enabled=False, feedback_storage=None
        ),
        mcp_servers=mcp_servers,
        customization=None,
    )
    assert cfg is not None
    assert len(cfg.mcp_servers) == 3
    assert cfg.mcp_servers[0].name == "server1"
    assert cfg.mcp_servers[1].name == "server2"
    assert cfg.mcp_servers[1].provider_id == "custom-provider"
    assert cfg.mcp_servers[2].name == "server3"
