# Task 003: PubMed Wrapper (PubMed 工具封裝)

**Phase:** 3
**Prerequisites:** Task 002 completed
**Constitution Reference:** §4.1, §4.2, §4.3

---

## Objective
Implement `PubMedWrapper` async client with rate limiting, error classification, and structured return types.

## Deliverables

### 1. `src/clients/pubmed_wrapper.py`

#### Data Models
- `PubMedQuery`: `term: str`, `max_results: int`, `sort: str`, `date_range: tuple | None`
- `PubMedSearchResult`: `ids: list[str]`, `count: int`, `query_translation: str`, `metrics: dict`
- `PubMedArticle`: `pmid: str`, `title: str`, `abstract: str`, `journal: str`, `published: str`, `raw: dict`
- `PubMedBatch`: `articles: list[PubMedArticle]`, `warnings: list[str]`, `metrics: dict`
- `PubMedSummary`: `pmid: str`, `title: str`, `authors: list[str]`, `source: str`, `raw: dict`

#### Error Hierarchy
```python
class PubMedError(Exception):          # Base, with request_id, status_code, detail
class PubMedRateLimitError(PubMedError): pass  # HTTP 429 or rate limiter timeout
class PubMedHTTPError(PubMedError): pass       # Non-2xx responses  
class PubMedParseError(PubMedError): pass      # XML/JSON parse failures
class PubMedEmptyResult(PubMedError): pass     # Zero results
```

#### Class: `PubMedWrapper`
**Init Parameters:**
- `async_client: httpx.AsyncClient`
- `api_key: str | None` → affects rate limit (3 vs 10 req/sec)
- `tool_name: str`, `email: str` → NCBI compliance
- `max_retries: int = 3`, `retry_backoff: tuple[float, float] = (0.5, 2.0)`
- `rate_limit_requests: int`, `rate_limit_period: float`, `rate_limit_timeout: float`

**Public Methods:**
```python
async def search(self, query: PubMedQuery) -> PubMedSearchResult
async def fetch_details(self, ids: list[str], *, rettype: str = "xml", retmode: str = "xml") -> PubMedBatch
async def fetch_summaries(self, ids: list[str]) -> list[PubMedSummary]
async def warm_up(self) -> None
```

**Private Methods:**
- `_build_params()`: Inject `tool`, `email`, `api_key`
- `_handle_response()`: Status code check + error classification
- `_throttle()`: `asyncio.Semaphore` based rate limiting
- `_parse_xml()`: XML → `PubMedBatch`

**Rate Limiting Implementation:**
- Use `asyncio.Semaphore` with sliding window timestamps
- Default: 3 req/sec without key, 10 req/sec with key
- Timeout raises `PubMedRateLimitError`

### 2. `tests/test_pubmed_wrapper.py`
Test cases:
- ✅ Successful search returning IDs
- ✅ Successful fetch_details returning articles
- ✅ Successful fetch_summaries returning summaries
- ⚠️ Rate limit exceeded → `PubMedRateLimitError`
- ❌ HTTP 500 → `PubMedHTTPError`
- ❌ Malformed XML → `PubMedParseError`
- ❌ Zero results → `PubMedEmptyResult`
- 🔄 Retry succeeds on second attempt

Use `pytest-asyncio` with mocked `httpx` transport (via `respx` or manual mock).

## Verification
```bash
pytest tests/test_pubmed_wrapper.py -v
```

## Acceptance Criteria
- [ ] 4 public async methods implemented
- [ ] 4 error classes with proper hierarchy
- [ ] Rate limiting works (semaphore-based)
- [ ] All requests include `tool` and `email` params
- [ ] All 8 test cases pass
