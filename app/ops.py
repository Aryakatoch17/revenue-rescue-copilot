"""Process-wide busy lock so mashed / concurrent judge clicks don't corrupt SQLite."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

_lock = threading.Lock()
_busy = False
_busy_op = ""
_busy_since = 0.0


class BusyError(RuntimeError):
    def __init__(self, op: str):
        super().__init__(f"Busy: another '{op}' is in progress. Wait and retry.")
        self.op = op


def status() -> dict:
    with _lock:
        return {
            "busy": _busy,
            "op": _busy_op or None,
            "busy_for_ms": int((time.time() - _busy_since) * 1000) if _busy else 0,
        }


@contextmanager
def exclusive(op: str) -> Iterator[None]:
    global _busy, _busy_op, _busy_since
    if not _lock.acquire(blocking=False):
        raise BusyError(_busy_op or op)
    if _busy:
        _lock.release()
        raise BusyError(_busy_op or op)
    _busy = True
    _busy_op = op
    _busy_since = time.time()
    _lock.release()
    try:
        yield
    finally:
        with _lock:
            _busy = False
            _busy_op = ""
            _busy_since = 0.0
