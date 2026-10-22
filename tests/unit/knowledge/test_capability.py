"""Unit tests for knowledge.capability."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.capabilities import AbstractCapability
from pytest_mock import MockerFixture, MockType

from knowledge.capability import Knowledge
from knowledge.sources.base import KnowledgeSource
from knowledge.types import KnowledgeMatch, KnowledgeReadiness


@dataclass
class FakeKnowledgeSource(KnowledgeSource):
    """Minimal knowledge source double for constructing `Knowledge`."""

    async def search(self, prompt: str) -> list[KnowledgeMatch]:
        """Unused; required by `KnowledgeSource`."""
        return []

    async def readiness(self) -> KnowledgeReadiness:
        """Report the source as ready."""
        return KnowledgeReadiness(status="ready")


class TestKnowledge:
    """Tests for the `Knowledge` capability dataclass."""

    def test_is_abstract_capability(self) -> None:
        """Knowledge is a pydantic-ai capability."""
        assert issubclass(Knowledge, AbstractCapability)

    def test_stores_sources_and_defaults_reranker_to_none(self) -> None:
        """Sources are retained and the cross-encoder is optional."""
        source = FakeKnowledgeSource(name="kb")

        capability = Knowledge(sources=[source])

        assert list(capability.sources) == [source]
        assert capability.reranker is None

    def test_stores_optional_reranker(self, mocker: MockerFixture) -> None:
        """An explicit reranker is retained on the capability."""
        source = FakeKnowledgeSource(name="kb")
        reranker: MockType = mocker.Mock()

        capability = Knowledge(sources=[source], reranker=reranker)

        assert capability.reranker is reranker
