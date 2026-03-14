# Task 007: Deployment & Quality Assurance (部署與品質保證)

**Phase:** 6
**Prerequisites:** Task 006 completed
**Constitution Reference:** §7.2, §8.3

---

## Objective
Create CI script, finalize test matrix, and verify all quality gates pass.

## Deliverables

### 1. `scripts/run_ci_checks.sh`
```bash
#!/bin/bash
set -e

echo "=== MARS CI Checks ==="

# 1. Lint
echo "[1/4] Running ruff..."
ruff check src/ tests/

# 2. Unit Tests
echo "[2/4] Running pytest..."
pytest tests/ -v --tb=short

# 3. Template Smoke Test
echo "[3/4] Checking FastAPI templates..."
python -c "from src.app.server import create_app; app = create_app(); print('App created OK')"

# 4. Correlation ID Smoke Test
echo "[4/4] Checking correlation ID generation..."
python -c "import uuid; print(f'Correlation ID: {uuid.uuid4()}')"

echo "=== All checks passed! ==="
```

### 2. QA Test Matrix Verification

| # | Scenario | Expected | Test File | Status |
|---|----------|----------|-----------|--------|
| 1 | Normal query (happy path) | `succeeded` | `test_app_e2e.py` | [ ] |
| 2 | PubMed empty result → 3 retries → fallback | `degraded` | `test_orchestrator.py` | [ ] |
| 3 | Qdrant unavailable → degraded pipeline | `degraded` | `test_qdrant_wrapper.py` | [ ] |
| 4 | Critic rejects → 2 rollbacks → fallback | `degraded` | `test_orchestrator.py` | [ ] |
| 5 | Invalid API request | HTTP 422 | `test_app_e2e.py` | [ ] |
| 6 | Schema validation (all 22 models) | Pass | `test_schemas.py` | [ ] |
| 7 | PubMed rate limit handling | `PubMedRateLimitError` | `test_pubmed_wrapper.py` | [ ] |
| 8 | UUID v5 ID format | Valid UUID | `test_qdrant_wrapper.py` | [ ] |

### 3. Final Documentation Check
- [ ] `README.md` created with project overview, setup instructions, and phase tracking
- [ ] All Spec Kit files present: `constitution.md`, `spec.md`, `plan.md`, `tasks/`
- [ ] `.env.example` documents all 14 variables
- [ ] `PROMPT.md` contains prompt engineering records

## Verification
```bash
# Full CI run
bash scripts/run_ci_checks.sh

# Manual E2E verification
uvicorn src.app.server:create_app --factory --port 8000 &
sleep 3
curl -N -s -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest treatments for type 2 diabetes?", "max_articles": 3}'
# Verify: NDJSON stream → status: succeeded → all tools: success
```

## Acceptance Criteria
- [ ] `ruff check` passes with zero errors
- [ ] All pytest tests pass (all test files)
- [ ] CI script completes successfully
- [ ] QA matrix: all 8 scenarios verified
- [ ] Manual E2E test returns `succeeded` status
- [ ] README.md is up to date
