from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
import typer

from researchmate import __version__
from researchmate.config import get_settings
from researchmate.services.oss_client import OssClient

app = typer.Typer(
    name="rmcli",
    help="ResearchMate command line client.",
    no_args_is_help=True,
)
session_app = typer.Typer(help="Manage ResearchMate chat sessions.")
memory_app = typer.Typer(help="Manage long-term memory.")
kb_app = typer.Typer(help="Manage knowledge-base documents.")
task_app = typer.Typer(help="Run and monitor asynchronous ResearchMate tasks.")
papers_app = typer.Typer(help="Manage paper metadata.")
app.add_typer(session_app, name="session")
app.add_typer(memory_app, name="memory")
app.add_typer(kb_app, name="kb")
app.add_typer(task_app, name="task")
app.add_typer(papers_app, name="papers")


@dataclass(slots=True)
class CliState:
    base_url: str
    token: str


def _default_base_url() -> str:
    settings = get_settings()
    return f"http://{settings.research_agent_bind}"


def _default_token() -> str:
    return get_settings().research_agent_token.get_secret_value()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show ResearchMate version and exit."),
    ] = False,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            envvar="RESEARCHMATE_BASE_URL",
            help="ResearchMate service URL.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            envvar="RESEARCH_AGENT_TOKEN",
            help="Internal service token.",
            hide_input=True,
        ),
    ] = None,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    ctx.obj = CliState(
        base_url=(base_url or _default_base_url()).rstrip("/"),
        token=token or _default_token(),
    )


def _state(ctx: typer.Context) -> CliState:
    if not isinstance(ctx.obj, CliState):
        ctx.obj = CliState(base_url=_default_base_url().rstrip("/"), token=_default_token())
    return ctx.obj


def _client(ctx: typer.Context, *, timeout: float = 60.0) -> httpx.Client:
    state = _state(ctx)
    return httpx.Client(
        base_url=state.base_url,
        headers={"X-Internal-Token": state.token},
        timeout=timeout,
    )


