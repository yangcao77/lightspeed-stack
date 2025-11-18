"""Unit tests for the /rags REST API endpoints."""

import pytest
from pytest_mock import MockerFixture
from fastapi import HTTPException, Request, status
from llama_stack_client import APIConnectionError

from authentication.interface import AuthTuple

from app.endpoints.rags import (
    rags_endpoint_handler,
)


@pytest.mark.asyncio
async def test_rags_endpoint_configuration_not_loaded(
    mocker: MockerFixture,
) -> None:
    """Test that /rags endpoint raises HTTP 500 if configuration is not loaded."""
    mocker.patch("app.endpoints.rags.configuration", None)
    request = Request(scope={"type": "http"})

    # Authorization tuple required by URL endpoint handler
    auth: AuthTuple = ("test_user_id", "test_user", True, "test_token")

    with pytest.raises(HTTPException) as e:
        await rags_endpoint_handler(request=request, auth=auth)
    assert e.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_rags_endpoint_connection_error(mocker: MockerFixture) -> None:
    """Test that /rags endpoint raises HTTP 500 if Llama Stack connection fails."""
    mock_client = mocker.AsyncMock()
    mock_client.vector_stores.list.side_effect = APIConnectionError(request=None)  # type: ignore
    mocker.patch(
        "app.endpoints.rags.AsyncLlamaStackClientHolder"
    ).return_value.get_client.return_value = mock_client

    request = Request(scope={"type": "http"})

    # Authorization tuple required by URL endpoint handler
    auth: AuthTuple = ("test_user_id", "test_user", True, "test_token")

    with pytest.raises(HTTPException) as e:
        await rags_endpoint_handler(request=request, auth=auth)
    assert e.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = e.value.detail
    assert isinstance(detail, dict)
    assert "response" in detail
    assert "Unable to connect to Llama Stack" in detail["response"]


@pytest.mark.asyncio
async def test_rags_endpoint_unable_to_retrieve_list(mocker: MockerFixture) -> None:
    """Test that /rags endpoint raises HTTP 500 if Llama Stack connection fails."""
    mock_client = mocker.AsyncMock()
    mock_client.vector_stores.list.side_effect = []  # type: ignore
    mocker.patch(
        "app.endpoints.rags.AsyncLlamaStackClientHolder"
    ).return_value.get_client.return_value = mock_client

    request = Request(scope={"type": "http"})

    # Authorization tuple required by URL endpoint handler
    auth: AuthTuple = ("test_user_id", "test_user", True, "test_token")

    with pytest.raises(HTTPException) as e:
        await rags_endpoint_handler(request=request, auth=auth)
    assert e.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = e.value.detail
    assert isinstance(detail, dict)
    assert "response" in detail
    assert "Unable to retrieve list of RAGs" in detail["response"]


@pytest.mark.asyncio
async def test_rags_endpoint_success(mocker: MockerFixture) -> None:
    """Test that /rags endpoint returns list of RAG IDs."""

    # pylint: disable=R0903
    class RagInfo:
        """RagInfo mock."""

        def __init__(self, rag_id: str) -> None:
            self.id = rag_id

    class RagList:
        """List of RAGs mock."""

        def __init__(self) -> None:
            self.data = [
                RagInfo("vs_00000000-cafe-babe-0000-000000000000"),
                RagInfo("vs_7b52a8cf-0fa3-489c-beab-27e061d102f3"),
                RagInfo("vs_7b52a8cf-0fa3-489c-cafe-27e061d102f3"),
            ]

    mock_client = mocker.AsyncMock()
    mock_client.vector_stores.list.return_value = RagList()
    mocker.patch(
        "app.endpoints.rags.AsyncLlamaStackClientHolder"
    ).return_value.get_client.return_value = mock_client

    request = Request(scope={"type": "http"})

    # Authorization tuple required by URL endpoint handler
    auth: AuthTuple = ("test_user_id", "test_user", True, "test_token")

    response = await rags_endpoint_handler(request=request, auth=auth)
    assert len(response.rags) == 3
