"""Unit tests for src/clients/qdrant_wrapper.py."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.qdrant_wrapper import (
    QdrantWrapper,
    QdrantRecord,
    QdrantQuery,
    QdrantError,
    QdrantConnectivityError,
    QdrantSchemaError,
    QdrantConsistencyError,
    QdrantTimeoutError,
    generate_point_id,
)


# ---------------------------------------------------------------------------
# UUID v5 ID Generation Tests (Constitution §5.1)
# ---------------------------------------------------------------------------


class TestPointIdGeneration:
    """Test UUID v5 generation — Constitution §5.1."""

    def test_generates_valid_uuid(self) -> None:
        pid = generate_point_id("12345")
        # Must be a valid UUID string
        parsed = uuid.UUID(pid)
        assert parsed.version == 5

    def test_same_input_same_output(self) -> None:
        """Idempotent: same PMID+idx → same ID."""
        a = generate_point_id("12345", 0)
        b = generate_point_id("12345", 0)
        assert a == b

    def test_different_idx_different_output(self) -> None:
        a = generate_point_id("12345", 0)
        b = generate_point_id("12345", 1)
        assert a != b

    def test_different_pmid_different_output(self) -> None:
        a = generate_point_id("12345", 0)
        b = generate_point_id("67890", 0)
        assert a != b


# ---------------------------------------------------------------------------
# Mock Qdrant Client
# ---------------------------------------------------------------------------


def make_mock_client() -> AsyncMock:
    """Create a mock AsyncQdrantClient."""
    client = AsyncMock()
    client.get_collection = AsyncMock()
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.query_points = AsyncMock(return_value=[])
    client.delete = AsyncMock()

    # Mock get_collections for healthcheck
    mock_collections = MagicMock()
    mock_collections.collections = []
    client.get_collections = AsyncMock(return_value=mock_collections)

    return client


# ---------------------------------------------------------------------------
# Wrapper Tests
# ---------------------------------------------------------------------------


class TestQdrantWrapperEnsureCollection:
    """Test collection assurance — Constitution §5.3."""

    @pytest.mark.asyncio
    async def test_collection_exists(self) -> None:
        client = make_mock_client()
        wrapper = QdrantWrapper(client, collection="test-coll")
        await wrapper.ensure_collection()
        client.get_collection.assert_called_once_with("test-coll")
        client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_collection_not_found_auto_create(self) -> None:
        client = make_mock_client()
        client.get_collection.side_effect = Exception("Not found: collection test-coll")
        wrapper = QdrantWrapper(client, collection="test-coll")
        await wrapper.ensure_collection()
        client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_collection_404_auto_create(self) -> None:
        client = make_mock_client()
        client.get_collection.side_effect = Exception("404: collection not found")
        wrapper = QdrantWrapper(client, collection="test-coll")
        await wrapper.ensure_collection()
        client.create_collection.assert_called_once()


class TestQdrantWrapperUpsert:
    """Test upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_success(self) -> None:
        client = make_mock_client()
        wrapper = QdrantWrapper(client, collection="test-coll")
        records = [
            QdrantRecord(id=generate_point_id("123", 0), vector=[0.1] * 8, payload={"pmid": "123"}),
            QdrantRecord(id=generate_point_id("456", 0), vector=[0.2] * 8, payload={"pmid": "456"}),
        ]
        result = await wrapper.upsert(records)
        assert result.succeeded == 2
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_upsert_all_fail_raises(self) -> None:
        client = make_mock_client()
        client.upsert.side_effect = Exception("Qdrant connection refused")
        wrapper = QdrantWrapper(client, collection="test-coll")
        records = [QdrantRecord(id=generate_point_id("123", 0), vector=[0.1] * 8)]
        with pytest.raises(QdrantConsistencyError):
            await wrapper.upsert(records)


class TestQdrantWrapperQuery:
    """Test query operations — uses query_points (Constitution §5.2)."""

    @pytest.mark.asyncio
    async def test_query_calls_query_points(self) -> None:
        """Must use query_points(), NOT search()."""
        client = make_mock_client()
        mock_result = MagicMock()
        mock_result.points = []
        client.query_points.return_value = mock_result

        wrapper = QdrantWrapper(client, collection="test-coll")
        await wrapper.query(QdrantQuery(vector=[0.1] * 8, limit=5))

        client.query_points.assert_called_once()
        # Verify search() was NOT called
        assert not hasattr(client, "search") or not client.search.called


class TestQdrantWrapperHealthcheck:
    """Test healthcheck."""

    @pytest.mark.asyncio
    async def test_healthy(self) -> None:
        client = make_mock_client()
        wrapper = QdrantWrapper(client, collection="test-coll")
        status = await wrapper.healthcheck()
        assert status.status == "healthy"

    @pytest.mark.asyncio
    async def test_unavailable(self) -> None:
        client = make_mock_client()
        client.get_collections.side_effect = Exception("Connection refused")
        wrapper = QdrantWrapper(client, collection="test-coll")
        status = await wrapper.healthcheck()
        assert status.status == "unavailable"


class TestQdrantErrorHierarchy:
    """Test error inheritance — Constitution §5.4."""

    def test_all_errors_inherit_from_qdrant_error(self) -> None:
        assert issubclass(QdrantConnectivityError, QdrantError)
        assert issubclass(QdrantSchemaError, QdrantError)
        assert issubclass(QdrantConsistencyError, QdrantError)
        assert issubclass(QdrantTimeoutError, QdrantError)
