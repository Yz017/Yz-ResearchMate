from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

import httpx
import typer

from researchmate import __version__
from researchmate.config import get_settings

app = typer.Typer(
    name="rmcli",
    help="ResearchMate command line client.",
    no_args_is_help=True,
)
session_app = typer.Typer(help="Manage ResearchMate chat sessions.")
app.add_typer(session_app, name="session")


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


if __name__ == "__main__":
    app()
