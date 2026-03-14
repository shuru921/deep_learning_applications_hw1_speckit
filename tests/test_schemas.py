"""Unit tests for src/orchestrator/schemas.py — all 22 Pydantic models."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from src.orchestrator.schemas import (
    BatchTelemetry,
    ContextChunk,
    CriticFeedback,
    CriticState,
    ErrorSignal,
    FallbackEvent,
    FallbackState,
    LangGraphState,
    OrchestratorBaseModel,
    PlanStep,
    PlanningState,
    PubMedDocument,
    PubMedQueryLog,
    PubMedState,
    QdrantSearchRecord,
    QdrantState,
    RagState,
    StreamUpdate,
    TaskStatus,
    TelemetryState,
    ToolCallMetric,
    UIState,
    UserQueryState,
    VectorHit,
)


class TestDataModels:
    """Test the 13 data models instantiate correctly with defaults."""

    def test_plan_step_defaults(self) -> None:
        step = PlanStep(step_id="s1", objective="Search PubMed")
        assert step.status == "pending"
        assert step.owner == "planner"
        assert step.dependencies == []
        assert step.outputs == []

    def test_pubmed_document_defaults(self) -> None:
        doc = PubMedDocument(pmid="12345")
        assert doc.source == "pubmed"
        assert doc.mesh_terms == []
        assert doc.authors == []
        assert doc.keywords == []

    def test_pubmed_query_log_defaults(self) -> None:
        log = PubMedQueryLog(term="diabetes")
        assert log.status == "pending"
        assert log.max_results == 10

    def test_tool_call_metric_defaults(self) -> None:
        metric = ToolCallMetric(tool="pubmed", action="search")
        assert metric.status == "pending"
        assert metric.retries == 0

    def test_vector_hit(self) -> None:
        hit = VectorHit(point_id="abc-123", score=0.95)
        assert hit.score == 0.95
        assert hit.payload is None

    def test_batch_telemetry_defaults(self) -> None:
        bt = BatchTelemetry(batch_size=10, processed=8)
        assert bt.retry_count == 0
        assert bt.warnings == []

    def test_qdrant_search_record_defaults(self) -> None:
        rec = QdrantSearchRecord()
        assert rec.hits == []
        assert rec.degraded is False

    def test_context_chunk(self) -> None:
        chunk = ContextChunk(chunk_id="c1", content="Hello world")
        assert chunk.source is None
        assert chunk.metadata == {}

    def test_critic_feedback_defaults(self) -> None:
        fb = CriticFeedback(issue="Outdated reference")
        assert fb.severity == "major"
        assert fb.requires_revision is True

    def test_task_status_defaults(self) -> None:
        ts = TaskStatus(task_id="t1")
        assert ts.status == "pending"

    def test_error_signal_defaults(self) -> None:
        es = ErrorSignal(source="pubmed", code="empty", message="No results")
        assert es.severity == "error"

    def test_fallback_event(self) -> None:
        fe = FallbackEvent(trigger="pubmed_empty", action="use_cache")
        assert fe.reason is None

    def test_stream_update_defaults(self) -> None:
        su = StreamUpdate(segment="planner", content="Planning...")
        assert su.channel == "text"
        assert su.final is False


class TestStateModels:
    """Test the 9 state models and root LangGraphState."""

    def test_user_query_state_defaults(self) -> None:
        uqs = UserQueryState()
        assert uqs.raw_prompt == ""
        assert uqs.normalized_terms == []

    def test_planning_state_defaults(self) -> None:
        ps = PlanningState()
        assert ps.iteration == 0
        assert ps.plan_steps == []

    def test_pubmed_state_defaults(self) -> None:
        pms = PubMedState()
        assert pms.empty_retry_count == 0
        assert pms.results == []

    def test_qdrant_state_defaults(self) -> None:
        qs = QdrantState()
        assert qs.health == "healthy"
        assert qs.collection_ready is False

    def test_rag_state_defaults(self) -> None:
        rs = RagState()
        assert rs.answer_draft is None

    def test_critic_state_defaults(self) -> None:
        cs = CriticState()
        assert cs.trust_score == 1.0
        assert cs.revision_required is False

    def test_telemetry_state_defaults(self) -> None:
        ts = TelemetryState()
        assert ts.tool_invocations == []
        assert ts.correlation_id is None

    def test_fallback_state_defaults(self) -> None:
        fs = FallbackState()
        assert fs.events == []
        assert fs.terminal_reason is None

    def test_ui_state_defaults(self) -> None:
        us = UIState()
        assert us.stream_anchor == "root"
        assert us.partial_updates == []


class TestLangGraphState:
    """Test root state and critical behaviors."""

    def test_default_instantiation(self) -> None:
        state = LangGraphState()
        assert state.status == "idle"
        assert state.current_node is None
        assert state.retry_counters == {}
        assert isinstance(state.pubmed, PubMedState)
        assert isinstance(state.qdrant, QdrantState)

    def test_touch_updates_timestamp(self) -> None:
        state = LangGraphState()
        old_ts = state.updated_at
        time.sleep(0.01)
        state.touch()
        assert state.updated_at > old_ts

    def test_mutable_defaults_are_independent(self) -> None:
        """Ensure Field(default_factory=list) creates independent lists."""
        state_a = LangGraphState()
        state_b = LangGraphState()
        state_a.pubmed.results.append(PubMedDocument(pmid="111"))
        assert len(state_b.pubmed.results) == 0

    def test_literal_rejects_invalid_status(self) -> None:
        """Literal fields should reject invalid values."""
        with pytest.raises(Exception):
            LangGraphState(status="invalid_status")  # type: ignore[arg-type]

    def test_literal_rejects_invalid_qdrant_health(self) -> None:
        with pytest.raises(Exception):
            QdrantState(health="broken")  # type: ignore[arg-type]

    def test_all_substates_present(self) -> None:
        """Root state must contain all 9 sub-states."""
        state = LangGraphState()
        assert hasattr(state, "user_query")
        assert hasattr(state, "planning")
        assert hasattr(state, "pubmed")
        assert hasattr(state, "qdrant")
        assert hasattr(state, "rag")
        assert hasattr(state, "critic")
        assert hasattr(state, "telemetry")
        assert hasattr(state, "fallback")
        assert hasattr(state, "ui")
        assert hasattr(state, "extensions")
