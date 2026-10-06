"""Slow down password guessing and mass sign-ups. In memory, per process (run a single backend worker)."""
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_events: dict[str, deque] = defaultdict(deque)


def blocked(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _lock:
        q = _events[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        return len(q) >= limit


def record(key: str) -> None:
    with _lock:
        _events[key].append(time.time())


def clear(key: str) -> None:
    with _lock:
        _events.pop(key, None)


def reset() -> None:
    """For tests."""
    with _lock:
        _events.clear()
