"""API 路由 — NDJSON 串流端點。

依據 tasks/task_006_ui_api.md 實作。
Constitution §3.2: recursion_limit=30 必設。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.orchestrator.schemas import LangGraphState, UserQueryState

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
        final_state = None
        try:
            # Constitution §3.2: recursion_limit=30 MANDATORY
            async for event in graph.astream(
                initial_state,
                config={"recursion_limit": 30},
            ):
                if isinstance(event, dict):
                    for node_name, node_state in event.items():
                        if isinstance(node_state, LangGraphState):
                            final_state = node_state
                            for update in node_state.ui.partial_updates:
                                yield json.dumps({
                                    "event": "update",
                                    "segment": update.segment,
                                    "content": update.content,
                                    "final": update.final,
                                    "created_at": update.created_at.isoformat(),
                                }) + "\n"
                            # 清除已發送的更新
                            node_state.ui.partial_updates.clear()

            # Summary event
            status = final_state.status if final_state else "failed"
            yield json.dumps({
                "event": "summary",
                "status": status,
                "correlation_id": correlation_id,
                "telemetry": {
                    "total_articles": len(final_state.pubmed.results) if final_state else 0,
                    "total_chunks": len(final_state.rag.context_bundle) if final_state else 0,
                    "trust_score": final_state.critic.trust_score if final_state else 0,
                },
            }) + "\n"

            # Complete event
            yield json.dumps({
                "event": "complete",
                "status": status,
                "correlation_id": correlation_id,
            }) + "\n"

        except Exception as e:
            yield json.dumps({
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
