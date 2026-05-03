from __future__ import annotations

from dataclasses import dataclass

from researchmate.config import Settings, get_settings
from researchmate.services.documents import MetadataValue, RetrievedChunk
from researchmate.services.embeddings import (
    EmbeddingBackend,
    LexicalReranker,
    Reranker,
    create_embedding_backend,
    create_reranker,
)
from researchmate.services.vector_store import KnowledgeVectorStore


@dataclass(slots=True)
class _Candidate:
    id: str
    text: str
    metadata: dict[str, MetadataValue]
    rrf_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None


class KnowledgeRetriever:
    """Hybrid dense + lexical retriever with RRF fusion and optional reranking."""

    def __init__(
        self,
        *,
        store: KnowledgeVectorStore,
        embedding_backend: EmbeddingBackend,
        reranker: Reranker | None = None,
        dense_k: int = 20,
        sparse_k: int = 20,
        final_k: int = 5,
        rrf_k: int = 60,
    ) -> None:
        self.store = store
        self.embedding_backend = embedding_backend
        self.reranker = reranker or LexicalReranker()
        self.dense_k = dense_k
        self.sparse_k = sparse_k
        self.final_k = final_k
        self.rrf_k = rrf_k

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KnowledgeRetriever:
        settings = settings or get_settings()
        return cls(
            store=KnowledgeVectorStore.from_settings(settings),
            embedding_backend=create_embedding_backend(settings),
            reranker=create_reranker(settings),
            dense_k=settings.rag_dense_k,
            sparse_k=settings.rag_sparse_k,
            final_k=settings.rag_final_k,
        )

    def search(
        self,
        query: str,
        *,
        filters: dict[str, MetadataValue] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        clean_query = query.strip()
        if not clean_query:
            return []
        final_k = top_k or self.final_k
        dense_results = self._dense_search(clean_query, filters=filters)
        sparse_results = self._sparse_search(clean_query, filters=filters)
        candidates = self._fuse(dense_results, sparse_results)
        if not candidates:
            return []
        self._rerank(clean_query, candidates)
        candidates.sort(
            key=lambda candidate: (
                candidate.rerank_score if candidate.rerank_score is not None else 0.0,
                candidate.rrf_score,
            ),
            reverse=True,
        )
        return [
            RetrievedChunk(
                id=candidate.id,
                text=candidate.text,
                metadata=candidate.metadata,
                score=candidate.rrf_score,
                dense_rank=candidate.dense_rank,
                sparse_rank=candidate.sparse_rank,
                rerank_score=candidate.rerank_score,
            )
            for candidate in candidates[:final_k]
        ]

    def _dense_search(
        self,
        query: str,
        *,
        filters: dict[str, MetadataValue] | None,
    ) -> list[RetrievedChunk]:
        try:
            query_embedding = self.embedding_backend.encode([query])[0]
            return self.store.query_dense(
                query_embedding,
                top_k=self.dense_k,
                filters=filters,
            )
        except Exception:
            return []

    def _sparse_search(
        self,
        query: str,
        *,
        filters: dict[str, MetadataValue] | None,
    ) -> list[RetrievedChunk]:
        candidates = self.store.list_chunks(filters=filters)
        if not candidates:
            return []
        scorer = LexicalReranker()
        scores = scorer.score(query, [candidate.text for candidate in candidates])
        ranked: list[RetrievedChunk] = []
        for candidate, score in zip(candidates, scores, strict=True):
            if score <= 0.0:
                continue
            ranked.append(
                RetrievedChunk(
                    id=candidate.id,
                    text=candidate.text,
                    metadata=candidate.metadata,
                    score=score,
                )
            )
        ranked.sort(key=lambda chunk: chunk.score, reverse=True)
        return [
            RetrievedChunk(
                id=chunk.id,
                text=chunk.text,
                metadata=chunk.metadata,
                score=chunk.score,
                sparse_rank=index + 1,
            )
            for index, chunk in enumerate(ranked[: self.sparse_k])
        ]

    def _fuse(
        self,
        dense_results: list[RetrievedChunk],
        sparse_results: list[RetrievedChunk],
    ) -> list[_Candidate]:
        candidates: dict[str, _Candidate] = {}

        def add_results(results: list[RetrievedChunk], *, is_dense: bool) -> None:
            for rank, chunk in enumerate(results, start=1):
                candidate = candidates.get(chunk.id)
                if candidate is None:
                    candidate = _Candidate(
                        id=chunk.id,
                        text=chunk.text,
                        metadata=chunk.metadata,
                    )
                    candidates[chunk.id] = candidate
                candidate.rrf_score += 1.0 / (self.rrf_k + rank)
                if is_dense:
                    candidate.dense_rank = rank
                else:
                    candidate.sparse_rank = rank

        add_results(dense_results, is_dense=True)
        add_results(sparse_results, is_dense=False)
        return list(candidates.values())

    def _rerank(self, query: str, candidates: list[_Candidate]) -> None:
        scores = self.reranker.score(query, [candidate.text for candidate in candidates])
        for candidate, score in zip(candidates, scores, strict=False):
            candidate.rerank_score = float(score)
