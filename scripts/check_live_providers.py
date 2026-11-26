"""Check the release's real Gemini adapters on an explicitly selected Render build."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from travel_app.models import Gemini, ModelError


def check_model(client):
    result = client.generate('Return the JSON object {"ok":true}.', {"check": "release"})
    return isinstance(result, dict) and result.get("ok") is True


def check_search(client):
    candidate = client.generate(
        "Use Google Search to find the official website of the National Museum of Korea, Seoul. "
        "Give the museum's name and cite the official website.", {"city": "Seoul"}, search=True)
    grounding = candidate.get("groundingMetadata", {})
    sources = [chunk.get("web", {}).get("uri", "") for chunk in grounding.get("groundingChunks", [])]
    return bool(grounding.get("webSearchQueries")) and any(urlsplit(url).scheme == "https" for url in sources)


def provider_error(error):
    cause = error.__context__
    if not isinstance(cause, HTTPError):
        return str(error)
    try:
        details = json.load(cause).get('error', {})
        codes = [details.get('status')] + [d.get('reason') for d in details.get('details', []) if isinstance(d, dict)]
        codes = [code for code in codes if isinstance(code, str) and re.fullmatch('[A-Z_]{3,64}', code)]
    except (ValueError, AttributeError, TypeError, OSError):
        codes = []
    return ' '.join([f'HTTP {cause.code}', *codes])


def main():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if os.environ.get("PROVIDER_CHECK_VERSION") != version:
        return
    key = os.environ.get("GEMINI_API_KEY", "")
    member = Gemini(key, os.getenv("MEMBER_MODEL", "gemini-3.1-flash-lite"), timeout=30)
    judge = Gemini(key, os.getenv("MEDIATOR_MODEL", "gemini-3.8-flash"), timeout=30)
    checks = (("member", member, check_model), ("decision", judge, check_model), ("search", member, check_search))
    for label, client, check in checks:
        try:
            status = 'verified' if check(client) else 'unconfirmed_response'
        except ModelError as error:
            status = 'unavailable: ' + provider_error(error)
        print(f'Provider check {version} {label} {client.model} {status}', flush=True)


if __name__ == '__main__':
    main()
