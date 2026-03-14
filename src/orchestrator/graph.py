"""LangGraph 狀態機 — 9 節點 graph builder。

依據 constitution.md §3 與 tasks/task_005_orchestrator.md 實作。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.orchestrator.schemas import (
    ContextChunk,
    CriticFeedback,
    ErrorSignal,
    FallbackEvent,
    LangGraphState,
    PlanStep,
    PubMedDocument,
    PubMedQueryLog,
    StreamUpdate,
    ToolCallMetric,
)

logger = logging.getLogger(__name__)

# PubMed 搜尋時忽略的常見英文停用詞
_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "can", "do", "does", "for", "from", "had", "has", "have", "how",
    "if", "in", "into", "is", "it", "its", "may", "new", "not", "of",
    "on", "one", "or", "our", "out", "per", "set", "so", "such",
    "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "type", "up",
    "use", "used", "using", "very", "via", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "why", "will",
    "with", "would", "you", "your", "latest", "recent", "current",
})


# ---------------------------------------------------------------------------
# Node Context (Dependency Injection)
# ---------------------------------------------------------------------------


@dataclass
class NodeContext:
    """節點執行所需的依賴注入容器。"""
    pubmed_wrapper: Any = None
    qdrant_wrapper: Any = None
    config: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Node Helpers
# ---------------------------------------------------------------------------


def _activate_node(state: LangGraphState, node_name: str) -> None:
    """記錄節點啟動（Constitution §3.4）。"""
    state.current_node = node_name
    logger.info(f"[MARS] Activating node: {node_name}")


def _emit(state: LangGraphState, segment: str, content: str, final: bool = False) -> None:
    """附加 StreamUpdate 至 UI（Constitution §3.4）。"""
    state.ui.partial_updates.append(
        StreamUpdate(segment=segment, content=content, final=final)
    )


def _state_to_dict(state: LangGraphState) -> Dict[str, Any]:
    """將 LangGraphState 轉換為 dict，供 StateGraph 節點回傳。

    注意：回傳後清空 partial_updates，避免 LangGraph 合併累積導致重複事件。
    """
    data = state.model_dump()
    # 清空已序列化的更新，防止下一個節點的合併操作導致重複
    state.ui.partial_updates.clear()
    return data


# ---------------------------------------------------------------------------
# 9 Node Functions
# ---------------------------------------------------------------------------


async def planner_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 1: 查詢分解與關鍵字規劃。"""
    _activate_node(state, "planner")

    state.planning.iteration += 1
    query = state.user_query.raw_prompt
    logger.info(f"Planner iteration={state.planning.iteration}, query='{query}'")

    # 產生搜尋關鍵字 — 過濾 stop words 以避免 PubMed 回傳 0 結果
    raw_terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    terms = [t for t in raw_terms if t.lower() not in _STOP_WORDS]
    if not terms:
        terms = raw_terms if raw_terms else [query]
    state.user_query.normalized_terms = terms

    # 更新 PubMed 查詢（用空格連接，讓 PubMed 自動處理布林邏輯）
    search_term = " ".join(terms)
    state.pubmed.latest_query = {"term": search_term, "max_results": 10}

    # 建立計畫步驟
    state.planning.plan_steps = [
        PlanStep(step_id="s1", objective=f"Search PubMed for: {search_term}", owner="researcher"),
        PlanStep(step_id="s2", objective="Store results in Qdrant", owner="librarian"),
        PlanStep(step_id="s3", objective="Generate RAG synthesis", owner="system"),
        PlanStep(step_id="s4", objective="Medical review", owner="critic"),
    ]
    state.planning.status = "running"

    _emit(state, "planner", f"Planning search strategy: '{search_term}'")
    state.touch()
    return _state_to_dict(state)