def _print_json(payload: object) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _exit_for_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {
            "code": "HTTP_ERROR",
            "message": response.text,
            "trace_id": response.headers.get("X-Trace-Id"),
        }
    trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
    message = payload.get("message") if isinstance(payload, dict) else str(payload)
    typer.secho(
        f"HTTP {response.status_code}: {message}" + (f" (trace_id={trace_id})" if trace_id else ""),
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(1)


def _iter_sse_lines(response: httpx.Response) -> Iterator[tuple[str, dict[str, object]]]:
    event = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    payload = {"raw": data}
                yield event, payload
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        data = "\n".join(data_lines)
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            payload = {"raw": data}
        yield event, payload


def _render_sse_event(event: str, payload: dict[str, object]) -> bool:
    if event == "thinking":
        text = payload.get("text")
        if text:
            typer.secho(f"[thinking] {text}", fg=typer.colors.BLUE)
    elif event == "tool_call":
        args_json = json.dumps(payload.get("args"), ensure_ascii=False)
        typer.secho(
            f"[tool_call] {payload.get('tool')} {args_json}",
            fg=typer.colors.YELLOW,
        )
    elif event == "tool_result":
        typer.secho(f"[tool_result] {payload.get('tool')}", fg=typer.colors.YELLOW)
    elif event == "citation":
        typer.secho(
            f"\n[citation] {payload.get('paper_id')} p.{payload.get('page')}",
            fg=typer.colors.GREEN,
        )
    elif event == "token":
        typer.echo(str(payload.get("delta", "")), nl=False)
    elif event == "final":
        typer.echo()
        return True
    elif event == "error":
        typer.secho(
            f"\n[error] {payload.get('code')}: {payload.get('message')}",
            fg=typer.colors.RED,
            err=True,
        )
        return True
    return False


def _render_job_event(event: str, payload: dict[str, object]) -> bool:
    if event in {"snapshot", "queued", "running", "progress"}:
        progress = payload.get("progress", 0)
        message = payload.get("message") or payload.get("state") or event
        typer.secho(f"[{progress}%] {message}", fg=typer.colors.BLUE)
        return False
    if event == "done":
        typer.secho("[done] job completed", fg=typer.colors.GREEN)
        result = payload.get("result")
        if result:
            _print_json(result)
        return True
    if event in {"failed", "cancelled", "interrupted"}:
        typer.secho(
            f"[{event}] {payload.get('error') or 'job stopped'}",
            fg=typer.colors.RED,
            err=True,
        )
        return True
    return False


def _stream_job(client: httpx.Client, job_id: str, *, events_path: str) -> None:
    with client.stream("GET", events_path.format(job_id=job_id), timeout=300.0) as response:
        _exit_for_error(response)
        for event, payload in _iter_sse_lines(response):
            if _render_job_event(event, payload):
                break


def _parse_params_json(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        typer.secho(f"invalid JSON params: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if not isinstance(payload, dict):
        typer.secho("--params-json must decode to an object", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return {str(key): item for key, item in payload.items()}


def _week_to_monday(value: str) -> str:
    try:
        year_raw, week_raw = value.upper().split("-W", maxsplit=1)
        monday = date.fromisocalendar(int(year_raw), int(week_raw), 1)
    except Exception as exc:
        typer.secho("--week must look like 2026-W17", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    return monday.isoformat()


@app.command()
def config() -> None:
    """Print non-secret local configuration."""
    settings = get_settings()
    payload = {
        "bind": settings.research_agent_bind,
        "adk_session_db_url": settings.adk_session_db_url,
        "embedding_device": settings.embedding_device,
        "embedding_backend": settings.embedding_backend,
        "embedding_model": settings.embedding_model,
        "embedding_allow_download": settings.embedding_allow_download,
        "rerank_backend": settings.rerank_backend,
        "reranker_model": settings.reranker_model,
        "rerank_allow_download": settings.rerank_allow_download,
        "chroma_dir": str(settings.chroma_dir),
        "kb_collection": settings.kb_collection,
        "llm_model": settings.researchmate_llm_model,
        "deepseek_api_key_configured": settings.has_deepseek_api_key,
    }
    _print_json(payload)


@app.command()
def hello() -> None:
    """Run a local CLI sanity check."""
    typer.echo("ResearchMate CLI is ready.")


@app.command()
def health(
    ctx: typer.Context,
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Run the cached LLM probe through /v1/healthz?deep=true."),
    ] = False,
) -> None:
    """Check the running ResearchMate service."""
    path = "/v1/healthz?deep=true" if deep else "/v1/readyz"
    with _client(ctx, timeout=30.0) as client:
        response = client.get(path)
    _exit_for_error(response)
    _print_json(response.json())


@session_app.command("create")
def session_create(
    ctx: typer.Context,
    user_id: Annotated[str, typer.Option("--user-id", help="ResearchMate user id.")] = "local",
) -> None:
    """Create a chat session."""
    with _client(ctx) as client:
        response = client.post("/v1/sessions", json={"user_id": user_id})
    _exit_for_error(response)
    _print_json(response.json())


@session_app.command("get")
def session_get(ctx: typer.Context, session_id: str) -> None:
    """Get a chat session."""
    with _client(ctx) as client:
        response = client.get(f"/v1/sessions/{session_id}")
    _exit_for_error(response)
    _print_json(response.json())


@session_app.command("delete")
def session_delete(ctx: typer.Context, session_id: str) -> None:
    """Delete a chat session."""
    with _client(ctx) as client:
        response = client.delete(f"/v1/sessions/{session_id}")
    _exit_for_error(response)
    _print_json(response.json())


def _create_session(client: httpx.Client, user_id: str) -> str:
    response = client.post("/v1/sessions", json={"user_id": user_id})
    _exit_for_error(response)
    payload = response.json()
    return str(payload["session_id"])


def _stream_chat(client: httpx.Client, session_id: str, message: str) -> None:
    with client.stream(
        "POST",
        f"/v1/chat/{session_id}",
        json={"message": message},
        timeout=120.0,
    ) as response:
        _exit_for_error(response)
        for event, payload in _iter_sse_lines(response):
            if _render_sse_event(event, payload):
                break


@app.command()
def chat(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Argument(help="Optional one-shot message.")] = None,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="Reuse an existing session."),
    ] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="ResearchMate user id.")] = "local",
) -> None:
    """Chat with the running ResearchMate service."""
    with _client(ctx, timeout=120.0) as client:
        active_session = session_id or _create_session(client, user_id)
        if message:
            _stream_chat(client, active_session, message)
            return
        typer.secho(f"session_id={active_session}", fg=typer.colors.GREEN)
        while True:
            try:
                prompt = typer.prompt("you")
            except (EOFError, KeyboardInterrupt):
                typer.echo()
                return
            if prompt.strip().lower() in {"exit", "quit", ":q"}:
                return
            if not prompt.strip():
                continue
            _stream_chat(client, active_session, prompt)


