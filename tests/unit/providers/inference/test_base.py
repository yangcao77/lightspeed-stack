"""Unit tests for the inference provider base class."""

import pytest

from models.config import InferenceProviderEntryBase
from providers.inference.catalog import CatalogModel
from tests.unit.providers.inference._helpers import FakeInferenceProvider


@pytest.fixture(name="provider")
def provider_fixture() -> FakeInferenceProvider:
    """Create a provider with a small preloaded catalog."""
    entry = InferenceProviderEntryBase(
        id="test-provider"
    )  # pyright: ignore[reportCallIssue]
    provider = FakeInferenceProvider(entry)
    provider._models = [  # pylint: disable=protected-access
        CatalogModel(
            name="chat-model",
            provider_resource_id="provider-chat-model",
            model_type="llm",
            metadata={"tags": ["chat"]},
        ),
        CatalogModel(
            name="embedding-model",
            provider_resource_id="provider-embedding-model",
            model_type="embedding",
            metadata={},
        ),
    ]
    return provider


def test_list_catalog_models_returns_all_models(
    provider: FakeInferenceProvider,
) -> None:
    """list_catalog_models returns every catalog entry when unfiltered."""
    models = provider.list_catalog_models()

    assert [model.name for model in models] == [
        "chat-model",
        "embedding-model",
    ]


def test_list_catalog_models_filters_by_type(
    provider: FakeInferenceProvider,
) -> None:
    """list_catalog_models keeps only entries matching the requested type."""
    models = provider.list_catalog_models("embedding")

    assert [model.name for model in models] == ["embedding-model"]


def test_list_catalog_models_returns_copy(
    provider: FakeInferenceProvider,
) -> None:
    """list_catalog_models returns a copy, not the live catalog list."""
    provider.list_catalog_models().clear()

    assert len(provider.list_catalog_models()) == 2


def test_list_catalog_models_returns_deep_copies(
    provider: FakeInferenceProvider,
) -> None:
    """Caller mutations to listed models do not affect the cached catalog."""
    models = provider.list_catalog_models()
    models[0].metadata["tags"].append("mutated")
    models[0].metadata["extra"] = "value"

    cached = provider.get_catalog_model("chat-model", "llm")
    assert cached is not None
    assert cached.metadata == {"tags": ["chat"]}


def test_get_catalog_model_matches_name_and_type(
    provider: FakeInferenceProvider,
) -> None:
    """get_catalog_model returns the entry matching both name and type."""
    model = provider.get_catalog_model("chat-model", "llm")

    assert model is not None
    assert model.provider_resource_id == "provider-chat-model"


def test_get_catalog_model_returns_deep_copy(
    provider: FakeInferenceProvider,
) -> None:
    """Caller mutations to a looked-up model do not affect the cached catalog."""
    model = provider.get_catalog_model("chat-model", "llm")
    assert model is not None
    model.metadata["tags"].append("mutated")

    cached = provider.get_catalog_model("chat-model", "llm")
    assert cached is not None
    assert cached.metadata == {"tags": ["chat"]}


def test_get_catalog_model_returns_none_for_unknown_model_or_type(
    provider: FakeInferenceProvider,
) -> None:
    """get_catalog_model returns None when name or type does not match."""
    assert provider.get_catalog_model("missing-model", "llm") is None
    assert provider.get_catalog_model("chat-model", "embedding") is None
