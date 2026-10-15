"""Unit tests for internal inference catalog models."""

from providers.inference.catalog import CatalogModel


def test_catalog_model_construction() -> None:
    """CatalogModel stores name, wire id, type, and metadata."""
    row = CatalogModel(
        name="fast-chat",
        provider_resource_id="gpt-4o-mini",
        model_type="llm",
        metadata={"context_window": 128000},
    )
    assert row.name == "fast-chat"
    assert row.provider_resource_id == "gpt-4o-mini"
    assert row.model_type == "llm"
    assert row.metadata["context_window"] == 128000
