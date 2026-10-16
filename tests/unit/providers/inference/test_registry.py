"""Unit tests for the ProviderRegistry singleton."""

from collections.abc import Generator
from typing import Optional

import pytest

from models.config import (
    AllowedModel,
    InferenceConfiguration,
    OpenAIInferenceProviderEntry,
    VllmInferenceProviderEntry,
)
from providers.inference.errors import ProviderNotFoundError
from providers.inference.registry import PROVIDER_CLASSES, ProviderRegistry
from providers.inference.types import ProviderType
from tests.unit.providers.inference._helpers import FakeInferenceProvider
from utils.types import Singleton


@pytest.fixture(autouse=True)
def _reset_registry_and_provider_classes() -> Generator[None, None, None]:
    """Isolate the provider registry and provider classes per test."""
    original = dict(PROVIDER_CLASSES)
    PROVIDER_CLASSES.clear()
    # pylint: disable=protected-access
    Singleton._instances.pop(ProviderRegistry, None)

    yield

    PROVIDER_CLASSES.clear()
    PROVIDER_CLASSES.update(original)
    Singleton._instances.pop(ProviderRegistry, None)
    # pylint: enable=protected-access


def _register_fake(*provider_types: ProviderType) -> None:
    """Register FakeInferenceProvider for the given provider types."""
    for provider_type in provider_types:
        PROVIDER_CLASSES[provider_type] = FakeInferenceProvider


def _openai_entry(
    provider_id: str = "openai",
    *,
    allowed_models: Optional[list[AllowedModel]] = None,
) -> OpenAIInferenceProviderEntry:
    """Build an OpenAI provider entry that skips model discovery."""
    return OpenAIInferenceProviderEntry(
        id=provider_id,
        skip_model_discovery=True,
        allowed_models=(
            allowed_models
            if allowed_models is not None
            else [
                AllowedModel(
                    name="chat",
                    provider_model_id="gpt-4o-mini",
                    model_type="llm",
                )
            ]
        ),
    )  # pyright: ignore[reportCallIssue]


def _vllm_entry(
    provider_id: str = "vllm",
    *,
    allowed_models: Optional[list[AllowedModel]] = None,
) -> VllmInferenceProviderEntry:
    """Build a vLLM provider entry that skips model discovery."""
    return VllmInferenceProviderEntry(
        id=provider_id,
        skip_model_discovery=True,
        allowed_models=(
            allowed_models
            if allowed_models is not None
            else [
                AllowedModel(
                    name="embed",
                    provider_model_id="text-embedding-3-small",
                    model_type="embedding",
                )
            ]
        ),
    )  # pyright: ignore[reportCallIssue]


def _inference_config(
    *providers: OpenAIInferenceProviderEntry | VllmInferenceProviderEntry,
) -> InferenceConfiguration:
    """Build inference configuration from provider entries."""
    return InferenceConfiguration.model_validate(
        {"providers": [provider.model_dump() for provider in providers]}
    )


@pytest.mark.asyncio
async def test_initialize_registers_configured_providers() -> None:
    """initialize registers a provider for each configured entry."""
    _register_fake("openai", "vllm")
    registry = ProviderRegistry()

    await registry.initialize(_inference_config(_openai_entry(), _vllm_entry()))

    assert [provider.provider_id for provider in registry.list_providers()] == [
        "openai",
        "vllm",
    ]


@pytest.mark.asyncio
async def test_initialize_adds_to_existing_providers() -> None:
    """Repeated initialization adds providers without removing existing ones."""
    _register_fake("openai", "vllm")
    registry = ProviderRegistry()

    await registry.initialize(_inference_config(_openai_entry()))
    await registry.initialize(_inference_config(_vllm_entry()))

    assert [provider.provider_id for provider in registry.list_providers()] == [
        "openai",
        "vllm",
    ]


@pytest.mark.asyncio
async def test_find_provider_returns_provider_or_none() -> None:
    """find_provider returns the provider or None when it is not registered."""
    _register_fake("openai")
    registry = ProviderRegistry()
    await registry.initialize(_inference_config(_openai_entry()))

    provider = registry.find_provider("openai")

    assert provider is not None
    assert provider.provider_id == "openai"
    assert registry.find_provider("missing") is None


@pytest.mark.asyncio
async def test_get_provider_returns_provider_or_raises() -> None:
    """get_provider raises ProviderNotFoundError for an unknown ID."""
    _register_fake("openai")
    registry = ProviderRegistry()
    await registry.initialize(_inference_config(_openai_entry()))

    assert registry.get_provider("openai").provider_id == "openai"

    with pytest.raises(ProviderNotFoundError) as exc_info:
        registry.get_provider("missing")

    assert exc_info.value.provider_id == "missing"


@pytest.mark.asyncio
async def test_list_models_aggregates_providers_and_filters_by_type() -> None:
    """list_models aggregates catalog entries and applies the optional type filter."""
    _register_fake("openai", "vllm")
    registry = ProviderRegistry()
    await registry.initialize(
        _inference_config(
            _openai_entry(
                allowed_models=[
                    AllowedModel(
                        name="chat",
                        provider_model_id="gpt-4o-mini",
                        model_type="llm",
                    ),
                    AllowedModel(
                        name="embed-a",
                        provider_model_id="text-embedding-3-small",
                        model_type="embedding",
                    ),
                ]
            ),
            _vllm_entry(
                allowed_models=[
                    AllowedModel(
                        name="embed-b",
                        provider_model_id="nomic-embed",
                        model_type="embedding",
                    )
                ]
            ),
        )
    )

    assert [model.name for model in registry.list_models()] == [
        "chat",
        "embed-a",
        "embed-b",
    ]
    assert [model.name for model in registry.list_models(model_type="embedding")] == [
        "embed-a",
        "embed-b",
    ]
