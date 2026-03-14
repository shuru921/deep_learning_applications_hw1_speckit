# 技術實作計畫

**依據：** `spec.md` v2.0.0 與 `.specify/constitution.md`
**狀態：** 等待審核

---

## 1. 專案目錄結構

```
deep_learning_applications_hw1_speckit/
├── .specify/
│   ├── constitution.md          # 專案憲法 (英文)
│   └── constitution_zh_TW.md    # 專案憲法 (繁體中文)
├── spec.md                      # 核心規格書 (英文)
├── spec_zh_TW.md                # 核心規格書 (繁體中文)
├── plan.md                      # 技術計畫 (英文)
├── plan_zh_TW.md                # 本檔案
├── tasks/                       # 工作拆解 (下一個 SDD 階段)
│   ├── task_001_infra.md
│   ├── task_002_schema.md
│   ├── task_003_pubmed_wrapper.md
│   ├── task_004_qdrant_wrapper.md
│   ├── task_005_orchestrator.md
│   ├── task_006_ui_api.md
│   └── task_007_quality.md
├── .env.example                 # 環境變數範本
├── .gitignore
├── docker-compose.yml           # Qdrant + PostgreSQL
├── requirements.txt             # Python 依賴套件
├── pytest.ini
├── src/
│   ├── __init__.py
│   ├── app/                     # FastAPI 應用層
│   │   ├── __init__.py
│   │   ├── server.py            # create_app() 進入點
│   │   ├── deps.py              # 依賴注入與 graph 工廠
│   │   ├── routes.py            # API 路由 (/api/research, /ui)
│   │   ├── templates/
│   │   │   └── index.html       # Jinja2 UI 模板
│   │   └── static/
│   │       └── main.css
│   ├── orchestrator/            # LangGraph 狀態機
│   │   ├── __init__.py
│   │   ├── schemas.py           # 22 個 Pydantic 模型
│   │   └── graph.py             # 9 個節點、條件邊、圖建構器
│   └── clients/                 # 外部工具封裝
│       ├── __init__.py
│       ├── pubmed_wrapper.py    # PubMedWrapper (非同步)
│       └── qdrant_wrapper.py    # QdrantWrapper (非同步)
├── tests/
│   ├── __init__.py
│   ├── test_schemas.py
│   ├── test_pubmed_wrapper.py
│   ├── test_qdrant_wrapper.py
│   ├── test_orchestrator.py
│   └── test_app_e2e.py
└── scripts/
    └── run_ci_checks.sh         # Linter + pytest + 煙測
```

---

## 2. 分階段實作計畫

### 第一階段：基礎設施建置

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| Docker 配置 | `docker-compose.yml` | Qdrant (6333/6334) + PostgreSQL (5432)，含健康檢查 |
| 環境變數範本 | `.env.example` | 記錄全部 14 個環境變數 |
| Git 設定 | `.gitignore` | 排除 `.env`、`.venv/`、`__pycache__/` 等 |
| 依賴清單 | `requirements.txt` | 固定 `qdrant-client<1.17.0` |
| 虛擬環境 | `.venv/` | `python -m venv .venv && pip install -r requirements.txt` |

**驗證方式：**
```bash
docker compose up -d
curl -f http://localhost:6333/healthz              # Qdrant 健康檢查
docker exec mars_postgres pg_isready -U mars_admin # PostgreSQL 健康檢查
```

---

### 第二階段：Schema 設計 (22 個 Pydantic 模型)

| 交付物 | 檔案 | 模型數量 |
|--------|------|---------|
| 基底模型 | `src/orchestrator/schemas.py` | `OrchestratorBaseModel` (1) |
| 資料模型 | 同上 | `PlanStep` 等 13 個 |
| 狀態模型 | 同上 | `UserQueryState` 等 9 個 |
| 根狀態 | 同上 | `LangGraphState` 含 `touch()` 方法 (1) |

**關鍵限制（依據憲法 §6）：**
- 所有模型繼承 `OrchestratorBaseModel`
- 使用 `Field(default_factory=list)` 處理可變預設值
- 所有 `Literal` 型別必須明確列舉允許值
- 支援 Pydantic v1/v2 雙版本相容

**驗證方式：**
```bash
pytest tests/test_schemas.py -v
```

---

### 第三階段：核心工具封裝 — PubMed Wrapper

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| 封裝類別 | `src/clients/pubmed_wrapper.py` | `PubMedWrapper` 含 4 個公開非同步方法 |
| 錯誤類別 | 同上 | `PubMedError` → 4 個子類別 |
| 資料模型 | 同上 | `PubMedQuery`、`PubMedSearchResult`、`PubMedBatch`、`PubMedSummary` |
| 單元測試 | `tests/test_pubmed_wrapper.py` | 覆蓋：成功、速率限制、重試、解析錯誤、空結果 |

**關鍵限制（依據憲法 §4）：**
- 所有請求包含 `tool` + `email` 參數
- 速率限制：3 req/sec (無金鑰) / 10 req/sec (有金鑰)
- 回傳結構化物件含 `data`、`raw`、`warnings`、`metrics`、`source`

**驗證方式：**
```bash
pytest tests/test_pubmed_wrapper.py -v
```

