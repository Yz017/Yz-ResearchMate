from __future__ import annotations

from fastapi import FastAPI

from researchmate import __version__
from researchmate.api.schemas import HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="ResearchMate",
        version=__version__,
        description="Local-first AI research assistant service.",
    )

    @app.get("/v1/livez", response_model=HealthResponse)
    def livez() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()