@app.command()
def ingest(
    ctx: typer.Context,
    pdf_paths: Annotated[list[Path], typer.Argument(help="Local PDF path(s) to ingest.")],
    user_id: Annotated[str, typer.Option("--user-id", help="Owner user id.")] = "local",
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Tag to attach to the ingested document."),
    ] = None,
    paper_id: Annotated[
        str | None,
        typer.Option("--paper-id", help="Override paper_id. Only valid with one PDF."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Override title. Only valid with one PDF."),
    ] = None,
    wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Stream job progress.")] = True,
) -> None:
    """Upload local PDFs to OSS/local store and submit a knowledge ingest job."""
    if len(pdf_paths) > 1 and (paper_id or title):
        typer.secho(
            "--paper-id/--title can only be used with one PDF",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    oss_client = OssClient.from_settings()
    oss_keys: list[str] = []
    for path in pdf_paths:
        if not path.exists():
            typer.secho(f"PDF not found: {path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        key = oss_client.put_file(path)
        oss_keys.append(key)
        typer.secho(f"[upload] {path} -> {key}", fg=typer.colors.GREEN)

    payload = {
        "oss_keys": oss_keys,
        "owner_user_id": user_id,
        "tags": tag or [],
        "paper_id": paper_id,
        "title": title,
    }
    with _client(ctx, timeout=300.0) as client:
        response = client.post("/v1/knowledge/ingest", json=payload)
        _exit_for_error(response)
        job_id = str(response.json()["job_id"])
        typer.secho(f"job_id={job_id}", fg=typer.colors.GREEN)
        if wait:
            _stream_job(
                client,
                job_id,
                events_path="/v1/knowledge/jobs/{job_id}/events",
            )


@kb_app.command("ls")
def kb_ls(
    ctx: typer.Context,
    user_id: Annotated[str | None, typer.Option("--user-id", help="Filter by user id.")] = None,
    tag: Annotated[str | None, typer.Option("--tag", help="Filter by tag.")] = None,
) -> None:
    """List indexed knowledge-base documents."""
    params = {key: value for key, value in {"user_id": user_id, "tag": tag}.items() if value}
    with _client(ctx) as client:
        response = client.get("/v1/knowledge/documents", params=params)
    _exit_for_error(response)
    _print_json(response.json())


@kb_app.command("rm")
def kb_rm(ctx: typer.Context, doc_id: str) -> None:
    """Remove a knowledge-base document and its chunks."""
    with _client(ctx) as client:
        response = client.delete(f"/v1/knowledge/documents/{doc_id}")
    _exit_for_error(response)
    _print_json(response.json())


@memory_app.command("add")
def memory_add(
    ctx: typer.Context,
    content: Annotated[str, typer.Argument(help="Memory content.")],
    category: Annotated[str, typer.Option("--category", "-c", help="Memory category.")],
    user_id: Annotated[str, typer.Option("--user-id", help="Owner user id.")] = "local",
    expires_at: Annotated[
        str | None,
        typer.Option("--expires-at", help="Optional ISO 8601 expiration timestamp."),
    ] = None,
) -> None:
    """Add a long-term memory record."""
    payload = {
        "user_id": user_id,
        "category": category,
        "content": content,
        "expires_at": expires_at,
    }
    with _client(ctx) as client:
        response = client.post("/v1/memory", json=payload)
    _exit_for_error(response)
    _print_json(response.json())


@memory_app.command("ls")
def memory_ls(
    ctx: typer.Context,
    user_id: Annotated[str, typer.Option("--user-id", help="Owner user id.")] = "local",
    category: Annotated[str | None, typer.Option("--category", "-c")] = None,
) -> None:
    """List long-term memory records."""
    params = {"user_id": user_id}
    if category:
        params["category"] = category
    with _client(ctx) as client:
        response = client.get("/v1/memory", params=params)
    _exit_for_error(response)
    _print_json(response.json())


@memory_app.command("rm")
def memory_rm(ctx: typer.Context, memory_id: str) -> None:
    """Delete a long-term memory record."""
    with _client(ctx) as client:
        response = client.delete(f"/v1/memory/{memory_id}")
    _exit_for_error(response)
    _print_json(response.json())


@memory_app.command("archive")
def memory_archive(ctx: typer.Context, session: Annotated[str, typer.Option("--session")]) -> None:
    """Archive a chat session into long-term memory."""
    with _client(ctx) as client:
        response = client.post("/v1/memory/archive", json={"session_id": session})
    _exit_for_error(response)
    _print_json(response.json())


@task_app.command("run")
def task_run(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="Task kind, e.g. weekly-report.")],
    params_json: Annotated[
        str | None,
        typer.Option("--params-json", help="Raw JSON object merged into task params."),
    ] = None,
    user_id: Annotated[str, typer.Option("--user-id", help="Owner user id.")] = "local",
    week: Annotated[
        str | None,
        typer.Option("--week", help="ISO week for weekly-report, e.g. 2026-W17."),
    ] = None,
    week_start: Annotated[
        str | None,
        typer.Option("--week-start", help="Monday date for weekly-report, e.g. 2026-04-20."),
    ] = None,
    paper_count: Annotated[
        int,
        typer.Option("--paper-count", min=1, max=20, help="Number of papers for weekly-report."),
    ] = 5,
    focus_keyword: Annotated[
        list[str] | None,
        typer.Option("--focus-keyword", help="Focus keyword for weekly-report."),
    ] = None,
    include_external: Annotated[
        bool,
        typer.Option("--include-external/--local-only", help="Include arXiv/S2 candidates."),
    ] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait", help="Stream task progress.")] = True,
) -> None:
    """Submit an asynchronous task."""
    normalized_kind = kind.replace("-", "_")
    params = _parse_params_json(params_json)
    if normalized_kind == "weekly_report":
        if week and week_start:
            typer.secho(
                "use either --week or --week-start, not both",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
        if week:
            params["week_start"] = _week_to_monday(week)
        elif week_start:
            params["week_start"] = week_start
        params.setdefault("paper_count", paper_count)
        params.setdefault("focus_keywords", focus_keyword or [])
        params.setdefault("include_external", include_external)
    payload = {"kind": normalized_kind, "params": params, "user_id": user_id}
    with _client(ctx, timeout=300.0) as client:
        response = client.post("/v1/tasks/run", json=payload)
        _exit_for_error(response)
        task_id = str(response.json()["task_id"])
        typer.secho(f"task_id={task_id}", fg=typer.colors.GREEN)
        if wait:
            _stream_job(client, task_id, events_path="/v1/tasks/{job_id}/events")


@task_app.command("status")
def task_status(
    ctx: typer.Context,
    task_id: str,
    watch: Annotated[bool, typer.Option("--watch/--no-watch", help="Stream task events.")] = True,
) -> None:
    """Show task status, optionally as an SSE stream."""
    with _client(ctx, timeout=300.0) as client:
        if watch:
            _stream_job(client, task_id, events_path="/v1/tasks/{job_id}/events")
            return
        response = client.get(f"/v1/tasks/{task_id}")
    _exit_for_error(response)
    _print_json(response.json())


@task_app.command("cancel")
def task_cancel(ctx: typer.Context, task_id: str) -> None:
    """Cancel a running task."""
    with _client(ctx) as client:
        response = client.post(f"/v1/tasks/{task_id}/cancel")
    _exit_for_error(response)
    _print_json(response.json())


@papers_app.command("ls")
def papers_ls(
    ctx: typer.Context,
    user_id: Annotated[str | None, typer.Option("--user-id", help="Filter by user id.")] = None,
    tag: Annotated[str | None, typer.Option("--tag", help="Filter by tag.")] = None,
    year: Annotated[int | None, typer.Option("--year", help="Filter by publication year.")] = None,
    q: Annotated[str | None, typer.Option("--q", help="Title/venue/author search.")] = None,
) -> None:
    """List paper metadata."""
    params = {
        key: value
        for key, value in {"user_id": user_id, "tag": tag, "year": year, "q": q}.items()
        if value is not None
    }
    with _client(ctx) as client:
        response = client.get("/v1/papers", params=params)
    _exit_for_error(response)
    _print_json(response.json())


@papers_app.command("show")
def papers_show(ctx: typer.Context, paper_id: str) -> None:
    """Show one paper metadata record."""
    with _client(ctx) as client:
        response = client.get(f"/v1/papers/{paper_id}")
    _exit_for_error(response)
    _print_json(response.json())


@papers_app.command("update")
def papers_update(
    ctx: typer.Context,
    paper_id: str,
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", help="Replace paper tags. Can be passed more than once."),
    ] = None,
    read_at: Annotated[
        str | None,
        typer.Option("--read-at", help="ISO 8601 read timestamp/date."),
    ] = None,
    rating: Annotated[
        float | None,
        typer.Option("--rating", min=0.0, max=5.0, help="Reading rating from 0 to 5."),
    ] = None,
) -> None:
    """Update paper tags, read timestamp, or rating."""
    payload: dict[str, object] = {}
    if tag is not None:
        payload["tags"] = tag
    if read_at is not None:
        payload["read_at"] = read_at
    if rating is not None:
        payload["rating"] = rating
    with _client(ctx) as client:
        response = client.patch(f"/v1/papers/{paper_id}", json=payload)
    _exit_for_error(response)
    _print_json(response.json())


if __name__ == "__main__":
    app()
