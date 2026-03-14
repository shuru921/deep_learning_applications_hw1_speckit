"""Qdrant 向量資料庫非同步封裝層。

依據 constitution.md §5 與 tasks/task_004_qdrant_wrapper.md 實作。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class QdrantRecord(BaseModel):
    """待寫入 Qdrant 的記錄。"""
    id: str
    vector: list[float]
    payload: dict[str, Any] = Field(default_factory=dict)


class QdrantQuery(BaseModel):
    """Qdrant 檢索查詢。"""
    vector: list[float]
    limit: int = 10
    filter: Optional[dict[str, Any]] = None


class QdrantUpsertResult(BaseModel):
    """Upsert 操作結果。"""
    succeeded: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)


class QdrantQueryResult(BaseModel):
    """Query 操作結果。"""
    hits: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0


class QdrantDeleteResult(BaseModel):
    """Delete 操作結果。"""
    deleted: int = 0


class QdrantHealthStatus(BaseModel):
    """健康檢查狀態。"""
    status: Literal["healthy", "degraded", "unavailable"] = "healthy"
    detail: str = ""


# ---------------------------------------------------------------------------
# Error Hierarchy (Constitution §5.4)
# ---------------------------------------------------------------------------


class QdrantError(Exception):
    """Qdrant 工具層基底例外。"""
    def __init__(self, message: str, *, operation: str = "",
                 collection: str = "", detail: str = ""):
        super().__init__(message)
        self.operation = operation
        self.collection = collection
        self.detail = detail


class QdrantConnectivityError(QdrantError):
    """連線被拒或逾時。"""


class QdrantSchemaError(QdrantError):
    """集合 Schema 不匹配。"""


class QdrantConsistencyError(QdrantError):
    """部分 upsert 失敗。"""


class QdrantTimeoutError(QdrantError):
    """操作逾時。"""


# ---------------------------------------------------------------------------
# ID Generation (Constitution §5.1 — CRITICAL)
# ---------------------------------------------------------------------------


def generate_point_id(pmid: str, idx: int = 0) -> str:
    """使用 uuid5 生成 Qdrant Point ID（禁止字串拼接）。

    Constitution §5.1:
    ✅ CORRECT: uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}")
    ❌ WRONG:   f"pmid-{pmid}-{idx}" ← 會導致 400 Bad Request
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}"))


# ---------------------------------------------------------------------------
# Wrapper Class (Constitution §5)
# ---------------------------------------------------------------------------


