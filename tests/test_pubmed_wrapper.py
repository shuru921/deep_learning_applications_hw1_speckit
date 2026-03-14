"""Unit tests for src/clients/pubmed_wrapper.py."""

from __future__ import annotations

import pytest
import httpx

from src.clients.pubmed_wrapper import (
    PubMedWrapper,
    PubMedQuery,
    PubMedSearchResult,
    PubMedBatch,
    PubMedError,
    PubMedRateLimitError,
    PubMedHTTPError,
    PubMedParseError,
    PubMedEmptyResult,
)

# ---------------------------------------------------------------------------
# Mock XML Responses
# ---------------------------------------------------------------------------

ESEARCH_SUCCESS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult>
  <Count>2</Count>
  <RetMax>2</RetMax>
  <IdList>
    <Id>12345678</Id>
    <Id>87654321</Id>
  </IdList>
  <QueryTranslation>diabetes[All Fields]</QueryTranslation>
</eSearchResult>"""

ESEARCH_EMPTY_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult>
  <Count>0</Count>
  <RetMax>0</RetMax>
  <IdList/>
  <QueryTranslation>nonexistent_query[All Fields]</QueryTranslation>
</eSearchResult>"""

EFETCH_SUCCESS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Test Article Title</ArticleTitle>
        <Abstract>
          <AbstractText>This is a test abstract.</AbstractText>
        </Abstract>
        <Journal>
          <Title>Test Journal</Title>
        </Journal>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>John</ForeName>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <Year>2024</Year>
        </PubMedPubDate>
      </History>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport for httpx client."""

    def __init__(self, handler):
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=MockTransport(handler))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPubMedWrapperSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ESEARCH_SUCCESS_XML)

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com")
        result = await wrapper.search(PubMedQuery(term="diabetes"))
        assert len(result.ids) == 2
        assert "12345678" in result.ids
        assert result.count == 2

    @pytest.mark.asyncio
    async def test_search_empty_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ESEARCH_EMPTY_XML)

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com")
        with pytest.raises(PubMedEmptyResult):
            await wrapper.search(PubMedQuery(term="nonexistent"))

    @pytest.mark.asyncio
    async def test_search_includes_tool_and_email(self) -> None:
        captured_params: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured_params.update(dict(req.url.params))
            return httpx.Response(200, content=ESEARCH_SUCCESS_XML)

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="mars", email="user@example.com")
        await wrapper.search(PubMedQuery(term="test"))
        assert captured_params["tool"] == "mars"
        assert captured_params["email"] == "user@example.com"


class TestPubMedWrapperFetch:
    """Test fetch_details functionality."""

    @pytest.mark.asyncio
    async def test_fetch_details_success(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=EFETCH_SUCCESS_XML)

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com")
        batch = await wrapper.fetch_details(["12345678"])
        assert len(batch.articles) == 1
        assert batch.articles[0].pmid == "12345678"
        assert batch.articles[0].title == "Test Article Title"
        assert "Smith John" in batch.articles[0].authors

    @pytest.mark.asyncio
    async def test_fetch_details_empty_ids(self) -> None:
        client = make_client(lambda _: httpx.Response(200))
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com")
        batch = await wrapper.fetch_details([])
        assert len(batch.articles) == 0


class TestPubMedWrapperErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_http_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"Internal Server Error")

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com",
                                max_retries=0)
        with pytest.raises(PubMedHTTPError):
            await wrapper.search(PubMedQuery(term="test"))

    @pytest.mark.asyncio
    async def test_rate_limit_429(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, content=b"Too Many Requests")

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com",
                                max_retries=0)
        with pytest.raises(PubMedRateLimitError):
            await wrapper.search(PubMedQuery(term="test"))

    @pytest.mark.asyncio
    async def test_parse_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<invalid xml>>>")

        client = make_client(handler)
        wrapper = PubMedWrapper(client, tool_name="test", email="test@test.com")
        with pytest.raises(PubMedParseError):
            await wrapper.search(PubMedQuery(term="test"))


class TestPubMedErrorHierarchy:
    """Test error inheritance."""

    def test_all_errors_inherit_from_pubmed_error(self) -> None:
        assert issubclass(PubMedRateLimitError, PubMedError)
        assert issubclass(PubMedHTTPError, PubMedError)
        assert issubclass(PubMedParseError, PubMedError)
        assert issubclass(PubMedEmptyResult, PubMedError)
