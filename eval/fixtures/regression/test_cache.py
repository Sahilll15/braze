from cache import LRUCache


def test_stores_and_reads():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    assert c.get("a") == 1


def test_missing_key_is_none():
    assert LRUCache().get("nope") is None


def test_evicts_the_oldest_when_full():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    assert c.keys() == ["b", "c"]


def test_reading_a_key_makes_it_recently_used():
    """A get() must count as use, or this is an insertion-order cache, not an LRU."""
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")
    c.put("c", 3)
    assert c.keys() == ["a", "c"]


def test_updating_an_existing_key_does_not_grow_the_cache():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("a", 9)
    c.put("b", 2)
    assert c.keys() == ["a", "b"]
    assert c.get("a") == 9
