"""Internal inference catalog models."""

from typing import Any

from pydantic import BaseModel, Field

from providers.inference.types import ModelType


class CatalogModel(BaseModel):
    """Cached catalog row for inference providers and the registry."""

    name: str
    provider_resource_id: str
    model_type: ModelType
    metadata: dict[str, Any] = Field(default_factory=dict)
