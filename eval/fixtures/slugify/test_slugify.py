from slugify import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_punctuation_collapses():
    assert slugify("Hello --- World!!!") == "hello-world"


def test_empty_string():
    assert slugify("") == ""


def test_accented_characters_are_transliterated():
    """Accents should become their ASCII base letter, not disappear."""
    assert slugify("Café Münster") == "cafe-munster"


def test_leading_digits_survive():
    assert slugify("2026 Review") == "2026-review"