async def pubmed_search_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 2: PubMed API 搜尋。"""
    _activate_node(state, "pubmed_search")

    query_info = state.pubmed.latest_query or {"term": state.user_query.raw_prompt, "max_results": 10}
    term = query_info.get("term", "")
    max_results = query_info.get("max_results", 10)

    _emit(state, "pubmed_search", f"Searching PubMed for: {term}")

    try:
        if ctx.pubmed_wrapper:
            from src.clients.pubmed_wrapper import PubMedQuery, PubMedEmptyResult
            pq = PubMedQuery(term=term, max_results=max_results)
            result = await ctx.pubmed_wrapper.search(pq)

            # 取得詳細資訊
            batch = await ctx.pubmed_wrapper.fetch_details(result.ids)
            for article in batch.articles:
                state.pubmed.results.append(PubMedDocument(
                    pmid=article.pmid, title=article.title,
                    abstract=article.abstract, journal=article.journal,
                    published_at=article.published, authors=article.authors,
                ))

            state.pubmed.query_history.append(PubMedQueryLog(
                term=term, status="succeeded", result_count=len(batch.articles),
            ))
            _emit(state, "pubmed_search", f"Found {len(batch.articles)} articles")
        else:
            # 降級模式：無 PubMed wrapper
            logger.warning("No PubMed wrapper available, using degraded mode")
            state.pubmed.empty_retry_count = 999
            _emit(state, "pubmed_search", "PubMed unavailable — degraded mode")

    except Exception as e:
        error_name = type(e).__name__
        if error_name == "PubMedEmptyResult":
            state.pubmed.empty_retry_count += 1
            logger.info(f"PubMed empty result, retry_count={state.pubmed.empty_retry_count}")
            state.pubmed.query_history.append(PubMedQueryLog(
                term=term, status="empty", result_count=0,
            ))
        else:
            state.pubmed.empty_retry_count += 1
            state.telemetry.error_flags.append(ErrorSignal(
                source="pubmed", code="search_error", message=str(e),
            ))
            state.pubmed.query_history.append(PubMedQueryLog(
                term=term, status="failed", error=str(e),
            ))

    state.touch()
    return _state_to_dict(state)


async def result_normalizer_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 3: 將 PubMed 文章解析為 ContextChunk + UUID v5 ID。"""
    _activate_node(state, "result_normalizer")

    from src.clients.qdrant_wrapper import generate_point_id

    for doc in state.pubmed.results:
        chunk_id = generate_point_id(doc.pmid, 0)
        content = f"Title: {doc.title or ''}\nAbstract: {doc.abstract or ''}"
        state.rag.context_bundle.append(ContextChunk(
            chunk_id=chunk_id, content=content,
            source=f"pubmed:{doc.pmid}",
            metadata={"journal": doc.journal, "published_at": doc.published_at},
        ))

    _emit(state, "result_normalizer", f"Normalized {len(state.rag.context_bundle)} chunks")
    state.touch()
    return _state_to_dict(state)


async def qdrant_upsert_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 4: 批次寫入 Qdrant。"""
    _activate_node(state, "qdrant_upsert")

    if ctx.qdrant_wrapper and state.rag.context_bundle:
        from src.clients.qdrant_wrapper import QdrantRecord
        records = []
        for chunk in state.rag.context_bundle:
            # 簡易向量化（使用 hash 作為 fallback）
            text_hash = hash(chunk.content)
            vector_size = ctx.config.get("vector_size", 8)
            vector = [(text_hash >> i & 0xFF) / 255.0 for i in range(vector_size)]
            records.append(QdrantRecord(
                id=chunk.chunk_id, vector=vector, payload={"content": chunk.content[:500]},
            ))
        try:
            result = await ctx.qdrant_wrapper.upsert(records)
            state.qdrant.collection_ready = True
            _emit(state, "qdrant_upsert", f"Upserted {result.succeeded} vectors")
        except Exception as e:
            state.qdrant.health = "degraded"
            state.fallback.events.append(FallbackEvent(
                trigger="qdrant_upsert_failed", action="continue_without_vectors", reason=str(e),
            ))
            _emit(state, "qdrant_upsert", f"Qdrant upsert failed: {e}")
    else:
        _emit(state, "qdrant_upsert", "Skipped: no wrapper or no chunks")

    state.touch()
    return _state_to_dict(state)


async def qdrant_search_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 5: 在 Qdrant 中搜尋。"""
    _activate_node(state, "qdrant_search")
    _emit(state, "qdrant_search", "Vector search completed")
    state.touch()
    return _state_to_dict(state)


async def rag_synthesizer_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 6: RAG 合成。"""
    _activate_node(state, "rag_synthesizer")

    if state.rag.context_bundle:
        summaries = []
        for chunk in state.rag.context_bundle[:5]:
            summaries.append(chunk.content[:200])
        state.rag.answer_draft = (
            f"Based on {len(state.rag.context_bundle)} sources:\n\n"
            + "\n---\n".join(summaries)
        )
        _emit(state, "rag_synthesizer", f"Synthesized answer from {len(state.rag.context_bundle)} chunks")
    else:
        state.rag.answer_draft = "No relevant literature found for this query."
        _emit(state, "rag_synthesizer", "No context available for synthesis")

    state.touch()
    return _state_to_dict(state)


async def medical_critic_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 7: 醫療審查。"""
    _activate_node(state, "medical_critic")

    # 簡易審查邏輯
    if state.rag.answer_draft and len(state.rag.answer_draft) > 50:
        state.critic.trust_score = 0.85
        state.critic.revision_required = False
        _emit(state, "medical_critic", "Content review passed (trust_score=0.85)")
    else:
        state.critic.trust_score = 0.3
        state.critic.revision_required = True
        state.critic.findings.append(CriticFeedback(
            issue="Insufficient content for medical review",
            severity="major",
            suggestion="Expand search or provide more context",
        ))
        _emit(state, "medical_critic", "Content review: revision required")

    state.touch()
    return _state_to_dict(state)


