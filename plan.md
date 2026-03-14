# Technical Implementation Plan (技術實作計畫)

**Based on:** `spec.md` v2.0.0 & `.specify/constitution.md`
**Status:** Awaiting Review

---

## 1. Project Directory Structure

```
deep_learning_applications_hw1_speckit/
├── .specify/
│   ├── constitution.md          # Project constitution (EN)
│   └── constitution_zh_TW.md    # Project constitution (ZH-TW)
├── spec.md                      # Core specification (EN)
├── spec_zh_TW.md                # Core specification (ZH-TW)
├── plan.md                      # This file
├── plan_zh_TW.md                # This file (ZH-TW)
├── tasks/                       # Task breakdown (next SDD phase)
│   ├── task_001_infra.md
│   ├── task_002_schema.md
│   ├── task_003_pubmed_wrapper.md
│   ├── task_004_qdrant_wrapper.md
│   ├── task_005_orchestrator.md
│   ├── task_006_ui_api.md
│   └── task_007_quality.md
├── .env.example                 # Environment variable template
├── .gitignore
├── docker-compose.yml           # Qdrant + PostgreSQL
├── requirements.txt             # Python dependencies
├── pytest.ini
├── src/
│   ├── __init__.py
│   ├── app/                     # FastAPI application layer
│   │   ├── __init__.py
│   │   ├── server.py            # create_app() entry point
│   │   ├── deps.py              # Dependency injection & graph factory
│   │   ├── routes.py            # API routes (/api/research, /ui)
│   │   ├── templates/
│   │   │   └── index.html       # Jinja2 UI template
│   │   └── static/
│   │       └── main.css
│   ├── orchestrator/            # LangGraph state machine
│   │   ├── __init__.py
│   │   ├── schemas.py           # 22 Pydantic models
│   │   └── graph.py             # 9 nodes, conditional edges, graph builder
│   └── clients/                 # External tool wrappers
│       ├── __init__.py
│       ├── pubmed_wrapper.py    # PubMedWrapper (async)
│       └── qdrant_wrapper.py    # QdrantWrapper (async)
├── tests/
│   ├── __init__.py
│   ├── test_schemas.py
│   ├── test_pubmed_wrapper.py
│   ├── test_qdrant_wrapper.py
│   ├── test_orchestrator.py
│   └── test_app_e2e.py
└── scripts/
    └── run_ci_checks.sh         # Linter + pytest + smoke tests
```

---

## 2. Phase-by-Phase Implementation Plan

### Phase 1: Infrastructure Setup

| Deliverable | File | Description |
|-------------|------|-------------|
| Docker Compose | `docker-compose.yml` | Qdrant (6333/6334) + PostgreSQL (5432) with healthchecks |
| Environment Template | `.env.example` | All 14 env vars documented |
| Git Config | `.gitignore` | Exclude `.env`, `.venv/`, `__pycache__/`, etc. |
| Dependencies | `requirements.txt` | Pin `qdrant-client<1.17.0` |
| Virtual Environment | `.venv/` | `python -m venv .venv && pip install -r requirements.txt` |

**Verification:**
```bash
docker compose up -d
curl -f http://localhost:6333/healthz           # Qdrant health
docker exec mars_postgres pg_isready -U mars_admin  # PostgreSQL health
```

---

### Phase 2: Schema Design (22 Pydantic Models)

| Deliverable | File | Models Count |
|-------------|------|-------------|
| Base Model | `src/orchestrator/schemas.py` | `OrchestratorBaseModel` (1) |
| Data Models | same file | `PlanStep`, `PubMedDocument`, `PubMedQueryLog`, `ToolCallMetric`, `VectorHit`, `BatchTelemetry`, `QdrantSearchRecord`, `ContextChunk`, `CriticFeedback`, `TaskStatus`, `ErrorSignal`, `FallbackEvent`, `StreamUpdate` (13) |
| State Models | same file | `UserQueryState`, `PlanningState`, `PubMedState`, `QdrantState`, `RagState`, `CriticState`, `TelemetryState`, `FallbackState`, `UIState` (9) |
| Root State | same file | `LangGraphState` with `touch()` method (1) |

**Key Constraints (from Constitution §6):**
- All models extend `OrchestratorBaseModel`
- Use `Field(default_factory=list)` for mutable defaults
- All `Literal` types must enumerate allowed values
- Support Pydantic v1/v2 compatibility via `ConfigDict` detection

**Verification:**
```bash
pytest tests/test_schemas.py -v
```

---

### Phase 3: Core Tooling — PubMed Wrapper

| Deliverable | File | Description |
|-------------|------|-------------|
| Wrapper Class | `src/clients/pubmed_wrapper.py` | `PubMedWrapper` with 4 public async methods |
| Error Classes | same file | `PubMedError` → 4 subclasses |
| Data Models | same file | `PubMedQuery`, `PubMedSearchResult`, `PubMedBatch`, `PubMedSummary` |
| Unit Tests | `tests/test_pubmed_wrapper.py` | Cover: success, rate limit, retry, parse error, empty result |

