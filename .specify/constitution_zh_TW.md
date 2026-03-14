# MARS 專案憲法

本憲法定義了多代理醫學文獻助理 (MARS) 專案的**不可妥協的規則**、架構原則與程式碼規範。**所有的 AI 代理人在產生任何程式碼或執行任務之前，必須嚴格遵守這些規則。**

---

## 1. 核心原則

### 1.1 規格即源碼 (Spec-as-Source)
`spec.md` 檔案是**最終的真實來源 (Single Source of Truth)**。如果實作過程需要偏離規格，**必須**先更新規格書並取得批准。絕對不允許未經核准的擅自修改。

### 1.2 優雅降級 (Fail Gracefully)
每一次呼叫外部 API (PubMed、Qdrant、PostgreSQL) 都必須具備錯誤處理機制與後備策略。系統在遇到錯誤時必須優雅地降級（回傳 `"Degraded"` 狀態），而不是直接崩潰或陷入死循環。

### 1.3 分階段開發 (Phase-Driven Development)
程式碼必須依照嚴格的階段開發（基礎設施 → Schema → 工具封裝 → Orchestrator → UI → 品質保證）。**不允許跳過前置階段。** 每個階段必須通過驗證才能開始下一階段。

### 1.4 模組化與去耦合 (Modularity & Decoupling)
代理人邏輯、資料庫操作、API 路由與資料流水線必須**完全分離**成獨立模組。嚴格禁止將業務邏輯寫在單一個大檔案中。

---

## 2. 技術堆疊與規則

### 2.1 語言與執行環境
- **Python 版本**：嚴格使用 Python 3.10 或以上版本，並搭配 `from __future__ import annotations`。
- **套件管理**：使用 `pip` 搭配 `requirements.txt`。關鍵套件必須固定版本上限（例如 `qdrant-client<1.17.0`）。

### 2.2 非同步 I/O
- 所有涉及 I/O 阻擋的操作**必須**使用 `asyncio` 以及非同步版本的函式庫。
- 使用 `httpx.AsyncClient`（**禁止**使用 `requests`）。使用 `AsyncQdrantClient`（**禁止**使用同步版 `QdrantClient`）。
- 使用 `asyncio.gather` 來平行執行工具呼叫（例如 PubMed 取得資料 + Qdrant upsert 同時進行）。
- 使用 `asyncio.TaskGroup` 來管理長時操作，以支援取消與進度追蹤。

### 2.3 型別安全
- 所有函式簽章與複雜變數 **100% 必須**具備嚴格的型別提示。
- 大量使用 `pydantic.BaseModel` (v2) 來進行資料驗證與序列化。
- 透過 `ConfigDict` 偵測模式支援 Pydantic v1 降級（參見 `schemas.py`）。
- **絕對禁止**在 LangGraph 狀態物件中使用 `typing.Any` 或原生 `dict` 來規避型別驗證。

### 2.4 配置管理
- 使用 `pydantic-settings` 搭配 `python-dotenv` 從 `.env` 載入所有設定。
- **絕對禁止**在程式碼中硬編碼 API 金鑰、密碼、主機名稱或通訊埠號碼。
- 所有環境變數必須記錄在 `.env.example` 中。

---

## 3. LangGraph 協調器嚴格準則

### 3.1 狀態機完整性
- 所有狀態物件必須嚴格遵守 `src/orchestrator/schemas.py` 中定義的 `LangGraphState` Pydantic 模型。
- 根狀態必須包含以下子狀態：`user_query`、`planning`、`pubmed`、`qdrant`、`rag`、`critic`、`telemetry`、`fallback`、`ui`、`extensions`。
- 每個節點函式在回傳之前都必須呼叫 `state.touch()` 來更新 `updated_at`。

### 3.2 遞迴限制 (必須設定)
- 在 `CompiledGraph` 執行器層級**必須**設定嚴格的 `recursion_limit`。**預設值：30。**
- 在沒有安全閥的情況下，不允許執行任何 Graph。
- 限制在 `src/app/routes.py` 中透過 `graph.astream(config={"recursion_limit": 30})` 配置。

### 3.3 分支安全 (關鍵規則)
所有的 `add_conditional_edges` 邏輯**必須**包含保證能退出的條件：
- **PubMed 空結果迴圈**：`_pubmed_branch` 必須強制執行**上限 3 次**的硬性重試限制。當 `pubmed.empty_retry_count >= 3` 時，分支**必須**導向 `fallback` 或 `final_responder`。無限制地重新導回 `planner` 是**嚴格禁止**的。
- **Medical Critic 回滾迴圈**：`_critic_branch` 必須追蹤回滾次數。2 次修訂仍失敗後，必須導向 `fallback`。
- **通用規則**：每個條件邊都必須有一條分支通往 `END` 或 `final_responder`。

### 3.4 節點契約
每個節點函式必須遵循此簽章模式：
```python
async def node_name(state_in: StateInput, ctx: NodeContext) -> LangGraphState:
```
- 節點不得在狀態物件之外執行副作用。
- 節點必須透過 `_activate_node(state, "node_name")` 記錄其啟動。
- 節點必須將 `StreamUpdate` 附加到 `state.ui.partial_updates` 以提供即時 UI 回饋。

---

## 4. PubMed 整合規則

