"""
Tests for TF-IDF fallback in context_injector.py

Validates:
- Pure Python TF-IDF using collections.Counter and math.log (no external deps)
- Tokenization on whitespace + punctuation
- Scoring chunks by sum of TF-IDF weights for query terms
- Returns top 1-5 snippets (≤1500 chars each)
- Completes within 500ms for 100KB files
- Each snippet includes source path, score (0.0-1.0 normalized), and char offset range
- Integration into enrich() as fallback when embeddings fail

Requirements: 2.3, 2.5
"""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mini_ai.core.context_injector import (
    _tokenize,
    _chunk_text,
    _compute_idf,
    _score_chunk,
    _tfidf_retrieve,
    ScoredSnippet,
)


class TestTokenize:
    """Test tokenization on whitespace + punctuation."""

    def test_basic_words(self):
        tokens = _tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_punctuation_split(self):
        tokens = _tokenize("hello, world! How are you?")
        assert tokens == ["hello", "world", "how", "are", "you"]

    def test_underscores_preserved(self):
        tokens = _tokenize("my_variable = some_function()")
        assert "my_variable" in tokens
        assert "some_function" in tokens

    def test_case_insensitive(self):
        tokens = _tokenize("Hello WORLD hElLo")
        assert tokens == ["hello", "world", "hello"]

    def test_numbers_included(self):
        tokens = _tokenize("version 3.14 and item42")
        assert "version" in tokens
        assert "3" in tokens
        assert "14" in tokens
        assert "item42" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_only_punctuation(self):
        assert _tokenize("!@#$%^&*()") == []


