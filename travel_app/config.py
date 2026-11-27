import os
from pathlib import Path

from dotenv import dotenv_values


def gemini_api_key() -> str:
    if "GEMINI_API_KEY" in os.environ:
        return os.environ["GEMINI_API_KEY"]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
    return values.get("GEMINI_API_KEY") or ""
