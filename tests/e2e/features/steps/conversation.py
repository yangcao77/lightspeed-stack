"""Implementation of common test steps."""

import json
from behave import step, when, then  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context
import requests
from tests.e2e.utils.utils import replace_placeholders

# default timeout for HTTP operations
DEFAULT_TIMEOUT = 10


@step(
    "I use REST API conversation endpoint with conversation_id from above using HTTP GET method"
)
def access_conversation_endpoint_get(context: Context) -> None:
    """Send GET HTTP request to tested service for conversation/{conversation_id}."""
    assert (
        context.response_data["conversation_id"] is not None
    ), "conversation id not stored"
    endpoint = "conversations"
    base = f"http://{context.hostname}:{context.port}"
    path = f"{context.api_prefix}/{endpoint}/{context.response_data['conversation_id']}".replace(
        "//", "/"
    )
    url = base + path
    headers = context.auth_headers if hasattr(context, "auth_headers") else {}
    # initial value
    context.response = None

    # perform REST API call
    context.response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)


@step(
    'I use REST API conversation endpoint with conversation_id "{conversation_id}" using HTTP GET method'
)
def access_conversation_endpoint_get_specific(
    context: Context, conversation_id: str
) -> None:
    """Send GET HTTP request to tested service for conversation/{conversation_id}."""
    endpoint = "conversations"
    base = f"http://{context.hostname}:{context.port}"
    path = f"{context.api_prefix}/{endpoint}/{conversation_id}".replace("//", "/")
    url = base + path
    headers = context.auth_headers if hasattr(context, "auth_headers") else {}
    # initial value
    context.response = None

    # perform REST API call
    context.response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)


@when(
    "I use REST API conversation endpoint with conversation_id from above using HTTP DELETE method"
)
def access_conversation_endpoint_delete(context: Context) -> None:
    """Send DELETE HTTP request to tested service for conversation/{conversation_id}."""
    assert (
        context.response_data["conversation_id"] is not None
    ), "conversation id not stored"
    endpoint = "conversations"
    base = f"http://{context.hostname}:{context.port}"
    path = f"{context.api_prefix}/{endpoint}/{context.response_data['conversation_id']}".replace(
        "//", "/"
    )
    url = base + path
    headers = context.auth_headers if hasattr(context, "auth_headers") else {}
    # initial value
    context.response = None

    # perform REST API call
    context.response = requests.delete(url, headers=headers, timeout=DEFAULT_TIMEOUT)


@step(
    'I use REST API conversation endpoint with conversation_id "{conversation_id}" using HTTP DELETE method'
)
def access_conversation_endpoint_delete_specific(
    context: Context, conversation_id: str
) -> None:
    """Send DELETE HTTP request to tested service for conversation/{conversation_id}."""
    endpoint = "conversations"
    base = f"http://{context.hostname}:{context.port}"
    path = f"{context.api_prefix}/{endpoint}/{conversation_id}".replace("//", "/")
    url = base + path
    headers = context.auth_headers if hasattr(context, "auth_headers") else {}
    # initial value
    context.response = None

    # perform REST API call
    context.response = requests.delete(url, headers=headers, timeout=DEFAULT_TIMEOUT)


@then("The conversation with conversation_id from above is returned")
def check_returned_conversation_id(context: Context) -> None:
    """Check the conversation id in response."""
    response_json = context.response.json()
    found_conversation = None
    for conversation in response_json["conversations"]:
        if conversation["conversation_id"] == context.response_data["conversation_id"]:
            found_conversation = conversation
            break

    context.found_conversation = found_conversation

    assert found_conversation is not None, "conversation not found"


@then("The conversation details are following")
def check_returned_conversation_content(context: Context) -> None:
    """Check the conversation content in response."""
    # Replace {MODEL} and {PROVIDER} placeholders with actual values
    json_str = replace_placeholders(context, context.text or "{}")

    expected_data = json.loads(json_str)
    found_conversation = context.found_conversation

    assert (
        found_conversation["last_used_model"] == expected_data["last_used_model"]
    ), f"last_used_model mismatch, was {found_conversation["last_used_model"]}"
    assert (
        found_conversation["last_used_provider"] == expected_data["last_used_provider"]
    ), f"last_used_provider mismatch, was {found_conversation["last_used_provider"]}"
    assert (
        found_conversation["message_count"] == expected_data["message_count"]
    ), f"message count mismatch, was {found_conversation["message_count"]}"


@then("The returned conversation details have expected conversation_id")
def check_found_conversation_id(context: Context) -> None:
    """Check whether the conversation details have expected conversation_id."""
    response_json = context.response.json()

    assert (
        response_json["conversation_id"] == context.response_data["conversation_id"]
    ), "found wrong conversation"


@then("The body of the response has following messages")
def check_found_conversation_content(context: Context) -> None:
    """Check whether the conversation details have expected data."""
    expected_data = json.loads(context.text)
    response_json = context.response.json()
    chat_messages = response_json["chat_history"][0]["messages"]

    assert chat_messages[0]["content"] == expected_data["content"]
    assert chat_messages[0]["type"] == expected_data["type"]
    assert (
        expected_data["content_response"] in chat_messages[1]["content"]
    ), f"expected substring not in response, has {chat_messages[1]["content"]}"
    assert chat_messages[1]["type"] == expected_data["type_response"]


@then("The conversation with details and conversation_id from above is not found")
def check_deleted_conversation(context: Context) -> None:
    """Check whether the deleted conversation is gone."""
    assert context.response is not None
