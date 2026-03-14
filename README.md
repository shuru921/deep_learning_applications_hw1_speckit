# 🩺 MARS — Multi-Agent Medical Research System

> AI 驅動的多代理醫療文獻研究與分析平台

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestrator-purple)](https://langchain-ai.github.io/langgraph/)
[![Tests](https://img.shields.io/badge/Tests-50%20passed-brightgreen)]()

## 📖 專案簡介

MARS 是一個基於 **Spec-Driven Development (SDD)** 方法建構的醫學文獻研究系統。

系統透過 **LangGraph 狀態機**編排 9 個 AI 代理節點，自動完成：

1. **查詢分解** — 過濾停用詞，提取醫學關鍵字
2. **PubMed 搜尋** — 即時檢索最新醫學文獻
3. **向量化儲存** — 將文獻嵌入 Qdrant 向量資料庫
4. **RAG 合成** — 基於檢索結果生成摘要
5. **醫療審查** — 自動評估內容可信度（trust score）
6. **降級復原** — 當任何環節失敗時，自動觸發 fallback 機制

## 🏗️ 系統架構

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│   Browser   │────▶│  FastAPI (NDJSON Streaming)               │
│   /ui       │◀────│  POST /api/research                       │
└─────────────┘     └──────────────┬───────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────┐
                    │         LangGraph StateGraph              │
                    │                                           │
                    │  planner → pubmed_search → normalizer     │
                    │              ↑ retry(≤3)                  │
                    │           → qdrant_upsert → qdrant_search │
                    │           → rag_synthesizer               │
                    │           → medical_critic                │
                    │              ↑ revise(≤2)                 │
                    │           → final_responder               │
                    │                                           │
                    │  fallback_recovery (forced after limits)  │
                    └──────────────┬──────────┬────────────────┘
                                   │          │
                    ┌──────────────▼──┐  ┌───▼──────────────┐
                    │  PubMed E-utils  │  │  Qdrant Vector   │
                    │  (NCBI API)      │  │  Database         │
                    └─────────────────┘  └──────────────────┘
```

## 🚀 快速開始

### 前置需求

- Python 3.9+
- Docker Desktop（用於 Qdrant + PostgreSQL）

### 安裝

```bash
# 1. 複製專案
git clone https://github.com/shuru921/deep_learning_applications_hw1_speckit.git
cd deep_learning_applications_hw1_speckit

# 2. 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 設定環境變數
cp .env.example .env
# 編輯 .env，填入你的 PubMed API Key 和 Email
```

### 啟動服務

```bash
# 啟動 Qdrant + PostgreSQL
docker compose up -d

# 啟動 MARS 伺服器
uvicorn src.app.server:create_app --factory --port 8000 --reload
```

### 使用

- **Web UI**: 開啟 [http://localhost:8000/ui](http://localhost:8000/ui)
- **API**:
  ```bash
  curl -N -s -X POST http://localhost:8000/api/research \
    -H "Content-Type: application/json" \
    -d '{"query": "SGLT2 inhibitors heart failure", "max_articles": 3}'
  ```

## 📁 專案結構

```
.
├── .specify/                    # SDD 規格文件
│   ├── constitution.md          # 專案憲法（英文）
│   └── constitution_zh_TW.md    # 專案憲法（繁體中文）
├── src/
│   ├── app/                     # FastAPI 應用層
│   │   ├── server.py            # 應用工廠
│   │   ├── deps.py              # 依賴注入 + Graph 工廠
│   │   ├── routes.py            # API 路由（NDJSON 串流）
│   │   ├── templates/           # Jinja2 UI 模板
│   │   └── static/              # CSS 靜態檔案
│   ├── orchestrator/            # LangGraph 狀態機
│   │   ├── schemas.py           # 22 個 Pydantic 模型
│   │   └── graph.py             # 9 節點 + 條件邊
│   └── clients/                 # 外部 API 封裝
│       ├── pubmed_wrapper.py    # PubMed E-utilities
│       └── qdrant_wrapper.py    # Qdrant 向量資料庫
├── tests/                       # 單元測試（50 個）
├── tasks/                       # SDD 工作包（7 個）
├── scripts/
│   └── run_ci_checks.sh         # CI 腳本
├── spec.md / spec_zh_TW.md      # 技術規格
├── plan.md / plan_zh_TW.md      # 實作計畫
├── docker-compose.yml           # Qdrant + PostgreSQL
└── requirements.txt             # Python 依賴
```

## 🧪 測試

```bash
# 所有測試
python -m pytest tests/ -v

# CI 完整檢查（lint + test + smoke test）
bash scripts/run_ci_checks.sh
```

```
50 passed in 0.96s
App created: MARS - Multi-Agent Medical Research System
=== All checks passed! ===
```

## ⚙️ 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `PUBMED_API_KEY` | NCBI API Key | （空） |
| `PUBMED_EMAIL` | NCBI 帳號 Email | （空） |
| `PUBMED_TOOL_NAME` | 工具名稱 | `mars-test-suite` |
| `QDRANT_HOST` | Qdrant 主機 | `localhost` |
| `QDRANT_PORT` | Qdrant 埠號 | `6333` |
| `QDRANT_COLLECTION` | 集合名稱 | `mars-test` |

完整清單見 [.env.example](.env.example)。

## 🔑 關鍵設計

| 決策 | 說明 |
|------|------|
| **UUID v5** | Qdrant Point ID 使用 `uuid5` 生成，避免 400 Bad Request |
| **query_points()** | 使用新 API 取代棄用的 `search()`（qdrant-client ≤1.16.2） |
| **recursion_limit=30** | 防止 LangGraph 無限遞迴 |
| **PubMed retry ≤ 3** | 空結果最多重試 3 次，超過則強制降級 |
| **Critic rollback ≤ 2** | 醫療審查最多回滾 2 次 |
| **Stop words 過濾** | 移除停用詞以提高 PubMed 搜尋品質 |
| **NDJSON 串流** | 即時回饋各節點執行進度 |

## 📚 SDD 開發方法

本專案遵循 **Specification-Driven Development** 生命週期：

```
Specify → Plan → Task → Implement → Verify → Deploy
```

詳見 `spec.md`、`plan.md`、`tasks/` 目錄。

## 📄 License

MIT
