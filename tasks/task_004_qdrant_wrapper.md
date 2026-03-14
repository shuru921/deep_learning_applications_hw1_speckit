# Task 004: Qdrant Wrapper (Qdrant 工具封裝)

**Phase:** 3b
**Prerequisites:** Task 002 completed
**Constitution Reference:** §5.1, §5.2, §5.3, §5.4, §5.5

---

## Objective
Implement `QdrantWrapper` async client with UUID v5 ID generation, auto collection creation, API 1.16.2 compatibility, and degradation strategy.

## Deliverables

### 1. `src/clients/qdrant_wrapper.py`

#### Data Models
- `QdrantRecord`: `id: str`, `vector: list[float]`, `payload: dict[str, Any]`
- `QdrantQuery`: `vector: list[float]`, `limit: int`, `filter: dict | None`
- `QdrantUpsertResult`: `succeeded: int`, `failed: int`, `details: list[dict]`
- `QdrantQueryResult`: `hits: list[VectorHit]`, `latency_ms: float`
- `QdrantDeleteResult`: `deleted: int`
- `QdrantHealthStatus`: `status: Literal["healthy","degraded","unavailable"]`, `detail: str`

#### Error Hierarchy
```python
class QdrantError(Exception):              # Base, with operation, collection, detail
class QdrantConnectivityError(QdrantError): pass  # Connection refused or timeout
class QdrantSchemaError(QdrantError): pass        # Collection schema mismatch
class QdrantConsistencyError(QdrantError): pass   # Partial upsert failures
class QdrantTimeoutError(QdrantError): pass       # Operation timeout
```

#### Class: `QdrantWrapper`
**Init Parameters:**
- `client: AsyncQdrantClient`
- `collection: str`
- `vector_size: int`
- `distance: str` → Must use **capitalized**: `"Cosine"`, `"Euclid"`, `"Dot"`
- `max_batch_size: int = 100`
- `timeout: float = 30.0`

**Public Methods:**
```python
async def ensure_collection(self) -> None
async def upsert(self, records: Sequence[QdrantRecord]) -> QdrantUpsertResult  
async def query(self, request: QdrantQuery) -> QdrantQueryResult
async def delete(self, point_ids: Sequence[str]) -> QdrantDeleteResult
async def healthcheck(self) -> QdrantHealthStatus
```

**Critical Implementation Rules:**

1. **Point ID Generation (Constitution §5.1):**
```python
import uuid
point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pmid-{pmid}-{idx}"))
# NEVER: chunk_id = f"pmid-{pmid}-{idx}"  ← THIS CAUSES 400 ERROR
```

2. **API Compatibility (Constitution §5.2):**
```python
# ✅ CORRECT - use query_points
result = await client.query_points(collection_name=..., query=..., limit=...)
# ❌ WRONG - deprecated method
result = await client.search(collection_name=..., query_vector=...)

# ✅ CORRECT - safe WriteConsistency handling
write_consistency = getattr(rest_models, 'WriteConsistency', None)
# ❌ WRONG - crashes on qdrant-client 1.16.2
from qdrant_client.http.models import WriteConsistency
```

3. **Collection Assurance (Constitution §5.3):**
```python
async def ensure_collection(self):
    try:
        await self.client.get_collection(self.collection)
    except Exception as e:
        if "Not found" in str(e) or "404" in str(e):
            await self._create_collection()
        else:
            raise

async def upsert(self, records):
    await self.ensure_collection()  # ALWAYS call first
    ...
```

4. **Distance Enum (Constitution §5.2):**
```python
from qdrant_client.models import Distance
distance_map = {"Cosine": Distance.COSINE, "Euclid": Distance.EUCLID, "Dot": Distance.DOT}
# Input must be capitalized: "Cosine", NOT "cosine"
```

### 2. `tests/test_qdrant_wrapper.py`
Test cases:
- ✅ `ensure_collection` creates collection when not found (404)
- ✅ `ensure_collection` skips creation when collection exists
- ✅ `upsert` successfully inserts records with UUID v5 IDs
- ✅ `query` returns `VectorHit` list via `query_points`
- ✅ `delete` removes specified point IDs
- ✅ `healthcheck` returns healthy status
- ⚠️ `upsert` partial failure returns `QdrantConsistencyError`
- ❌ Connection refused → `QdrantConnectivityError`
- ❌ Operation timeout → `QdrantTimeoutError`

## Verification
```bash
pytest tests/test_qdrant_wrapper.py -v
```

## Acceptance Criteria
- [ ] 5 public async methods implemented
- [ ] Point IDs generated via `uuid.uuid5` (NEVER string concatenation)
- [ ] Uses `query_points()` (NOT `search()`)
- [ ] `ensure_collection()` called before every `upsert`/`query`
- [ ] Distance enum uses capitalized values
- [ ] All 9 test cases pass
