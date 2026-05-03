from __future__ import annotations

import json
from typing import Annotated

import typer

from researchmate import __version__
from researchmate.config import get_settings

app = typer.Typer(
    name="rmcli",
    help="ResearchMate command line client.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show ResearchMate version and exit."),
    ] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


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
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def hello() -> None:
    """Run a local CLI sanity check."""
    typer.echo("ResearchMate CLI is ready.")


if __name__ == "__main__":
    app()
