"""
Unit tests for the retrieval building blocks: rank fusion, query tokenising and
chunking. These are pure functions, so they run instantly and pin down the parts
of the pipeline most likely to break silently.
"""
from __future__ import annotations

from app.services.chunking import chunk_pages
from app.services.hybrid_retrieval import _query_terms, _rrf_merge


class TestReciprocalRankFusion:
    def test_document_in_both_lists_outranks_either_leg_alone(self):
        # "b" is 2nd in both legs; "a" is 1st in only one. Agreement wins.
        fused = _rrf_merge(["a", "b", "c"], ["d", "b", "e"])
        assert fused[0] == "b"

    def test_preserves_order_when_only_one_leg_has_results(self):
        assert _rrf_merge(["a", "b", "c"], []) == ["a", "b", "c"]
        assert _rrf_merge([], ["x", "y"]) == ["x", "y"]

    def test_returns_empty_for_two_empty_legs(self):
        assert _rrf_merge([], []) == []

    def test_deduplicates_ids_present_in_both_legs(self):
        fused = _rrf_merge(["a", "b"], ["b", "a"])
        assert sorted(fused) == ["a", "b"]

    def test_score_uses_rank_not_position_magnitude(self):
        # With k=60 the gap between rank 1 and rank 2 is small, so a chunk
        # ranked 2nd twice beats a chunk ranked 1st once.
        fused = _rrf_merge(["solo", "shared"], ["other", "shared"])
        assert fused[0] == "shared"


class TestQueryTerms:
    def test_drops_stopwords_and_short_tokens(self):
        terms = _query_terms("What are the payment terms in this agreement?")
        assert "the" not in terms
        assert "are" not in terms
        assert "payment" in terms
        assert "agreement" in terms

    def test_falls_back_when_query_is_all_stopwords(self):
        # A stopword-only query should still produce something to match on
        # rather than silently returning zero results.
        assert _query_terms("what is the") != []

    def test_deduplicates_repeated_words(self):
        terms = _query_terms("payment payment payment schedule")
        assert terms.count("payment") == 1

    def test_is_case_insensitive(self):
        assert _query_terms("PAYMENT Terms") == _query_terms("payment terms")


class TestChunking:
    def test_respects_page_boundaries_for_citations(self):
        pages = [(1, "alpha " * 400), (2, "beta " * 400)]
        chunks = chunk_pages(pages, chunk_tokens=100, overlap_tokens=10)
        assert {c.page_number for c in chunks} == {1, 2}

    def test_chunks_overlap_so_context_is_not_severed(self):
        pages = [(1, " ".join(f"w{i}" for i in range(400)))]
        chunks = chunk_pages(pages, chunk_tokens=100, overlap_tokens=20)
        assert len(chunks) > 1
        first_words = set(chunks[0].content.split())
        second_words = set(chunks[1].content.split())
        assert first_words & second_words, "consecutive chunks should overlap"

    def test_indexes_are_sequential(self):
        pages = [(1, " ".join(f"w{i}" for i in range(600)))]
        chunks = chunk_pages(pages, chunk_tokens=100, overlap_tokens=10)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_empty_input_produces_no_chunks(self):
        assert chunk_pages([]) == []
        assert chunk_pages([(1, "   \n  ")]) == []
