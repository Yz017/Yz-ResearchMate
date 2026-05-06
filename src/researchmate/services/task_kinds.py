from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

from researchmate.config import Settings
from researchmate.services.job_runner import JobContext, JobHandler, JobRunner
from researchmate.services.knowledge_base import KnowledgeBaseService
from researchmate.services.memory_service import MemoryRecord, ResearchMemoryService
from researchmate.services.oss_client import OssClient
from researchmate.services.paper_repo import PaperRecord, PaperRepository, infer_year
from researchmate.services.retriever import KnowledgeRetriever
from researchmate.tools.arxiv_search import search_arxiv
from researchmate.tools.s2_search import search_semantic_scholar

_TITLE_WORD_RE = re.compile(r"[^a-z0-9]+")
_MAX_WEEKLY_PAPERS = 20


class WeeklyReportParams(BaseModel):
    week_start: date | None = Field(
        default=None,
        description="Monday date for the report week. Defaults to the current local week.",
    )
    paper_count: int = Field(default=5, ge=1, le=_MAX_WEEKLY_PAPERS)
    focus_keywords: list[str] = Field(default_factory=list)
    include_external: bool = Field(
        default=False,
        description="When true, gather extra candidates from arXiv and Semantic Scholar.",
    )
    timeout_seconds: float = Field(default=600.0, ge=10.0, le=3600.0)


@dataclass(frozen=True, slots=True)
class TaskKind:
    kind: str
    description: str
    params_schema: type[BaseModel]


@dataclass(slots=True)
class _Candidate:
    source: str
    paper_id: str
    title: str
    authors: list[str]
    venue: str
    year: int | None
    tags: list[str]
    doi: str
    arxiv_id: str
    url: str
    pdf_url: str
    citation: str
    summary: str
    score: float = 0.0
    local: bool = False


_TASK_KINDS: dict[str, TaskKind] = {
    "weekly_report": TaskKind(
        kind="weekly_report",
        description=(
            "Generate a Markdown weekly reading report from local papers "
            "and optional external search."
        ),
        params_schema=WeeklyReportParams,
    )
}


def normalize_task_kind(kind: str) -> str:
    return kind.strip().lower().replace("-", "_")


def registered_task_kinds() -> list[TaskKind]:
    return list(_TASK_KINDS.values())


