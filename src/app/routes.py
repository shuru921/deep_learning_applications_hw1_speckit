"""API 路由 — NDJSON 串流端點。

依據 tasks/task_006_ui_api.md 實作。
Constitution §3.2: recursion_limit=30 必設。
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class _DateTimeEncoder(json.JSONEncoder):
    """自訂 JSON encoder 處理 datetime 物件。"""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_DateTimeEncoder, ensure_ascii=False)


from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.orchestrator.schemas import LangGraphState, UserQueryState

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    """研究查詢請求。"""
    query: str
    max_articles: int = 3


# ---------------------------------------------------------------------------
# Streaming Endpoint — NDJSON
# ---------------------------------------------------------------------------


@router.post("/api/research")
async def api_research(request: ResearchRequest) -> StreamingResponse:
    """執行醫學研究工作流，以 NDJSON 串流回傳。"""
    from src.app.deps import create_graph_factory

    correlation_id = str(uuid.uuid4())
    graph, ctx = create_graph_factory()

    initial_state = LangGraphState(
        user_query=UserQueryState(raw_prompt=request.query),
    )

    async def event_stream():
        final_state_data = None
        try:
            # Constitution §3.2: recursion_limit=30 MANDATORY
            async for event in graph.astream(
                initial_state,
                config={"recursion_limit": 30},
            ):
                if isinstance(event, dict):
                    for node_name, node_state_data in event.items():
                        if isinstance(node_state_data, dict):
                            final_state_data = node_state_data

                            # 提取 UI partial_updates
                            ui_data = node_state_data.get("ui", {})
                            partial_updates = ui_data.get("partial_updates", [])

                            for update in partial_updates:
                                if isinstance(update, dict):
                                    yield _dumps({
                                        "event": "update",
                                        "segment": update.get("segment", node_name),
                                        "content": update.get("content", ""),
                                        "final": update.get("final", False),
                                        "created_at": update.get("created_at", ""),
                                    }) + "\n"

            # Summary event
            status = "failed"
            total_articles = 0
            total_chunks = 0
            trust_score = 0

            if final_state_data:
                status = final_state_data.get("status", "failed")
                pubmed = final_state_data.get("pubmed", {})
                total_articles = len(pubmed.get("results", []))
                rag = final_state_data.get("rag", {})
                total_chunks = len(rag.get("context_bundle", []))
                critic = final_state_data.get("critic", {})
                trust_score = critic.get("trust_score", 0)

            yield _dumps({
                "event": "summary",
                "status": status,
                "correlation_id": correlation_id,
                "telemetry": {
                    "total_articles": total_articles,
                    "total_chunks": total_chunks,
                    "trust_score": trust_score,
                },
            }) + "\n"

            # Complete event
            yield _dumps({
                "event": "complete",
                "status": status,
                "correlation_id": correlation_id,
            }) + "\n"

        except Exception as e:
            logger.exception(f"Graph execution error: {e}")
            yield _dumps({
                "event": "complete",
                "status": "failed",
                "correlation_id": correlation_id,
                "error": str(e),
            }) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
    )


# ---------------------------------------------------------------------------
# UI Endpoint
# ---------------------------------------------------------------------------


@router.get("/ui", response_class=HTMLResponse)
async def ui_page(request: Request) -> HTMLResponse:
    """渲染互動式 UI 頁面。"""
    return templates.TemplateResponse("index.html", {"request": request})
