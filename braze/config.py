import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".braze"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _read_config() -> dict:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # Readable by the owner only. A key in a world-readable file is a leaked key.
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def get_api_key() -> str:
    """Find the user's own key, or ask for it once and remember it.

    Order: environment, then ~/.braze/config.json, then prompt. No key ever
    ships with this package.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key

    key = _read_config().get("api_key")
    if key:
        return key

    print("braze needs your own OpenAI API key.")
    print("Get one at https://platform.openai.com/api-keys\n")
    key = input("  paste your key: ").strip()
    if not key:
        raise SystemExit("no key given, nothing to do")

    data = _read_config()
    data["api_key"] = key
    _write_config(data)
    print(f"\nsaved to {CONFIG_FILE} (owner-readable only)")
    print("Delete that file or set OPENAI_API_KEY to change it.\n")
    return key
