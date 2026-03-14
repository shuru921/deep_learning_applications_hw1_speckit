# Task 002: Schema Design (Schema 設計)

**Phase:** 2
**Prerequisites:** Task 001 completed
**Constitution Reference:** §6.1, §6.2

---

## Objective
Implement all 22 Pydantic models in `src/orchestrator/schemas.py` plus unit tests.

## Deliverables

### 1. `src/orchestrator/schemas.py`

#### Base Model
```python
class OrchestratorBaseModel(BaseModel):
    # Support Pydantic v1/v2 via ConfigDict detection
    # arbitrary_types_allowed=True, validate_assignment=True, extra="ignore"
```

#### Data Models (13)
| Model | Key Fields | Purpose |
|-------|-----------|---------|
| `PlanStep` | `step_id`, `objective`, `status` (6 Literals), `owner` (7 Literals) | Planner sub-task |
| `PubMedDocument` | `pmid`, `title`, `abstract`, `journal`, `published_at`, `mesh_terms`, `authors`, `keywords`, `score` | Standardized PubMed article |
| `PubMedQueryLog` | `query: PubMedQuery`, `status` (6 Literals), `result_count`, `error` | Query execution record |
| `ToolCallMetric` | `tool`, `action`, `status` (7 Literals), `started_at`, `ended_at`, `latency_ms`, `retries` | Tool invocation telemetry |
| `VectorHit` | `point_id`, `score`, `payload`, `source` | Vector search result |
| `BatchTelemetry` | `batch_size`, `processed`, `latency_ms`, `retry_count` | Qdrant batch metrics |
| `QdrantSearchRecord` | `query_vector`, `filter`, `hits: list[VectorHit]`, `degraded` | Search request/response |
| `ContextChunk` | `chunk_id`, `content`, `source`, `score` | RAG context slice |
| `CriticFeedback` | `issue`, `severity` (4 Literals), `suggestion`, `requires_revision` | Medical review finding |
| `TaskStatus` | `task_id`, `status` (7 Literals), `started_at`, `finished_at` | Async task tracking |
| `ErrorSignal` | `source`, `code`, `message`, `severity` (4 Literals) | Error flag for branching |
| `FallbackEvent` | `trigger`, `action`, `reason` | Degradation record |
| `StreamUpdate` | `segment`, `content`, `channel` (4 Literals), `final` | UI streaming output |

#### State Models (9)
| Model | Key Fields |
|-------|-----------|
| `UserQueryState` | `raw_prompt`, `normalized_terms`, `constraints` |
| `PlanningState` | `iteration`, `plan_steps: list[PlanStep]`, `status` |
| `PubMedState` | `latest_query`, `query_history`, `results`, `empty_retry_count` |
| `QdrantState` | `collection_ready`, `upsert_metrics`, `search_results`, `health` |
| `RagState` | `context_bundle`, `synthesis_notes`, `answer_draft` |
| `CriticState` | `findings`, `trust_score`, `revision_required` |
| `TelemetryState` | `tool_invocations`, `active_tasks`, `error_flags`, `correlation_id` |
| `FallbackState` | `events`, `terminal_reason` |
| `UIState` | `stream_anchor`, `partial_updates` |

#### Root State (1)
```python
class LangGraphState(OrchestratorBaseModel):
    # Contains all 9 sub-states + extensions, status, current_node,
    # retry_counters, created_at, updated_at
    def touch(self) -> None:
        self.updated_at = datetime.utcnow()
```

### 2. `tests/test_schemas.py`
- Test instantiation of every model with default values
- Test `LangGraphState.touch()` updates timestamp
- Test `Literal` fields reject invalid values
- Test `Field(default_factory=list)` produces independent lists

## Verification
```bash
pytest tests/test_schemas.py -v
```

## Acceptance Criteria
- [ ] All 22 models + `OrchestratorBaseModel` implemented
- [ ] All models use `Field(default_factory=...)` for mutable defaults
- [ ] `__all__` exports all 22 model names
- [ ] All tests pass
