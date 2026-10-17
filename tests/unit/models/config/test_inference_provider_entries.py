"""Unit tests for discriminated inference.providers[] config entries."""

import pytest
from pydantic import TypeAdapter, ValidationError

from models.config import (
    AllowedModel,
    BedrockInferenceProviderEntry,
    InferenceConfiguration,
    OpenAIInferenceProviderEntry,
    SentenceTransformersInferenceProviderEntry,
    UnifiedInferenceProviderEntry,
    VllmInferenceProviderEntry,
)

PROVIDER_ADAPTER = TypeAdapter(UnifiedInferenceProviderEntry)


@pytest.mark.parametrize(
    "provider_type",
    [
        "openai",
        "azure",
        "vertexai",
        "bedrock",
        "watsonx",
        "vllm",
        "sentence_transformers",
    ],
)
def test_all_seven_provider_types_parse(provider_type: str) -> None:
    """Each supported provider type parses into the discriminated union."""
    payload: dict[str, object] = {"type": provider_type}
    if provider_type == "sentence_transformers":
        payload["allowed_models"] = ["all-MiniLM-L6-v2"]
    provider = PROVIDER_ADAPTER.validate_python(payload)
    assert provider.type == provider_type
    assert provider.id == provider_type


def test_allowed_models_string_form_normalizes() -> None:
    """Bare string allow-list entries set name and provider_model_id equal."""
    model = AllowedModel.model_validate("gpt-4o-mini")
    assert model.name == "gpt-4o-mini"
    assert model.provider_model_id == "gpt-4o-mini"
    assert model.model_type is None
    assert model.metadata == {}


def test_allowed_models_structured_form() -> None:
    """Structured allow-list entries keep local name, wire id, type, metadata."""
    model = AllowedModel.model_validate(
        {
            "name": "fast-chat",
            "provider_model_id": "gpt-4o-mini",
            "model_type": "llm",
            "metadata": {"context_window": 128000},
        }
    )
    assert model.name == "fast-chat"
    assert model.provider_model_id == "gpt-4o-mini"
    assert model.model_type == "llm"
    assert model.metadata["context_window"] == 128000


def test_allowed_models_defaults_name_to_provider_model_id() -> None:
    """Omitted name defaults to provider_model_id."""
    model = AllowedModel.model_validate(
        {"provider_model_id": "openai/gpt-4o-mini", "model_type": "llm"}
    )
    assert model.name == "openai/gpt-4o-mini"
    assert model.provider_model_id == "openai/gpt-4o-mini"


def test_omitted_id_defaults_to_type() -> None:
    """Provider id defaults to type when omitted."""
    provider = OpenAIInferenceProviderEntry.model_validate({"type": "openai"})
    assert provider.id == "openai"


def test_explicit_id_is_kept() -> None:
    """Explicit provider id is preserved."""
    provider = VllmInferenceProviderEntry.model_validate(
        {"type": "vllm", "id": "vllm-prod"}
    )
    assert provider.id == "vllm-prod"


def test_duplicate_provider_ids_fail() -> None:
    """Two providers resolving to the same id fail validation."""
    with pytest.raises(ValidationError, match="duplicate inference provider id"):
        InferenceConfiguration(
            providers=[
                {"type": "vllm"},
                {"type": "vllm"},
            ]
        )


def test_duplicate_local_model_names_within_provider_fail() -> None:
    """Duplicate local names in one provider's allow-list fail validation."""
    with pytest.raises(ValidationError, match="allowed model names must be unique"):
        OpenAIInferenceProviderEntry.model_validate(
            {
                "type": "openai",
                "allowed_models": [
                    "same",
                    {"name": "same", "provider_model_id": "other"},
                ],
            }
        )


def test_same_local_model_name_across_providers_allowed() -> None:
    """The same local model name may appear on different providers."""
    config = InferenceConfiguration(
        providers=[
            {"type": "openai", "allowed_models": ["shared"]},
            {"type": "vllm", "id": "vllm-prod", "allowed_models": ["shared"]},
        ]
    )
    assert config.providers[0].allowed_models is not None
    assert config.providers[1].allowed_models is not None
    assert config.providers[0].allowed_models[0].name == "shared"
    assert config.providers[1].allowed_models[0].name == "shared"


def test_skip_model_discovery_requires_allowed_models() -> None:
    """skip_model_discovery: true requires a non-empty allow-list."""
    with pytest.raises(ValidationError, match="skip_model_discovery"):
        OpenAIInferenceProviderEntry.model_validate(
            {"type": "openai", "skip_model_discovery": True}
        )


def test_skip_model_discovery_with_allowed_models() -> None:
    """skip_model_discovery succeeds when allowed_models is non-empty."""
    provider = OpenAIInferenceProviderEntry.model_validate(
        {
            "type": "openai",
            "skip_model_discovery": True,
            "allowed_models": ["gpt-4o-mini"],
        }
    )
    assert provider.skip_model_discovery is True


def test_sentence_transformers_requires_allowed_models() -> None:
    """Sentence-transformers rejects an empty/missing allow-list."""
    with pytest.raises(
        ValidationError,
        match="allowed_models must be non-empty for sentence_transformers",
    ):
        SentenceTransformersInferenceProviderEntry.model_validate(
            {"type": "sentence_transformers"}
        )


def test_nested_config_parses() -> None:
    """Typed nested config blocks parse for a remote provider."""
    provider = BedrockInferenceProviderEntry.model_validate(
        {
            "type": "bedrock",
            "config": {"region": "${env.AWS_REGION}", "profile_name": "default"},
        }
    )
    assert provider.config.region == "${env.AWS_REGION}"
    assert provider.config.profile_name == "default"
