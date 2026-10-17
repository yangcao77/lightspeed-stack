"""Unit tests for internal inference catalog models."""

from providers.inference.catalog import CatalogModel, DiscoveredModel


def test_catalog_model_construction() -> None:
    """CatalogModel stores name, wire id, type, and metadata."""
    row = CatalogModel(
        name="fast-chat",
        provider_model_id="gpt-4o-mini",
        model_type="llm",
        metadata={"context_window": 128000},
    )
    assert row.name == "fast-chat"
    assert row.provider_model_id == "gpt-4o-mini"
    assert row.model_type == "llm"
    assert row.metadata["context_window"] == 128000


def test_discovered_model_construction() -> None:
    """DiscoveredModel stores wire id, type, and optional metadata."""
    row = DiscoveredModel(
        provider_model_id="gpt-4o-mini",
        model_type="llm",
        metadata={"owned_by": "openai"},
    )
    assert row.provider_model_id == "gpt-4o-mini"
    assert row.model_type == "llm"
    assert row.metadata == {"owned_by": "openai"}
