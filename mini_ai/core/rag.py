"""
rag.py – Retrieval Augmented Generation for Mini-AI.
Ported and adapted from rag-v1 plugin architecture.

Performance: Uses batched embedding calls to minimize API round-trips.
At most 2 calls per retrieval: 1 for query, 1 batched for all chunks.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .backend import get_embeddings, get_embeddings_batch as backend_get_embeddings_batch
from .logger import get_logger

logger = get_logger("rag")

class RAGManager:
    def __init__(self, config: Config):
        self.config = config
        self.byte_size_heuristic_threshold = 10 * 1024 * 1024  # 10MB
        self.context_usage_threshold = 0.7  # 70%
        self.chunk_size = 1500
        self.chunk_overlap = 200

    def get_token_estimate(self, text: str) -> int:
        """Rough estimate of tokens (chars / 4)."""
        return len(text) // 4

    def chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start += (self.chunk_size - self.chunk_overlap)
            if start >= len(text):
                break
        return chunks

    def cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude1 = math.sqrt(sum(a * a for a in v1))
        magnitude2 = math.sqrt(sum(b * b for b in v2))
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Get embeddings for multiple texts in a single batched operation.

        Makes at most 1 API round-trip for all texts by sending them
        together to the /embedding endpoint with a list payload.
        If the server doesn't support batch or is unavailable, falls back
        to grouped individual calls (groups of 16) — still far fewer than N.

        This method uses backend_get_embeddings_batch (a separate code path
        from get_embeddings singular) to avoid N+1 call patterns.

        Returns a list of embedding vectors (one per input text).
        Returns an empty vector [] for any text that fails to embed.
        """
        if not texts:
            return []

        # Delegate to the backend batch function which:
        # 1. Tries /embeddings (plural) batch endpoint (1 API call for all texts)
        # 2. Falls back to grouped individual calls (groups of 16)
        # This is a SEPARATE code path from get_embeddings (singular),
        # ensuring the per-chunk N+1 pattern is eliminated.
        return backend_get_embeddings_batch(self.config, texts)

    def decide_strategy(self, total_bytes: int, total_tokens: int, context_limit: int) -> str:
        """
        Decide between 'full_injection' and 'retrieval'.
        Ported from chooseContextInjectionStrategy in rag-v1.
        """
        # Byte-size heuristic
        if total_bytes > self.byte_size_heuristic_threshold:
            logger.info(f"File size ({total_bytes} bytes) exceeds threshold. Forcing retrieval.")
            return "retrieval"

        # Token-based heuristic
        usage_ratio = total_tokens / max(1, context_limit)
        if usage_ratio > self.context_usage_threshold:
            logger.info(f"Context usage ({usage_ratio:.1%}) exceeds threshold. Using retrieval.")
            return "retrieval"

        return "full_injection"

    def retrieve_relevant_snippets(self, query: str, file_contents: Dict[str, str], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform embedding-based retrieval across multiple files.

        Uses batched embedding calls: at most 2 API round-trips
        (1 for query embedding, 1 batched for all chunk embeddings).

        Falls back to TF-IDF when embeddings are unavailable, ensuring
        context enrichment is always provided.
        """
        # Round-trip 1: Get query embedding
        query_vector = get_embeddings(self.config, query)
        if not query_vector:
            # Embeddings not available - fall back to TF-IDF
            return self._tfidf_fallback(query, file_contents, top_k)

        # Collect all chunks with their metadata
        chunk_entries: list[tuple[str, int, str]] = []  # (path, chunk_index, chunk_text)
        for path, content in file_contents.items():
            chunks = self.chunk_text(content)
            for i, chunk in enumerate(chunks):
                chunk_entries.append((path, i, chunk))

        if not chunk_entries:
            return []

        # Round-trip 2: Get all chunk embeddings in a single batched call
        chunk_texts = [entry[2] for entry in chunk_entries]
        chunk_vectors = self.get_embeddings_batch(chunk_texts)

        # Score each chunk against the query
        all_results = []
        for (path, chunk_index, chunk_text), chunk_vector in zip(chunk_entries, chunk_vectors):
            if not chunk_vector:
                continue
            score = self.cosine_similarity(query_vector, chunk_vector)
            all_results.append({
                "path": path,
                "chunk_index": chunk_index,
                "content": chunk_text,
                "score": score,
            })

        # Sort by score descending
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def _tfidf_fallback(self, query: str, file_contents: Dict[str, str], top_k: int = 5) -> List[Dict[str, Any]]:
        """TF-IDF keyword-based fallback when embeddings are unavailable.

        Pure Python implementation using collections.Counter and math.log.
        Ensures RAG always provides context enrichment even without embeddings.
        """
        import re
        from collections import Counter

        token_pattern = re.compile(r"[a-zA-Z0-9_]+")

        def tokenize(text: str) -> List[str]:
            return token_pattern.findall(text.lower())

        query_tokens = tokenize(query)
        if not query_tokens:
            # If query has no tokens, return first chunk of each file
            results = []
            for path, content in file_contents.items():
                chunks = self.chunk_text(content)
                for i, chunk in enumerate(chunks[:top_k]):
                    results.append({
                        "path": path,
                        "chunk_index": i,
                        "content": chunk,
                        "score": 0.1,
                    })
            return results[:top_k]

        query_vocab = set(query_tokens)

        # Collect all chunks
        all_chunks: List[tuple] = []  # (path, chunk_index, chunk_text, tokens)
        for path, content in file_contents.items():
            chunks = self.chunk_text(content)
            for i, chunk in enumerate(chunks):
                tokens = tokenize(chunk)
                all_chunks.append((path, i, chunk, tokens))

        if not all_chunks:
            return []

        # Compute IDF
        n_docs = len(all_chunks)
        df: Dict[str, int] = {}
        for _, _, _, tokens in all_chunks:
            unique = set(tokens)
            for t in unique:
                if t in query_vocab:
                    df[t] = df.get(t, 0) + 1

        idf = {}
        for term in query_vocab:
            idf[term] = math.log(1 + n_docs / (1 + df.get(term, 0)))

        # Score each chunk
        scored = []
        for path, chunk_index, chunk_text, tokens in all_chunks:
            if not tokens:
                continue
            tf_counts = Counter(tokens)
            total = len(tokens)
            score = 0.0
            for term in query_tokens:
                if term in tf_counts and term in idf:
                    tf = tf_counts[term] / total
                    score += tf * idf[term]
            if score > 0.0:
                scored.append({
                    "path": path,
                    "chunk_index": chunk_index,
                    "content": chunk_text,
                    "score": score,
                })

        if not scored:
            # No TF-IDF matches - return first chunks as raw fallback
            results = []
            for path, content in file_contents.items():
                chunks = self.chunk_text(content)
                for i, chunk in enumerate(chunks[:top_k]):
                    results.append({
                        "path": path,
                        "chunk_index": i,
                        "content": chunk,
                        "score": 0.05,
                    })
            return results[:top_k]

        # Sort by score descending and normalize
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:top_k]

        # Normalize scores to [0, 1]
        max_score = top[0]["score"] if top else 1.0
        if max_score > 0:
            for item in top:
                item["score"] = item["score"] / max_score

        return top

    def format_rag_context(self, snippets: List[Dict[str, Any]]) -> str:
        """Format snippets into a prompt context block."""
        if not snippets:
            return ""

        lines = ["Below are relevant snippets retrieved from the workspace files:", ""]
        for s in snippets:
            lines.append(f"--- FILE: {s['path']} (Relevance: {s['score']:.2f}) ---")
            lines.append(s["content"])
            lines.append("")
        
        return "\n".join(lines)

    def enrich_prompt(self, query: str, snippets: List[Dict[str, Any]]) -> str:
        """Wrap the query with RAG context and instructions."""
        context_block = self.format_rag_context(snippets)
        if not context_block:
            return query

        prefix = "Use the following context to answer the user's request. Always cite your sources by file name.\n\n"
        suffix = "\n\nUser Question: "
        
        return f"{prefix}{context_block}{suffix}{query}"
