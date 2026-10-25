"""Generate page-complete study notes and export them as readable PDFs."""
import json
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import prompt_language_directive, remedial_title_prefixes, t
from app.models.note import Note
from app.models.chat import Chat
from app.utils.chroma_client import get_or_create_collection
from app.services import llm_client

logger = logging.getLogger(__name__)

_PAGE_SCHEMA_PROMPT = """[
  {
        "source": "filename.pdf",
        "page": 1,
        "topic": "Short page topic",
        "summary": "Complete but concise summary of this page.",
    "key_points": [
            "Important fact, definition, example, or conclusion",
            "Formula: write the exact formula and define its variables"
    ],
        "tag": "Summary"
  }
]"""


_PDF_CSS = """
@page { size: A4; margin: 48pt 48pt 48pt 48pt; }
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.5; color: #111; }
h1 { font-size: 17pt; margin: 0 0 6pt 0; }
h2 { font-size: 12pt; margin: 14pt 0 4pt 0; }
p { margin: 0 0 4pt 0; }
.sub { font-size: 10pt; color: #555; }
.meta { font-size: 11pt; font-weight: bold; margin-top: 12pt; }
.pt { margin: 0 0 2pt 12pt; }
.blank { height: 8pt; }
"""

_HTML_ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
}


def _html_escape(value: object) -> str:
    """Escape text for the PDF HTML templates (keeps quotes, which are safe)."""
    escaped = str(value)
    for needle, replacement in _HTML_ESCAPES.items():
        escaped = escaped.replace(needle, replacement)
    return escaped


def _render_html_pdf(sections: list[str]) -> bytes:
    """
    Render ``sections`` (HTML fragments) to a searchable A4 PDF.

    Uses PyMuPDF's Story layout engine so Chinese text wraps by width rather
    than by character count, and CJK glyphs fall back to a bundled font instead
    of rendering as blank boxes (which is what the built-in Helvetica does).

    ``subset_fonts()`` matters: without it the embedded fallback font is written
    out in full (~1.7 MB for a one-page summary); subsetting brings the same
    document down to a few tens of kilobytes.
    """
    import io

    import fitz

    buffer = io.BytesIO()
    story = fitz.Story(
        html="<html><head><style>%s</style></head><body>%s</body></html>"
        % (_PDF_CSS, "".join(sections)),
    )
    writer = fitz.DocumentWriter(buffer)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (48, 48, -48, -48)

    while True:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        if not more:
            break
    writer.close()

    document = fitz.open("pdf", buffer.getvalue())
    document.subset_fonts()
    document.set_metadata({"title": "RagVault", "producer": "RagVault"})
    data = document.tobytes(garbage=4, deflate=True)
    document.close()
    return data


def _get_file_chunks(chat_id: str) -> dict[str, list[dict[str, Any]]]:
    """Group all stored ChromaDB chunks by their source filename."""
    collection = get_or_create_collection(chat_id)
    try:
        results = collection.get(include=["documents", "metadatas"])
    except Exception as exc:
        logger.warning("ChromaDB get failed for notes: %s", exc)
        return {}

    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    if not docs:
        return {}

    file_buckets: dict[str, list[dict[str, Any]]] = {}
    for doc_text, meta in zip(docs, metas):
        source = meta.get("source", t("notes.default_source")) if meta else t("notes.default_source")
        chunk_item = {
            "text": doc_text,
            "source": source,
            "page": meta.get("page", 1) if meta else 1,
            "chunk_index": meta.get("chunk_index", 0) if meta else 0,
        }
        file_buckets.setdefault(source, []).append(chunk_item)

    return file_buckets


def _build_page_summary_prompt(filename: str, pages: list[dict[str, Any]]) -> str:
    page_context = "\n\n".join(
        f"===== PAGE {page['page']} =====\n{page['text']}" for page in pages
    )
    page_numbers = ", ".join(str(page["page"]) for page in pages)
    return f"""You are an expert academic tutor creating exam-ready notes for "{filename}".

Rules:
- Return exactly one summary object for every page number in this batch: {page_numbers}.
- Summarize each page in 2 concise sentences (max 30 words total).
- Maximum 3 key points per card (max 12 words per bullet point).
- Copy every formula, equation, symbol, unit, and important relationship accurately. Prefix formula items with "Formula:".
- Use the exact page number shown in each PAGE marker and attribute source as "{filename}".
- Output ONLY valid JSON array -- no markdown fences, no conversational text before or after.
- Valid tags: "Concept", "Definition", "Formula", "Takeaway", "Summary".

JSON SCHEMA:
{_PAGE_SCHEMA_PROMPT}

DOCUMENT TEXT ({filename}):
{page_context}

JSON ARRAY:{prompt_language_directive()}"""


