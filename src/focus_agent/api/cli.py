from __future__ import annotations

import uvicorn

from focus_agent.config import Settings, load_local_env_document


def run_api() -> None:
    # The API process needs provider credentials available in os.environ
    # because the model SDK reads them during application startup.
    load_local_env_document()
    settings = Settings.from_env()
    uvicorn.run(
        "focus_agent.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        factory=False,
    )


main = run_api


if __name__ == "__main__":
    run_api()
