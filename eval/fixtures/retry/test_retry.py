import pytest

from retry import retry


def test_returns_on_first_success():
    calls = []

    @retry(attempts=3)
    def ok():
        calls.append(1)
        return "fine"

    assert ok() == "fine"
    assert len(calls) == 1


def test_retries_until_success():
    calls = []

    @retry(attempts=3)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "fine"

    assert flaky() == "fine"
    assert len(calls) == 3


def test_uses_every_attempt_before_giving_up():
    """attempts=3 means the function is called three times, not two."""
    calls = []

    @retry(attempts=3)
    def always_fails():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_fails()
    assert len(calls) == 3
