from wrapper import wrap


def test_short_text_is_one_line():
    assert wrap("hello world", width=40) == ["hello world"]


def test_wraps_at_the_width():
    assert wrap("aaa bbb ccc ddd", width=7) == ["aaa bbb", "ccc ddd"]


def test_empty_text_is_no_lines():
    assert wrap("", width=10) == []


def test_a_word_longer_than_the_width_gets_its_own_line():
    """An over-long word cannot be wrapped, so it stands alone rather than
    being glued onto the previous line."""
    assert wrap("hi supercalifragilistic there", width=10) == [
        "hi",
        "supercalifragilistic",
        "there",
    ]


def test_the_joining_space_counts_toward_the_width():
    """'aaa bbb' is 7 characters, so it does not fit in a width of 6."""
    assert wrap("aaa bbb", width=6) == ["aaa", "bbb"]
