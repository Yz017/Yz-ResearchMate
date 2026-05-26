from __future__ import annotations

from researchmate.services.documents import KnowledgeChunk, RetrievedChunk


def test_citation_uses_section_for_first_page_single_page_documents() -> None:
    chunk = KnowledgeChunk.create(
        text="Method text",
        paper_id="doc_1",
        title="Doc",
        page=1,
        section="Methods",
        source_path="/tmp/doc.md",
        chunk_index=0,
    )

    assert chunk.citation == "[source: doc_1 · Methods]"


def test_citation_keeps_page_for_later_pages() -> None:
    chunk = KnowledgeChunk.create(
        text="Method text",
        paper_id="doc_1",
        title="Doc",
        page=5,
        section="Methods",
        source_path="/tmp/doc.pdf",
        chunk_index=0,
    )

    assert chunk.citation == "[source: doc_1, p.5]"


def test_retrieved_chunk_fallback_matches_citation_rule() -> None:
    retrieved = RetrievedChunk(
        id="x",
        text="body",
        metadata={"paper_id": "doc_1", "title": "Doc", "page": 1, "section": "Methods"},
        score=1.0,
    )

    assert retrieved.citation == "[source: doc_1 · Methods]"
