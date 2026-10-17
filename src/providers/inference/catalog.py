"""Internal inference catalog models."""

from typing import Any

from pydantic import BaseModel, Field

from providers.inference.types import ModelType


class DiscoveredModel(BaseModel):
    """Model reported by a provider before allow-list mapping."""

    provider_model_id: str
    model_type: ModelType
    metadata: dict[str, Any] = Field(default_factory=dict)


class CatalogModel(BaseModel):
    """Cached catalog row for inference providers and the registry."""

    name: str
    provider_model_id: str
    model_type: ModelType
    metadata: dict[str, Any] = Field(default_factory=dict)