def _parse_and_repair_json(text: str) -> list[dict[str, Any]]:
    """Extract and repair potentially truncated JSON arrays or object wrappers from LLM output."""
    text = re.sub(r"```(?:json)?", "", text).strip()

    def _extract_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            # Check common wrapper keys
            for key in ["cards", "notes", "summaries", "pages", "data", "items"]:
                if key in data and isinstance(data[key], list):
                    return [item for item in data[key] if isinstance(item, dict)]
            # If dict contains topic/summary/key_points directly, treat as single item list
            if "topic" in data or "summary" in data or "key_points" in data:
                return [data]
            # Fallback: check any value that is a list of dicts
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
        return []

    # Try 1: Direct JSON parse on cleaned text
    try:
        res = json.loads(text)
        extracted = _extract_list(res)
        if extracted:
            return extracted
    except Exception:
        pass

    # Try 2: Extract substring from first '[' or '{' to last ']' or '}'
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        res = json.loads(raw)
        extracted = _extract_list(res)
        if extracted:
            return extracted
    except Exception:
        pass

    # Try 3: Truncated JSON repair (find last complete object '}')
    try:
        start = raw.find('[')
        if start != -1:
            sub = raw[start:]
            last_brace = sub.rfind('}')
            if last_brace != -1:
                repaired = sub[:last_brace + 1] + '\n]'
                res = json.loads(repaired)
                extracted = _extract_list(res)
                if extracted:
                    return extracted
    except Exception:
        pass

    return []


def _normalise_cards(cards_raw: list[dict[str, Any]], filename: str) -> list[dict[str, Any]]:
    valid = []
    allowed_tags = {"Concept", "Definition", "Formula", "Takeaway", "Summary"}

    for i, raw in enumerate(cards_raw):
        try:
            topic = str(raw.get("topic", t("notes.default_topic", index=i + 1))).strip()
            summary = str(raw.get("summary", "")).strip()
            kp_raw = raw.get("key_points", [])
            key_points = [str(p).strip() for p in kp_raw if str(p).strip()] if isinstance(kp_raw, list) else []

            if not summary and not key_points:
                continue

            tag = str(raw.get("tag", "Concept")).capitalize()
            if tag not in allowed_tags:
                tag = "Concept"

            page_raw = raw.get("page", 1)
            try:
                page_num = int(page_raw) if str(page_raw).strip().isdigit() else 1
            except Exception:
                page_num = 1

            valid.append({
                "id": f"card_{uuid4().hex[:8]}",
                "topic": topic,
                "summary": summary if summary else t("notes.default_summary"),
                "key_points": key_points if key_points else [t("notes.default_keypoint")],
                "source": filename,
                "page": max(1, page_num),
                "tag": tag,
            })
        except Exception as exc:
            logger.warning("[NOTES] Card parse error: %s", exc)

    return valid