class QdrantWrapper:
    """Qdrant 向量資料庫非同步客戶端。

    - 所有 Point ID 使用 uuid5 生成
    - 使用 query_points() 而非已棄用的 search()
    - 自動偵測並建立集合
    - Distance 列舉使用首字母大寫
    """

    def __init__(
        self,
        client: Any,  # AsyncQdrantClient
        *,
        collection: str = "mars-default",
        vector_size: int = 8,
        distance: str = "Cosine",
        max_batch_size: int = 100,
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._collection = collection
        self._vector_size = vector_size
        self._distance = distance  # Must be "Cosine", "Euclid", or "Dot"
        self._max_batch_size = max_batch_size
        self._timeout = timeout

    # -----------------------------------------------------------------------
    # Collection Assurance (Constitution §5.3)
    # -----------------------------------------------------------------------

    async def ensure_collection(self) -> None:
        """確保集合存在，不存在時自動建立。

        Constitution §5.3: 偵測 404 錯誤自動建立，
        包括字串中包含 "Not found" 的封裝例外。
        """
        try:
            await self._client.get_collection(self._collection)
            logger.info(f"Collection '{self._collection}' exists")
        except Exception as e:
            error_str = str(e)
            if "Not found" in error_str or "404" in error_str or "doesn't exist" in error_str:
                logger.info(f"Collection '{self._collection}' not found, creating...")
                await self._create_collection()
            else:
                raise QdrantConnectivityError(
                    f"Failed to check collection: {e}",
                    operation="ensure_collection",
                    collection=self._collection,
                    detail=error_str,
                )

    async def _create_collection(self) -> None:
        """建立新集合。Distance 列舉使用首字母大寫 (Constitution §5.2)。"""
        from qdrant_client.models import Distance, VectorParams

        # Constitution §5.2: Distance 列舉首字母大寫
        distance_map = {
            "Cosine": Distance.COSINE,
            "Euclid": Distance.EUCLID,
            "Dot": Distance.DOT,
        }
        dist = distance_map.get(self._distance.capitalize())
        if dist is None:
            dist = Distance.COSINE

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=self._vector_size,
                distance=dist,
            ),
        )
        logger.info(f"Created collection '{self._collection}' "
                     f"(size={self._vector_size}, distance={self._distance})")

    # -----------------------------------------------------------------------
    # Public Async Methods
    # -----------------------------------------------------------------------

    async def upsert(self, records: Sequence[QdrantRecord]) -> QdrantUpsertResult:
        """批次寫入向量。所有 ID 必須為 UUID 格式。

        Constitution §5.3: 操作前先確保集合存在。
        """
        await self.ensure_collection()

        from qdrant_client.models import PointStruct

        succeeded = 0
        failed = 0
        details: list[dict[str, Any]] = []

        # 分批處理
        for i in range(0, len(records), self._max_batch_size):
            batch = records[i:i + self._max_batch_size]
            points = [
                PointStruct(
                    id=rec.id,
                    vector=rec.vector,
                    payload=rec.payload,
                )
                for rec in batch
            ]
            try:
                await self._client.upsert(
                    collection_name=self._collection,
                    points=points,
                )
                succeeded += len(batch)
                logger.info(f"Upsert batch {i // self._max_batch_size}: "
                            f"{len(batch)} points succeeded")
            except Exception as e:
                failed += len(batch)
                details.append({"batch_start": i, "error": str(e)})
                logger.error(f"Upsert batch failed: {e}")

        if failed > 0 and succeeded == 0:
            raise QdrantConsistencyError(
                f"All upserts failed ({failed} points)",
                operation="upsert",
                collection=self._collection,
            )

        return QdrantUpsertResult(
            succeeded=succeeded, failed=failed, details=details
        )

    async def query(self, request: QdrantQuery) -> QdrantQueryResult:
        """語義相似度搜尋。使用 query_points() (Constitution §5.2)。

        Constitution §5.3: 操作前先確保集合存在。
        """
        await self.ensure_collection()

        import time
        start = time.monotonic()

        try:
            # Constitution §5.2: 使用 query_points 而非 search
            results = await self._client.query_points(
                collection_name=self._collection,
                query=request.vector,
                limit=request.limit,
            )
            latency = (time.monotonic() - start) * 1000

            hits = []
            points = getattr(results, "points", results)
            if isinstance(points, list):
                for pt in points:
                    hits.append({
                        "point_id": str(getattr(pt, "id", "")),
                        "score": float(getattr(pt, "score", 0.0)),
                        "payload": dict(getattr(pt, "payload", {}) or {}),
                    })
            logger.info(f"Query returned {len(hits)} hits in {latency:.1f}ms")
            return QdrantQueryResult(hits=hits, latency_ms=latency)

        except Exception as e:
            raise QdrantConnectivityError(
                f"Query failed: {e}",
                operation="query",
                collection=self._collection,
                detail=str(e),
            )

    async def delete(self, point_ids: Sequence[str]) -> QdrantDeleteResult:
        """刪除指定 Point ID。"""
        from qdrant_client.models import PointIdsList

        try:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=list(point_ids)),
            )
            logger.info(f"Deleted {len(point_ids)} points")
            return QdrantDeleteResult(deleted=len(point_ids))
        except Exception as e:
            raise QdrantConnectivityError(
                f"Delete failed: {e}",
                operation="delete",
                collection=self._collection,
                detail=str(e),
            )

    async def healthcheck(self) -> QdrantHealthStatus:
        """檢查 Qdrant 連線健康狀態。"""
        try:
            collections = await self._client.get_collections()
            count = len(getattr(collections, "collections", []))
            return QdrantHealthStatus(
                status="healthy",
                detail=f"{count} collections available",
            )
        except Exception as e:
            logger.warning(f"Qdrant healthcheck failed: {e}")
            return QdrantHealthStatus(
                status="unavailable",
                detail=str(e),
            )
