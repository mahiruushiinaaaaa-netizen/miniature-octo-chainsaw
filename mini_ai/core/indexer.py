"""
indexer.py – Simple local text indexing for documentation (RAG-lite).
"""
import os
import re
import math
from pathlib import Path
from typing import Any

class SimpleIndexer:
    def __init__(self, docs_dir: Path):
        self.docs_dir = Path(docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.index: dict[str, dict[str, int]] = {}  # word -> {doc_path: count}
        self.doc_lengths: dict[str, int] = {}
        self.num_docs = 0

    def add_document(self, name: str, content: str):
        """Add a document to the index."""
        path = self.docs_dir / f"{name}.txt"
        path.write_text(content, encoding="utf-8", errors="replace")
        
        words = self._tokenize(content)
        self.doc_lengths[str(path)] = len(words)
        self.num_docs += 1
        
        for word in set(words):
            if word not in self.index:
                self.index[word] = {}
            self.index[word][str(path)] = words.count(word)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Search documents using a simple BM25-like scoring."""
        query_words = self._tokenize(query)
        scores: dict[str, float] = {}
        
        avg_doc_len = sum(self.doc_lengths.values()) / max(1, self.num_docs)
        k1 = 1.5
        b = 0.75

        for word in query_words:
            if word not in self.index:
                continue
            
            # IDF
            df = len(self.index[word])
            idf = math.log((self.num_docs - df + 0.5) / (df + 0.5) + 1.0)
            
            for doc_path, freq in self.index[word].items():
                # BM25 term frequency normalization
                doc_len = self.doc_lengths[doc_path]
                tf = (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * doc_len / avg_doc_len))
                
                scores[doc_path] = scores.get(doc_path, 0.0) + idf * tf

        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        formatted = []
        for path, score in results:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            formatted.append({
                "path": path,
                "score": round(score, 3),
                "content": content[:1500]  # Return a snippet
            })
        return formatted

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase words."""
        return re.findall(r'\w+', text.lower())

def get_indexer(workspace: Path) -> SimpleIndexer:
    """Get or create the indexer for a workspace."""
    docs_dir = workspace / "scratch" / "docs"
    return SimpleIndexer(docs_dir)
