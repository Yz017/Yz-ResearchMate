from __future__ import annotations

import pytest
from pydantic import SecretStr

from researchmate.config import Settings
from researchmate.services.documents import MetadataValue, RetrievedChunk
from researchmate.services.query_expansion import (
    MultiQueryRetriever,
    QueryExpansionError,
    generate_hyde_documents,
    generate_query_variants,
    rrf_merge,
)


def _settings(*, has_key: bool = True) -> Settings:
    return Settings(
        DEEPSEEK_API_KEY=SecretStr("sk-test") if has_key else None,
        RAG_MULTI_QUERY_VARIANTS=3,
        RAG_MULTI_QUERY_POOL_K=5,
        RAG_HYDE_DOCS=1,
        RAG_HYDE_POOL_K=7,
        RAG_FINAL_K=2,
    )


def _chunk(chunk_id: str, *, score: float = 1.0, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        text=f"text for {chunk_id}",
        metadata={
            "paper_id": "paper",
            "title": "Paper",
            "page": page,
            "section": "Methods",
        },
        score=score,
    )


def test_rrf_merge_ranks_dedupes_and_truncates() -> None:
    merged = rrf_merge(
        [
            [_chunk("a"), _chunk("b")],
            [_chunk("b"), _chunk("c")],
        ],
        top_k=2,
    )

    assert [chunk.id for chunk in merged] == ["b", "a"]
    assert merged[0].score == pytest.approx((1.0 / 62) + (1.0 / 61))
    assert len({chunk.id for chunk in merged}) == len(merged)


def test_generate_variants_parsing() -> None:
    def fake_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        assert messages[0]["role"] == "user"
        assert "2 个语义等价" in messages[0]["content"]
        return """
        1. How does RAG retrieval work?

        2) how does RAG retrieval work?
        - What is RAG retrieval?
        3. Which documents discuss RAG retrieval?
        4. Extra variant that should be truncated.
        """

    variants = generate_query_variants(
        "What is RAG retrieval?",
        n_variants=2,
        settings=_settings(),
        llm_caller=fake_llm,
    )

    assert variants == [
        "How does RAG retrieval work?",
        "Which documents discuss RAG retrieval?",
    ]


def test_raise_when_key_missing() -> None:
    with pytest.raises(QueryExpansionError, match="DEEPSEEK_API_KEY"):
        generate_query_variants(
            "What is RAG?",
            n_variants=3,
            settings=_settings(has_key=False),
        )


def test_raise_when_llm_fails() -> None:
    def failing_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        raise RuntimeError("boom")

    with pytest.raises(QueryExpansionError, match="RuntimeError: boom"):
        generate_query_variants(
            "What is RAG?",
            n_variants=3,
            settings=_settings(),
            llm_caller=failing_llm,
        )

    class BaseRetriever:
        final_k = 2

        def search(
            self,
            query: str,
            *,
            filters: dict[str, MetadataValue] | None = None,
            top_k: int | None = None,
        ) -> list[RetrievedChunk]:
            return [_chunk(query)]

    def failing_provider(query: str) -> list[str]:
        raise QueryExpansionError("provider failed")

    retriever = MultiQueryRetriever(
        BaseRetriever(),
        settings=_settings(),
        variant_provider=failing_provider,
    )

    with pytest.raises(QueryExpansionError, match="provider failed"):
        retriever.search("What is RAG?")


def test_raise_when_variants_empty() -> None:
    def empty_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        return """
        1. What is RAG?
        - what is rag?
        """

    with pytest.raises(QueryExpansionError, match="no usable variants"):
        generate_query_variants(
            "What is RAG?",
            n_variants=3,
            settings=_settings(),
            llm_caller=empty_llm,
        )


def test_generate_hyde_parsing() -> None:
    def single_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        assert messages[0]["role"] == "user"
        assert "仅用于检索匹配" in messages[0]["content"]
        assert "中文问题→中文" in messages[0]["content"]
        return """
        HyDE describes a plausible answer for retrieval.

        It keeps the wording broad and textbook-like.
        """

    single = generate_hyde_documents(
        "What is HyDE?",
        n_docs=1,
        settings=_settings(),
        llm_caller=single_llm,
    )

    assert single == [
        "HyDE describes a plausible answer for retrieval. "
        "It keeps the wording broad and textbook-like."
    ]

    def multi_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        return """
        1. 第一段假想答案。
        它使用通用术语描述问题。

        2. 第二段假想答案。
        它避免编造具体细节。

        3. 多余段落应被截断。
        """

    documents = generate_hyde_documents(
        "什么是 HyDE?",
        n_docs=2,
        settings=_settings(),
        llm_caller=multi_llm,
    )

    assert documents == [
        "第一段假想答案。 它使用通用术语描述问题。",
        "第二段假想答案。 它避免编造具体细节。",
    ]


def test_hyde_raise_when_key_missing() -> None:
    with pytest.raises(QueryExpansionError, match="DEEPSEEK_API_KEY"):
        generate_hyde_documents(
            "What is HyDE?",
            n_docs=1,
            settings=_settings(has_key=False),
        )


def test_hyde_raise_when_llm_fails() -> None:
    def failing_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        raise RuntimeError("hyde boom")

    with pytest.raises(QueryExpansionError, match="RuntimeError: hyde boom"):
        generate_hyde_documents(
            "What is HyDE?",
            n_docs=1,
            settings=_settings(),
            llm_caller=failing_llm,
        )


def test_hyde_raise_when_empty() -> None:
    def empty_llm(messages: list[dict[str, str]], *, settings: Settings) -> str:
        return "\n\n   "

    with pytest.raises(QueryExpansionError, match="no usable documents"):
        generate_hyde_documents(
            "What is HyDE?",
            n_docs=1,
            settings=_settings(),
            llm_caller=empty_llm,
        )


def test_fusion_includes_hyde_pool() -> None:
    class BaseRetriever:
        final_k = 2

        def __init__(self) -> None:
            self.calls: list[tuple[str, int | None]] = []

        def search(
            self,
            query: str,
            *,
            filters: dict[str, MetadataValue] | None = None,
            top_k: int | None = None,
        ) -> list[RetrievedChunk]:
            self.calls.append((query, top_k))
            if "ideal HyDE document" in query:
                return [_chunk("hyde-hit")]
            return []

    base = BaseRetriever()
    retriever = MultiQueryRetriever(
        base,
        settings=_settings(),
        use_multi_query=False,
        use_hyde=True,
        hyde_provider=lambda query: ["ideal HyDE document"],
    )

    results = retriever.search("What is HyDE?", top_k=2)

    assert [chunk.id for chunk in results] == ["hyde-hit"]
    assert ("ideal HyDE document", 7) in base.calls


def test_hyde_disabled_skips_generation() -> None:
    class BaseRetriever:
        final_k = 1

        def search(
            self,
            query: str,
            *,
            filters: dict[str, MetadataValue] | None = None,
            top_k: int | None = None,
        ) -> list[RetrievedChunk]:
            return [_chunk("baseline")]

    def forbidden_hyde_provider(query: str) -> list[str]:
        raise AssertionError("HyDE provider should not be called")

    retriever = MultiQueryRetriever(
        BaseRetriever(),
        settings=_settings(),
        use_multi_query=False,
        use_hyde=False,
        hyde_provider=forbidden_hyde_provider,
    )

    results = retriever.search("What is HyDE?", top_k=1)

    assert [chunk.id for chunk in results] == ["baseline"]
