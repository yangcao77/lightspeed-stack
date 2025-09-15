"""Unit tests for endpoints utility functions."""

import os
import pytest
from fastapi import HTTPException

import constants
from configuration import AppConfig
from models.config import CustomProfile
from models.requests import QueryRequest
from models.config import Action
from utils import endpoints

from tests.unit import config_dict

CONFIGURED_SYSTEM_PROMPT = "This is a configured system prompt"


@pytest.fixture(name="input_file")
def input_file_fixture(tmp_path):
    """Create file manually using the tmp_path fixture."""
    filename = os.path.join(tmp_path, "prompt.txt")
    with open(filename, "wt", encoding="utf-8") as fout:
        fout.write("this is prompt!")
    return filename


@pytest.fixture(name="config_without_system_prompt")
def config_without_system_prompt_fixture():
    """Configuration w/o custom system prompt set."""
    test_config = config_dict.copy()

    # no customization provided
    test_config["customization"] = None

    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    return cfg


@pytest.fixture(name="config_with_custom_system_prompt")
def config_with_custom_system_prompt_fixture():
    """Configuration with custom system prompt set."""
    test_config = config_dict.copy()

    # system prompt is customized
    test_config["customization"] = {
        "system_prompt": CONFIGURED_SYSTEM_PROMPT,
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    return cfg


@pytest.fixture(name="config_with_custom_system_prompt_and_disable_query_system_prompt")
def config_with_custom_system_prompt_and_disable_query_system_prompt_fixture():
    """Configuration with custom system prompt and disabled query system prompt set."""
    test_config = config_dict.copy()

    # system prompt is customized and query system prompt is disabled
    test_config["customization"] = {
        "system_prompt": CONFIGURED_SYSTEM_PROMPT,
        "disable_query_system_prompt": True,
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    return cfg


@pytest.fixture(
    name="config_with_custom_profile_prompt_and_enabled_query_system_prompt"
)
def config_with_custom_profile_prompt_and_enabled_query_system_prompt_fixture():
    """Configuration with custom profile loaded for prompt and disabled query system prompt set."""
    test_config = config_dict.copy()

    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
        "system_prompt": CONFIGURED_SYSTEM_PROMPT,
        "disable_query_system_prompt": False,
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    return cfg


@pytest.fixture(
    name="config_with_custom_profile_prompt_and_disable_query_system_prompt"
)
def config_with_custom_profile_prompt_and_disable_query_system_prompt_fixture():
    """Configuration with custom profile loaded for prompt and disabled query system prompt set."""
    test_config = config_dict.copy()

    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
        "system_prompt": CONFIGURED_SYSTEM_PROMPT,
        "disable_query_system_prompt": True,
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    return cfg


@pytest.fixture(name="query_request_without_system_prompt")
def query_request_without_system_prompt_fixture():
    """Fixture for query request without system prompt."""
    return QueryRequest(query="query", system_prompt=None)


@pytest.fixture(name="query_request_with_system_prompt")
def query_request_with_system_prompt_fixture():
    """Fixture for query request with system prompt."""
    return QueryRequest(query="query", system_prompt="System prompt defined in query")


def test_get_default_system_prompt(
    config_without_system_prompt, query_request_without_system_prompt
):
    """Test that default system prompt is returned when other prompts are not provided."""
    system_prompt = endpoints.get_system_prompt(
        query_request_without_system_prompt, config_without_system_prompt
    )
    assert system_prompt == constants.DEFAULT_SYSTEM_PROMPT


def test_get_customized_system_prompt(
    config_with_custom_system_prompt, query_request_without_system_prompt
):
    """Test that customized system prompt is used when system prompt is not provided in query."""
    system_prompt = endpoints.get_system_prompt(
        query_request_without_system_prompt, config_with_custom_system_prompt
    )
    assert system_prompt == CONFIGURED_SYSTEM_PROMPT


def test_get_query_system_prompt(
    config_without_system_prompt, query_request_with_system_prompt
):
    """Test that system prompt from query is returned."""
    system_prompt = endpoints.get_system_prompt(
        query_request_with_system_prompt, config_without_system_prompt
    )
    assert system_prompt == query_request_with_system_prompt.system_prompt


def test_get_query_system_prompt_not_customized_one(
    config_with_custom_system_prompt, query_request_with_system_prompt
):
    """Test that system prompt from query is returned even when customized one is specified."""
    system_prompt = endpoints.get_system_prompt(
        query_request_with_system_prompt, config_with_custom_system_prompt
    )
    assert system_prompt == query_request_with_system_prompt.system_prompt


def test_get_system_prompt_with_disable_query_system_prompt(
    config_with_custom_system_prompt_and_disable_query_system_prompt,
    query_request_with_system_prompt,
):
    """Test that query system prompt is disallowed when disable_query_system_prompt is True."""
    with pytest.raises(HTTPException) as exc_info:
        endpoints.get_system_prompt(
            query_request_with_system_prompt,
            config_with_custom_system_prompt_and_disable_query_system_prompt,
        )
    assert exc_info.value.status_code == 422


def test_get_system_prompt_with_disable_query_system_prompt_and_non_system_prompt_query(
    config_with_custom_system_prompt_and_disable_query_system_prompt,
    query_request_without_system_prompt,
):
    """Test that query without system prompt is allowed when disable_query_system_prompt is True."""
    system_prompt = endpoints.get_system_prompt(
        query_request_without_system_prompt,
        config_with_custom_system_prompt_and_disable_query_system_prompt,
    )
    assert system_prompt == CONFIGURED_SYSTEM_PROMPT


def test_get_profile_prompt_with_disable_query_system_prompt(
    config_with_custom_profile_prompt_and_disable_query_system_prompt,
    query_request_without_system_prompt,
):
    """Test that system prompt is set if profile enabled and query system prompt disabled."""
    custom_profile = CustomProfile(path="tests/profiles/test/profile.py")
    prompts = custom_profile.get_prompts()
    system_prompt = endpoints.get_system_prompt(
        query_request_without_system_prompt,
        config_with_custom_profile_prompt_and_disable_query_system_prompt,
    )
    assert system_prompt == prompts.get("default")


def test_get_profile_prompt_with_enabled_query_system_prompt(
    config_with_custom_profile_prompt_and_enabled_query_system_prompt,
    query_request_with_system_prompt,
):
    """Test that profile system prompt is overridden by query system prompt enabled."""
    system_prompt = endpoints.get_system_prompt(
        query_request_with_system_prompt,
        config_with_custom_profile_prompt_and_enabled_query_system_prompt,
    )
    assert system_prompt == query_request_with_system_prompt.system_prompt


def test_validate_model_provider_override_allowed_with_action():
    """Ensure no exception when caller has MODEL_OVERRIDE and request includes model/provider."""
    query_request = QueryRequest(query="q", model="m", provider="p")
    authorized_actions = {Action.MODEL_OVERRIDE}
    endpoints.validate_model_provider_override(query_request, authorized_actions)


def test_validate_model_provider_override_rejected_without_action():
    """Ensure HTTP 403 when request includes model/provider and caller lacks permission."""
    query_request = QueryRequest(query="q", model="m", provider="p")
    authorized_actions: set[Action] = set()
    with pytest.raises(HTTPException) as exc_info:
        endpoints.validate_model_provider_override(query_request, authorized_actions)
    assert exc_info.value.status_code == 403


def test_validate_model_provider_override_no_override_without_action():
    """No exception when request does not include model/provider regardless of permission."""
    query_request = QueryRequest(query="q")
    endpoints.validate_model_provider_override(query_request, set())


# Tests for get_validation_system_prompt


def test_get_default_validation_system_prompt(config_without_system_prompt):
    """Test that default validation system prompt is returned when no custom profile is provided."""
    validation_prompt = endpoints.get_validation_system_prompt(
        config_without_system_prompt
    )
    assert validation_prompt == constants.DEFAULT_VALIDATION_SYSTEM_PROMPT


def test_get_validation_system_prompt_with_custom_profile():
    """Test that validation system prompt from custom profile is returned when available."""
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    validation_prompt = endpoints.get_validation_system_prompt(cfg)

    # Get the expected prompt from the test profile
    custom_profile = CustomProfile(path="tests/profiles/test/profile.py")
    expected_prompt = custom_profile.get_prompts().get("validation")

    assert validation_prompt == expected_prompt


def test_get_validation_system_prompt_with_custom_profile_no_validation_prompt():
    """Test that default validation system prompt is returned when custom profile has no validation prompt."""
    # Create a test profile that doesn't have validation prompt
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    # Manually set the prompts to not include validation
    cfg.customization.custom_profile.prompts = {"default": "test prompt"}

    validation_prompt = endpoints.get_validation_system_prompt(cfg)
    assert validation_prompt == constants.DEFAULT_VALIDATION_SYSTEM_PROMPT


def test_get_validation_system_prompt_with_custom_profile_empty_validation_prompt():
    """Test that default validation system prompt is returned when custom profile has empty validation prompt."""
    # Create a test profile that has empty validation prompt
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    # Manually set the prompts to have empty validation prompt
    cfg.customization.custom_profile.prompts = {"validation": ""}

    validation_prompt = endpoints.get_validation_system_prompt(cfg)
    assert validation_prompt == constants.DEFAULT_VALIDATION_SYSTEM_PROMPT


# Tests for get_invalid_query_response


def test_get_default_invalid_query_response(config_without_system_prompt):
    """Test that default invalid query response is returned when no custom profile is provided."""
    invalid_response = endpoints.get_invalid_query_response(
        config_without_system_prompt
    )
    assert invalid_response == constants.DEFAULT_INVALID_QUERY_RESPONSE


def test_get_invalid_query_response_with_custom_profile():
    """Test that invalid query response from custom profile is returned when available."""
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    invalid_response = endpoints.get_invalid_query_response(cfg)

    # Get the expected response from the test profile
    custom_profile = CustomProfile(path="tests/profiles/test/profile.py")
    expected_response = custom_profile.get_query_responses().get("invalid_resp")

    assert invalid_response == expected_response


def test_get_invalid_query_response_with_custom_profile_no_invalid_resp():
    """Test that default invalid query response is returned when custom profile has no invalid_resp."""
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    # Manually set the query_responses to not include invalid_resp
    cfg.customization.custom_profile.query_responses = {}

    invalid_response = endpoints.get_invalid_query_response(cfg)
    assert invalid_response == constants.DEFAULT_INVALID_QUERY_RESPONSE


def test_get_invalid_query_response_with_custom_profile_empty_invalid_resp():
    """Test that default invalid query response is returned when custom profile has empty invalid_resp."""
    test_config = config_dict.copy()
    test_config["customization"] = {
        "profile_path": "tests/profiles/test/profile.py",
    }
    cfg = AppConfig()
    cfg.init_from_dict(test_config)

    # Manually set the query_responses to have empty invalid_resp
    cfg.customization.custom_profile.query_responses = {"invalid_resp": ""}

    invalid_response = endpoints.get_invalid_query_response(cfg)
    assert invalid_response == constants.DEFAULT_INVALID_QUERY_RESPONSE
