"""FastAPI 應用工廠。

依據 tasks/task_006_ui_api.md 實作。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path


def create_app() -> FastAPI:
    """Application factory with lifespan management."""
    app = FastAPI(
        title="MARS - Multi-Agent Medical Research System",
        description="AI-powered medical literature research platform",
        version="2.0.0",
    )

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register routes
    from src.app.routes import router
    app.include_router(router)

    return app
