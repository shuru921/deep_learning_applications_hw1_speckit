# Task 001: Infrastructure Setup (基礎設施建置)

**Phase:** 1
**Prerequisites:** None
**Constitution Reference:** §7.1, §2.4, §8.1

---

## Objective
Set up the project skeleton, Docker services (Qdrant + PostgreSQL), environment variable template, dependency file, and Git configuration.

## Deliverables

### 1. `.gitignore`
```
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
*.log
*.jsonl
```

### 2. `.env.example`
Must document all 14 environment variables as defined in `spec.md §7.2`.

### 3. `docker-compose.yml`
- Service `mars_qdrant`: image `qdrant/qdrant:latest`, ports 6333/6334, healthcheck via `/healthz`, named volume `qdrant_data`
- Service `mars_postgres`: image `postgres:15-alpine`, port 5432, healthcheck via `pg_isready`, named volume `postgres_data`
- Both on `mars_net` bridge network

### 4. `requirements.txt`
```
fastapi
uvicorn[standard]
httpx
langgraph
langchain
langchain-core
qdrant-client<1.17.0
pydantic
pydantic-settings
python-dotenv
jinja2
python-multipart
pytest
pytest-asyncio
pytest-anyio
ruff
```

### 5. `pytest.ini`
```ini
[pytest]
asyncio_mode = auto
```

### 6. Package Init Files
Create empty `__init__.py` in: `src/`, `src/app/`, `src/orchestrator/`, `src/clients/`, `tests/`

### 7. Directory Structure
Create empty directories: `src/app/templates/`, `src/app/static/`, `scripts/`, `tasks/`

## Verification
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
sleep 5
curl -f http://localhost:6333/healthz
docker exec mars_postgres pg_isready -U mars_admin
```

## Acceptance Criteria
- [ ] All files created as specified
- [ ] `pip install` completes without errors
- [ ] Qdrant healthcheck returns 200
- [ ] PostgreSQL ready check passes
