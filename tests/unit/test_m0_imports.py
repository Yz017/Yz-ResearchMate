from __future__ import annotations

from typer.testing import CliRunner

from researchmate import __version__
from researchmate.api import app as fastapi_app
from researchmate.cli.main import app as cli_app


def test_package_version() -> None:
    assert __version__ == "0.4.0"


def test_agent_exports_root_agent() -> None:
    from researchmate.agent import root_agent

    assert root_agent.name == "researchmate"


def test_api_exports_fastapi_app() -> None:
    assert fastapi_app.title == "ResearchMate"


def test_rmcli_help() -> None:
    result = CliRunner().invoke(cli_app, ["--help"])

    assert result.exit_code == 0
    assert "ResearchMate command line client" in result.output
