# Task 005: LangGraph Orchestrator (狀態機編排)

**Phase:** 4
**Prerequisites:** Task 003, Task 004 completed
**Constitution Reference:** §3.1, §3.2, §3.3, §3.4

---

## Objective
Implement the full LangGraph state machine with 9 nodes, conditional edges, loop prevention, and fallback strategies.

## Deliverables

### 1. `src/orchestrator/graph.py`

#### `NodeContext` Dataclass
```python
@dataclass
class NodeContext:
    config: OrchestratorConfig
    dependencies: Dependencies  # PubMedWrapper, QdrantWrapper, vectorizer
    def logger(self) -> logging.Logger: ...
```

#### 9 Node Functions
All nodes follow this contract:
```python
async def node_name(state_in: StateInput, ctx: NodeContext) -> LangGraphState:
    state = _ensure_state(state_in)
    _activate_node(state, "node_name")
    state.ui.partial_updates.append(StreamUpdate(segment="node_name", content="..."))
    # ... node logic ...
    state.touch()
    return state
```

| Node | Logic Summary |
|------|--------------|
| `planner` | Decompose query → `plan_steps`, set `latest_query`. Log iteration + search term. |
| `pubmed_search` | Call `PubMedWrapper.search()` + `fetch_details()` + `fetch_summaries()`. Store results. On empty: increment `empty_retry_count`. |
| `result_normalizer` | Parse articles → `ContextChunk` list. **Generate UUID v5 IDs.** Create vectors via vectorizer or hash fallback. |
| `qdrant_upsert` | Call `QdrantWrapper.upsert()`. Update `upsert_metrics`. |
| `qdrant_search` | Call `QdrantWrapper.query()`. Update `search_results`. |
| `rag_synthesizer` | Combine `context_bundle` + `plan_steps` → `answer_draft`. |
| `medical_critic` | Review `answer_draft` → `findings`, `trust_score`. Set `revision_required`. |
| `fallback_recovery` | Record `FallbackEvent`. Set `terminal_reason`. Generate degraded response. |
| `final_responder` | Emit final `StreamUpdate(final=True)`. Aggregate telemetry. |

#### Conditional Edges (CRITICAL)

**`_pubmed_branch` — PubMed Empty Result Loop Prevention:**
```python
def _pubmed_branch(state: LangGraphState) -> str:
    retry_count = state.pubmed.empty_retry_count
    has_results = bool(state.pubmed.results)
    
    logger.info(f"Branch decision: has_results={has_results}, retry_count={retry_count}")
    
    if has_results:
        return "normalizer"        # Success → continue pipeline
    elif retry_count < 3:
        return "retry"             # Retry with new keywords (max 3 times)
    else:
        return "fallback"          # FORCED EXIT after 3 failures
```

**`_critic_branch` — Medical Critic Rollback Prevention:**
```python
def _critic_branch(state: LangGraphState) -> str:
    if not state.critic.revision_required:
        return "approved"          # → final_responder
    
    rollback_count = state.retry_counters.get("critic_rollback", 0)
    if rollback_count >= 2:
        return "fallback"          # FORCED EXIT after 2 rollbacks
    
    return "revise"                # → rag_synthesizer for revision
```

#### Graph Builder Function
```python
def build_medical_research_graph(ctx: NodeContext) -> CompiledGraph:
    builder = StateGraph(LangGraphState)
    # Add 9 nodes
    # Add edges with conditional branches
    # Compile with recursion_limit fallback
    return builder.compile()
```

### 2. `tests/test_orchestrator.py`
Test cases:
- ✅ Happy path: query → PubMed success → normalize → Qdrant → RAG → Critic approved → final response
- ⚠️ PubMed empty × 3 → forced fallback with degraded status
- ⚠️ PubMed empty × 1 → retry with planner → success on 2nd attempt
- ❌ Critic rejects × 2 → forced fallback
- ❌ Qdrant unavailable → degraded status but pipeline completes

## Verification
```bash
pytest tests/test_orchestrator.py -v
```

## Acceptance Criteria
- [ ] 9 node functions implemented with proper contracts
- [ ] `_pubmed_branch` enforces max 3 retries (HARD LIMIT)
- [ ] `_critic_branch` enforces max 2 rollbacks
- [ ] Every conditional edge has path to `END` or `final_responder`
- [ ] All nodes call `state.touch()` and `_activate_node()`
- [ ] All nodes append `StreamUpdate` for UI feedback
- [ ] All 5 test cases pass
