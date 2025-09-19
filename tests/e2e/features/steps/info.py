"""Implementation of common test steps."""

from behave import then  # pyright: ignore[reportAttributeAccessIssue]
from behave.runner import Context


@then("The body of the response has proper name {service_name} and version {version}")
def check_name_version(context: Context, service_name: str, version: str) -> None:
    """Check proper service name and version number."""
    response_json = context.response.json()
    assert response_json is not None, "Response is not valid JSON"

    assert response_json["name"] == service_name, f"name is {response_json["name"]}"
    assert (
        response_json["service_version"] == version
    ), f"version is {response_json["service_version"]}"


@then("The body of the response has llama-stack version {llama_version}")
def check_llama_version(context: Context, llama_version: str) -> None:
    """Check proper llama-stack version number."""
    response_json = context.response.json()
    assert response_json is not None, "Response is not valid JSON"

    assert (
        response_json["llama_stack_version"] == llama_version
    ), f"llama-stack version is {response_json["llama_stack_version"]}"


@then("The body of the response for model {model} has proper structure")
def check_model_structure(context: Context, model: str) -> None:
    """Check that the gpt-4o-mini model has the correct structure and required fields."""
    response_json = context.response.json()
    assert response_json is not None, "Response is not valid JSON"

    assert "models" in response_json, "Response missing 'models' field"
    models = response_json["models"]
    assert len(models) > 0, "Models list should not be empty"

    gpt_model = None
    for model_id in models:
        if "gpt-4o-mini" in model_id.get("identifier", ""):
            gpt_model = model_id
            break

    assert gpt_model is not None

    assert gpt_model["type"] == "model", "type should be 'model'"
    assert gpt_model["api_model_type"] == "llm", "api_model_type should be 'llm'"
    assert gpt_model["model_type"] == "llm", "model_type should be 'llm'"
    assert gpt_model["provider_id"] == "openai", "provider_id should be 'openai'"
    assert (
        gpt_model["provider_resource_id"] == model
    ), "provider_resource_id should be 'gpt-4o-mini'"
    assert (
        gpt_model["identifier"] == f"openai/{model}"
    ), "identifier should be 'openai/gpt-4o-mini'"
