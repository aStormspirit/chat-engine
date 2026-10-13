import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.accounts import AccountManager
from app.api.routers import accounts, chat, ws
from app.config import settings
from app.services.anon_chat import ChatError

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager = AccountManager(settings)
    app.state.accounts = manager

    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


async def handle_chat_error(request: Request, exc: ChatError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def create_app() -> FastAPI:
    app = FastAPI(
        title="Anonymous Chat Userbot",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ChatError, handle_chat_error)
    app.include_router(accounts.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")

    @app.get("/health", tags=["service"], summary="Проверка живости")
    async def health() -> dict[str, str]:
        """Отвечает, пока процесс запущен; состояние аккаунтов не проверяет."""
        return {"status": "ok"}

    # Mounted last so that API routes keep priority over the demo UI.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app