---

### 第三階段 b：核心工具封裝 — Qdrant Wrapper

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| 封裝類別 | `src/clients/qdrant_wrapper.py` | `QdrantWrapper` 含 5 個公開非同步方法 |
| 錯誤類別 | 同上 | `QdrantError` → 4 個子類別 |
| 單元測試 | `tests/test_qdrant_wrapper.py` | 覆蓋：ensure_collection、upsert、query、delete、healthcheck |

**關鍵限制（依據憲法 §5）：**
- Point ID 透過 `uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}")` 生成
- 使用 `query_points()`（**禁止** `search()`）
- 遇到 404 時自動建立集合
- Distance 列舉：`"Cosine"`（首字母大寫）

**驗證方式：**
```bash
pytest tests/test_qdrant_wrapper.py -v
```

---

### 第四階段：LangGraph Orchestrator

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| 圖建構器 | `src/orchestrator/graph.py` | `build_medical_research_graph()` 函式 |
| 9 個節點函式 | 同上 | `planner`、`pubmed_search`、`result_normalizer`、`qdrant_upsert`、`qdrant_search`、`rag_synthesizer`、`medical_critic`、`fallback_recovery`、`final_responder` |
| 條件邊 | 同上 | `_pubmed_branch` (最多 3 次重試)、`_critic_branch` (最多 2 次回滾) |
| 節點上下文 | 同上 | `NodeContext` dataclass 用於依賴注入 |
| 單元測試 | `tests/test_orchestrator.py` | 覆蓋：正向流程、PubMed 空結果 → 降級、Critic 駁回 → 回滾 |

**關鍵限制（依據憲法 §3）：**
- `recursion_limit = 30` 為必設項目
- 每個條件邊都必須有通往 `END` 或 `final_responder` 的分支
- 每個節點呼叫 `state.touch()` + `_activate_node()` + 附加 `StreamUpdate`

**驗證方式：**
```bash
pytest tests/test_orchestrator.py -v
```

---

### 第五階段：UI 與 API 整合

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| FastAPI 應用 | `src/app/server.py` | `create_app()` 含生命週期與中介軟體 |
| 依賴注入 | `src/app/deps.py` | Graph 工廠、Qdrant/PubMed 客戶端注入 |
| 路由 | `src/app/routes.py` | `POST /api/research` (NDJSON 串流)、`GET /ui` |
| 模板 | `src/app/templates/index.html` | 查詢表單搭配 SSE 渲染 |
| 樣式 | `src/app/static/main.css` | 現代響應式設計 |
| E2E 測試 | `tests/test_app_e2e.py` | 覆蓋：串流驗證、complete 事件、降級回應 |

**NDJSON 事件協議：**
```
update → 各個區段 (segment) 的進度訊息
summary → 遥測數據 + 工具呼叫指標
complete → 最終狀態 + correlation_id
```

**驗證方式：**
```bash
uvicorn src.app.server:create_app --factory --port 8000 &
curl -N -s -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "diabetes", "max_articles": 1}'
# 預期：NDJSON 串流包含 update → summary → complete
pytest tests/test_app_e2e.py -v
```

---

### 第六階段：部署與品質保證

| 交付物 | 檔案 | 說明 |
|--------|------|------|
| CI 腳本 | `scripts/run_ci_checks.sh` | `ruff check` + `pytest` + 煙測 |
| 品質設定 | `pytest.ini` | 測試設定 |

**QA 測試矩陣：**

| 場景 | 預期狀態 | 驗證方式 |
|------|---------|----------|
| 正常查詢 | `succeeded` | E2E 測試 |
| PubMed 空結果 (>3 次重試) | `degraded` 含降級事件 | Orchestrator 測試 |
| Qdrant 不可用 | `degraded` 含警告 | Qdrant wrapper 測試 |
| Critic 駁回 (>2 次) | `degraded` 含審查發現 | Orchestrator 測試 |
| 無效查詢 | 錯誤回應 | E2E 測試 |

**驗證方式：**
```bash
bash scripts/run_ci_checks.sh
```

---

## 3. 依賴安裝順序

```bash
# 1. 建立虛擬環境
python -m venv .venv
source .venv/bin/activate

# 2. 安裝依賴
pip install --upgrade pip
pip install -r requirements.txt

# 3. 啟動基礎設施
docker compose up -d

# 4. 驗證
curl -f http://localhost:6333/healthz
pytest --co  # 收集測試但不執行
```

---

## 4. 風險緩解策略 (來自前次開發的教訓)

| 風險 | 緩解措施 | 憲法參考 |
|------|---------|----------|
| LangGraph 無限遞迴 | 硬性重試限制 (3) + recursion_limit (30) | §3.2、§3.3 |
| Qdrant 400 Bad Request (ID 格式) | UUID v5 生成，禁止字串拼接 | §5.1 |
| Qdrant API 不相容 | 固定 `qdrant-client<1.17.0`，使用 `query_points()` | §5.2 |
| PubMed 速率限制違規 | `asyncio.Semaphore` 搭配滑動視窗 | §4.1 |
| 機密資料外洩 | `pydantic-settings` + `.env` | §8.1 |
