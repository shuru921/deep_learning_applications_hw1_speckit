"""LangGraph Orchestrator 狀態機資料結構定義。

依據 spec.md §4.1 與 constitution.md §6 定義所有 22 個 Pydantic 模型。
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, Field

try:  # pragma: no cover - pydantic v1 相容處理
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 沒有 ConfigDict
    ConfigDict = None  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# Base Model
# ---------------------------------------------------------------------------

class OrchestratorBaseModel(BaseModel):
    """提供共用的 pydantic 設定以支援狀態物件。"""

    if ConfigDict is not None:  # pragma: no branch
        model_config = ConfigDict(  # type: ignore[assignment]
            arbitrary_types_allowed=True,
            populate_by_name=True,
            validate_assignment=True,
            extra="ignore",
        )
    else:  # pragma: no cover - pydantic v1 配置
        class Config:  # type: ignore[too-few-public-methods]
            arbitrary_types_allowed = True
            allow_population_by_field_name = True
            validate_assignment = True
            extra = "ignore"


# ---------------------------------------------------------------------------
# Data Models (13)
# ---------------------------------------------------------------------------

class PlanStep(OrchestratorBaseModel):
    """Planner 子任務計畫的結構化描述。"""

    step_id: str
    objective: str
    status: Literal[
        "pending", "running", "succeeded", "degraded", "skipped", "failed"
    ] = "pending"
    owner: Literal[
        "planner", "researcher", "librarian", "critic",
        "fallback", "responder", "system",
    ] = "planner"
    dependencies: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PubMedDocument(OrchestratorBaseModel):
    """標準化的 PubMed 文獻資料。"""

    pmid: str
    title: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    published_at: Optional[str] = None
    mesh_terms: List[str] = Field(default_factory=list)
    authors: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    score: Optional[float] = None
    source: str = "pubmed"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PubMedQueryLog(OrchestratorBaseModel):
    """紀錄 PubMed 查詢歷程與結果統計。"""

    term: str
    max_results: int = 10
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal[
        "pending", "sent", "succeeded", "empty", "failed", "degraded"
    ] = "pending"
    result_count: Optional[int] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCallMetric(OrchestratorBaseModel):
    """工具呼叫遙測資料。"""

    tool: str
    action: str
    status: Literal[
        "pending", "running", "success", "warning", "error", "timeout", "cancelled"
    ] = "pending"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    retries: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class VectorHit(OrchestratorBaseModel):
    """向量檢索命中結果。"""

    point_id: str
    score: float
    payload: Optional[Mapping[str, Any]] = None
    source: Optional[str] = None


class BatchTelemetry(OrchestratorBaseModel):
    """Qdrant upsert 批次遙測紀錄。"""

    batch_size: int
    processed: int
    latency_ms: Optional[float] = None
    retry_count: int = 0
    warnings: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detail: Dict[str, Any] = Field(default_factory=dict)


class QdrantSearchRecord(OrchestratorBaseModel):
    """Qdrant 檢索請求與結果封裝。"""

    query_vector: Optional[List[float]] = None
    filter: Optional[Dict[str, Any]] = None
    hits: List[VectorHit] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = None
    degraded: bool = False
    notes: List[str] = Field(default_factory=list)


class ContextChunk(OrchestratorBaseModel):
    """RAG 合成所需的上下文切片。"""

    chunk_id: str
    content: str
    source: Optional[str] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CriticFeedback(OrchestratorBaseModel):
    """醫療審查節點的發現與建議。"""

    issue: str
    severity: Literal["info", "minor", "major", "critical"] = "major"
    suggestion: Optional[str] = None
    supporting_evidence: List[str] = Field(default_factory=list)
    requires_revision: bool = True
    source_nodes: List[str] = Field(default_factory=list)


class TaskStatus(OrchestratorBaseModel):
    """非同步任務執行情況，用於監控長時操作。"""

    task_id: str
    status: Literal[
        "pending", "running", "completed", "failed",
        "cancelled", "timeout", "degraded",
    ] = "pending"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ErrorSignal(OrchestratorBaseModel):
    """狀態機條件分支所需的錯誤旗標。"""

    source: str
    code: str
    message: str
    severity: Literal["info", "warning", "error", "critical"] = "error"
    raised_at: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)


class FallbackEvent(OrchestratorBaseModel):
    """降級策略啟動紀錄。"""

    trigger: str
    action: str
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StreamUpdate(OrchestratorBaseModel):
    """UI streaming 的增量輸出。"""

    segment: str
    content: str
    channel: Literal["text", "citation", "telemetry", "alert"] = "text"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    final: bool = False


# ---------------------------------------------------------------------------
# State Models (9)
# ---------------------------------------------------------------------------

class UserQueryState(OrchestratorBaseModel):
    """使用者提問的原始與正規化資料。"""

    raw_prompt: str = ""
    normalized_terms: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class PlanningState(OrchestratorBaseModel):
    """Planner 節點的執行狀態。"""

    iteration: int = 0
    plan_steps: List[PlanStep] = Field(default_factory=list)
    status: Literal[
        "pending", "running", "succeeded", "degraded", "failed"
    ] = "pending"


class PubMedState(OrchestratorBaseModel):
    """PubMed 工具輸入輸出狀態。"""

    latest_query: Optional[Dict[str, Any]] = None
    query_history: List[PubMedQueryLog] = Field(default_factory=list)
    results: List[PubMedDocument] = Field(default_factory=list)
    empty_retry_count: int = 0


class QdrantState(OrchestratorBaseModel):
    """Qdrant Wrapper 相關的狀態資訊。"""

    collection_ready: bool = False
    upsert_metrics: List[BatchTelemetry] = Field(default_factory=list)
    search_results: List[QdrantSearchRecord] = Field(default_factory=list)
    health: Literal["healthy", "degraded", "unavailable"] = "healthy"


class RagState(OrchestratorBaseModel):
    """RAG 合成節點的暫存資料。"""

    context_bundle: List[ContextChunk] = Field(default_factory=list)
    synthesis_notes: List[str] = Field(default_factory=list)
    answer_draft: Optional[str] = None


class CriticState(OrchestratorBaseModel):
    """醫療審查節點的結果。"""

    findings: List[CriticFeedback] = Field(default_factory=list)
    trust_score: float = 1.0
    revision_required: bool = False


class TelemetryState(OrchestratorBaseModel):
    """跨節點共享的遙測資訊。"""

    tool_invocations: List[ToolCallMetric] = Field(default_factory=list)
    active_tasks: Dict[str, TaskStatus] = Field(default_factory=dict)
    error_flags: List[ErrorSignal] = Field(default_factory=list)
    correlation_id: Optional[str] = None


class FallbackState(OrchestratorBaseModel):
    """降級流程紀錄。"""

    events: List[FallbackEvent] = Field(default_factory=list)
    terminal_reason: Optional[str] = None


class UIState(OrchestratorBaseModel):
    """UI streaming 與輸出控管。"""

    stream_anchor: str = "root"
    partial_updates: List[StreamUpdate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Root State (1)
# ---------------------------------------------------------------------------

class LangGraphState(OrchestratorBaseModel):
    """LangGraph 狀態機核心資料結構。"""

    user_query: UserQueryState = Field(default_factory=UserQueryState)
    planning: PlanningState = Field(default_factory=PlanningState)
    pubmed: PubMedState = Field(default_factory=PubMedState)
    qdrant: QdrantState = Field(default_factory=QdrantState)
    rag: RagState = Field(default_factory=RagState)
    critic: CriticState = Field(default_factory=CriticState)
    telemetry: TelemetryState = Field(default_factory=TelemetryState)
    fallback: FallbackState = Field(default_factory=FallbackState)
    ui: UIState = Field(default_factory=UIState)
    extensions: Dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "idle", "running", "succeeded", "failed", "degraded", "cancelled"
    ] = "idle"
    current_node: Optional[str] = None
    retry_counters: Dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        """更新最後修改時間，供節點寫入後呼叫。"""
        self.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "BatchTelemetry",
    "ContextChunk",
    "CriticFeedback",
    "CriticState",
    "ErrorSignal",
    "FallbackEvent",
    "FallbackState",
    "LangGraphState",
    "OrchestratorBaseModel",
    "PlanStep",
    "PlanningState",
    "PubMedDocument",
    "PubMedQueryLog",
    "PubMedState",
    "QdrantSearchRecord",
    "QdrantState",
    "RagState",
    "StreamUpdate",
    "TaskStatus",
    "TelemetryState",
    "ToolCallMetric",
    "UIState",
    "UserQueryState",
    "VectorHit",
]
