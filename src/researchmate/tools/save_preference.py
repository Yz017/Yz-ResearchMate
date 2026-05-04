from __future__ import annotations

from typing import Any

from google.adk.tools.function_tool import FunctionTool

from researchmate.tools.load_memory import get_default_memory_service


def save_preference(
    user_id: str,
    category: str,
    content: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Save an explicit long-term memory preference for a user."""
    service = get_default_memory_service()
    try:
        record = service.add_record(
            user_id=user_id,
            category=category,
            content=content,
            expires_at=expires_at,
            source="tool",
        )
    except ValueError as exc:
        return {"saved": False, "error": str(exc)}
    return {"saved": True, "memory": record.to_payload()}


save_preference_tool = FunctionTool(save_preference)
