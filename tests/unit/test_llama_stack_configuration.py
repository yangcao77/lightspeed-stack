"""Unit tests for src/llama_stack_configuration.py."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from llama_stack_configuration import (
    generate_configuration,
    construct_vector_dbs_section,
    construct_vector_io_providers_section,
)
from models.config import (
    Configuration,
    ServiceConfiguration,
    LlamaStackConfiguration,
    UserDataCollection,
    InferenceConfiguration,
)

# =============================================================================
# Test construct_vector_dbs_section
# =============================================================================


def test_construct_vector_dbs_section_empty() -> None:
    """Test with no BYOK RAG config."""
    ls_config: dict[str, Any] = {}
    byok_rag: list[dict[str, Any]] = []
    output = construct_vector_dbs_section(ls_config, byok_rag)
    assert len(output) == 0


def test_construct_vector_dbs_section_preserves_existing() -> None:
    """Test preserves existing vector_dbs entries."""
    ls_config = {
        "vector_dbs": [
            {"vector_db_id": "existing", "provider_id": "existing_provider"},
        ]
    }
    byok_rag: list[dict[str, Any]] = []
    output = construct_vector_dbs_section(ls_config, byok_rag)
    assert len(output) == 1
    assert output[0]["vector_db_id"] == "existing"


def test_construct_vector_dbs_section_adds_new() -> None:
    """Test adds new BYOK RAG entries."""
    ls_config: dict[str, Any] = {}
    byok_rag = [
        {
            "rag_id": "rag1",
            "vector_db_id": "db1",
            "embedding_model": "test-model",
            "embedding_dimension": 512,
        },
    ]
    output = construct_vector_dbs_section(ls_config, byok_rag)
    assert len(output) == 1
    assert output[0]["vector_db_id"] == "db1"
    assert output[0]["provider_id"] == "byok_db1"
    assert output[0]["embedding_model"] == "test-model"
    assert output[0]["embedding_dimension"] == 512


def test_construct_vector_dbs_section_merge() -> None:
    """Test merges existing and new entries."""
    ls_config = {"vector_dbs": [{"vector_db_id": "existing"}]}
    byok_rag = [{"vector_db_id": "new_db"}]
    output = construct_vector_dbs_section(ls_config, byok_rag)
    assert len(output) == 2


# =============================================================================
# Test construct_vector_io_providers_section
# =============================================================================


def test_construct_vector_io_providers_section_empty() -> None:
    """Test with no BYOK RAG config."""
    ls_config: dict[str, Any] = {"providers": {}}
    byok_rag: list[dict[str, Any]] = []
    output = construct_vector_io_providers_section(ls_config, byok_rag)
    assert len(output) == 0


def test_construct_vector_io_providers_section_preserves_existing() -> None:
    """Test preserves existing vector_io entries."""
    ls_config = {"providers": {"vector_io": [{"provider_id": "existing"}]}}
    byok_rag: list[dict[str, Any]] = []
    output = construct_vector_io_providers_section(ls_config, byok_rag)
    assert len(output) == 1
    assert output[0]["provider_id"] == "existing"


def test_construct_vector_io_providers_section_adds_new() -> None:
    """Test adds new BYOK RAG entries."""
    ls_config: dict[str, Any] = {"providers": {}}
    byok_rag = [
        {
            "vector_db_id": "db1",
            "rag_type": "inline::faiss",
        },
    ]
    output = construct_vector_io_providers_section(ls_config, byok_rag)
    assert len(output) == 1
    assert output[0]["provider_id"] == "byok_db1"
    assert output[0]["provider_type"] == "inline::faiss"


# =============================================================================
# Test generate_configuration
# =============================================================================


def test_generate_configuration_no_input_file(tmp_path: Path) -> None:
    """Test generate_configuration when input file does not exist."""
    config: dict[str, Any] = {}
    outfile = tmp_path / "output.yaml"

    with pytest.raises(FileNotFoundError):
        generate_configuration("/nonexistent/file.yaml", str(outfile), config)


def test_generate_configuration_with_dict(tmp_path: Path) -> None:
    """Test generate_configuration accepts dict."""
    config: dict[str, Any] = {"byok_rag": []}
    outfile = tmp_path / "output.yaml"

    generate_configuration("tests/configuration/run.yaml", str(outfile), config)

    assert outfile.exists()
    with open(outfile, encoding="utf-8") as f:
        result = yaml.safe_load(f)
    assert "providers" in result


def test_generate_configuration_with_pydantic_model(tmp_path: Path) -> None:
    """Test generate_configuration accepts Pydantic model via model_dump()."""
    cfg = Configuration(  # type: ignore[call-arg]
        name="test",
        service=ServiceConfiguration(),  # type: ignore[call-arg]
        llama_stack=LlamaStackConfiguration(  # type: ignore[call-arg]
            use_as_library_client=True,
            library_client_config_path="run.yaml",
        ),
        user_data_collection=UserDataCollection(),  # type: ignore[call-arg]
        inference=InferenceConfiguration(),  # type: ignore[call-arg]
    )
    outfile = tmp_path / "output.yaml"

    # generate_configuration expects dict, so convert Pydantic model
    generate_configuration(
        "tests/configuration/run.yaml", str(outfile), cfg.model_dump()
    )

    assert outfile.exists()


def test_generate_configuration_with_byok(tmp_path: Path) -> None:
    """Test generate_configuration adds BYOK entries."""
    config = {
        "byok_rag": [
            {
                "rag_id": "rag1",
                "vector_db_id": "db1",
                "embedding_model": "test-model",
                "embedding_dimension": 256,
                "rag_type": "inline::faiss",
            },
        ],
    }
    outfile = tmp_path / "output.yaml"

    generate_configuration("tests/configuration/run.yaml", str(outfile), config)

    with open(outfile, encoding="utf-8") as f:
        result = yaml.safe_load(f)

    db_ids = [db["vector_db_id"] for db in result["vector_dbs"]]
    assert "db1" in db_ids
