from __future__ import annotations

from pathlib import Path

from researchmate.services.documents import KnowledgeChunk
from researchmate.services.embeddings import HashingEmbeddingBackend, LexicalReranker
from researchmate.services.retriever import KnowledgeRetriever
from researchmate.services.vector_store import KnowledgeVectorStore


def _chunk(
    *,
    text: str,
    paper_id: str,
    page: int,
    index: int,
) -> KnowledgeChunk:
    return KnowledgeChunk.create(
        text=text,
        paper_id=paper_id,
        title=paper_id.replace("_", " ").title(),
        page=page,
        section="Methods",
        source_path=f"/tmp/{paper_id}.pdf",
        chunk_index=index,
    )


def test_retriever_returns_grounded_chunk_with_citation(tmp_path: Path) -> None:
    store = KnowledgeVectorStore(persist_directory=tmp_path, collection_name="kb_chunks")
    embedder = HashingEmbeddingBackend()
    chunks = [
        _chunk(
            text=(
                "The RAG pipeline retrieves local PDF chunks and produces "
                "grounded citation answers."
            ),
            paper_id="rag_paper",
            page=3,
            index=0,
        ),
        _chunk(
            text="The baseline optimizer uses a cosine learning rate schedule for image models.",
            paper_id="optimizer_paper",
            page=7,
            index=1,
        ),
        _chunk(
            text=(
                "Weekly reports should summarize reading progress, open questions, and next tasks."
            ),
            paper_id="weekly_note",
            page=1,
            index=2,
        ),
    ]
    store.upsert_chunks(
        chunks,
        embedder.encode([chunk.text for chunk in chunks]),
        embedding_model=embedder.model_id,
    )
    retriever = KnowledgeRetriever(
        store=store,
        embedding_backend=embedder,
        reranker=LexicalReranker(),
        dense_k=3,
        sparse_k=3,
        final_k=2,
    )

    results = retriever.search("local PDF grounded citation retrieval", top_k=2)

    assert results
    assert results[0].paper_id == "rag_paper"
    assert results[0].citation == "[source: rag_paper, p.3]"
    assert "grounded citation" in results[0].text


def test_retriever_supports_paper_id_filter(tmp_path: Path) -> None:
    store = KnowledgeVectorStore(persist_directory=tmp_path, collection_name="kb_chunks")
    embedder = HashingEmbeddingBackend()
    chunks = [
        _chunk(
            text="Memory records save writing preferences and advisor requirements.",
            paper_id="memory_paper",
            page=2,
            index=0,
        ),
        _chunk(
            text="RAG records save source paths, page numbers, and citations.",
            paper_id="rag_paper",
            page=4,
            index=1,
        ),
    ]
    store.upsert_chunks(
        chunks,
        embedder.encode([chunk.text for chunk in chunks]),
        embedding_model=embedder.model_id,
    )
    retriever = KnowledgeRetriever(
        store=store,
        embedding_backend=embedder,
        reranker=LexicalReranker(),
        dense_k=2,
        sparse_k=2,
        final_k=1,
    )

    results = retriever.search(
        "save citations",
        filters={"paper_id": "rag_paper"},
        top_k=1,
    )

    assert len(results) == 1
    assert results[0].paper_id == "rag_paper"
