"""
In-memory ingestion progress registry.

Parsing a scanned PDF is slow -- OCR of a single page costs seconds, and a long
scan costs minutes. A UI that only knows ``processing`` cannot tell "still
working" from "hung", so the pipeline reports fine-grained progress.

Progress is deliberately *not* authoritative state: it lives in this process and
disappears on restart, because a progress bar that survived a crash would be
lying. The durable record is the ``Document`` row (``status``, ``progress`` and
``parse_audit``), which the async pump in
:mod:`app.services.ingestion_service` keeps in sync.

The thread pool writes here and the event loop reads here, so every mutation is
guarded by a lock. Contention is nil -- one writer, one reader, a few updates
per second.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

#: Percent at which parsing starts. Auditing and OCR own the bulk of the range
#: because that is where the wall-clock time actually goes.
PARSE_START = 5
PARSE_END = 75
CHUNK_AT = 80
EMBED_START = 82
EMBED_END = 95
STORE_AT = 97
DONE = 100


class ProgressReporter:
    """Thread-safe progress holder for one document."""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        self._lock = threading.Lock()
        self._percent = 0
        self._stage = "queued"
        self._detail = ""
        self._updated = time.time()

    def update(self, percent: Optional[int] = None, stage: Optional[str] = None, detail: str = "") -> None:
        with self._lock:
            if percent is not None:
                # Never move backwards: a late callback from a previous stage
                # must not make the bar jump around.
                self._percent = max(self._percent, max(0, min(100, int(percent))))
            if stage is not None:
                self._stage = stage
            self._detail = detail
            self._updated = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "progress": self._percent,
                "stage": self._stage,
                "detail": self._detail,
                "updated_at": self._updated,
            }


_REPORTERS: Dict[str, ProgressReporter] = {}
_REGISTRY_LOCK = threading.Lock()


def start(document_id: str) -> ProgressReporter:
    """Create (or reset) the reporter for a document."""
    reporter = ProgressReporter(document_id)
    with _REGISTRY_LOCK:
        _REPORTERS[document_id] = reporter
    return reporter


def get(document_id: str) -> Optional[ProgressReporter]:
    with _REGISTRY_LOCK:
        return _REPORTERS.get(document_id)


def snapshot(document_id: str) -> Optional[Dict[str, Any]]:
    reporter = get(document_id)
    return reporter.snapshot() if reporter else None


def finish(document_id: str) -> None:
    """Drop the reporter once the row itself carries the final state."""
    with _REGISTRY_LOCK:
        _REPORTERS.pop(document_id, None)
