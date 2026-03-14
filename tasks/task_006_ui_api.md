# Task 006: UI & API Integration (UI 與 API 整合)

**Phase:** 5
**Prerequisites:** Task 005 completed
**Constitution Reference:** §2.2, §2.4, §3.2

---

## Objective
Implement FastAPI application with NDJSON streaming endpoint, Jinja2 UI, and dependency injection.

## Deliverables

### 1. `src/app/server.py`
```python
def create_app() -> FastAPI:
    """Application factory with lifespan management."""
    # - Load settings from .env via pydantic-settings
    # - Register routes
    # - Mount static files
    # - Configure Jinja2 templates
    # - Setup CORS middleware if needed
```

### 2. `src/app/deps.py`
- `OrchestratorConfig`: Settings dataclass loaded from environment
- `create_default_graph_factory()`: Instantiate PubMed/Qdrant clients → NodeContext → build graph
- **Qdrant Distance**: Must use `.capitalize()` (e.g., `"Cosine"`, NOT `"cosine"`)

### 3. `src/app/routes.py`

**Streaming Endpoint:**
```python
@router.post("/api/research")
async def api_research(request: ResearchRequest) -> StreamingResponse:
    # 1. Build graph from factory
    # 2. Execute graph.astream() with recursion_limit=30
    # 3. Yield NDJSON events: update → summary → complete
```

**UI Endpoint:**
```python
@router.get("/ui")
async def ui_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})
```

**NDJSON Event Format:**
```jsonc
// Progress updates (multiple)
{"event": "update", "segment": "planner", "content": "正在規劃搜尋策略...", "created_at": "..."}

// Final answer (one)
{"event": "update", "segment": "final", "final": true, "content": "研究總結...", "created_at": "..."}

// Telemetry summary (one)
{"event": "summary", "status": "succeeded", "telemetry": {...}, "correlation_id": "..."}

// Completion signal (one)
{"event": "complete", "status": "succeeded", "correlation_id": "..."}
```

**Critical: Recursion Limit:**
```python
async for snapshot in graph.astream(
    initial_state,
    config={"recursion_limit": 30}  # MANDATORY per Constitution §3.2
):
```

### 4. `src/app/templates/index.html`
- Query input form
- Submit button triggers `fetch()` to `/api/research`
- Parse NDJSON stream line-by-line
- Display progress updates and final answer
- Show telemetry summary

### 5. `src/app/static/main.css`
- Modern, responsive design
- Progress indicator styling
- Result card layout

### 6. `tests/test_app_e2e.py`
Test cases:
- ✅ `POST /api/research` returns streaming response
- ✅ Stream contains `update` events
- ✅ Stream ends with `complete` event with `status: "succeeded"`
- ✅ `GET /ui` returns 200 with HTML content
- ❌ Invalid request body returns 422

## Verification
```bash
# Start server
uvicorn src.app.server:create_app --factory --port 8000 &

# Test streaming
curl -N -s -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "diabetes", "max_articles": 1}'

# Run E2E tests
pytest tests/test_app_e2e.py -v
```

## Acceptance Criteria
- [ ] `create_app()` factory pattern works
- [ ] `/api/research` returns NDJSON stream
- [ ] Stream contains update → summary → complete events
- [ ] `recursion_limit=30` is set in graph execution
- [ ] `/ui` renders Jinja2 template
- [ ] All 5 E2E test cases pass
