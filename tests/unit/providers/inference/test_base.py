"""Unit tests for the inference provider base class."""

from typing import Any

import pytest

from models.config import AllowedModel
from providers.inference.catalog import CatalogModel, DiscoveredModel
from providers.inference.types import ModelType
from tests.unit.providers.inference._helpers import (
    FakeInferenceProvider,
    make_fake_provider,
)


@pytest.fixture(name="provider")
def provider_fixture() -> FakeInferenceProvider:
    """Create a provider with a preloaded catalog."""
    return make_fake_provider()


def test_list_catalog_models_returns_all_models(
    provider: FakeInferenceProvider,
) -> None:
    """list_catalog_models returns every catalog entry when unfiltered."""
    models = provider.list_catalog_models()

    assert [model.name for model in models] == [
        "chat-model",
        "embedding-model",
        "rerank-model",
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

    assert len(provider.list_catalog_models()) == 3


@pytest.mark.parametrize(
    ("name", "model_type", "creator"),
    [
        ("chat-model", "llm", "_create_llm"),
        ("embedding-model", "embedding", "_create_embedding"),
        ("rerank-model", "rerank", "_create_rerank"),
    ],
)
def test_get_model_instance_dispatches_to_typed_creator(
    provider: FakeInferenceProvider,
    mocker: Any,
    name: str,
    model_type: ModelType,
    creator: str,
) -> None:
    """get_model_instance looks up by type and calls the matching creator."""
    sentinel = object()
    mock = mocker.patch.object(provider, creator, return_value=sentinel)

    instance = provider.get_model_instance(name, model_type)

    assert instance is sentinel
    mock.assert_called_once()


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
    assert model.provider_model_id == "provider-chat-model"


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


def test_filter_discovered_without_allow_list_uses_provider_ids(
    provider: FakeInferenceProvider,
) -> None:
    """Empty allow-list publishes discovered models under their wire ids."""
    discovered = [
        DiscoveredModel(provider_model_id="gpt-4o-mini", model_type="llm"),
        DiscoveredModel(
            provider_model_id="text-embedding-3-small",
            model_type="embedding",
            metadata={"owned_by": "openai"},
        ),
    ]

    catalog = provider._filter_discovered(  # pylint: disable=protected-access
        discovered, []
    )

    assert catalog == [
        CatalogModel(
            name="gpt-4o-mini",
            provider_model_id="gpt-4o-mini",
            model_type="llm",
        ),
        CatalogModel(
            name="text-embedding-3-small",
            provider_model_id="text-embedding-3-small",
            model_type="embedding",
            metadata={"owned_by": "openai"},
        ),
    ]


def test_filter_discovered_applies_allow_list_aliases(
    provider: FakeInferenceProvider,
) -> None:
    """Allow-list maps discovered wire ids to local catalog names."""
    discovered = [
        DiscoveredModel(provider_model_id="gpt-4o-mini", model_type="llm"),
        DiscoveredModel(
            provider_model_id="text-embedding-3-small", model_type="embedding"
        ),
    ]
    allowed = [
        AllowedModel(
            name="chat",
            provider_model_id="gpt-4o-mini",
            model_type=None,
            metadata={"tier": "fast"},
        ),
        AllowedModel(
            name="missing",
            provider_model_id="does-not-exist",
            model_type=None,
        ),
    ]

    catalog = provider._filter_discovered(  # pylint: disable=protected-access
        discovered, allowed
    )

    assert len(catalog) == 1
    assert catalog[0] == CatalogModel(
        name="chat",
        provider_model_id="gpt-4o-mini",
        model_type="llm",
        metadata={"tier": "fast"},
    )
