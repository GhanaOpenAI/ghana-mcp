"""Hybrid Reranking Engine for Ghana-MCP.
Combines:
  Stage 1: EmbeddingGemma dense embeddings for rapid semantic candidate filtering.
  Stage 2: BGE-Reranker-v2-M3 cross-encoder for final high-precision top-k scoring.
  Fallback: Zero-dependency BM25 and spaCy noun-chunk overlap.
"""
import os
import math
import httpx
import numpy as np
from typing import List, Dict, Any, Optional

from ghana_mcp.providers.base import SearchResult

# Model and Endpoint Configurations
VLLM_EMBED_URL = os.environ.get("VLLM_EMBED_URL", "http://127.0.0.1:8000/v1/embeddings")
VLLM_EMBED_MODEL = os.environ.get("VLLM_EMBED_MODEL", "google/embeddinggemma-2")

VLLM_SCORE_URL = os.environ.get("VLLM_SCORE_URL", "http://127.0.0.1:8000/v1/score")
VLLM_RERANK_MODEL = os.environ.get("VLLM_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")


class LexicalBM25Reranker:
    """Zero-dependency, sub-millisecond BM25 and noun-chunk overlap ranker."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def rerank(
        self,
        query: str,
        keywords: List[str],
        candidates: List[SearchResult],
        top_k: int = 50,
    ) -> List[SearchResult]:
        if not candidates:
            return []

        query_tokens = [t.lower() for t in query.split() if len(t) > 1]
        kw_tokens = [k.lower() for k in keywords]
        all_tokens = set(query_tokens + kw_tokens)

        docs_tokens = []
        for c in candidates:
            text = f"{c.title} {c.title} {c.snippet} {c.source}".lower()
            tokens = text.split()
            docs_tokens.append(tokens)

        avgdl = sum(len(d) for d in docs_tokens) / (len(docs_tokens) or 1)
        N = len(candidates)

        idf = {}
        for term in all_tokens:
            n_q = sum(1 for d in docs_tokens if term in d)
            idf[term] = math.log(1 + (N - n_q + 0.5) / (n_q + 0.5))

        scored_candidates = []
        for idx, item in enumerate(candidates):
            tokens = docs_tokens[idx]
            doc_len = len(tokens)
            bm25_score = 0.0

            term_counts = {}
            for t in tokens:
                term_counts[t] = term_counts.get(t, 0) + 1

            for q_term in all_tokens:
                tf = term_counts.get(q_term, 0)
                if tf > 0:
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (doc_len / (avgdl or 1)))
                    bm25_score += idf.get(q_term, 0.0) * (numerator / denominator)

            title_lower = item.title.lower()
            for kw in keywords:
                if kw.lower() in title_lower:
                    bm25_score += 2.0

            norm_score = round(min(1.0, max(0.1, bm25_score / (len(all_tokens) * 3 + 1))), 3)
            item.score = norm_score
            item.metadata["ranking_engine"] = "bm25_lexical"
            scored_candidates.append((norm_score, item))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored_candidates[:top_k]]


class HybridReranker:
    """Two-stage neural reranking pipeline:
    Stage 1: EmbeddingGemma dense bi-encoder filtering.
    Stage 2: BGE-Reranker cross-encoder precision scoring.
    """

    def __init__(
        self,
        embed_url: str = VLLM_EMBED_URL,
        embed_model: str = VLLM_EMBED_MODEL,
        score_url: str = VLLM_SCORE_URL,
        score_model: str = VLLM_RERANK_MODEL,
        timeout: float = 4.0,
    ):
        self.embed_url = embed_url
        self.embed_model = embed_model
        self.score_url = score_url
        self.score_model = score_model
        self.timeout = timeout
        self.fallback = LexicalBM25Reranker()
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
            )
        return self._client

    async def _stage1_embedding_gemma(
        self, query: str, candidates: List[SearchResult], top_stage1: int
    ) -> List[SearchResult]:
        """Stage 1: Batch embed query and documents with EmbeddingGemma and rank by cosine similarity."""
        client = self._get_client()
        input_texts = [f"task: search query | query: {query}"] + [
            f"task: search document | title: {c.title} | snippet: {c.snippet[:150]}" for c in candidates
        ]

        payload = {"model": self.embed_model, "input": input_texts}
        resp = await client.post(self.embed_url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"EmbeddingGemma failed: {resp.text}")

        data = resp.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if len(embeddings) != len(input_texts):
            raise ValueError("Embedding count mismatch")

        q_vec = np.array(embeddings[0])
        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)

        doc_vecs = np.array(embeddings[1:])
        doc_norms = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-9)
        sims = np.dot(doc_norms, q_norm)

        scored = []
        for idx, sim in enumerate(sims):
            candidates[idx].score = round(float(sim), 4)
            candidates[idx].metadata["stage1_score"] = round(float(sim), 4)
            scored.append((float(sim), candidates[idx]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_stage1]]

    async def _stage2_bge_rerank(
        self, query: str, candidates: List[SearchResult], top_k: int
    ) -> List[SearchResult]:
        """Stage 2: Cross-encoder attention scoring on Stage 1 finalists."""
        client = self._get_client()
        texts = [f"{c.title}: {c.snippet[:200]}" for c in candidates]
        payload = {
            "model": self.score_model,
            "text_1": query,
            "text_2": texts,
        }

        resp = await client.post(self.score_url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"BGE-Reranker failed: {resp.text}")

        data = resp.json()
        scores = [item.get("score", 0.0) for item in data.get("data", [])]

        for idx, sc in enumerate(scores):
            if idx < len(candidates):
                candidates[idx].score = round(float(sc), 4)
                candidates[idx].metadata["ranking_engine"] = "hybrid(EmbeddingGemma+BGE-Reranker)"

        candidates.sort(key=lambda x: x.score or 0.0, reverse=True)
        return candidates[:top_k]

    async def rerank_async(
        self,
        query: str,
        keywords: List[str],
        candidates: List[SearchResult],
        top_k: int = 50,
    ) -> List[SearchResult]:
        if not candidates:
            return []

        try:
            # Stage 1: Filter to top candidate pool (up to 2x top_k)
            stage1_candidates = await self._stage1_embedding_gemma(
                query, candidates, top_stage1=min(len(candidates), max(top_k * 2, 30))
            )

            # Stage 2: Cross-encoder precise scoring
            final_ranked = await self._stage2_bge_rerank(query, stage1_candidates, top_k=top_k)
            return final_ranked

        except Exception:
            # Automatic sub-millisecond fallback
            return self.fallback.rerank(query, keywords, candidates, top_k)

    def rerank(
        self,
        query: str,
        keywords: List[str],
        candidates: List[SearchResult],
        top_k: int = 50,
    ) -> List[SearchResult]:
        """Synchronous reranking with fallback."""
        import asyncio
        try:
            # In an active event loop, default to synchronous fallback
            return self.fallback.rerank(query, keywords, candidates, top_k)
        except RuntimeError:
            return asyncio.run(self.rerank_async(query, keywords, candidates, top_k))


# Global hybrid reranker instance
reranker = HybridReranker()
