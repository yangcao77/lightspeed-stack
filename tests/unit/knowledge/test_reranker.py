"""Unit tests for knowledge.reranker."""

import logging

import numpy as np
import pytest
from pytest_mock import MockerFixture, MockType

from knowledge.reranker import rerank
from knowledge.types import KnowledgeMatch


def _match(
    content: str,
    score: float,
    *,
    match_id: str = "match-id",
    source: str | None = "source",
) -> KnowledgeMatch:
    """Build a knowledge match for reranker tests.

    Args:
        content: Match text scored by the cross-encoder.
        score: Original similarity score.
        match_id: Stable identifier so tests can assert identity preservation.
        source: Optional citation identifier.

    Returns:
        A `KnowledgeMatch` with the given fields and empty metadata.

    """
    return KnowledgeMatch(
        content=content,
        score=score,
        id=match_id,
        source=source,
        metadata={"origin": content},
    )


@pytest.fixture(name="cross_encoder")
def cross_encoder_fixture(mocker: MockerFixture) -> MockType:
    """Create a mock cross-encoder whose `predict` return value tests control.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        A mock stand-in for `sentence_transformers.CrossEncoder`.

    """
    return mocker.Mock()


class TestRerank:
    """Tests for the `rerank` function."""

    @pytest.mark.asyncio
    async def test_empty_matches_returns_same_list(
        self, cross_encoder: MockType
    ) -> None:
        """Empty input is returned unchanged and the model is not invoked."""
        matches: list[KnowledgeMatch] = []

        result = await rerank("prompt", matches, cross_encoder)

        assert result is matches
        cross_encoder.predict.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_reranking_sorts_by_combined_score(
        self, cross_encoder: MockType
    ) -> None:
        """Matches are scored 30% cross-encoder / 70% original and sorted descending."""
        matches = [
            _match("Content 1", 0.5, match_id="1"),
            _match("Content 2", 0.3, match_id="2"),
            _match("Content 3", 0.8, match_id="3"),
        ]
        cross_encoder.predict.return_value = [2.5, 1.0, 3.0]

        result = await rerank("test query", matches, cross_encoder)

        cross_encoder.predict.assert_called_once_with(
            [
                ("test query", "Content 1"),
                ("test query", "Content 2"),
                ("test query", "Content 3"),
            ]
        )
        # CE min/max 1.0/3.0 → [0.75, 0.0, 1.0]
        # orig min/max 0.3/0.8 → [0.4, 0.0, 1.0]
        # combined: 0.3*ce + 0.7*orig → [0.505, 0.0, 1.0]
        assert [match.content for match in result] == [
            "Content 3",
            "Content 1",
            "Content 2",
        ]
        assert result[0].score == pytest.approx(1.0)
        assert result[1].score == pytest.approx(0.505)
        assert result[2].score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_preserves_non_score_fields(self, cross_encoder: MockType) -> None:
        """Reranking replaces only `score`; other match fields are copied through."""
        matches = [
            _match("keep-me", 0.2, match_id="stable-id", source="doc://1"),
        ]
        cross_encoder.predict.return_value = [1.5]

        result = await rerank("prompt", matches, cross_encoder)

        assert len(result) == 1
        assert result[0].content == "keep-me"
        assert result[0].id == "stable-id"
        assert result[0].source == "doc://1"
        assert result[0].metadata == {"origin": "keep-me"}
        assert result[0].score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_does_not_mutate_input_matches(self, cross_encoder: MockType) -> None:
        """Input matches and their original scores are left unchanged."""
        matches = [
            _match("Content 1", 0.5, match_id="1"),
            _match("Content 2", 0.3, match_id="2"),
        ]
        original = list(matches)
        cross_encoder.predict.return_value = [2.0, 1.0]

        result = await rerank("prompt", matches, cross_encoder)

        assert matches == original
        assert matches[0].score == 0.5
        assert matches[1].score == 0.3
        assert result[0] is not matches[0]
        assert result[1] is not matches[1]

    @pytest.mark.asyncio
    async def test_identical_cross_encoder_scores_normalize_to_half(
        self, cross_encoder: MockType
    ) -> None:
        """Identical cross-encoder scores become 0.5, so original scores decide order."""
        matches = [
            _match("Content 1", 0.5, match_id="1"),
            _match("Content 2", 0.3, match_id="2"),
        ]
        cross_encoder.predict.return_value = [1.5, 1.5]

        result = await rerank("prompt", matches, cross_encoder)

        # CE → 0.5 each; orig 0.5/0.3 → 1.0/0.0
        # combined: 0.85, 0.15
        assert [match.content for match in result] == ["Content 1", "Content 2"]
        assert result[0].score == pytest.approx(0.85)
        assert result[1].score == pytest.approx(0.15)

    @pytest.mark.asyncio
    async def test_identical_original_scores_normalize_to_half(
        self, cross_encoder: MockType
    ) -> None:
        """Identical original scores become 0.5, so cross-encoder scores decide order."""
        matches = [
            _match("Content 1", 0.4, match_id="1"),
            _match("Content 2", 0.4, match_id="2"),
        ]
        cross_encoder.predict.return_value = [3.0, 1.0]

        result = await rerank("prompt", matches, cross_encoder)

        # CE 3.0/1.0 → 1.0/0.0; orig → 0.5 each
        # combined: 0.65, 0.35
        assert [match.content for match in result] == ["Content 1", "Content 2"]
        assert result[0].score == pytest.approx(0.65)
        assert result[1].score == pytest.approx(0.35)

    @pytest.mark.asyncio
    async def test_all_identical_scores_preserve_input_order(
        self, cross_encoder: MockType
    ) -> None:
        """When combined scores tie, Python's stable sort keeps the input order."""
        matches = [
            _match("first", 0.4, match_id="1"),
            _match("second", 0.4, match_id="2"),
        ]
        cross_encoder.predict.return_value = [1.0, 1.0]

        result = await rerank("prompt", matches, cross_encoder)

        assert [match.content for match in result] == ["first", "second"]
        assert result[0].score == pytest.approx(0.5)
        assert result[1].score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_single_match_normalizes_to_one(
        self, cross_encoder: MockType
    ) -> None:
        """A single match gets combined score 1.0 regardless of raw values."""
        matches = [_match("only", 0.12, match_id="1")]
        cross_encoder.predict.return_value = [-4.2]

        result = await rerank("prompt", matches, cross_encoder)

        assert len(result) == 1
        assert result[0].content == "only"
        assert result[0].score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_cross_encoder_can_reorder_close_original_scores(
        self, cross_encoder: MockType
    ) -> None:
        """A strong cross-encoder score can outrank a slightly higher original score."""
        matches = [
            _match("high-orig", 1.0, match_id="1"),
            _match("high-ce", 0.95, match_id="2"),
            _match("low", 0.0, match_id="3"),
        ]
        cross_encoder.predict.return_value = [1.0, 5.0, 2.0]

        result = await rerank("prompt", matches, cross_encoder)

        # CE min/max 1.0/5.0 → [0.0, 1.0, 0.25]
        # orig min/max 0.0/1.0 → [1.0, 0.95, 0.0]
        # combined: 0.70, 0.965, 0.075
        assert [match.content for match in result] == ["high-ce", "high-orig", "low"]
        assert result[0].score == pytest.approx(0.965)
        assert result[1].score == pytest.approx(0.7)
        assert result[2].score == pytest.approx(0.075)

    @pytest.mark.asyncio
    async def test_numpy_array_scores(self, cross_encoder: MockType) -> None:
        """Cross-encoder scores returned as a numpy array are ranked the same as a list."""
        matches = [
            _match("Content 1", 0.5, match_id="1"),
            _match("Content 2", 0.3, match_id="2"),
            _match("Content 3", 0.8, match_id="3"),
        ]
        cross_encoder.predict.return_value = np.array([2.5, 1.0, 3.0])

        result = await rerank("prompt", matches, cross_encoder)

        assert [match.content for match in result] == [
            "Content 3",
            "Content 1",
            "Content 2",
        ]
        assert result[0].score == pytest.approx(1.0)
        assert result[1].score == pytest.approx(0.505)
        assert result[2].score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_prediction_failure_returns_unranked_matches(
        self, cross_encoder: MockType, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A predict failure logs a warning and returns the original matches unranked."""
        matches = [
            _match("Content 1", 0.2, match_id="1"),
            _match("Content 2", 0.9, match_id="2"),
        ]
        cross_encoder.predict.side_effect = RuntimeError("prediction failed")

        with caplog.at_level(logging.WARNING, logger="knowledge.reranker"):
            result = await rerank("prompt", matches, cross_encoder)

        assert result is matches
        assert [match.content for match in result] == ["Content 1", "Content 2"]
        assert result[0].score == 0.2
        assert result[1].score == 0.9
        assert "Cross-encoder reranking failed; returning unranked matches." in (
            caplog.text
        )
        assert caplog.records[0].exc_info is not None
