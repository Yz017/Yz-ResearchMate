from __future__ import annotations

import uvicorn

from researchmate.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "researchmate.api:app",
        host=settings.bind_host,
        port=settings.bind_port,
        workers=1,
    )


if __name__ == "__main__":
    main()
