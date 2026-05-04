from __future__ import annotations

from functools import lru_cache
from typing import Any

from google.adk.tools.function_tool import FunctionTool

from researchmate.services.memory_service import ResearchMemoryService

_MAX_MEMORY_TOP_K = 10


@lru_cache(maxsize=1)
def get_default_memory_service() -> ResearchMemoryService:
    return ResearchMemoryService.from_settings()


def load_memory(
    query: str,
    user_id: str,
    category: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search long-term user memory.

    Args:
        query: Natural language query for relevant memories.
        user_id: User id whose memory should be searched.
        category: Optional memory category filter.
        top_k: Number of memory records to return, clamped to 1..10.
    """
    safe_top_k = min(max(int(top_k), 1), _MAX_MEMORY_TOP_K)
    service = get_default_memory_service()
    try:
        records = service.search_records(
            query=query,
            user_id=user_id,
            category=category,
            top_k=safe_top_k,
        )
    except ValueError as exc:
        return {"query": query, "count": 0, "results": [], "error": str(exc)}
    return {
        "query": query,
        "user_id": user_id,
        "category": category,
        "count": len(records),
        "results": [record.to_payload() for record in records],
    }


load_memory_tool = FunctionTool(load_memory)
