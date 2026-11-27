"""Validate private requests before attributing an agent's public choice to a participant."""

import re
from decimal import Decimal

from .domain import BY_KEY, PRIORITIES
from .models import ModelError
from .prompts import REQUEST_REVIEW_PROMPT


def budget_in_quote(value, quote):
    currency = {"KRW": "원", "JPY": "엔", "USD": "달러", "EUR": "유로",
                "CNY": "위안", "GBP": "파운드", "THB": "바트", "VND": "동"}[value["currency"]]
    iso = value["currency"]
    prefix = {"KRW": "₩", "EUR": "€", "GBP": "£", "USD": r"\$"}.get(iso)
    prefix = rf"(?:{iso}|{prefix})" if prefix else iso
    number = r"((?:[1-9]\d{0,2}(?:,\d{3})+|0|[1-9]\d*)(?:\.\d+)?)"
    scale = r"\s*(만|천|억)?"
    patterns = (rf"(?<![\d.,+\-]){number}{scale}\s*(?:{currency}|{iso})",
                rf"(?<![a-z]){prefix}\s*{number}(?![\d.,]){scale}")
    for pattern in patterns:
        for match in re.finditer(pattern, quote, re.I):
            amount = Decimal(match[1].replace(",", "")) * {None: 1, "천": 1000, "만": 10000, "억": 100000000}[match[2]]
            if amount == value["amount"]:
                return True
    return False


def review_requests(adapter, text, candidates, prior=None):
    if not text or not candidates:
        return {}
    # The second reader gets the field and its schema, never the agent's proposed
    # answer. It must independently recover that same value from this person's words.
    raw = adapter.generate(REQUEST_REVIEW_PROMPT, {
        "private_request": text, "candidates": list(candidates), "previous_conditions": prior or {},
        "field_formats": {k: BY_KEY[k] for k in candidates}})
    reviews = raw.get("requests") if isinstance(raw, dict) else None
    if not isinstance(reviews, list):
        raise ModelError("개인 요청의 확인 결과를 읽지 못했어요. 다시 시도해 주세요.", transient=True)
    accepted = {}
    seen = set()
    for item in reviews:
        if not isinstance(item, dict):
            continue
        key, quote = item.get("field"), item.get("quote")
        if not isinstance(key, str) or key not in candidates:
            continue
        if key in seen:
            accepted.pop(key, None)
            continue
        seen.add(key)
        value = candidates[key]
        if (item.get("value") != value or item.get("priority") not in PRIORITIES or
                item.get("explicit") is not True or not isinstance(quote, str) or not quote.strip() or
                quote not in text or key == "budget" and not budget_in_quote(value, quote)):
            continue
        if BY_KEY[key]["kind"] in ("text", "schedule"):
            # Preserve a concrete referent as well as the semantic verdict. A
            # generic instruction about meeting at an airport cannot authorize
            # an unrelated accessible-room claim, even if a reviewer repeats it.
            words = re.findall(r"\w{2,}", value.casefold())
            if not any(word in quote.casefold() for word in words):
                continue
        accepted[key] = {"value": value, "priority": item["priority"]}
    return accepted


def participant_condition(member, proposal, field):
    record = proposal.get("accepted", {}).get(field)
    if record and (record.get("source") == "extra" and member["profile"]["extra"] or
                   record.get("source") == "note" and type(record.get("seq")) is int and
                   0 < record["seq"] <= member["handled"] and
                   any(n["seq"] == record["seq"] for n in member["notes"])):
        return {"value": record["value"], "priority": record["priority"]}
    # Older overrides have no value-bound witness. They still protect the stored
    # cap/required choice, but cannot establish authorship of a later proposal.
    if field not in proposal.get("overrides", []):
        return member["profile"]["preferences"].get(field)
    return None
