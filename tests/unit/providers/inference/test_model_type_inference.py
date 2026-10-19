"""Unit tests for model type inference helpers."""

from providers.inference.model_type_inference import (
    KNOWN_EMBEDDING_IDS,
    KNOWN_LLM_IDS,
    infer_model_type_from_pai_known_names,
)


def test_known_ids_include_openai_model_ids() -> None:
    """PAI known-name tables are exposed as prefix-stripped model ids."""
    assert "gpt-4o-mini" in KNOWN_LLM_IDS
    assert "text-embedding-3-small" in KNOWN_EMBEDDING_IDS
    assert "openai:gpt-4o-mini" not in KNOWN_LLM_IDS


def test_infer_model_type_from_pai_known_names() -> None:
    """Known ids map to embedding or llm; unknown ids return None."""
    assert (
        infer_model_type_from_pai_known_names("text-embedding-3-small") == "embedding"
    )
    assert infer_model_type_from_pai_known_names("gpt-4o-mini") == "llm"
    assert infer_model_type_from_pai_known_names("totally-custom-chat") is None
