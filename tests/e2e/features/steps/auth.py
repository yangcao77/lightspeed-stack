"""Implementation of common test steps."""

import requests
from behave import given, when  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context
from tests.e2e.utils.utils import normalize_endpoint


@given("I set the Authorization header to {header_value}")
def set_authorization_header_custom(context: Context, header_value: str) -> None:
    """Set a custom Authorization header value.

    Parameters:
        header_value (str): The value to set for the `Authorization` header.
    """
    if not hasattr(context, "auth_headers"):
        context.auth_headers = {}
    context.auth_headers["Authorization"] = header_value
    print(f"🔑 Set Authorization header to: {header_value}")


@given("I remove the auth header")  # type: ignore
def remove_authorization_header(context: Context) -> None:
    """Remove Authorization header."""
    if hasattr(context, "auth_headers") and "Authorization" in context.auth_headers:
        del context.auth_headers["Authorization"]


@when("I access endpoint {endpoint} using HTTP POST method with user_id {user_id}")
def access_rest_api_endpoint_post(
    context: Context, endpoint: str, user_id: str
) -> None:
    """Send POST HTTP request with payload in the endpoint as parameter to tested service.

    The response is stored in `context.response` attribute.

    Parameters:
        endpoint (str): Endpoint path to call; will be normalized.
        user_id (str): Value used for the `user_id` query parameter (surrounding quotes are removed).
    """
    endpoint = normalize_endpoint(endpoint)
    user_id = user_id.replace('"', "")
    base = f"http://{context.hostname}:{context.port}"
    path = f"{endpoint}?user_id={user_id}".replace("//", "/")
    url = base + path

    if not hasattr(context, "auth_headers"):
        context.auth_headers = {}

    # perform REST API call
    context.response = requests.post(
        url, json="", headers=context.auth_headers, timeout=10
    )


@when("I access endpoint {endpoint} using HTTP POST method without user_id")
def access_rest_api_endpoint_post_without_param(
    context: Context, endpoint: str
) -> None:
    """Send POST HTTP request without user_id payload.

    The response is stored in `context.response` attribute.
    """
    endpoint = normalize_endpoint(endpoint)
    base = f"http://{context.hostname}:{context.port}"
    path = f"{endpoint}".replace("//", "/")
    url = base + path

    if not hasattr(context, "auth_headers"):
        context.auth_headers = {}

    # perform REST API call
    context.response = requests.post(
        url, json="", headers=context.auth_headers, timeout=10
    )