class TestChunkText:
    """Test content chunking with offset tracking."""

    def test_short_content_single_chunk(self):
        content = "short text"
        chunks = _chunk_text(content, chunk_size=1500, chunk_overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == ("short text", 0, 10)

    def test_multiple_chunks_with_overlap(self):
        content = "a" * 3000
        chunks = _chunk_text(content, chunk_size=1500, chunk_overlap=200)
        # Step = 1500 - 200 = 1300
        # Chunk 0: [0, 1500), Chunk 1: [1300, 2800), Chunk 2: [2600, 3000)
        assert len(chunks) == 3
        assert chunks[0][1] == 0
        assert chunks[0][2] == 1500
        assert chunks[1][1] == 1300
        assert chunks[1][2] == 2800

    def test_empty_content(self):
        assert _chunk_text("", 1500, 200) == []

    def test_offsets_are_correct(self):
        content = "0123456789" * 200  # 2000 chars
        chunks = _chunk_text(content, chunk_size=1500, chunk_overlap=200)
        for chunk_text, start, end in chunks:
            assert content[start:end] == chunk_text


class TestComputeIdf:
    """Test IDF computation."""

    def test_common_term_low_idf(self):
        # Term appears in all documents → low IDF (but still non-negative)
        docs = [["hello", "world"], ["hello", "python"], ["hello", "code"]]
        idf = _compute_idf(docs, {"hello"})
        # IDF = log(1 + 3 / (1 + 3)) = log(1.75) > 0 but small
        assert idf["hello"] > 0
        assert idf["hello"] < 1.0  # Low but positive

    def test_rare_term_high_idf(self):
        # Term appears in 1 of 10 documents → high IDF
        docs = [["rare"]] + [["common"] for _ in range(9)]
        idf = _compute_idf(docs, {"rare", "common"})
        assert idf["rare"] > idf["common"]

    def test_empty_docs(self):
        assert _compute_idf([], {"hello"}) == {}

    def test_missing_term(self):
        docs = [["hello", "world"]]
        idf = _compute_idf(docs, {"missing"})
        # IDF = log(1 + 1 / (1 + 0)) = log(2) ≈ 0.693
        assert idf["missing"] > 0


class TestScoreChunk:
    """Test chunk scoring by TF-IDF weights."""

    def test_matching_terms_positive_score(self):
        chunk_tokens = ["python", "code", "function", "python"]
        query_tokens = ["python"]
        idf = {"python": 1.0}
        score = _score_chunk(chunk_tokens, query_tokens, idf)
        # TF = 2/4 = 0.5, IDF = 1.0, score = 0.5
        assert abs(score - 0.5) < 0.001

    def test_no_matching_terms_zero_score(self):
        chunk_tokens = ["hello", "world"]
        query_tokens = ["python"]
        idf = {"python": 1.0}
        score = _score_chunk(chunk_tokens, query_tokens, idf)
        assert score == 0.0

    def test_empty_inputs(self):
        assert _score_chunk([], ["python"], {"python": 1.0}) == 0.0
        assert _score_chunk(["hello"], [], {"python": 1.0}) == 0.0


class TestTfidfRetrieve:
    """Test the full TF-IDF retrieval pipeline."""

    def test_returns_scored_snippets(self):
        content = (
            "Python is a programming language. " * 20
            + "Java is another language. " * 20
            + "Python has great libraries for data science. " * 20
        )
        snippets = _tfidf_retrieve("test.py", content, "Python programming")
        assert len(snippets) >= 1
        assert len(snippets) <= 5
        assert all(isinstance(s, ScoredSnippet) for s in snippets)

    def test_scores_normalized_0_to_1(self):
        content = "authentication login password " * 100 + "database query sql " * 100
        snippets = _tfidf_retrieve("auth.py", content, "authentication login")
        for s in snippets:
            assert 0.0 <= s.score <= 1.0

    def test_top_snippet_has_score_1(self):
        content = "authentication login password " * 100 + "database query sql " * 100
        snippets = _tfidf_retrieve("auth.py", content, "authentication login")
        if snippets:
            assert snippets[0].score == 1.0  # Top score normalized to 1.0

    def test_snippets_max_1500_chars(self):
        content = "x" * 100000  # 100KB of content
        snippets = _tfidf_retrieve("big.txt", content, "x")
        for s in snippets:
            assert len(s.content) <= 1500

    def test_returns_1_to_5_snippets(self):
        content = "function hello world code " * 500
        snippets = _tfidf_retrieve("code.py", content, "function code")
        assert 1 <= len(snippets) <= 5

    def test_source_path_included(self):
        content = "test content for path verification " * 50
        snippets = _tfidf_retrieve("src/main.py", content, "test content")
        for s in snippets:
            assert s.source_path == "src/main.py"

    def test_offset_range_valid(self):
        content = "hello world python code " * 200
        snippets = _tfidf_retrieve("test.py", content, "python code")
        for s in snippets:
            assert s.offset_start >= 0
            assert s.offset_end > s.offset_start
            assert s.offset_end <= len(content)

    def test_empty_content_returns_empty(self):
        assert _tfidf_retrieve("test.py", "", "query") == []

    def test_empty_query_returns_empty(self):
        assert _tfidf_retrieve("test.py", "some content", "") == []

    def test_no_matching_terms_returns_empty(self):
        content = "alpha beta gamma delta " * 100
        snippets = _tfidf_retrieve("test.py", content, "zzzzz xxxxx")
        assert snippets == []

    def test_performance_100kb_under_500ms(self):
        """TF-IDF must complete within 500ms for 100KB files."""
        # Generate ~100KB of realistic content
        content = ""
        words = ["function", "class", "import", "return", "variable",
                 "python", "code", "module", "test", "data", "file",
                 "system", "process", "error", "handler", "config"]
        import random
        rng = random.Random(42)
        while len(content) < 100_000:
            content += " ".join(rng.choices(words, k=20)) + "\n"

        start = time.perf_counter()
        snippets = _tfidf_retrieve("large_file.py", content, "function import module")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"TF-IDF took {elapsed:.3f}s, exceeds 500ms budget"
        assert len(snippets) >= 1
        assert len(snippets) <= 5

    def test_relevance_ordering(self):
        """Chunks with more query terms should score higher."""
        # Build content where one section has many query terms
        section_a = "python programming language code function " * 30
        section_b = "database sql query table index " * 30
        section_c = "python function decorator class method " * 30
        content = section_b + section_a + section_c

        snippets = _tfidf_retrieve(
            "test.py", content, "python function programming",
            chunk_size=500, chunk_overlap=50
        )
        # Top snippets should come from sections with python/function/programming
        assert len(snippets) >= 1
        # The top snippet should contain query terms
        top_content = snippets[0].content.lower()
        assert "python" in top_content or "function" in top_content


class TestContextInjectorIntegration:
    """Test TF-IDF integration into ContextInjector.enrich() as fallback."""

    def test_tfidf_fallback_when_embeddings_fail(self):
        """When embeddings are unavailable, TF-IDF should provide results."""
        from unittest.mock import MagicMock, patch

        # Mock config
        mock_config = MagicMock()
        mock_config.get.return_value = None

        # Mock RAGManager that fails (embeddings unavailable)
        mock_rag = MagicMock()
        mock_rag.retrieve_relevant_snippets.return_value = []
        mock_rag.chunk_size = 1500
        mock_rag.chunk_overlap = 200

        from mini_ai.core.context_injector import ContextInjector

        injector = ContextInjector(mock_config, rag_manager=mock_rag)

        content = "authentication login password security " * 100
        snippets = injector.enrich("auth.py", content, "authentication security")

        # Should get TF-IDF results (not raw fallback)
        assert len(snippets) >= 1
        assert len(snippets) <= 5
        # Scores should be normalized
        for s in snippets:
            assert 0.0 <= s.score <= 1.0
            assert len(s.content) <= 1500

    def test_raw_fallback_when_both_fail(self):
        """When both embedding and TF-IDF fail, return raw 3000 chars."""
        from unittest.mock import MagicMock

        mock_config = MagicMock()
        mock_rag = MagicMock()
        mock_rag.retrieve_relevant_snippets.return_value = []
        mock_rag.chunk_size = 1500
        mock_rag.chunk_overlap = 200

        from mini_ai.core.context_injector import ContextInjector

        injector = ContextInjector(mock_config, rag_manager=mock_rag)

        # Content with no matching terms for the query
        content = "aaaa bbbb cccc dddd " * 200
        snippets = injector.enrich("test.py", content, "zzzzz yyyyy")

        # TF-IDF returns empty (no matches), so raw fallback triggers
        assert len(snippets) == 1
        assert snippets[0].score == 0.0
        assert len(snippets[0].content) <= 3000


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
