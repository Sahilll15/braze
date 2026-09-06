from version import parse_version


def test_full_version():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_single_number():
    assert parse_version("4") == (4,)


def test_two_part_version_is_padded_to_three():
    """A two-part version should be normalised to three parts."""
    assert parse_version("1.2") == (1, 2, 0)


def test_two_part_version_keeps_its_length():
    """A two-part version should be returned exactly as written."""
    assert parse_version("1.2") == (1, 2)