async def _invoke_llm(prompt: str) -> str:
    """Send a page-batch prompt to the cloud LLM and return raw JSON text."""
    return await llm_client.chat_completion(
        [
            {
                "role": "system",
                "content": "You are a precise study-notes assistant. Reply with JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1200,
        json_mode=True,
    )


async def generate_notes(db: AsyncSession, chat_id: str) -> Note:
    """Generate one complete, formula-aware study summary for every extracted page."""
    cid = UUID(str(chat_id)) if not isinstance(chat_id, UUID) else chat_id
    # Load chat title
    chat_res = await db.execute(select(Chat).where(Chat.id == cid))
    chat = chat_res.scalar_one_or_none()
    chat_title = chat.title if chat else t("title.new_space")

    file_buckets = _get_file_chunks(chat_id)
    if not file_buckets:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("notes.no_documents"),
        )

    all_cards: list[dict[str, Any]] = []

    for filename, chunks in file_buckets.items():
        pages: dict[int, dict[str, Any]] = {}
        for chunk in sorted(chunks, key=lambda item: (int(item["page"]), int(item["chunk_index"]))):
            page_number = int(chunk["page"])
            page = pages.setdefault(page_number, {"page": page_number, "text": ""})
            page["text"] += f"\n{chunk['text']}"

        page_items = list(pages.values())
        # Keep prompts bounded while ensuring every page is processed.
        for start in range(0, len(page_items), 3):
            page_batch = page_items[start:start + 3]
            prompt = _build_page_summary_prompt(filename, page_batch)
            logger.info("[NOTES] Summarizing pages %s from %s", [p["page"] for p in page_batch], filename)
            try:
                raw = await _invoke_llm(prompt)
                parsed = _parse_and_repair_json(raw)
                all_cards.extend(_normalise_cards(parsed, filename))
            except Exception as exc:
                logger.warning("[NOTES] Page summary error for %s: %s", filename, exc)

            summarized_pages = {int(card["page"]) for card in all_cards if card["source"] == filename}
            for page in page_batch:
                if page["page"] not in summarized_pages:
                    all_cards.append({
                        "id": f"card_fb_{uuid4().hex[:8]}",
                        "topic": t("notes.fallback_topic", page=page["page"]),
                        "summary": page["text"][:1200].strip(),
                        "key_points": [line.strip() for line in page["text"].splitlines() if line.strip()][:8],
                        "source": filename,
                        "page": page["page"],
                        "tag": "Summary",
                    })

    # Fallback if no cards parsed
    if not all_cards:
        for filename, chunks in file_buckets.items():
            for i, c in enumerate(chunks[:3], start=1):
                all_cards.append({
                    "id": f"card_fb_{uuid4().hex[:6]}",
                    "topic": t("notes.fallback_key_topic", index=i, filename=filename),
                    "summary": c["text"][:180] + "...",
                    "key_points": [c["text"][180:350] + "..."],
                    "source": filename,
                    "page": c["page"],
                    "tag": "Summary",
                })

    # Save to DB
    note = Note(
        id=uuid4(),
        chat_id=cid,
        title=t("notes.title", chat=chat_title),
        cards=all_cards,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    logger.info("[NOTES] Total page summaries generated: %d across %d files", len(all_cards), len(file_buckets))
    return note


def build_notes_pdf(note: Note) -> bytes:
    """Render the generated notes as a searchable, language-aware PDF."""
    sections: list[str] = [
        f"<h1>{_html_escape(note.title)}</h1>",
        f'<p class="sub">{_html_escape(t("notes.pdf_subtitle"))}</p>',
    ]
    for card in note.cards or []:
        page_number = card.get("page", 1)
        source = card.get("source", t("notes.default_source"))
        topic = card.get("topic", t("notes.fallback_topic", page=page_number))
        sections.append(
            f'<p class="meta">{_html_escape(t("notes.pdf_page_line", source=source, page=page_number))}</p>'
        )
        sections.append(f"<h2>{_html_escape(topic)}</h2>")
        sections.append(f'<p>{_html_escape(card.get("summary", ""))}</p>')
        for point in card.get("key_points", []):
            sections.append(f'<p class="pt">&bull; {_html_escape(point)}</p>')
        sections.append('<div class="blank"></div>')

    return _render_html_pdf(sections)


async def get_latest_notes(db: AsyncSession, chat_id: str | UUID) -> Note | None:
    """Retrieve the most recent generated notes for a chat."""
    cid = UUID(str(chat_id)) if not isinstance(chat_id, UUID) else chat_id
    remedial_filters = [Note.title.like(f"{prefix}%") for prefix in remedial_title_prefixes()]
    query = select(Note).where(Note.chat_id == cid).order_by(desc(Note.created_at)).limit(1)
    for condition in remedial_filters:
        query = query.where(~condition)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def generate_remedial_quiz_notes(
    db: AsyncSession,
    chat_id: str | UUID,
    quiz_id: str | UUID | None = None,
) -> Note:
    """Generate targeted remedial study cards for missed questions from a submitted quiz."""
    from app.models.quiz import Quiz

    cid = UUID(str(chat_id)) if not isinstance(chat_id, UUID) else chat_id

    if quiz_id:
        qid = UUID(str(quiz_id)) if not isinstance(quiz_id, UUID) else quiz_id
        q_res = await db.execute(select(Quiz).where(Quiz.id == qid, Quiz.chat_id == cid))
        quiz = q_res.scalar_one_or_none()
    else:
        q_res = await db.execute(
            select(Quiz)
            .where(Quiz.chat_id == cid, Quiz.score.isnot(None))
            .order_by(desc(Quiz.created_at))
            .limit(1)
        )
        quiz = q_res.scalar_one_or_none()

    if not quiz or not quiz.questions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("notes.no_completed_quiz"),
        )

    # Extract wrong questions
    wrong_cards: list[dict[str, Any]] = []
    questions_data = quiz.questions if isinstance(quiz.questions, list) else []

    for i, q in enumerate(questions_data, start=1):
        if not isinstance(q, dict):
            continue
        user_ans_id = q.get("user_answer")
        correct_ans_id = q.get("correct_option_id") or q.get("answer")

        user_opt_str = q.get("user_answer_text")
        correct_opt_str = q.get("correct_answer_text")

        opts = q.get("options", [])
        if not user_opt_str and opts:
            for opt in opts:
                if isinstance(opt, dict) and opt.get("id") == user_ans_id:
                    user_opt_str = str(opt.get("text", "")).strip()
            if not user_opt_str and isinstance(user_ans_id, int) and 0 <= user_ans_id < len(opts):
                user_opt_str = str(opts[user_ans_id])
            if not user_opt_str:
                user_opt_str = t("notes.remedial_not_answered")

        if not correct_opt_str and opts:
            for opt in opts:
                if isinstance(opt, dict) and opt.get("id") == correct_ans_id:
                    correct_opt_str = str(opt.get("text", "")).strip()
            if not correct_opt_str and isinstance(correct_ans_id, int) and 0 <= correct_ans_id < len(opts):
                correct_opt_str = str(opts[correct_ans_id])
            if not correct_opt_str:
                correct_opt_str = t("notes.remedial_unknown")

        is_wrong = (user_ans_id != correct_ans_id) if (user_ans_id is not None and correct_ans_id is not None) else True

        if is_wrong:
            q_text = q.get("question", t("notes.remedial_question_default", index=i))
            explanation = q.get("explanation", t("notes.remedial_review"))

            wrong_cards.append({
                "id": f"remedial_{uuid4().hex[:6]}",
                "topic": t("notes.remedial_card_topic", index=i, topic=q.get("topic", quiz.topic)),
                "summary": (
                    f"{t('notes.remedial_question_line', question=q_text)}\n"
                    f"• {t('notes.remedial_your_answer', answer=user_opt_str)}\n"
                    f"• {t('notes.remedial_correct_answer', answer=correct_opt_str)}\n\n"
                    f"{t('notes.remedial_explanation', explanation=explanation)}"
                ),
                "key_points": [
                    t("notes.remedial_correct_answer", answer=correct_opt_str),
                    t("notes.remedial_key_concept", concept=explanation[:120]),
                ],
                "source": t("notes.remedial_source", topic=quiz.topic),
                "page": i,
                "tag": "Remedial",
            })

    if not wrong_cards:
        wrong_cards.append({
            "id": f"remedial_perfect_{uuid4().hex[:6]}",
            "topic": t("notes.remedial_perfect_title", topic=quiz.topic),
            "summary": t("notes.remedial_perfect_summary"),
            "key_points": [
                t("notes.remedial_perfect_point_1"),
                t("notes.remedial_perfect_point_2"),
            ],
            "source": t("notes.remedial_source", topic=quiz.topic),
            "page": 1,
            "tag": "Remedial",
        })

    note = Note(
        id=uuid4(),
        chat_id=cid,
        title=t("notes.remedial_title", topic=quiz.topic),
        cards=wrong_cards,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    logger.info("[REMEDIAL] Generated %d remedial cards for quiz %s", len(wrong_cards), quiz.id)
    return note


def build_remedial_notes_pdf(note: Note) -> bytes:
    """Render the remedial notes as a searchable, language-aware PDF."""
    sections: list[str] = [
        f"<h1>{_html_escape(note.title)}</h1>",
        f'<p class="sub">{_html_escape(t("notes.remedial_pdf_subtitle"))}</p>',
    ]
    for card in note.cards or []:
        topic = card.get("topic", t("notes.remedial_default_topic"))
        sections.append(f"<h2>{_html_escape(topic)}</h2>")
        sections.append(f'<p>{_html_escape(card.get("summary", ""))}</p>')
        for point in card.get("key_points", []):
            sections.append(f'<p class="pt">&bull; {_html_escape(point)}</p>')
        sections.append('<div class="blank"></div>')

    return _render_html_pdf(sections)


async def get_latest_remedial_notes(db: AsyncSession, chat_id: str | UUID) -> Note | None:
    """Retrieve the most recent remedial quiz notes for a chat."""
    cid = UUID(str(chat_id)) if not isinstance(chat_id, UUID) else chat_id
    filters = [Note.title.like(f"{prefix}%") for prefix in remedial_title_prefixes()]
    condition = filters[0]
    for extra in filters[1:]:
        condition = condition | extra
    result = await db.execute(
        select(Note)
        .where(Note.chat_id == cid, condition)
        .order_by(desc(Note.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()
