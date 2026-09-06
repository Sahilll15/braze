"""A tiny LRU cache."""

from __future__ import annotations

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int = 3):
        self.capacity = capacity
        self._items: OrderedDict[str, int] = OrderedDict()

    def get(self, key: str) -> int | None:
        if key not in self._items:
            return None
        return self._items[key]

    def put(self, key: str, value: int) -> None:
        self._items[key] = value
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def keys(self) -> list[str]:
        return list(self._items)
