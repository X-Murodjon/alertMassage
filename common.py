from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = DATA_DIR / "state.json"


def load_bot_settings(require_chat_id: bool = True) -> dict[str, str | int | bool]:
    load_dotenv(ENV_FILE)
    required = ["BOT_TOKEN"]
    if require_chat_id:
        required.append("ALERT_CHAT_ID")

    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError(
            ".env faylida quyidagi qiymatlar to'ldirilmagan: "
            + ", ".join(missing)
        )

    try:
        poll_seconds = max(20, int(os.getenv("POLL_SECONDS", "45")))
    except ValueError as exc:
        raise RuntimeError("POLL_SECONDS butun son bo'lishi kerak.") from exc

    value = os.getenv("ALERT_ALL_DOCUMENTS", "true").strip().casefold()
    alert_all_documents = value in {"1", "true", "yes", "ha"}
    ai_value = os.getenv("AI_ENABLED", "true").strip().casefold()
    ai_enabled = ai_value in {"1", "true", "yes", "ha"}

    return {
        "bot_token": os.environ["BOT_TOKEN"].strip(),
        "alert_chat_id": os.getenv("ALERT_CHAT_ID", "").strip(),
        "poll_seconds": poll_seconds,
        "alert_all_documents": alert_all_documents,
        "ai_enabled": ai_enabled,
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "gemini_model": os.getenv(
            "GEMINI_MODEL", "gemini-3.5-flash-lite"
        ).strip(),
    }


def read_config_lines(filename: str) -> list[str]:
    path = CONFIG_DIR / filename
    if not path.exists():
        return []

    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            values.append(line)
    return values


def normalize_channel(value: str) -> str:
    channel = value.strip().rstrip("/")
    for prefix in ("https://t.me/s/", "http://t.me/s/", "https://t.me/", "http://t.me/"):
        if channel.casefold().startswith(prefix):
            channel = channel[len(prefix):]
            break
    return channel.lstrip("@").split("?", 1)[0].strip()
