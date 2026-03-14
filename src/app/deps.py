"""依賴注入與 Graph 工廠。

依據 tasks/task_006_ui_api.md 實作。
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def get_config() -> dict[str, Any]:
    """從 .env 載入設定。"""
    return {
        "pubmed_api_key": os.getenv("PUBMED_API_KEY", ""),
        "pubmed_tool_name": os.getenv("PUBMED_TOOL_NAME", "mars-research"),
        "pubmed_email": os.getenv("PUBMED_EMAIL", ""),
        "pubmed_rate_requests": int(os.getenv("PUBMED_RATE_REQUESTS", "3")),
        "pubmed_rate_period": float(os.getenv("PUBMED_RATE_PERIOD", "1.0")),
        "qdrant_host": os.getenv("QDRANT_HOST", "localhost"),
        "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
        "qdrant_collection": os.getenv("QDRANT_COLLECTION", "mars-test"),
        "vector_size": int(os.getenv("QDRANT_VECTOR_SIZE", "8")),
        "qdrant_distance": os.getenv("QDRANT_DISTANCE", "COSINE").capitalize(),  # Constitution §5.2
    }


def create_graph_factory() -> Any:
    """建立 Graph 工廠函式。"""
    from src.orchestrator.graph import NodeContext, build_medical_research_graph

    config = get_config()
    ctx = NodeContext(config=config)

    # 嘗試建立 PubMed wrapper
    try:
        import httpx
        from src.clients.pubmed_wrapper import PubMedWrapper
        client = httpx.AsyncClient(timeout=30.0)
        ctx.pubmed_wrapper = PubMedWrapper(
            client,
            api_key=config["pubmed_api_key"] or None,
            tool_name=config["pubmed_tool_name"],
            email=config["pubmed_email"],
            rate_limit_requests=config["pubmed_rate_requests"],
        )
    except Exception:
        pass

    # 嘗試建立 Qdrant wrapper
    try:
        from qdrant_client import AsyncQdrantClient
        from src.clients.qdrant_wrapper import QdrantWrapper
        qdrant_client = AsyncQdrantClient(
            host=config["qdrant_host"],
            port=config["qdrant_port"],
        )
        ctx.qdrant_wrapper = QdrantWrapper(
            qdrant_client,
            collection=config["qdrant_collection"],
            vector_size=config["vector_size"],
            distance=config["qdrant_distance"],
        )
    except Exception:
        pass

    graph = build_medical_research_graph(ctx)
    return graph, ctx
