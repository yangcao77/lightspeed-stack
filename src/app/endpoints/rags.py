"""Handler for REST API calls to list and retrieve available RAGs."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.params import Depends
from llama_stack_client import APIConnectionError

from authentication import get_auth_dependency
from authentication.interface import AuthTuple
from authorization.middleware import authorize
from client import AsyncLlamaStackClientHolder
from configuration import configuration
from models.config import Action
from models.responses import RAGListResponse, RAGInfoResponse
from utils.endpoints import check_configuration_loaded

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rags"])


rags_responses: dict[int | str, dict[str, Any]] = {
    200: {
        "rags": [
            "vs_00000000-cafe-babe-0000-000000000000",
            "vs_7b52a8cf-0fa3-489c-beab-27e061d102f3",
            "vs_7b52a8cf-0fa3-489c-cafe-27e061d102f3",
        ]
    },
    500: {"description": "Connection to Llama Stack is broken"},
}

rag_responses: dict[int | str, dict[str, Any]] = {
    200: {},
    404: {"response": "RAG with given id not found"},
    500: {
        "response": "Unable to retrieve list of RAGs",
        "cause": "Connection to Llama Stack is broken",
    },
}


@router.get("/rags", responses=rags_responses)
@authorize(Action.LIST_RAGS)
async def rags_endpoint_handler(
    request: Request,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> RAGListResponse:
    """
    Handle GET requests to list all available RAGs.

    Retrieves RAGs from the Llama Stack service.

    Raises:
        HTTPException:
            - 500 if configuration is not loaded,
            - 500 if unable to connect to Llama Stack,
            - 500 for any unexpected retrieval errors.

    Returns:
        RAGListResponse: List of RAGs.
    """
    # Used only by the middleware
    _ = auth

    # Nothing interesting in the request
    _ = request

    # make sure that the configuration is loaded
    check_configuration_loaded(configuration)

    llama_stack_configuration = configuration.llama_stack_configuration
    logger.info("Llama stack config: %s", llama_stack_configuration)

    try:
        # try to get Llama Stack client
        client = AsyncLlamaStackClientHolder().get_client()
        # retrieve list of RAGs
        rags = await client.vector_stores.list()
        logger.info("List of rags: %d", len(rags.data))

        # convert into the proper response object
        return RAGListResponse(rags=[rag.id for rag in rags.data])

    # connection to Llama Stack server
    except APIConnectionError as e:
        logger.error("Unable to connect to Llama Stack: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unable to connect to Llama Stack",
                "cause": str(e),
            },
        ) from e
    # any other exception that can occur during model listing
    except Exception as e:
        logger.error("Unable to retrieve list of RAGs: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unable to retrieve list of RAGs",
                "cause": str(e),
            },
        ) from e


@router.get("/rags/{rag_id}", responses=rag_responses)
@authorize(Action.GET_RAG)
async def get_rag_endpoint_handler(
    request: Request,
    rag_id: str,
    auth: Annotated[AuthTuple, Depends(get_auth_dependency())],
) -> RAGInfoResponse:
    """Retrieve a single RAG by its unique ID.

    Raises:
        HTTPException:
            - 404 if RAG with the given ID is not found,
            - 500 if unable to connect to Llama Stack,
            - 500 for any unexpected retrieval errors.

    Returns:
        RAGInfoResponse: A single RAG's details
    """
    # Used only by the middleware
    _ = auth

    # Nothing interesting in the request
    _ = request

    check_configuration_loaded(configuration)

    llama_stack_configuration = configuration.llama_stack_configuration
    logger.info("Llama stack config: %s", llama_stack_configuration)

    try:
        # try to get Llama Stack client
        client = AsyncLlamaStackClientHolder().get_client()
        # retrieve info about RAG
        rag_info = await client.vector_stores.retrieve(rag_id)
        return RAGInfoResponse(
            id=rag_info.id,
            name=rag_info.name,
            created_at=rag_info.created_at,
            last_active_at=rag_info.last_active_at,
            expires_at=rag_info.expires_at,
            object=rag_info.object,
            status=rag_info.status,
            usage_bytes=rag_info.usage_bytes,
        )

    # connection to Llama Stack server
    except HTTPException:
        raise
    except APIConnectionError as e:
        logger.error("Unable to connect to Llama Stack: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unable to connect to Llama Stack",
                "cause": str(e),
            },
        ) from e
    # any other exception that can occur during model listing
    except Exception as e:
        logger.error("Unable to retrieve info about RAG: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "response": "Unable to retrieve info about RAG",
                "cause": str(e),
            },
        ) from e
