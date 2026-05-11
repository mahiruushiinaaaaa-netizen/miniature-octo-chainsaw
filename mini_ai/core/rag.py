"""
rag.py – Retrieval Augmented Generation for Mini-AI.
Ported and adapted from rag-v1 plugin architecture.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .backend import get_embeddings
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
        Returns empty list if embeddings unavailable (graceful fallback).
        """
        query_vector = get_embeddings(self.config, query)
        if not query_vector:
            # Embeddings not available - return empty to allow fallback to full injection
            return []

        all_results = []

        for path, content in file_contents.items():
            chunks = self.chunk_text(content)
            for i, chunk in enumerate(chunks):
                chunk_vector = get_embeddings(self.config, chunk)
                if not chunk_vector:
                    continue
                
                score = self.cosine_similarity(query_vector, chunk_vector)
                all_results.append({
                    "path": path,
                    "chunk_index": i,
                    "content": chunk,
                    "score": score
                })

        # Sort by score descending
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

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
