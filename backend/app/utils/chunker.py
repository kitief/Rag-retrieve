"""
Token-aware text chunker. Splits document pages into overlapping chunks of
~chunk_size tokens, preferring sentence boundaries when possible.

`tiktoken` needs to download the `cl100k_base` BPE table the first time an
encoding is created. On an air-gapped host, or when DNS is unreliable, that
download fails — and since it happens at import time it used to take the whole
API down. We therefore degrade to an approximate token count instead of
crashing: chunk boundaries move by a few tokens, retrieval quality does not.

Set `TIKTOKEN_CACHE_DIR` (the desktop launcher points it at the model cache
under the data directory) to keep the downloaded table across restarts.
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - depends on the host network
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception as exc:  # ImportError, or a ConnectionError while downloading
    _ENCODING = None
    logger.warning(
        "tiktoken is unavailable (%s: %s) — falling back to an approximate token "
        "counter. Chunk sizes may differ slightly from the configured values.",
        type(exc).__name__,
        exc,
    )

# CJK, Hiragana, Katakana and Hangul: roughly one token per character.
_WIDE_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")


def _approximate_tokens(text: str) -> int:
    """Cheap token estimate: 1 per CJK glyph, 1 per ~4 Latin characters."""
    if not text:
        return 0
    wide = len(_WIDE_CHAR_RE.findall(text))
    return wide + max(1, (len(text) - wide + 3) // 4)


def _encode_tokens(text: str) -> list[int]:
    return _ENCODING.encode(text) if _ENCODING is not None else []


def _decode_tokens(token_ids: list[int]) -> str:
    return _ENCODING.decode(token_ids) if _ENCODING is not None else ""


def _count_tokens(text: str) -> int:
    if _ENCODING is None:
        return _approximate_tokens(text)
    return len(_ENCODING.encode(text))



def _split_into_sentences(text: str) -> list[str]:
    """
    Naïve sentence splitter. Falls back gracefully on edge cases.
    Splits after sentence-ending punctuation — English ".", "!", "?" and
    Chinese "。", "！", "？", "；" — and on blank-line boundaries.

    Chinese punctuation is followed directly by the next sentence (no space),
    so the split is zero-width: the punctuation stays attached to its sentence
    instead of being consumed by the delimiter.
    """
    # Split after sentence-ending punctuation, or on blank-line boundaries.
    # English punctuation requires trailing whitespace (so "3.14" / "e.g." are
    # not split); Chinese punctuation is zero-width because the next sentence
    # follows the mark directly with no space.
    parts = re.split(r"(?<=[.!?])\s+|(?<=[。！？；])\s*|\n{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_pages(
    pages: list[dict[str, Any]],
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """
    Chunk a list of parsed document pages into overlapping token windows.

    Args:
        pages:      Output of parsers.parse_file() — list of {text, page, source}.
        chunk_size: Target maximum tokens per chunk.
        overlap:    Number of tokens to carry over between consecutive chunks.

    Returns:
        List of dicts: {text, page, source, chunk_index, token_count}.
    """
    chunks: list[dict[str, Any]] = []
    chunk_index = 0

    for page_obj in pages:
        page_text: str = page_obj["text"]
        page_num: int = page_obj["page"]
        source: str = page_obj["source"]

        if not page_text.strip():
            continue

        sentences = _split_into_sentences(page_text)
        if not sentences:
            continue

        current_sentences: list[str] = []
        current_tokens: int = 0

        for sentence in sentences:
            s_tokens = _count_tokens(sentence)

            # If a single sentence exceeds chunk_size, force-split it by tokens
            if s_tokens > chunk_size:
                # Flush current buffer first
                if current_sentences:
                    chunk_text = " ".join(current_sentences)
                    chunks.append(
                        {
                            "text": chunk_text,
                            "page": page_num,
                            "source": source,
                            "chunk_index": chunk_index,
                            "token_count": _count_tokens(chunk_text),
                        }
                    )
                    chunk_index += 1
                    current_sentences = []
                    current_tokens = 0

                # Hard-split the long sentence at token boundaries
                token_ids = _encode_tokens(sentence)
                if not token_ids:
                    # Approximate mode: slice by characters instead (≈4 per token).
                    stride = max(1, chunk_size * 4)
                    step = max(1, stride - overlap * 4)
                    for start in range(0, len(sentence), step):
                        sub_text = sentence[start:start + stride]
                        if not sub_text:
                            continue
                        chunks.append(
                            {
                                "text": sub_text,
                                "page": page_num,
                                "source": source,
                                "chunk_index": chunk_index,
                                "token_count": _count_tokens(sub_text),
                            }
                        )
                        chunk_index += 1
                    continue

                start = 0
                while start < len(token_ids):
                    end = min(start + chunk_size, len(token_ids))
                    sub_text = _decode_tokens(token_ids[start:end])
                    chunks.append(
                        {
                            "text": sub_text,
                            "page": page_num,
                            "source": source,
                            "chunk_index": chunk_index,
                            "token_count": end - start,
                        }
                    )
                    chunk_index += 1
                    start += chunk_size - overlap
                continue

            # Would adding this sentence exceed the target size?
            if current_tokens + s_tokens > chunk_size and current_sentences:
                chunk_text = " ".join(current_sentences)
                chunks.append(
                    {
                        "text": chunk_text,
                        "page": page_num,
                        "source": source,
                        "chunk_index": chunk_index,
                        "token_count": _count_tokens(chunk_text),
                    }
                )
                chunk_index += 1

                # Carry over overlap: take trailing sentences summing to ≤ overlap tokens
                overlap_sentences: list[str] = []
                overlap_tokens = 0
                for prev_sentence in reversed(current_sentences):
                    pt = _count_tokens(prev_sentence)
                    if overlap_tokens + pt > overlap:
                        break
                    overlap_sentences.insert(0, prev_sentence)
                    overlap_tokens += pt

                current_sentences = overlap_sentences
                current_tokens = overlap_tokens

            current_sentences.append(sentence)
            current_tokens += s_tokens

        # Flush any remaining sentences for this page
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            chunks.append(
                {
                    "text": chunk_text,
                    "page": page_num,
                    "source": source,
                    "chunk_index": chunk_index,
                    "token_count": _count_tokens(chunk_text),
                }
            )
            chunk_index += 1

    logger.info("Chunked %d pages into %d chunks", len(pages), len(chunks))
    return chunks
