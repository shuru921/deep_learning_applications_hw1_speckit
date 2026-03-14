"""PubMed E-utilities 非同步封裝層。

依據 constitution.md §4 與 tasks/task_003_pubmed_wrapper.md 實作。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedQuery(BaseModel):
    """PubMed 搜尋查詢參數。"""
    term: str
    max_results: int = 10
    sort: str = "relevance"
    date_range: Optional[tuple[str, str]] = None


class PubMedSearchResult(BaseModel):
    """PubMed esearch 回傳結果。"""
    ids: list[str] = Field(default_factory=list)
    count: int = 0
    query_translation: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class PubMedArticle(BaseModel):
    """單篇 PubMed 文章解析結果。"""
    pmid: str
    title: str = ""
    abstract: str = ""
    journal: str = ""
    published: str = ""
    authors: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PubMedBatch(BaseModel):
    """efetch 批次回傳結果。"""
    articles: list[PubMedArticle] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class PubMedSummary(BaseModel):
    """esummary 單篇摘要。"""
    pmid: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    source: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Error Hierarchy (Constitution §4.2)
# ---------------------------------------------------------------------------

class PubMedError(Exception):
    """PubMed 工具層基底例外。"""
    def __init__(self, message: str, *, request_id: Optional[str] = None,
                 status_code: Optional[int] = None, detail: Optional[str] = None):
        super().__init__(message)
        self.request_id = request_id
        self.status_code = status_code
        self.detail = detail


class PubMedRateLimitError(PubMedError):
    """HTTP 429 或速率限制器逾時。"""


class PubMedHTTPError(PubMedError):
    """非 2xx 回應。"""


class PubMedParseError(PubMedError):
    """XML/JSON 解析失敗。"""


class PubMedEmptyResult(PubMedError):
    """有效回應但零筆結果。"""


# ---------------------------------------------------------------------------
# Wrapper Class (Constitution §4)
# ---------------------------------------------------------------------------

class PubMedWrapper:
    """PubMed E-utilities 非同步客戶端。

    所有請求包含 tool + email 參數以符合 NCBI 使用政策。
    支援速率限制與指數退避重試。
    """

    def __init__(
        self,
        async_client: httpx.AsyncClient,
        *,
        api_key: Optional[str] = None,
        tool_name: str = "mars-research",
        email: str = "",
        max_retries: int = 3,
        retry_backoff: tuple[float, float] = (0.5, 2.0),
        rate_limit_requests: int = 3,
        rate_limit_period: float = 1.0,
        rate_limit_timeout: float = 2.0,
    ) -> None:
        self._client = async_client
        self._api_key = api_key
        self._tool_name = tool_name
        self._email = email
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._rate_limit_timeout = rate_limit_timeout

        # 速率限制：Constitution §4.1
        effective_rate = 10 if api_key else rate_limit_requests
        self._semaphore = asyncio.Semaphore(effective_rate)
        self._request_timestamps: list[float] = []
        self._rate_period = rate_limit_period

    def _build_params(self, extra: dict[str, str]) -> dict[str, str]:
        """注入 tool、email、api_key 到請求參數。"""
        params: dict[str, str] = {"tool": self._tool_name, "email": self._email}
        if self._api_key:
            params["api_key"] = self._api_key
        params.update(extra)
        return params

    async def _throttle(self) -> None:
        """基於 Semaphore 的速率限制。"""
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(), timeout=self._rate_limit_timeout
            )
        except asyncio.TimeoutError:
            raise PubMedRateLimitError(
                "Rate limiter timeout exceeded",
                detail=f"Timeout after {self._rate_limit_timeout}s",
            )

        now = time.monotonic()
        self._request_timestamps = [
            t for t in self._request_timestamps if now - t < self._rate_period
        ]
        self._request_timestamps.append(now)

        # 確保在速率限制期間後釋放 semaphore
        asyncio.get_event_loop().call_later(self._rate_period, self._semaphore.release)

    async def _handle_response(self, response: httpx.Response) -> bytes:
        """檢查狀態碼並分類錯誤。"""
        if response.status_code == 429:
            raise PubMedRateLimitError(
                "NCBI rate limit exceeded (HTTP 429)",
                status_code=429,
            )
        if response.status_code >= 400:
            raise PubMedHTTPError(
                f"PubMed API error: HTTP {response.status_code}",
                status_code=response.status_code,
                detail=response.text[:200],
            )
        return response.content

    async def _request_with_retry(
        self, url: str, params: dict[str, str]
    ) -> bytes:
        """帶有指數退避的重試邏輯。"""
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._throttle()
                start = time.monotonic()
                resp = await self._client.get(url, params=params)
                latency = (time.monotonic() - start) * 1000
                logger.info(
                    "PubMed request",
                    extra={"url": url, "attempt": attempt, "latency_ms": latency},
                )
                return await self._handle_response(resp)
            except (PubMedRateLimitError, PubMedHTTPError) as e:
                last_exc = e
                if attempt < self._max_retries:
                    backoff = self._retry_backoff[0] * (self._retry_backoff[1] ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{self._max_retries} after {backoff}s")
                    await asyncio.sleep(backoff)
        raise last_exc  # type: ignore[misc]

    def _parse_esearch_xml(self, raw: bytes) -> PubMedSearchResult:
        """解析 esearch XML 回傳。"""
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as e:
            raise PubMedParseError(f"XML parse error: {e}", detail=str(e))

        ids = [id_el.text or "" for id_el in root.findall(".//Id")]
        count_el = root.find(".//Count")
        count = int(count_el.text) if count_el is not None and count_el.text else 0
        trans_el = root.find(".//QueryTranslation")
        translation = trans_el.text if trans_el is not None and trans_el.text else ""

        return PubMedSearchResult(
            ids=ids, count=count, query_translation=translation
        )

    def _parse_efetch_xml(self, raw: bytes) -> PubMedBatch:
        """解析 efetch XML 回傳。"""
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as e:
            raise PubMedParseError(f"XML parse error: {e}", detail=str(e))

        articles: list[PubMedArticle] = []
        warnings: list[str] = []
        for article_el in root.findall(".//PubmedArticle"):
            try:
                pmid_el = article_el.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None and pmid_el.text else ""
                title_el = article_el.find(".//ArticleTitle")
                title = title_el.text if title_el is not None and title_el.text else ""
                abstract_parts = article_el.findall(".//AbstractText")
                abstract = " ".join(
                    (p.text or "") for p in abstract_parts
                )
                journal_el = article_el.find(".//Title")
                journal = journal_el.text if journal_el is not None and journal_el.text else ""
                year_el = article_el.find(".//PubDate/Year")
                published = year_el.text if year_el is not None and year_el.text else ""
                author_els = article_el.findall(".//Author")
                authors = []
                for a in author_els:
                    ln = a.find("LastName")
                    fn = a.find("ForeName")
                    name = f"{ln.text or ''} {fn.text or ''}".strip() if ln is not None else ""
                    if name:
                        authors.append(name)
                articles.append(PubMedArticle(
                    pmid=pmid, title=title, abstract=abstract,
                    journal=journal, published=published, authors=authors,
                ))
            except Exception as e:
                warnings.append(f"Parse warning for article: {e}")

        return PubMedBatch(articles=articles, warnings=warnings)

    # -----------------------------------------------------------------------
    # Public Async Methods (Constitution §4)
    # -----------------------------------------------------------------------

    async def search(self, query: PubMedQuery) -> PubMedSearchResult:
        """執行 esearch 搜尋，回傳 PMID 清單。"""
        params = self._build_params({
            "db": "pubmed",
            "term": query.term,
            "retmax": str(query.max_results),
            "sort": query.sort,
            "retmode": "xml",
        })
        if query.date_range:
            params["mindate"] = query.date_range[0]
            params["maxdate"] = query.date_range[1]
            params["datetype"] = "pdat"

        start = time.monotonic()
        raw = await self._request_with_retry(f"{BASE_URL}/esearch.fcgi", params)
        latency = (time.monotonic() - start) * 1000
        result = self._parse_esearch_xml(raw)
        result.metrics = {"latency_ms": latency, "source": "esearch"}

        if not result.ids:
            raise PubMedEmptyResult(
                f"No results for query: {query.term}",
                detail=f"query_translation={result.query_translation}",
            )
        return result

    async def fetch_details(
        self, ids: list[str], *, rettype: str = "xml", retmode: str = "xml"
    ) -> PubMedBatch:
        """取得文章完整詳情 (efetch)。"""
        if not ids:
            return PubMedBatch()

        params = self._build_params({
            "db": "pubmed",
            "id": ",".join(ids),
            "rettype": rettype,
            "retmode": retmode,
        })
        start = time.monotonic()
        raw = await self._request_with_retry(f"{BASE_URL}/efetch.fcgi", params)
        latency = (time.monotonic() - start) * 1000
        batch = self._parse_efetch_xml(raw)
        batch.metrics = {"latency_ms": latency, "source": "efetch", "id_count": len(ids)}
        return batch

    async def fetch_summaries(self, ids: list[str]) -> list[PubMedSummary]:
        """取得文章摘要資訊 (esummary)。"""
        if not ids:
            return []

        params = self._build_params({
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
        })
        start = time.monotonic()
        raw = await self._request_with_retry(f"{BASE_URL}/esummary.fcgi", params)
        latency = (time.monotonic() - start) * 1000

        try:
            import json
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise PubMedParseError(f"JSON parse error: {e}", detail=str(e))

        summaries: list[PubMedSummary] = []
        result = data.get("result", {})
        for uid in ids:
            item = result.get(uid, {})
            if not item:
                continue
            authors = [
                a.get("name", "") for a in item.get("authors", [])
            ]
            summaries.append(PubMedSummary(
                pmid=uid,
                title=item.get("title", ""),
                authors=authors,
                source=item.get("source", ""),
                raw=item,
            ))
        return summaries

    async def warm_up(self) -> None:
        """預熱 client 與 rate limiter。"""
        params = self._build_params({"db": "pubmed", "term": "test", "retmax": "1", "retmode": "xml"})
        try:
            resp = await self._client.get(f"{BASE_URL}/esearch.fcgi", params=params)
            logger.info(f"PubMed warm-up: status={resp.status_code}")
        except Exception as e:
            logger.warning(f"PubMed warm-up failed: {e}")
