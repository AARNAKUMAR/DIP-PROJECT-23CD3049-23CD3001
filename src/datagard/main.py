"""FastAPI composition root and local application lifecycle."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from datagard.api import router
from datagard.application import ApplicationServices
from datagard.config import Settings, get_settings
from datagard.logging_config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an app with one configured service graph and SQLite store."""

    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = ApplicationServices(application_settings)
        yield

    application = FastAPI(title=application_settings.app_name, lifespan=lifespan)

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Report process liveness and the active environment."""

        return {"status": "ok", "environment": application_settings.environment}

    application.include_router(router)
    return application


app = create_app()