def validate_task_params(kind: str, params: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_task_kind(kind)
    task_kind = _TASK_KINDS.get(normalized)
    if task_kind is None:
        msg = f"unknown task kind: {kind}"
        raise ValueError(msg)
    model = task_kind.params_schema.model_validate(params or {})
    return model.model_dump(mode="json")


def register_task_handlers(
    runner: JobRunner,
    *,
    settings: Settings,
    memory_service: ResearchMemoryService,
) -> None:
    runner.register_handler(
        "weekly_report",
        _build_weekly_report_handler(settings=settings, memory_service=memory_service),
    )


def _build_weekly_report_handler(
    *,
    settings: Settings,
    memory_service: ResearchMemoryService,
) -> JobHandler:
    async def handle_weekly_report(context: JobContext) -> dict[str, Any]:
        params = WeeklyReportParams.model_validate(context.params)
        return await asyncio.wait_for(
            _run_weekly_report(
                context=context,
                params=params,
                settings=settings,
                memory_service=memory_service,
            ),
            timeout=params.timeout_seconds,
        )

    return handle_weekly_report


async def _run_weekly_report(
    *,
    context: JobContext,
    params: WeeklyReportParams,
    settings: Settings,
    memory_service: ResearchMemoryService,
) -> dict[str, Any]:
    week_start = params.week_start or _current_week_start()
    week_end = week_start + timedelta(days=6)
    keywords = [item.strip() for item in params.focus_keywords if item.strip()]
    await context.progress(5.0, "weekly_report: loading local papers")
    repo = PaperRepository.from_settings(settings)
    local_papers = await asyncio.to_thread(
        _load_local_papers,
        settings,
        repo,
        context.user_id,
        keywords,
        params.paper_count,
    )

    await context.progress(25.0, "weekly_report: gathering external candidates")
    external_candidates: list[_Candidate] = []
    if params.include_external:
        external_candidates = await asyncio.to_thread(
            _search_external_candidates,
            keywords,
            params.paper_count,
        )

    await context.progress(40.0, "weekly_report: ranking candidates")
    memories = memory_service.list_records(user_id=context.user_id, limit=20)
    memory_text = " ".join(record.content for record in memories)
    candidates = _deduplicate_candidates([*local_papers, *external_candidates])
    ranked = _rank_candidates(
        candidates,
        keywords=keywords,
        memory_text=memory_text,
    )[: params.paper_count]

    await context.progress(65.0, "weekly_report: summarizing papers")
    summaries = await asyncio.to_thread(_summarize_local_context, settings, ranked, keywords)

    await context.progress(82.0, "weekly_report: synthesizing markdown")
    report_markdown = _render_weekly_report(
        user_id=context.user_id,
        week_start=week_start,
        week_end=week_end,
        keywords=keywords,
        memories=memories,
        candidates=ranked,
        summaries=summaries,
    )

    await context.progress(92.0, "weekly_report: uploading artifact")
    artifact_key = await asyncio.to_thread(
        _persist_report,
        settings,
        context.user_id,
        context.job_id,
        week_start,
        report_markdown,
    )
    artifact_url = OssClient.from_settings(settings).sign_url(artifact_key)
    memory_service.add_record(
        user_id=context.user_id,
        category="recent_tasks",
        content=(
            f"Weekly report job {context.job_id} completed for {week_start.isoformat()} "
            f"with {len(ranked)} paper(s). Artifact: {artifact_key}."
        ),
        source="job",
    )
    return {
        "artifact_oss_key": artifact_key,
        "artifact_url": artifact_url,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "paper_count": len(ranked),
        "papers": [
            {
                "id": candidate.paper_id,
                "title": candidate.title,
                "authors": candidate.authors,
                "citation": candidate.citation,
                "source": candidate.source,
            }
            for candidate in ranked
        ],
        "report_preview": report_markdown[:1000],
    }


def _current_week_start() -> date:
    today = datetime.now(UTC).date()
    return today - timedelta(days=today.weekday())


def _load_local_papers(
    settings: Settings,
    repo: PaperRepository,
    user_id: str,
    keywords: list[str],
    paper_count: int,
) -> list[_Candidate]:
    papers = repo.list_papers(
        user_id=user_id,
        q=" ".join(keywords) if keywords else None,
        limit=max(paper_count * 3, paper_count),
    )
    if not papers:
        kb_service = KnowledgeBaseService.from_settings(settings)
        documents = kb_service.list_documents(user_id=user_id, limit=max(paper_count * 3, 10))
        for document in documents:
            papers.append(repo.upsert_ingested_document(document))
    return [_candidate_from_record(record) for record in papers]


def _candidate_from_record(record: PaperRecord) -> _Candidate:
    return _Candidate(
        source="local",
        paper_id=record.id,
        title=record.title,
        authors=record.authors or [],
        venue=record.venue,
        year=record.year,
        tags=record.tags or [],
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        url="",
        pdf_url=record.oss_path,
        citation=f"[source: {record.id}, p.?]",
        summary="",
        local=True,
    )


def _search_external_candidates(keywords: list[str], paper_count: int) -> list[_Candidate]:
    query = " ".join(keywords) if keywords else "retrieval augmented generation research assistant"
    limit = min(max(paper_count, 1), 10)
    candidates: list[_Candidate] = []
    for result in search_arxiv(query, max_results=limit).get("results", []):
        if isinstance(result, dict):
            candidates.append(_candidate_from_external("arxiv", result))
    for result in search_semantic_scholar(query, max_results=limit).get("results", []):
        if isinstance(result, dict):
            candidates.append(_candidate_from_external("semantic_scholar", result))
    return candidates


def _candidate_from_external(source: str, result: dict[str, Any]) -> _Candidate:
    paper_id = str(
        result.get("doi")
        or result.get("arxiv_id")
        or result.get("paper_id")
        or result.get("title")
        or "external"
    )
    title = str(result.get("title") or "Untitled external paper")
    authors = [str(author) for author in result.get("authors", []) if str(author).strip()]
    return _Candidate(
        source=source,
        paper_id=paper_id,
        title=title,
        authors=authors,
        venue=str(result.get("venue") or result.get("primary_category") or source),
        year=infer_year(result.get("year"), result.get("published"), result.get("updated")),
        tags=[source],
        doi=str(result.get("doi") or ""),
        arxiv_id=str(result.get("arxiv_id") or ""),
        url=str(result.get("url") or result.get("entry_url") or ""),
        pdf_url=str(result.get("pdf_url") or ""),
        citation=f"[external: {source}:{paper_id}]",
        summary=str(result.get("external_content") or ""),
    )


def _deduplicate_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    unique: list[_Candidate] = []
    doi_seen: set[str] = set()
    for candidate in candidates:
        doi_key = candidate.doi.lower().strip()
        if doi_key:
            if doi_key in doi_seen:
                continue
            doi_seen.add(doi_key)
            unique.append(candidate)
            continue
        title_key = _normalize_title(candidate.title)
        if any(_same_title(title_key, _normalize_title(existing.title)) for existing in unique):
            continue
        unique.append(candidate)
    return unique


def _normalize_title(title: str) -> str:
    return _TITLE_WORD_RE.sub(" ", title.lower()).strip()


def _same_title(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.92


def _rank_candidates(
    candidates: list[_Candidate],
    *,
    keywords: list[str],
    memory_text: str,
) -> list[_Candidate]:
    scored: list[_Candidate] = []
    memory_lower = memory_text.lower()
    for candidate in candidates:
        haystack = " ".join(
            [candidate.title, candidate.venue, " ".join(candidate.tags), candidate.summary]
        ).lower()
        score = 1.0
        if candidate.local:
            score += 2.0
        for keyword in keywords:
            if keyword.lower() in haystack:
                score += 1.5
        for token in _normalize_title(memory_lower).split():
            if len(token) >= 4 and token in haystack:
                score += 0.1
        scored.append(
            _Candidate(
                source=candidate.source,
                paper_id=candidate.paper_id,
                title=candidate.title,
                authors=candidate.authors,
                venue=candidate.venue,
                year=candidate.year,
                tags=candidate.tags,
                doi=candidate.doi,
                arxiv_id=candidate.arxiv_id,
                url=candidate.url,
                pdf_url=candidate.pdf_url,
                citation=candidate.citation,
                summary=candidate.summary,
                score=score,
                local=candidate.local,
            )
        )
    scored.sort(key=lambda item: (item.score, item.year or 0, item.title), reverse=True)
    return scored


def _summarize_local_context(
    settings: Settings,
    candidates: list[_Candidate],
    keywords: list[str],
) -> dict[str, dict[str, str]]:
    retriever = KnowledgeRetriever.from_settings(settings)
    summaries: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        if not candidate.local:
            summaries[candidate.paper_id] = {
                "summary": _strip_external_tags(candidate.summary)[:600]
                or "External metadata candidate; full text has not been ingested.",
                "citation": candidate.citation,
            }
            continue
        query = " ".join([candidate.title, *keywords]).strip() or candidate.title
        results = retriever.search(
            query,
            filters={"paper_id": candidate.paper_id},
            top_k=2,
        )
        if results:
            best = results[0]
            summaries[candidate.paper_id] = {
                "summary": best.text[:700],
                "citation": best.citation,
            }
        else:
            summaries[candidate.paper_id] = {
                "summary": "Local metadata is available, but no strong chunk was retrieved.",
                "citation": candidate.citation,
            }
    return summaries


def _strip_external_tags(text: str) -> str:
    return (
        text.replace('<external_content source="arxiv">', "")
        .replace('<external_content source="semantic_scholar">', "")
        .replace("</external_content>", "")
        .strip()
    )


def _render_weekly_report(
    *,
    user_id: str,
    week_start: date,
    week_end: date,
    keywords: list[str],
    memories: list[MemoryRecord],
    candidates: list[_Candidate],
    summaries: dict[str, dict[str, str]],
) -> str:
    focus = ", ".join(keywords) if keywords else "general research reading"
    memory_lines = [
        f"- {record.category}: {record.content}"
        for record in memories[:5]
        if getattr(record, "content", "")
    ]
    candidate_lines: list[str] = []
    note_lines: list[str] = []
    citation_lines: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        summary = summaries.get(candidate.paper_id, {})
        citation = summary.get("citation") or candidate.citation
        authors = ", ".join(candidate.authors) if candidate.authors else "Unknown"
        year = f", {candidate.year}" if candidate.year else ""
        venue = f", {candidate.venue}" if candidate.venue else ""
        candidate_lines.append(
            f"{index}. **{candidate.title}** ({candidate.source}{year}{venue})\n"
            f"   Authors: {authors}\n"
            f"   Citation: {citation}"
        )
        note_lines.append(
            f"### {index}. {candidate.title}\n\n"
            f"- TL;DR: {_single_line(summary.get('summary', candidate.summary), 320)}\n"
            f"- Why it matters this week: Matches `{focus}` and current ResearchMate context.\n"
            f"- Evidence: {citation}"
        )
        citation_lines.append(f"- {citation} {candidate.title}")
    if not candidate_lines:
        candidate_lines.append("No candidate papers were found for this week.")
        note_lines.append(
            "### No Papers Found\n\n"
            "- TL;DR: Ingest local PDFs or enable external search to populate the report.\n"
            "- Evidence: No citation available."
        )
        citation_lines.append("- No citation available.")

    memory_block = "\n".join(memory_lines) if memory_lines else "- No matching long-term memory."
    return "\n\n".join(
        [
            f"# Weekly Research Report ({week_start.isoformat()} to {week_end.isoformat()})",
            f"User: `{user_id}`\n\nFocus: {focus}",
            "## TL;DR\n\n"
            f"- Reviewed {len(candidates)} candidate paper(s).\n"
            f"- Primary focus: {focus}.\n"
            "- Prioritize papers with local evidence first; external metadata is marked "
            "separately.",
            f"## Memory Context\n\n{memory_block}",
            "## Candidate Papers\n\n" + "\n\n".join(candidate_lines),
            "## Reading Notes\n\n" + "\n\n".join(note_lines),
            "## Citations\n\n" + "\n".join(citation_lines),
            "## Next Actions\n\n"
            "- Ingest full PDFs for any external-only candidate before detailed "
            "literature review.\n"
            "- Mark read status and rating through `rmcli papers update` after reading.\n"
            "- Carry unresolved questions into next week's task list.",
        ]
    )


def _single_line(text: str, limit: int) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _persist_report(
    settings: Settings,
    user_id: str,
    job_id: str,
    week_start: date,
    markdown: str,
) -> str:
    safe_user = re.sub(r"[^A-Za-z0-9_.-]+", "_", user_id).strip("._-") or "local"
    key = f"artifacts/weekly_reports/{safe_user}/{week_start.isoformat()}/{job_id}.md"
    local_path = settings.oss_cache_dir / "generated" / f"{job_id}.md"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(markdown, encoding="utf-8")
    return OssClient.from_settings(settings).put_file(local_path, key=key)


def task_kind_schema_payload() -> dict[str, Any]:
    return {
        item.kind: {
            "description": item.description,
            "params_schema": item.params_schema.model_json_schema(),
        }
        for item in registered_task_kinds()
    }
