"""
RAG service implemented as an explicit LangGraph StateGraph.

Graph topology:
  embed_question → retrieve_chunks → assemble_context → generate_answer → extract_citations → END

Supports both streaming (SSE token-by-token) and non-streaming response modes.
Answer generation goes to a cloud LLM over the OpenAI-compatible Chat
Completions API (see ``app/services/llm_client.py``); retrieval still uses the
local FastEmbed ONNX embedder.
"""
import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator, TypedDict

from langgraph.graph import END, StateGraph

from app.core.i18n import prompt_language_directive, t
from app.utils.chroma_client import query_collection, get_or_create_collection
from app.utils.embedder import embed_single
from app.services import llm_client

logger = logging.getLogger(__name__)


def no_docs_message() -> str:
    """Localized "this space has no indexed documents" reply."""
    return t("ai.no_documents")


def not_found_message() -> str:
    """Localized "the documents do not cover this" refusal."""
    return t("ai.not_found")


def _not_found_markers() -> tuple[str, ...]:
    """
    Language-independent way to detect a refusal.

    The model is told to copy the refusal sentence verbatim, so the wording of
    every supported language is a valid signal.
    """
    from app.core import i18n

    markers = {
        i18n.t_in("en", "ai.not_found").lower(),
        i18n.t_in("zh", "ai.not_found").lower(),
        "cannot find sufficient information",
        "no relevant documents",
    }
    return tuple(m for m in markers if m)

# ─── LangGraph State ──────────────────────────────────────────────────────────

class RAGState(TypedDict):
    question: str
    chat_id: str
    chat_history: list[dict[str, str]]   # [{role, content}, ...]
    top_k: int

    # Populated by nodes
    query_embedding: list[float]
    retrieved_chunks: list[dict[str, Any]]
    context: str
    answer: str
    citations: list[dict[str, Any]]      # [{source, page}, ...]


# ─── LangGraph Nodes ─────────────────────────────────────────────────────────

def _derive_search_query(question: str, chat_history: list[dict[str, str]]) -> str:
    """
    If there is chat history and the current question is ambiguous or a follow-up,
    combine key context from the last user question to form a contextualized vector search query.
    """
    if not chat_history:
        return question

    last_user_msgs = [m["content"] for m in chat_history if m.get("role") == "user"]
    if not last_user_msgs:
        return question

    q_lower = question.lower()
    pronouns = {"it", "its", "this", "that", "these", "those", "they", "them", "second", "first", "third", "previous", "above", "former", "latter", "more", "detail", "explain"}
    words = set(re.findall(r'\b\w+\b', q_lower))

    if len(words) < 8 or (words & pronouns):
        last_q = last_user_msgs[-1][:200]
        logger.debug("[RAG] Contextualized follow-up query: '%s %s'", last_q, question)
        return f"{last_q} {question}"

    return question


async def embed_question_node(state: RAGState) -> RAGState:
    """Node 1: Embed the user question using the fast ONNX embedding model."""
    logger.debug("[RAG] Embedding question")
    search_query = _derive_search_query(state["question"], state.get("chat_history", []))
    state["query_embedding"] = await asyncio.to_thread(embed_single, search_query)
    return state


async def retrieve_chunks_node(state: RAGState) -> RAGState:
    """Node 2: Retrieve top-k similar chunks from the chat's ChromaDB collection within max_distance."""
    from app.config import get_settings
    cfg = get_settings()
    logger.debug("[RAG] Retrieving chunks (top_k=%d, max_dist=%.2f)", state["top_k"], cfg.rag_max_distance)
    chunks = await asyncio.to_thread(
        query_collection,
        chat_id=state["chat_id"],
        query_embedding=state["query_embedding"],
        k=state["top_k"],
        max_distance=cfg.rag_max_distance,
    )
    state["retrieved_chunks"] = chunks
    logger.info("[RAG] Retrieved %d chunks meeting distance threshold <= %.2f", len(chunks), cfg.rag_max_distance)
    return state


def _assemble_context(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a numbered context block (shared by both paths)."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] Source: {chunk['source']} | Page: {chunk['page']}\n{chunk['text']}"
        )
    return "\n\n---\n\n".join(parts) if parts else ""


