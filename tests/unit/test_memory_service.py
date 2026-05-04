from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from google.adk.events import Event
from google.adk.sessions import Session
from google.genai import types

from researchmate.services.embeddings import HashingEmbeddingBackend
from researchmate.services.memory_service import ResearchMemoryService


def _service(tmp_path: Path) -> ResearchMemoryService:
    return ResearchMemoryService(
        persist_directory=tmp_path,
        collection_name="memory_records",
        embedding_backend=HashingEmbeddingBackend(),
        max_session_facts=4,
    )


def test_memory_crud_search_and_expiry(tmp_path: Path) -> None:
    service = _service(tmp_path)
    active = service.add_record(
        user_id="u1",
        category="research_direction",
        content="我的研究方向是多模态对齐。",
    )
    expired = service.add_record(
        user_id="u1",
        category="writing_style",
        content="写作偏好是短句。",
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )

    results = service.search_records(query="多模态", user_id="u1")

    assert results[0].id == active.id
    assert service.get_record(expired.id) is None
    assert service.expire_sweep() == 0

    updated = service.update_record(active.id, content="我的研究方向是视觉语言对齐。")
    assert updated.content == "我的研究方向是视觉语言对齐。"
    assert service.delete_record(active.id) is True


async def test_add_session_to_memory_extracts_explicit_facts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text="记住我的研究方向是检索增强生成。")],
    )
    event = Event(author="user", content=content)
    session = Session(
        id="s1",
        app_name="researchmate",
        user_id="u1",
        events=[event],
        state={},
        last_update_time=datetime.now(UTC).timestamp(),
    )

    await service.add_session_to_memory(session)

    records = service.list_records(user_id="u1", category="research_direction")
    assert len(records) == 1
    assert "检索增强生成" in records[0].content
    assert service.has_session_archive("s1") is True
