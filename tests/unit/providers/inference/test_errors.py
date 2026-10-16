"""Unit tests for inference provider errors."""

import pytest

from models.config import InferenceProviderEntryBase
from providers.inference.errors import ModelNotAvailableError
from providers.inference.types import ModelType
from tests.unit.providers.inference._helpers import FakeInferenceProvider


def test_model_not_available_error_message_and_attributes() -> None:
    """Error message and attributes identify the unavailable model."""
    error = ModelNotAvailableError("chat", "llm", "fake-openai")

    assert error.name == "chat"
    assert error.model_type == "llm"
    assert error.provider_id == "fake-openai"
    assert str(error) == (
        "Model 'chat' of type 'llm' is not available for provider 'fake-openai'"
    )


@pytest.mark.parametrize("model_type", ["llm", "embedding", "rerank"])
def test_get_model_instance_raises_model_not_available_error(
    model_type: ModelType,
) -> None:
    """get_model_instance raises an error when the model is absent."""
    entry = InferenceProviderEntryBase(
        id="fake-openai"
    )  # pyright: ignore[reportCallIssue]
    provider = FakeInferenceProvider(entry)

    with pytest.raises(ModelNotAvailableError) as exc_info:
        provider.get_model_instance("missing", model_type)

    assert exc_info.value.name == "missing"
    assert exc_info.value.model_type == model_type
    assert exc_info.value.provider_id == "fake-openai"