### 4.1 API 合規性
- 所有對 NCBI E-utilities 的請求**必須**包含 `tool` 和 `email` 參數，以符合 NCBI 使用政策。
- 預設速率限制：無 API 金鑰時 **3 req/sec**，有 API 金鑰時 **10 req/sec**。
- 透過 `asyncio.Semaphore` 搭配滑動視窗時間戳實作速率限制。

### 4.2 錯誤分類階層
所有 PubMed 錯誤必須繼承自 `PubMedError(ToolingError)`：
- `PubMedRateLimitError` — HTTP 429 或速率限制器逾時
- `PubMedHTTPError` — 非 2xx 回應
- `PubMedParseError` — XML/JSON 解析失敗
- `PubMedEmptyResult` — 有效回應但零筆結果

### 4.3 回傳格式
每個 PubMed 方法都必須回傳包含以下欄位的結構化物件：`data`、`raw`、`warnings`、`metrics`（RTT、重試次數）以及 `source`。

---

## 5. Qdrant 整合規則

### 5.1 Point ID 格式 (關鍵規則)
- 所有 Qdrant Point ID **必須**使用 `uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}")` 生成。
- 字串拼接（如 `"pmid-123-1"`）**嚴格禁止** — 這會導致 400 Bad Request 錯誤。

### 5.2 API 相容性 (qdrant-client ≤ 1.16.2)
- 使用 `query_points()` 替代已棄用的 `search()` 方法。
- **禁止**使用不支援的引數，如 `write_consistency`。
- 透過 `getattr(rest_models, 'WriteConsistency', None)` 安全處理缺失的 `WriteConsistency` 屬性。
- `Distance` 列舉使用**首字母大寫**的值：`"Cosine"`、`"Euclid"`、`"Dot"`（**不是**小寫）。

### 5.3 確保集合存在 (Collection Assurance)
- 在執行任何 `upsert` 或 `query` 操作之前，封裝層**必須**呼叫 `ensure_collection()`。
- `ensure_collection()` 必須偵測 404 錯誤（包括字串中包含 `"Not found"` 的封裝例外），並自動建立集合。

### 5.4 錯誤分類階層
所有 Qdrant 錯誤必須繼承自 `QdrantError(ToolingError)`：
- `QdrantConnectivityError` — 連線被拒或逾時
- `QdrantSchemaError` — 集合 Schema 不匹配
- `QdrantConsistencyError` — 部分 upsert 失敗
- `QdrantTimeoutError` — 操作逾時

### 5.5 降級策略
- Upsert 失敗：回傳部分成功記錄與失敗明細。
- Query 失敗：回傳快取結果並附帶警告旗標。
- 健康檢查失敗：設定 `qdrant.health = "degraded"` 以觸發 Orchestrator 後備策略。

---

## 6. 資料 Schema 規則

### 6.1 Pydantic 模型標準
- 所有模型必須繼承 `OrchestratorBaseModel`（已配置 `arbitrary_types_allowed`、`validate_assignment`、`extra="ignore"`）。
- 對可變預設值使用 `Field(default_factory=list)` — **絕對禁止**直接使用 `[]` 或 `{}`。
- 所有 `Literal` 型別必須明確列舉允許的值。

### 6.2 必要的 Schema 模型 (共 22 個)
以下模型**必須**存在於 `src/orchestrator/schemas.py`：
`PlanStep`、`PubMedDocument`、`PubMedQueryLog`、`ToolCallMetric`、`VectorHit`、`BatchTelemetry`、`QdrantSearchRecord`、`ContextChunk`、`CriticFeedback`、`TaskStatus`、`ErrorSignal`、`FallbackEvent`、`StreamUpdate`、`UserQueryState`、`PlanningState`、`PubMedState`、`QdrantState`、`RagState`、`CriticState`、`TelemetryState`、`FallbackState`、`UIState`、`LangGraphState`。

---

## 7. 基礎設施規則

### 7.1 Docker Compose
- 服務：`qdrant`（通訊埠 6333/6334）與 `postgres`（通訊埠 5432）。
- 所有服務都必須具備 `healthcheck` 配置。
- 使用命名 Volume（`qdrant_data`、`postgres_data`）進行資料持久化。
- 容器名稱必須以 `mars_` 為前綴。

### 7.2 測試要求
- 所有工具（PubMed/Qdrant 封裝層）**必須**具備對應的 `pytest` 測試腳本。
- 使用 `pytest-asyncio` 進行非同步測試案例。
- 測試覆蓋範圍必須包含：成功、速率限制、重試、解析錯誤與空結果場景。

---

## 8. 安全與開發實踐

### 8.1 機密管理
- 絕對禁止在原始碼檔案中硬編碼 API 金鑰或密碼。
- 使用 `pydantic-settings` 從 `.env` 或系統環境變數載入。
- `.env` 必須列入 `.gitignore`。

### 8.2 檔案系統工具
- AI 代理人**必須**使用平台提供的標準檔案讀寫 API。
- 在 bash 指令中使用 `cat`、`echo` 或 shell 重導向（`>`、`>>`）來建立或修改原始碼檔案是**嚴格禁止**的。

### 8.3 日誌與可觀測性
- 使用 `structlog` 或標準 `logging` 搭配結構化輸出。
- 每次工具呼叫必須記錄：`tool`、`action`、`status`、`started_at`、`ended_at`、`latency_ms`、`retries`、`error`。
- 同一請求內的所有日誌條目必須共享一個 `correlation_id`。
