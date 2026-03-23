import json
import os
import sys


def _data_dir() -> str:
    """Return the directory for user config/data files.

    Frozen builds use %APPDATA%/Prism so the app works when installed
    to a read-only location like Program Files.  Dev mode uses the
    script directory for convenience.
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        d = os.path.join(appdata, "Prism")
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.abspath(__file__))


_BASE = _data_dir()
CONFIG_FILE = os.path.join(_BASE, "config.json")
ENV_FILE = os.path.join(_BASE, ".env")


def _load_env_file() -> dict:
    """Parse .env file and return key/value pairs."""
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env

DEFAULTS = {
    "api_key": "",
    "model": "gpt-4o-mini",
    "theme": "dark",
    "opacity": 0.35,
    "always_on_top": True,
    "lock_position": False,
    "restore_position": True,
    "window_x": -1,
    "window_y": -1,
    "window_width": 320,
    "window_height": 460,
}


def load() -> dict:
    result = DEFAULTS.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result.update(data)
        except Exception:
            pass
    # .env takes priority for the API key
    env = _load_env_file()
    env_key = env.get("OPENAI_API_KEY", "").strip()
    if env_key and env_key != "your-api-key-here":
        result["api_key"] = env_key
    return result


def save(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