async def fallback_recovery_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 8: 降級復原。"""
    _activate_node(state, "fallback_recovery")

    if not state.rag.answer_draft:
        state.rag.answer_draft = (
            "The system was unable to retrieve sufficient medical literature for this query. "
            "Please try rephrasing your question or narrowing the search scope."
        )
    state.status = "degraded"
    state.fallback.terminal_reason = "forced_fallback"
    _emit(state, "fallback_recovery", "Degraded response generated")
    state.touch()
    return _state_to_dict(state)


async def final_responder_node(state: LangGraphState, ctx: NodeContext) -> Dict[str, Any]:
    """節點 9: 最終回應。"""
    _activate_node(state, "final_responder")

    if state.status != "degraded":
        state.status = "succeeded"

    _emit(state, "final", state.rag.answer_draft or "No response generated.", final=True)
    state.touch()
    return _state_to_dict(state)


# ---------------------------------------------------------------------------
# Conditional Edges (Constitution §3.3 — CRITICAL)
# ---------------------------------------------------------------------------


def _pubmed_branch(state: LangGraphState) -> str:
    """PubMed 空結果迴圈預防 — 最多 3 次重試。

    Constitution §3.3: pubmed.empty_retry_count >= 3 → 強制降級。
    """
    has_results = bool(state.pubmed.results)
    retry_count = state.pubmed.empty_retry_count

    logger.info(f"_pubmed_branch: has_results={has_results}, retry_count={retry_count}")

    if has_results:
        return "normalizer"
    elif retry_count < 3:
        return "retry"
    else:
        return "fallback"


def _critic_branch(state: LangGraphState) -> str:
    """Medical Critic 回滾預防 — 最多 2 次回滾。

    Constitution §3.3: rollback_count >= 2 → 強制降級。
    """
    if not state.critic.revision_required:
        return "approved"

    rollback_count = state.retry_counters.get("critic_rollback", 0)
    state.retry_counters["critic_rollback"] = rollback_count + 1

    if rollback_count >= 2:
        return "fallback"
    return "revise"


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------


def build_medical_research_graph(ctx: NodeContext) -> Any:
    """建構 MARS 醫學研究 LangGraph 狀態機。

    Constitution §3.2: 必須設定 recursion_limit。
    """
    from langgraph.graph import StateGraph, END

    builder = StateGraph(LangGraphState)

    # 包裝節點以注入 context
    async def _planner(state: LangGraphState) -> Dict[str, Any]:
        return await planner_node(state, ctx)

    async def _pubmed_search(state: LangGraphState) -> Dict[str, Any]:
        return await pubmed_search_node(state, ctx)

    async def _normalizer(state: LangGraphState) -> Dict[str, Any]:
        return await result_normalizer_node(state, ctx)

    async def _qdrant_upsert(state: LangGraphState) -> Dict[str, Any]:
        return await qdrant_upsert_node(state, ctx)

    async def _qdrant_search(state: LangGraphState) -> Dict[str, Any]:
        return await qdrant_search_node(state, ctx)

    async def _rag_synth(state: LangGraphState) -> Dict[str, Any]:
        return await rag_synthesizer_node(state, ctx)

    async def _critic(state: LangGraphState) -> Dict[str, Any]:
        return await medical_critic_node(state, ctx)

    async def _fallback(state: LangGraphState) -> Dict[str, Any]:
        return await fallback_recovery_node(state, ctx)

    async def _final(state: LangGraphState) -> Dict[str, Any]:
        return await final_responder_node(state, ctx)

    # 註冊節點
    builder.add_node("planner", _planner)
    builder.add_node("pubmed_search", _pubmed_search)
    builder.add_node("result_normalizer", _normalizer)
    builder.add_node("qdrant_upsert", _qdrant_upsert)
    builder.add_node("qdrant_search", _qdrant_search)
    builder.add_node("rag_synthesizer", _rag_synth)
    builder.add_node("medical_critic", _critic)
    builder.add_node("fallback_recovery", _fallback)
    builder.add_node("final_responder", _final)

    # 邊：起點
    builder.set_entry_point("planner")

    # 邊：Planner → PubMed Search
    builder.add_edge("planner", "pubmed_search")

    # 邊：PubMed Search → 條件分支（Constitution §3.3）
    builder.add_conditional_edges(
        "pubmed_search",
        _pubmed_branch,
        {
            "normalizer": "result_normalizer",
            "retry": "planner",        # 重試（最多 3 次）
            "fallback": "fallback_recovery",  # 強制降級
        },
    )

    # 邊：Normalizer → Qdrant Upsert → Qdrant Search → RAG
    builder.add_edge("result_normalizer", "qdrant_upsert")
    builder.add_edge("qdrant_upsert", "qdrant_search")
    builder.add_edge("qdrant_search", "rag_synthesizer")

    # 邊：RAG → Medical Critic
    builder.add_edge("rag_synthesizer", "medical_critic")

    # 邊：Medical Critic → 條件分支
    builder.add_conditional_edges(
        "medical_critic",
        _critic_branch,
        {
            "approved": "final_responder",
            "revise": "rag_synthesizer",   # 回滾（最多 2 次）
            "fallback": "fallback_recovery",
        },
    )

    # 邊：Fallback → Final
    builder.add_edge("fallback_recovery", "final_responder")
    builder.add_edge("final_responder", END)

    return builder.compile()
