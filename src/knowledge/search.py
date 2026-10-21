"""Concurrent multi-source knowledge search with optional cross-encoder reranking."""

import asyncio
from dataclasses import replace
from typing import Optional

from sentence_transformers import CrossEncoder

from knowledge.reranker import rerank
from knowledge.sources.base import KnowledgeSource
from knowledge.types import KnowledgeMatch


async def search_sources(
    sources: list[KnowledgeSource],
    prompt: str,
    reranker: Optional[CrossEncoder] = None,
) -> list[KnowledgeMatch]:
    """Search `sources` concurrently and return merged matches, ranked highest-score-first.

    Each match is tagged with `metadata['knowledge_source']` so hits stay
    attributable after the merge. Ranked by cross-encoder score if
    `reranker` is set, otherwise by each source's own similarity score.
    """
    results = await asyncio.gather(*(source.search(prompt) for source in sources))
    matches = [
        replace(match, metadata={**match.metadata, "knowledge_source": source.name})
        for source, source_matches in zip(sources, results)
        for match in source_matches
    ]
    if reranker:
        return await rerank(prompt, matches, reranker)
    return sorted(matches, key=lambda match: match.score, reverse=True)