**Key Constraints (from Constitution §4):**
- All requests include `tool` + `email` params
- Rate limiting: 3 req/sec (no key) / 10 req/sec (with key)
- Return structured objects with `data`, `raw`, `warnings`, `metrics`, `source`

**Verification:**
```bash
pytest tests/test_pubmed_wrapper.py -v
```

---

### Phase 3b: Core Tooling — Qdrant Wrapper

| Deliverable | File | Description |
|-------------|------|-------------|
| Wrapper Class | `src/clients/qdrant_wrapper.py` | `QdrantWrapper` with 5 public async methods |
| Error Classes | same file | `QdrantError` → 4 subclasses |
| Unit Tests | `tests/test_qdrant_wrapper.py` | Cover: ensure_collection, upsert, query, delete, healthcheck |

**Key Constraints (from Constitution §5):**
- Point IDs via `uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}")`
- Use `query_points()` (NOT `search()`)
- Auto-create collection on 404
- Distance enum: `"Cosine"` (capitalized)

**Verification:**
```bash
pytest tests/test_qdrant_wrapper.py -v
```

---

### Phase 4: LangGraph Orchestrator

| Deliverable | File | Description |
|-------------|------|-------------|
| Graph Builder | `src/orchestrator/graph.py` | `build_medical_research_graph()` function |
| 9 Node Functions | same file | `planner`, `pubmed_search`, `result_normalizer`, `qdrant_upsert`, `qdrant_search`, `rag_synthesizer`, `medical_critic`, `fallback_recovery`, `final_responder` |
| Conditional Edges | same file | `_pubmed_branch` (max 3 retries), `_critic_branch` (max 2 rollbacks) |
| Node Context | same file | `NodeContext` dataclass for dependency injection |
| Unit Tests | `tests/test_orchestrator.py` | Cover: happy path, PubMed empty → fallback, critic rejection → rollback |

**Key Constraints (from Constitution §3):**
- `recursion_limit = 30` mandatory
- Every conditional edge has guaranteed exit to `END` or `final_responder`
- Every node calls `state.touch()` + `_activate_node()` + appends `StreamUpdate`

**Verification:**
```bash
pytest tests/test_orchestrator.py -v
```

---

### Phase 5: UI & API Integration

| Deliverable | File | Description |
|-------------|------|-------------|
| FastAPI App | `src/app/server.py` | `create_app()` with lifespan, middleware |
| Dependencies | `src/app/deps.py` | Graph factory, Qdrant/PubMed client injection |
| Routes | `src/app/routes.py` | `POST /api/research` (NDJSON stream), `GET /ui` |
| Template | `src/app/templates/index.html` | Query form with SSE rendering |
| Styles | `src/app/static/main.css` | Modern responsive design |
| E2E Tests | `tests/test_app_e2e.py` | Cover: streaming, complete event, degraded response |

**NDJSON Event Protocol:**
```
update → progress messages per segment
summary → telemetry + tool invocation metrics
complete → final status + correlation_id
```

**Verification:**
```bash
uvicorn src.app.server:create_app --factory --port 8000 &
curl -N -s -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "diabetes", "max_articles": 1}'
# Expect: NDJSON stream with update → summary → complete
pytest tests/test_app_e2e.py -v
```

---

### Phase 6: Deployment & Quality Assurance

| Deliverable | File | Description |
|-------------|------|-------------|
| CI Script | `scripts/run_ci_checks.sh` | `ruff check` + `pytest` + smoke tests |
| Quality Config | `pytest.ini` | Test configuration |

**QA Test Matrix:**

| Scenario | Expected Status | Verified By |
|----------|----------------|-------------|
| Normal query | `succeeded` | E2E test |
| PubMed empty (>3 retries) | `degraded` with fallback | Orchestrator test |
| Qdrant unavailable | `degraded` with warning | Qdrant wrapper test |
| Critic rejects (>2 times) | `degraded` with critic findings | Orchestrator test |
| Invalid query | Error response | E2E test |

**Verification:**
```bash
bash scripts/run_ci_checks.sh
```

---

## 3. Dependency Installation Order

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Start infrastructure
docker compose up -d

# 4. Verify
curl -f http://localhost:6333/healthz
pytest --co  # collect tests without running
```

---

## 4. Risk Mitigation (Lessons from Previous Build)

| Risk | Mitigation | Constitution Reference |
|------|-----------|----------------------|
| Infinite recursion in LangGraph | Hard retry limit (3) + recursion_limit (30) | §3.2, §3.3 |
| Qdrant 400 Bad Request on IDs | UUID v5 generation, never string concatenation | §5.1 |
| Qdrant API incompatibility | Pin `qdrant-client<1.17.0`, use `query_points()` | §5.2 |
| PubMed rate limit violations | `asyncio.Semaphore` with sliding window | §4.1 |
| Hardcoded secrets | `pydantic-settings` + `.env` | §8.1 |
