"""Shared test helpers for inference providers."""

from typing import Any, Optional

from pydantic_ai.embeddings import EmbeddingModel
from pydantic_ai.models import Model
from pydantic_ai.providers import Provider
from sentence_transformers import CrossEncoder

from models.config import InferenceProviderEntryBase
from providers.inference.base import InferenceProvider
from providers.inference.catalog import CatalogModel
from providers.inference.types import ModelType


class FakeInferenceProvider(InferenceProvider[InferenceProviderEntryBase]):
    """Minimal concrete provider for testing shared behavior."""

    def _build_provider(self) -> Optional[Provider[Any]]:
        return None

    async def _discover_models(self) -> list[CatalogModel]:
        return []

    def _create_llm(self, model: CatalogModel) -> Model:
        raise NotImplementedError

    def _create_embedding(self, model: CatalogModel) -> EmbeddingModel:
        raise NotImplementedError

    def _create_rerank(self, model: CatalogModel) -> CrossEncoder:
        raise NotImplementedError

    def _infer_model_type(
        self,
        provider_model_id: str,
        **kwargs: Any,
    ) -> ModelType:
        raise NotImplementedError
