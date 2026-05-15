"""
context_injector.py – Decoupled context injection layer for mini_ai.

Provides a clean interface for enriching tool execution with relevant context
snippets, decoupling RAG strategy decisions from the executor module.

Interface:
    enrich(path, content, query) → list[ScoredSnippet]

Delegates to RAGManager for embedding-based retrieval, falls back to TF-IDF
when embeddings are unavailable, and returns raw content as a last resort.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .rag import RAGManager
from .logger import get_logger

logger = get_logger("context_injector")


@dataclass
class ScoredSnippet:
    """A scored context snippet with source metadata.

    Attributes:
        source_path: File path the snippet was extracted from.
        score: Relevance score between 0.0 and 1.0.
        content: The snippet text content.
        offset_start: Character offset where the snippet starts in the source file.
        offset_end: Character offset where the snippet ends in the source file.
    """
    source_path: str
    score: float
    content: str
    offset_start: int
    offset_end: int


class ContextInjector:
    """Decoupled context injection layer.

    Enriches file content with relevant context snippets using a tiered
    retrieval strategy:
      1. Embedding-based retrieval via RAGManager (best quality)
      2. TF-IDF keyword fallback (when embeddings unavailable)
      3. Raw content truncation (last resort, with warning)

    Usage:
        injector = ContextInjector(config)
        snippets = injector.enrich("src/main.py", file_content, "how does auth work?")
    """

    def __init__(self, config: Config, rag_manager: Optional[RAGManager] = None):
        """Initialize the context injector.

        Args:
            config: Application configuration.
            rag_manager: Optional RAGManager instance. If not provided, one
                         will be created from the config.
        """
        self.config = config
        self.rag = rag_manager or RAGManager(config)

    def enrich(self, path: str, content: str, query: str) -> List[ScoredSnippet]:
        """Enrich context by retrieving relevant snippets from file content.

        Attempts embedding-based retrieval first, falls back to TF-IDF,
        and returns raw content block as last resort.

        Args:
            path: Source file path.
            content: Full file content to search within.
            query: The query/goal to find relevant context for.

        Returns:
            List of ScoredSnippet objects sorted by relevance (highest first).
            Each snippet includes source path, score (0.0-1.0), content text,
            and character offset range within the source file.
        """
        if not content:
            return []

        # Strategy 1: Embedding-based retrieval via RAGManager
        snippets = self._try_embedding_retrieval(path, content, query)
        if snippets:
            return snippets

        # Strategy 2: TF-IDF keyword fallback (pure Python, no external deps)
        snippets = self._try_tfidf_fallback(path, content, query)
        if snippets:
            return snippets

        # Strategy 3: Raw content fallback (last resort)
        logger.warn(
            f"Both embedding and TF-IDF retrieval failed for '{path}'. "
            f"Returning raw content block (first 3000 chars).",
            operation="context_fallback",
            context={"path": path},
        )
        return self._raw_content_fallback(path, content)

    def _try_embedding_retrieval(
        self, path: str, content: str, query: str
    ) -> List[ScoredSnippet]:
        """Attempt embedding-based retrieval via RAGManager.

        Returns:
            List of ScoredSnippet if embeddings are available and produce results,
            empty list otherwise.
        """
        try:
            file_contents = {path: content}
            raw_snippets = self.rag.retrieve_relevant_snippets(
                query, file_contents, top_k=5
            )

            if not raw_snippets:
                return []

            # Convert RAGManager results to ScoredSnippet with offset calculation
            scored = []
            for snippet in raw_snippets:
                chunk_content = snippet.get("content", "")
                chunk_index = snippet.get("chunk_index", 0)
                raw_score = snippet.get("score", 0.0)

                # Clamp score to [0.0, 1.0]
                score = max(0.0, min(1.0, raw_score))

                # Calculate character offsets from chunk index
                offset_start, offset_end = self._calculate_offsets(
                    content, chunk_content, chunk_index
                )

                scored.append(ScoredSnippet(
                    source_path=snippet.get("path", path),
                    score=score,
                    content=chunk_content,
                    offset_start=offset_start,
                    offset_end=offset_end,
                ))

            return scored

        except Exception as e:
            logger.debug(
                f"Embedding retrieval failed for '{path}': {e}",
                operation="embedding_retrieval",
            )
            return []

    def _try_tfidf_fallback(
        self, path: str, content: str, query: str
    ) -> List[ScoredSnippet]:
        """TF-IDF keyword-based fallback retrieval.

        Pure Python implementation using collections.Counter and math.log.
        Tokenizes on whitespace + punctuation, scores chunks by sum of TF-IDF
        weights for query terms, returns top 1-5 snippets (≤1500 chars each).

        Designed to complete within 500ms for files up to 100KB.

        Returns:
            List of ScoredSnippet sorted by relevance (highest first),
            or empty list if content is too short to chunk meaningfully.
        """
        try:
            return _tfidf_retrieve(path, content, query, self.rag.chunk_size, self.rag.chunk_overlap)
        except Exception as e:
            logger.debug(
                f"TF-IDF fallback failed for '{path}': {e}",
                operation="tfidf_fallback",
            )
            return []

    def _raw_content_fallback(self, path: str, content: str) -> List[ScoredSnippet]:
        """Return first 3000 chars as a raw context block.

        Used as last resort when both embedding and TF-IDF retrieval fail.
        """
        truncated = content[:3000]
        return [ScoredSnippet(
            source_path=path,
            score=0.0,
            content=truncated,
            offset_start=0,
            offset_end=len(truncated),
        )]

    def _calculate_offsets(
        self, full_content: str, chunk_content: str, chunk_index: int
    ) -> tuple[int, int]:
        """Calculate character offsets for a chunk within the full content.

        Uses the RAGManager's chunk_size and chunk_overlap to compute the
        expected start position, then verifies by searching nearby.

        Args:
            full_content: The complete file content.
            chunk_content: The chunk text to locate.
            chunk_index: The chunk's index from RAGManager chunking.

        Returns:
            Tuple of (offset_start, offset_end) character positions.
        """
        chunk_size = self.rag.chunk_size
        chunk_overlap = self.rag.chunk_overlap
        step = chunk_size - chunk_overlap

        # Expected start based on chunking algorithm
        expected_start = chunk_index * step

        # Try exact match at expected position first
        if (expected_start < len(full_content) and
                full_content[expected_start:expected_start + len(chunk_content)] == chunk_content):
            return expected_start, expected_start + len(chunk_content)

        # Fallback: search for the chunk in the content
        found = full_content.find(chunk_content)
        if found >= 0:
            return found, found + len(chunk_content)

        # Last resort: use calculated position
        offset_start = min(expected_start, len(full_content))
        offset_end = min(offset_start + len(chunk_content), len(full_content))
        return offset_start, offset_end

# ---------------------------------------------------------------------------
# TF-IDF Fallback Implementation (Pure Python, no external dependencies)
# ---------------------------------------------------------------------------

# Regex pattern for tokenization: splits on whitespace and punctuation
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> List[str]:
    """Tokenize text on whitespace + punctuation boundaries.

    Extracts alphanumeric tokens (including underscores) and lowercases them.
    Fast enough for 100KB files within the 500ms budget.
    """
    return _TOKEN_PATTERN.findall(text.lower())


def _chunk_text(content: str, chunk_size: int, chunk_overlap: int) -> List[tuple]:
    """Split content into overlapping chunks with offset tracking.

    Returns list of (chunk_text, offset_start, offset_end) tuples.
    Each chunk is at most chunk_size characters.
    """
    if not content:
        return []

    chunks = []
    start = 0
    step = chunk_size - chunk_overlap

    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunk_text = content[start:end]
        chunks.append((chunk_text, start, end))
        start += step
        if start >= len(content):
            break

    return chunks


def _compute_idf(doc_tokens_list: List[List[str]], vocabulary: set) -> dict:
    """Compute IDF (Inverse Document Frequency) for each term in vocabulary.

    IDF(t) = log(1 + N / (1 + df(t)))
    where N = total number of documents, df(t) = number of docs containing term t.
    The +1 inside log ensures IDF is always non-negative.
    The +1 in denominator prevents division by zero.
    """
    n_docs = len(doc_tokens_list)
    if n_docs == 0:
        return {}

    # Count document frequency for each term
    df = Counter()
    for tokens in doc_tokens_list:
        # Use set to count each term once per document
        unique_tokens = set(tokens)
        for token in unique_tokens:
            if token in vocabulary:
                df[token] += 1

    # Compute IDF values (always non-negative due to log(1 + ...))
    idf = {}
    for term in vocabulary:
        idf[term] = math.log(1 + n_docs / (1 + df.get(term, 0)))

    return idf


def _score_chunk(chunk_tokens: List[str], query_tokens: List[str], idf: dict) -> float:
    """Score a chunk by sum of TF-IDF weights for query terms.

    TF-IDF(t, d) = TF(t, d) * IDF(t)
    where TF(t, d) = count of term t in document d / total terms in d

    The final score is the sum of TF-IDF values for all query terms present
    in the chunk.
    """
    if not chunk_tokens or not query_tokens:
        return 0.0

    # Compute term frequency for the chunk
    tf_counts = Counter(chunk_tokens)
    total_terms = len(chunk_tokens)

    score = 0.0
    for term in query_tokens:
        if term in tf_counts and term in idf:
            tf = tf_counts[term] / total_terms
            score += tf * idf[term]

    return score


def _tfidf_retrieve(
    path: str,
    content: str,
    query: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> List[ScoredSnippet]:
    """Perform TF-IDF based retrieval on file content.

    Pure Python implementation using collections.Counter and math.log.
    Returns top 1-5 snippets (≤1500 chars each) sorted by relevance.

    Args:
        path: Source file path.
        content: Full file content.
        query: Search query.
        chunk_size: Maximum characters per chunk (default 1500).
        chunk_overlap: Overlap between adjacent chunks (default 200).

    Returns:
        List of ScoredSnippet sorted by score descending.
        Returns empty list if no meaningful matches found.
    """
    if not content or not query:
        return []

    # Tokenize query
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Build vocabulary from query terms (only score against query terms)
    query_vocab = set(query_tokens)

    # Chunk the content
    chunks = _chunk_text(content, chunk_size, chunk_overlap)
    if not chunks:
        return []

    # Tokenize all chunks
    chunk_tokens_list = [_tokenize(chunk_text) for chunk_text, _, _ in chunks]

    # Compute IDF across all chunks (each chunk is a "document")
    idf = _compute_idf(chunk_tokens_list, query_vocab)

    # Score each chunk
    scored_chunks = []
    for i, (chunk_text, offset_start, offset_end) in enumerate(chunks):
        score = _score_chunk(chunk_tokens_list[i], query_tokens, idf)
        if score > 0.0:
            scored_chunks.append((score, chunk_text, offset_start, offset_end))

    if not scored_chunks:
        return []

    # Sort by score descending
    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    # Take top 5
    top_chunks = scored_chunks[:5]

    # Normalize scores to [0.0, 1.0] range
    max_score = top_chunks[0][0] if top_chunks else 1.0
    if max_score == 0.0:
        max_score = 1.0  # Prevent division by zero

    # Build ScoredSnippet results
    snippets = []
    for raw_score, chunk_text, offset_start, offset_end in top_chunks:
        normalized_score = raw_score / max_score
        # Ensure snippet is ≤1500 chars
        truncated_content = chunk_text[:1500]
        snippets.append(ScoredSnippet(
            source_path=path,
            score=round(normalized_score, 4),
            content=truncated_content,
            offset_start=offset_start,
            offset_end=offset_start + len(truncated_content),
        ))

    return snippets
