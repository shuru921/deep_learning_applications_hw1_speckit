#!/bin/bash
set -e

echo "=== MARS CI Checks ==="

# 1. Lint
echo "[1/3] Running ruff..."
ruff check src/ tests/ --ignore E501 || echo "Lint warnings (non-blocking)"

# 2. Unit Tests
echo "[2/3] Running pytest..."
python -m pytest tests/ -v --tb=short

# 3. App Import Smoke Test
echo "[3/3] Checking FastAPI app creation..."
python -c "from src.app.server import create_app; app = create_app(); print(f'App created: {app.title}')"

echo "=== All checks passed! ==="
