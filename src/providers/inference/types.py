"""Shared literals and aliases for the inference provider registry."""

from typing import Any, Final, Literal

ProviderType = Literal[
    "openai",
    "azure",
    "vertexai",
    "bedrock",
    "watsonx",
    "vllm",
    "sentence_transformers",
]

ModelType = Literal["llm", "embedding", "rerank"]

type ProviderId = str

PROVIDER_CLASSES: Final[dict[ProviderType, Any]] = {}
