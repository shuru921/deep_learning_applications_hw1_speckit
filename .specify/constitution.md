# MARS Project Constitution

This constitution defines the **non-negotiable rules**, architectural principles, and coding standards for the Multi-Agent Medical Literature Assistant (MARS) project. **All AI agents MUST strictly adhere to these rules before generating any code or executing tasks.**

---

## 1. Core Principles

### 1.1 Spec-as-Source
The `spec.md` file is the **ultimate source of truth**. If implementation requires deviation from the spec, the spec MUST be updated and approved first. No rogue coding allowed.

### 1.2 Fail Gracefully
Every external API call (PubMed, Qdrant, PostgreSQL) must have error handling and a fallback strategy. The system must degrade gracefully (e.g., return `"Degraded"` status) rather than crash or hang.

### 1.3 Phase-Driven Development
Code must be developed in strict phases (Infra → Schema → Tooling → Orchestrator → UI → Quality). **No phase may skip its predecessor.** Each phase must pass verification before the next begins.

### 1.4 Modularity & Decoupling
Agent logic, database operations, API routes, and data pipelines must be **completely separated** into distinct modules. It is strictly forbidden to write business logic in a single monolithic file.

---

## 2. Technology Stack & Rules

### 2.1 Language & Runtime
- **Python Version**: Strict use of Python 3.10+ with `from __future__ import annotations`.
- **Package Manager**: `pip` with `requirements.txt`. Pin upper bounds on critical packages (e.g., `qdrant-client<1.17.0`).

### 2.2 Asynchronous I/O
- All I/O-bound operations MUST use `asyncio` and asynchronous library versions.
- Use `httpx.AsyncClient` (NOT `requests`). Use `AsyncQdrantClient` (NOT sync `QdrantClient`).
- Use `asyncio.gather` for parallel tool invocations (e.g., PubMed fetch + Qdrant upsert).
- Use `asyncio.TaskGroup` for long-running operations to enable cancellation and progress tracking.

### 2.3 Type Safety
- **100% strict type hinting** is required for all function signatures and complex variables.
- Use `pydantic.BaseModel` (v2) heavily for data validation and serialization.
- Support Pydantic v1 fallback via `ConfigDict` detection pattern (see `schemas.py`).
- **NEVER use `typing.Any`** or raw `dict` to bypass state validation in LangGraph state objects.

### 2.4 Configuration
- Use `pydantic-settings` with `python-dotenv` to load all configurations from `.env`.
- **NEVER hardcode** API keys, passwords, hostnames, or port numbers.
- All environment variables must be documented in `.env.example`.

---

## 3. LangGraph Orchestrator Strict Guidelines

### 3.1 State Machine Integrity
- All state objects MUST strictly adhere to the `LangGraphState` Pydantic model defined in `src/orchestrator/schemas.py`.
- The root state must contain exactly these sub-states: `user_query`, `planning`, `pubmed`, `qdrant`, `rag`, `critic`, `telemetry`, `fallback`, `ui`, `extensions`.
- Every node function must call `state.touch()` before returning to update `updated_at`.

### 3.2 Recursion Limits (MANDATORY)
- A strict `recursion_limit` MUST be set at the `CompiledGraph` executor level. **Default: 30.**
- No graph execution is allowed without this safety valve.
- The limit is configured in `src/app/routes.py` via `graph.astream(config={"recursion_limit": 30})`.

### 3.3 Branching Safety (CRITICAL)
All `add_conditional_edges` logic MUST include a **guaranteed exit condition**:
- **PubMed Empty Result Loop**: `_pubmed_branch` must enforce a **hard retry limit of 3**. If `pubmed.empty_retry_count >= 3`, the branch MUST route to `fallback` or `final_responder`. Routing back to `planner` indefinitely is **STRICTLY FORBIDDEN**.
- **Medical Critic Rollback Loop**: `_critic_branch` must track rollback count. After 2 failed revisions, route to `fallback`.
- **General Rule**: Every conditional edge must have a branch leading to `END` or `final_responder`.

### 3.4 Node Contracts
Each node function must follow this signature pattern:
```python
async def node_name(state_in: StateInput, ctx: NodeContext) -> LangGraphState:
```
- Nodes must NOT perform side effects outside the state object.
- Nodes must log their activation via `_activate_node(state, "node_name")`.
- Nodes must append `StreamUpdate` to `state.ui.partial_updates` for real-time UI feedback.

---

## 4. PubMed Integration Rules

### 4.1 API Compliance
- All requests to NCBI E-utilities MUST include `tool` and `email` parameters per NCBI usage policy.
- Default rate limit: **3 req/sec** without API key, **10 req/sec** with API key.
- Implement rate limiting via `asyncio.Semaphore` with sliding window timestamps.

