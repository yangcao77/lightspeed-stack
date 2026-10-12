"""Abstract base for pluggable knowledge sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from knowledge.types import KnowledgeMatch, KnowledgeReadiness


@dataclass
class KnowledgeSource(ABC):
    """Knowledge source to search, with its own exposure mode.

    `mode` lives here (rather than on whatever capability attaches this
    source) so each source controls how *it* is exposed, independent of how
    many other sources a `Knowledge` capability combines it with.
    """

    name: str
    """Name of the knowledge source."""

    mode: set[Literal["tool", "auto"]] = field(
        default_factory=lambda: {"tool"}, kw_only=True
    )
    """
    `'tool'`: exposes a model-callable `search_<name>` tool for this source.
    `'auto'`: searches the latest user prompt automatically and injects this
    source's matches as bounded, delimited context on every model request.
    """

    @abstractmethod
    async def search(self, prompt: str) -> list[KnowledgeMatch]:
        """Search the knowledge source for matches."""

    @abstractmethod
    async def readiness(self) -> KnowledgeReadiness:
        """Check the readiness of the knowledge source."""
