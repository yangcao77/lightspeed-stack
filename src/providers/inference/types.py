"""Shared literals and aliases for the inference provider registry."""

from typing import Literal

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
