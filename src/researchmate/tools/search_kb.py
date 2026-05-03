from __future__ import annotations

from functools import lru_cache
from typing import Any

from google.adk.tools.function_tool import FunctionTool

from researchmate.services.documents import MetadataValue
from researchmate.services.retriever import KnowledgeRetriever

_MAX_TOOL_TOP_K = 10


@lru_cache(maxsize=1)
def get_default_retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever.from_settings()


def _clean_filters(filters: dict[str, str] | None) -> dict[str, MetadataValue] | None:
    if not filters:
        return None
    cleaned: dict[str, MetadataValue] = {}
    for key, value in filters.items():
        if value is None:
            continue
        stripped = str(value).strip()
        if not stripped:
            continue
        if key == "page" and stripped.isdigit():
            cleaned[key] = int(stripped)
        else:
            cleaned[key] = stripped
    return cleaned or None


def _has_grounding_signal(result: Any) -> bool:
    return result.sparse_rank is not None or (result.rerank_score or 0.0) > 0.0


def search_knowledge_base(
    query: str,
    filters: dict[str, str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search the local PDF knowledge base.

    Args:
        query: Natural language research question or retrieval query.
        filters: Optional exact metadata filters, for example {"paper_id": "paper_X"}.
        top_k: Number of chunks to return, clamped to 1..10.

    Returns:
        A JSON object with retrieved chunks. Each result includes a citation string
        like [source: paper_id, p.N]. Use those citation strings verbatim in answers.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"query": query, "count": 0, "results": [], "error": "query is empty"}
    safe_top_k = min(max(int(top_k), 1), _MAX_TOOL_TOP_K)
    retriever = get_default_retriever()
    raw_results = retriever.search(
        clean_query,
        filters=_clean_filters(filters),
        top_k=safe_top_k,
    )
    results = [result for result in raw_results if _has_grounding_signal(result)]
    warning = None
    if raw_results and not results:
        warning = "retrieved chunks had no lexical or rerank support; evidence is insufficient"
    return {
        "query": clean_query,
        "count": len(results),
        "results": [result.to_tool_payload() for result in results],
        "citation_rule": "Answer only from these chunks and cite as [source: paper_id, p.N].",
        "warning": warning,
    }


search_knowledge_base_tool = FunctionTool(search_knowledge_base)
