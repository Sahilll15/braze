import json
import subprocess
import sys
from pathlib import Path

import pytest

import wc

SAMPLE = "alpha beta\ngamma\n"


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    file = tmp_path / "sample.txt"
    file.write_text(SAMPLE, encoding="utf-8")
    return file


def test_count_counts_lines_words_and_chars():
    assert wc.count(SAMPLE) == {"lines": 2, "words": 3, "chars": 17}


def test_count_handles_empty_input():
    assert wc.count("") == {"lines": 0, "words": 0, "chars": 0}


def test_main_prints_a_row_per_file(sample: Path, capsys: pytest.CaptureFixture[str]):
    assert wc.main([str(sample)]) == 0
    out = capsys.readouterr().out
    assert str(sample) in out
    assert "2" in out and "3" in out


def test_main_reports_missing_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert wc.main([str(tmp_path / "nope.txt")]) == 1
    assert "no such file" in capsys.readouterr().err


def test_json_flag_emits_one_object_per_file(sample: Path, capsys: pytest.CaptureFixture[str]):
    """--json should print a JSON array of {name, lines, words, chars} objects."""
    assert wc.main(["--json", str(sample)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"name": str(sample), "lines": 2, "words": 3, "chars": 17}]


def test_json_flag_is_documented_in_help():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "wc.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert "--json" in result.stdout