### 4.2 Error Classification Hierarchy
All PubMed errors must inherit from `PubMedError(ToolingError)`:
- `PubMedRateLimitError` — HTTP 429 or rate limiter timeout
- `PubMedHTTPError` — Non-2xx responses
- `PubMedParseError` — XML/JSON parsing failures
- `PubMedEmptyResult` — Valid response but zero results

### 4.3 Return Format
Every PubMed method must return a structured object containing: `data`, `raw`, `warnings`, `metrics` (RTT, retry count), and `source`.

---

## 5. Qdrant Integration Rules

### 5.1 Point ID Format (CRITICAL)
- All Qdrant Point IDs **MUST** be generated using `uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}")`.
- Concatenated strings (like `"pmid-123-1"`) are **STRICTLY FORBIDDEN** — they cause 400 Bad Request errors.

### 5.2 API Compatibility (qdrant-client ≤ 1.16.2)
- Use `query_points()` instead of the deprecated `search()` method.
- **DO NOT** use unsupported arguments like `write_consistency`.
- Handle missing `WriteConsistency` attribute safely via `getattr(rest_models, 'WriteConsistency', None)`.
- Use `Distance` enum with **capitalized** values: `"Cosine"`, `"Euclid"`, `"Dot"` (NOT lowercase).

### 5.3 Collection Assurance
- Before ANY `upsert` or `query` operation, the wrapper MUST call `ensure_collection()`.
- `ensure_collection()` must detect 404 errors (including wrapped exceptions with `"Not found"` in string representation) and automatically create the collection.

### 5.4 Error Classification Hierarchy
All Qdrant errors must inherit from `QdrantError(ToolingError)`:
- `QdrantConnectivityError` — Connection refused or timeout
- `QdrantSchemaError` — Collection schema mismatch
- `QdrantConsistencyError` — Partial upsert failures
- `QdrantTimeoutError` — Operation timeout

### 5.5 Degradation Strategy
- Upsert failure: Return partial success records with failure details.
- Query failure: Return cached results with warning flags.
- Health check failure: Set `qdrant.health = "degraded"` to trigger orchestrator fallback.

---

## 6. Data Schema Rules

### 6.1 Pydantic Model Standards
- All models must extend `OrchestratorBaseModel` (which configures `arbitrary_types_allowed`, `validate_assignment`, `extra="ignore"`).
- Use `Field(default_factory=list)` for mutable defaults — NEVER use `[]` or `{}` directly.
- All `Literal` types must explicitly enumerate allowed values.

### 6.2 Required Schema Models (22 total)
The following models MUST exist in `src/orchestrator/schemas.py`:
`PlanStep`, `PubMedDocument`, `PubMedQueryLog`, `ToolCallMetric`, `VectorHit`, `BatchTelemetry`, `QdrantSearchRecord`, `ContextChunk`, `CriticFeedback`, `TaskStatus`, `ErrorSignal`, `FallbackEvent`, `StreamUpdate`, `UserQueryState`, `PlanningState`, `PubMedState`, `QdrantState`, `RagState`, `CriticState`, `TelemetryState`, `FallbackState`, `UIState`, `LangGraphState`.

---

## 7. Infrastructure Rules

### 7.1 Docker Compose
- Services: `qdrant` (ports 6333/6334) and `postgres` (port 5432).
- All services must have `healthcheck` configurations.
- Use named volumes (`qdrant_data`, `postgres_data`) for data persistence.
- Container names must be prefixed with `mars_`.

### 7.2 Testing Requirements
- All Tools (PubMed/Qdrant wrappers) MUST have corresponding `pytest` test scripts.
- Use `pytest-asyncio` for async test cases.
- Test coverage must include: success, rate limit, retry, parsing error, and empty result scenarios.

---

## 8. Security & Development Practices

### 8.1 Secrets Management
- NEVER hardcode API keys or passwords in source files.
- Use `pydantic-settings` to load from `.env` or system environment variables.
- `.env` must be listed in `.gitignore`.

### 8.2 Filesystem Tools
- AI Agents MUST use standard file writing APIs provided by the platform.
- Using `cat`, `echo`, or shell redirection (`>`, `>>`) inside bash commands to create or modify source files is **STRICTLY PROHIBITED**.

### 8.3 Logging & Observability
- Use `structlog` or standard `logging` with structured output.
- Every tool invocation must record: `tool`, `action`, `status`, `started_at`, `ended_at`, `latency_ms`, `retries`, `error`.
- All log entries within a request must share a `correlation_id`.