def _dedupe_citations(chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build a deduplicated citation list from chunk metadata (shared by both paths)."""
    seen: set[tuple[str, int]] = set()
    citations: list[dict[str, str]] = []
    for chunk in chunks:
        key = (chunk["source"], chunk["page"])
        if key not in seen:
            seen.add(key)
            citations.append({"source": chunk["source"], "page": chunk["page"]})
    return citations


def assemble_context_node(state: RAGState) -> RAGState:
    """Node 3: Format retrieved chunks into a numbered context block."""
    state["context"] = _assemble_context(state["retrieved_chunks"])
    return state


def _format_history(chat_history: list[dict[str, str]]) -> str:
    """Render the last few turns as a plain transcript block for the prompt."""
    history_lines: list[str] = []
    for msg in chat_history[-6:]:  # last 3 turns
        role = "User" if msg["role"] == "user" else "Assistant"
        history_lines.append(f"{role}: {msg['content']}")
    return "\n".join(history_lines) if history_lines else "(no prior conversation)"


def _build_prompt(
    question: str,
    context: str,
    history_block: str,
) -> list[dict[str, str]]:
    """
    Build the strict document-grounded messages sent to the cloud LLM.

    The guardrail instructions stay in English (models follow them most
    reliably that way); the language requirement is appended last so the answer
    itself comes back in the language the UI is currently using.
    """
    system_content = (
        "You are RagVault, a strict document-grounded AI knowledge assistant.\n\n"
        "MANDATORY RESTRICTIONS:\n"
        "1. Answer questions ONLY and EXCLUSIVELY based on the facts directly stated in the CONTEXT excerpts from the user's uploaded documents.\n"
        "2. ABSOLUTELY NEVER use outside knowledge, pre-trained knowledge, physics/science/math/trivia knowledge, or assumptions.\n"
        "3. If the provided CONTEXT does NOT explicitly contain the answer to the user's question, you MUST reply EXACTLY with:\n"
        f'"{not_found_message()}"\n'
        "4. Never answer from general knowledge. If the topic is absent from the provided context excerpts, refuse immediately with the exact refusal sentence above.\n"
        "5. Reference facts using inline citations like [Source: <filename>, Page: <page>]."
        f"{prompt_language_directive()}"
    )

    user_content = (
        f"=== CONTEXT FROM UPLOADED DOCUMENTS ===\n"
        f"{context}\n\n"
        f"=== CONVERSATION HISTORY ===\n"
        f"{history_block}\n\n"
        f"=== USER QUESTION ===\n"
        f"{question}\n\n"
        f"=== GROUNDED RESPONSE ==="
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _build_messages(state: RAGState) -> list[dict[str, str]]:
    """Construct the strict document-grounded system and user messages for the LLM."""
    return _build_prompt(
        question=state["question"],
        context=state["context"],
        history_block=_format_history(state["chat_history"]),
    )


async def generate_answer_node(state: RAGState) -> RAGState:
    """Node 4: Call the cloud LLM with the assembled prompt (non-streaming path)."""
    collection = get_or_create_collection(state["chat_id"])
    if not collection or collection.count() == 0:
        state["answer"] = no_docs_message()
        state["citations"] = []
        return state

    if not state.get("retrieved_chunks") or not state.get("context"):
        state["answer"] = not_found_message()
        state["citations"] = []
        return state

    messages = _build_messages(state)

    try:
        answer = await llm_client.chat_completion(messages, temperature=0.0)
        state["answer"] = (answer or "").strip() or not_found_message()
    except Exception as exc:
        logger.error("[RAG] LLM generation error: %s", exc)
        state["answer"] = llm_client.format_llm_error(exc)
    return state


def extract_citations_node(state: RAGState) -> RAGState:
    """
    Node 5: Build a deduplicated citation list from the retrieved chunk metadata.
    Citations are derived from metadata, NOT from LLM hallucination.
    """
    state["citations"] = _dedupe_citations(state.get("retrieved_chunks") or [])
    return state


# ─── Build & Compile the LangGraph ───────────────────────────────────────────

def _build_rag_graph() -> Any:
    workflow: StateGraph = StateGraph(RAGState)

    workflow.add_node("embed_question", embed_question_node)
    workflow.add_node("retrieve_chunks", retrieve_chunks_node)
    workflow.add_node("assemble_context", assemble_context_node)
    workflow.add_node("generate_answer", generate_answer_node)
    workflow.add_node("extract_citations", extract_citations_node)

    workflow.set_entry_point("embed_question")
    workflow.add_edge("embed_question", "retrieve_chunks")
    workflow.add_edge("retrieve_chunks", "assemble_context")
    workflow.add_edge("assemble_context", "generate_answer")
    workflow.add_edge("generate_answer", "extract_citations")
    workflow.add_edge("extract_citations", END)

    return workflow.compile()


rag_graph = _build_rag_graph()


# ─── Public API ──────────────────────────────────────────────────────────────

async def run_rag(
    question: str,
    chat_id: str,
    chat_history: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Execute the full RAG LangGraph and return the complete result.

    Returns:
        {"answer": str, "citations": List[{source, page}]}
    """
    from app.config import get_settings

    cfg = get_settings()

    initial_state: RAGState = {
        "question": question,
        "chat_id": chat_id,
        "chat_history": chat_history,
        "top_k": cfg.top_k,
        "query_embedding": [],
        "retrieved_chunks": [],
        "context": "",
        "answer": "",
        "citations": [],
    }

    # Run the graph (synchronous nodes wrapped in async invoke)
    final_state: RAGState = await rag_graph.ainvoke(initial_state)
    return {
        "answer": final_state["answer"],
        "citations": final_state["citations"],
    }


async def stream_rag(
    question: str,
    chat_id: str,
    chat_history: list[dict[str, str]],
) -> AsyncGenerator[str, None]:
    """
    Stream the RAG answer token-by-token as SSE events.

    Yields lines in JSON format:
        data: {"token": "..."}\\n\\n
    Terminates with:
        data: {"citations": [...]}\\n\\n
        data: [DONE]\\n\\n
    """
    from app.config import get_settings

    cfg = get_settings()

    # ── Guard: Check if collection has documents at all ───────────────────────
    collection = get_or_create_collection(chat_id)
    doc_count = collection.count() if collection else 0
    if doc_count == 0:
        yield f"data: {json.dumps({'token': no_docs_message()})}\n\n"
        yield f"data: {json.dumps({'citations': []})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── Steps 1-2: embed → retrieve with strict max_distance threshold ───────
    # Both embed_single (FastEmbed ONNX) and query_collection (ChromaDB) are
    # synchronous CPU/disk bound; offload them so a slow embed or a large
    # collection does not stall the event loop for every other request.
    search_query = _derive_search_query(question, chat_history)

    def _embed_and_retrieve():
        embedding = embed_single(search_query)
        return query_collection(
            chat_id=chat_id,
            query_embedding=embedding,
            k=cfg.top_k,
            max_distance=cfg.rag_max_distance,
        )

    retrieved_chunks = await asyncio.to_thread(_embed_and_retrieve)

    # ── Guard: If no relevant chunks meet the similarity threshold ────────────
    if not retrieved_chunks:
        yield f"data: {json.dumps({'token': not_found_message()})}\n\n"
        yield f"data: {json.dumps({'citations': []})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── Step 3: Build context block (shared helper, same as graph node) ─────
    context = _assemble_context(retrieved_chunks)

    # Build prompt messages (shared with the non-streaming graph node)
    messages = _build_prompt(
        question=question,
        context=context,
        history_block=_format_history(chat_history),
    )

    # ── Step 4: Stream tokens from the cloud LLM (temperature=0.0, strict grounding)
    logger.info("[RAG:stream] Streaming response from %s", llm_client.describe_llm_setup())

    full_response_text: list[str] = []
    try:
        async for token in llm_client.stream_chat_completion(messages, temperature=0.0):
            full_response_text.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"
    except Exception as exc:
        logger.error("[RAG:stream] LLM streaming error: %s", exc)
        err_msg = llm_client.format_llm_error(exc)
        yield f"data: {json.dumps({'token': err_msg})}\n\n"

    # ── Step 5: Emit deduplicated citations as metadata event ─────────────────
    complete_text = "".join(full_response_text).lower()
    if any(marker in complete_text for marker in _not_found_markers()):
        citations: list[dict[str, str]] = []
    else:
        citations = _dedupe_citations(retrieved_chunks)

    yield f"data: {json.dumps({'citations': citations})}\n\n"
    yield "data: [DONE]\n\n"
