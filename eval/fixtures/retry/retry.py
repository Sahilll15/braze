"""A retry decorator."""

from __future__ import annotations

import time
from functools import wraps


def retry(attempts: int = 3, delay: float = 0.0):
    """Retry a callable up to `attempts` times before giving up."""

    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for _ in range(attempts - 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last = exc
                    if delay:
                        time.sleep(delay)
            raise last

        return wrapper

    return decorate
