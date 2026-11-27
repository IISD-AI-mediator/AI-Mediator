"""Server-side Gemini generateContent and grounded search adapters."""

import hashlib
import json
import re
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .domain import BY_KEY
from .prompts import (EVIDENCE_REVIEW_PROMPT, FAITHFULNESS_PROMPT, JUDGE_PROMPT, OPENING_REVIEW_PROMPT,
                      OPENING_VOICE_PROMPT, QUOTE_PERMISSION_PROMPT, SEARCH_PROMPTS, VOICE_PROMPT)


def _required_object(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_TEXT = {"type": "string"}
_QUOTES = {"type": "array", "items": _TEXT}
_OPENING_WITHOUT_VALUE = _required_object(core_speech=_TEXT)
_OPENING_WITH_VALUE = _required_object(
    opening_frame=_required_object(before_value=_TEXT, after_value=_TEXT),
    core_speech=_TEXT,
    rendering=_required_object(register={"type": "string", "enum": ["formal_polite", "polite", "informal"]},
                               opening={"type": "string", "enum": ["none", "attention", "thought"]}),
)
_REVIEWED_ACTION = _required_object(
    kind={"type": "string", "enum": ["defend", "yield", "alternative", "verify", "maintain", "other"]}, quote=_TEXT,
)
_OPENING_REVIEW = _required_object(
    opening_assessment={"type": "string", "enum": ["own_offer", "assumes_prior_turn", "unsupported_claim", "changed_offer"]},
    faithful={"type": "boolean"}, added=_QUOTES, missing=_QUOTES,
    actions=_required_object(source=_REVIEWED_ACTION, candidate=_REVIEWED_ACTION),
    matches={"type": "array", "items": _required_object(candidate=_TEXT, source=_TEXT)},
)


class ModelError(Exception):
    def __init__(self, message, *, transient=False):
        super().__init__(message)
        self.transient = transient


def online_url(raw):
    if not isinstance(raw, str) or not 0 < len(raw) <= 4000 or any(char.isspace() or ord(char) < 32 for char in raw):
        return ""
    try:
        parsed = urlsplit(raw)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return raw
    except (ValueError, TypeError, AttributeError):
        pass
    return ""


class Gemini:
    def __init__(self, key, model, timeout=45):
        self.key, self.model, self.timeout = key, model, timeout

    def generate(self, instruction, data, *, search=False):
        return self._generate(instruction, data, search, 8192, self.timeout)

    def generate_voice(self, instruction, data):
        # A stalled optional utterance must not consume a full negotiation timeout.
        if self.model == "gemini-3.8-flash" and instruction in (FAITHFULNESS_PROMPT, OPENING_REVIEW_PROMPT):
            # This verdict includes aligned quotations from both public messages.
            return self._generate(instruction, data, False, 3072, min(self.timeout, 16))
        return self._generate(instruction, data, False, 1024, min(self.timeout, 12))

    def _generate(self, instruction, data, search, max_tokens, timeout):
        if not self.key:
            raise ModelError("서버의 Gemini API 키를 설정한 뒤 다시 시도해 주세요.")
        content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        body = {"systemInstruction": {"parts": [{"text": instruction}]},
                "contents": [{"role": "user", "parts": [{"text": content}]}],
                "generationConfig": {"maxOutputTokens": max_tokens}}
        if search:
            body["tools"] = [{"google_search": {}}]
        else:
            body["generationConfig"]["responseMimeType"] = "application/json"
            if instruction == OPENING_VOICE_PROMPT:
                body["generationConfig"]["responseJsonSchema"] = (
                    _OPENING_WITHOUT_VALUE if data.get("value") is None else _OPENING_WITH_VALUE)
            elif instruction == OPENING_REVIEW_PROMPT:
                body["generationConfig"]["responseJsonSchema"] = _OPENING_REVIEW
            if self.model == "gemini-3.8-flash" and instruction in (
                    JUDGE_PROMPT, VOICE_PROMPT, OPENING_VOICE_PROMPT, FAITHFULNESS_PROMPT,
                    OPENING_REVIEW_PROMPT, QUOTE_PERMISSION_PROMPT):
                body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "LOW"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='-._')}:generateContent"
        req = Request(url, data=json.dumps(body).encode(), method="POST",
                      headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        try:
            with urlopen(req, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code in (401, 403, 404):
                raise ModelError(f"Gemini 모델 {self.model}의 키·접근 권한·모델 이름을 확인해 주세요.") from None
            if error.code == 429:
                raise ModelError("Gemini 사용 한도에 도달했어요. 잠시 후 다시 시도해 주세요.", transient=True) from None
            raise ModelError(f"Gemini가 요청을 처리하지 못했어요 (HTTP {error.code}).",
                             transient=error.code >= 500) from None
        except (HTTPException, OSError, URLError, TimeoutError, ValueError):
            raise ModelError("Gemini 연결이 지연됐어요. 다시 시도해 주세요.", transient=True) from None
        candidates = result.get("candidates") if isinstance(result, dict) else None
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise ModelError("Gemini가 사용할 수 있는 응답을 반환하지 않았어요.", transient=True)
        candidate = candidates[0]
        if search:
            return candidate
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ModelError("모델 응답의 본문을 읽을 수 없어요.", transient=True)
        raw = "".join(p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought"))
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError
            return parsed
        except (TypeError, ValueError):
            raise ModelError("모델 응답의 형식을 읽을 수 없어요. 다시 시도해 주세요.", transient=True) from None


SEARCH_FIELDS = {"flight": ("origin", "destination", "dates", "departure_time", "budget", "transport"),
                 "restaurant": ("destination", "lodging", "food", "accessibility"),
                 "lodging": ("destination", "dates", "lodging", "accessibility"),
                 "activity": ("destination", "dates", "activities", "accessibility")}
SEARCH_TOPICS = {"flight": "transport", "restaurant": "food", "lodging": "lodging", "activity": "activities"}
MAX_SEARCH_SOURCES = 6


def flight_quote(text, context):
    """Read comparable facts from one cited fare. The reviewer interprets its conditions."""
    parts = {}
    for part in text.strip().rstrip(".").split("|"):
        key, sep, val = part.partition("=")
        key = key.strip()
        if not sep or key in parts or not val.strip():
            return None
        parts[key] = val.strip()
    if set(parts) != {"출발지","도착지","가는날","오는날","출발시각","금액","통화","조건"}:
        return None
    dates = context.get("dates") or {}
    expected = {"출발지": context.get("origin"), "도착지": context.get("destination"),
                "가는날": dates.get("start"), "오는날": dates.get("end"), "통화": context.get("currency")}
    if any(not val or parts.get(key) != val for key, val in expected.items()):
        return None
    ranges = {"새벽": (4, 7), "오전": (7, 12), "오후": (12, 18), "저녁": (18, 22), "심야": (22, 4)}
    window = ranges.get(context.get("departure_time"))
    clock = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", parts.get("출발시각", ""))
    if not window or not clock:
        return None
    hour = int(clock[1])
    if window[0] < window[1]:
        matches = window[0] <= hour < window[1]
    else:
        matches = hour >= window[0] or hour < window[1]
    fare = parts.get("조건", "")
    amount = parts["금액"]
    if not re.fullmatch(r"(?:[1-9][0-9]{0,9}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,3})", amount):
        return None
    amount = amount.replace(",", "")
    if not matches or len(amount) > 10 or not 0 < len(fare) < 180:
        return None
    return {"amount": int(amount), "currency": parts["통화"], "time": parts["출발시각"],
            "origin": parts["출발지"], "destination": parts["도착지"], "dates": dates, "terms": fare}


def public_context(kind, fixed, preferences, inferred=None):
    context = {}
    inferred = inferred or {}
    for key in SEARCH_FIELDS[kind]:
        value = fixed.get(key, inferred.get(key, preferences.get(key, {}).get("value")))
        if kind == "flight" and key == "budget" and value is None and inferred.get("currency"):
            context["currency"] = inferred["currency"]
        if value is not None:
            if kind == "flight" and key == "budget":
                context["currency"] = value["currency"]
            else:
                context[key] = value
    return context


def review_signature(kind, context, source):
    """Bind the stored AI verdict to the exact public facts that it confirmed."""
    facts = [kind, context, source.get("url"), source.get("excerpt"), source.get("quote"), source.get("venue")]
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sem1-" + hashlib.sha256(payload).hexdigest()


def reviewed_source(evidence, source):
    context = evidence.get("review_context")
    return (source.get("matched") is True and isinstance(context, dict)
            and evidence.get("destination", "") == context.get("destination", "")
            and bool(online_url(source.get("url")))
            and source.get("review_proof") == review_signature(evidence["kind"], context, source))


def grounded_passages(chunks, supports, *, single_only=False):
    for support in supports:
        if not isinstance(support, dict):
            continue
        segment = support.get("segment")
        text = segment.get("text") if isinstance(segment, dict) else None
        indices = support.get("groundingChunkIndices")
        if not isinstance(text, str) or not text.strip() or not isinstance(indices, list):
            continue
        if single_only and (len(indices) != 1 or len(text) > 650):
            continue
        for index in indices:
            if type(index) is not int or not 0 <= index < len(chunks) or not isinstance(chunks[index], dict):
                continue
            web = chunks[index].get("web")
            url = online_url(web.get("uri")) if isinstance(web, dict) else ""
            if url:
                yield (url, text), web


def cited_sources(metadata, kind, context):
    chunks = metadata.get("groundingChunks")
    supports = metadata.get("groundingSupports")
    sources, segments, fares = [], [], {}
    if not isinstance(chunks, list) or not isinstance(supports, list):
        return sources, segments, fares

    # Reserve review slots before filling the remaining space with display-only links.
    # A passage can have both a composite support and an independent support.
    eligible = {}
    for key, _ in grounded_passages(chunks, supports, single_only=True):
        if key in eligible:
            continue
        fare = flight_quote(key[1], context) if kind == "flight" else None
        if kind == "flight" and not fare:
            continue
        eligible[key] = fare
        if len(eligible) == MAX_SEARCH_SOURCES:
            break

    other_slots = MAX_SEARCH_SOURCES - len(eligible)
    shown = set()
    for key, web in grounded_passages(chunks, supports):
        if key in shown:
            continue
        url, text = key
        source_id = len(sources)
        if key in eligible:
            segments.append({"id": source_id, "text": text})
            if eligible[key] is not None:
                fares[source_id] = eligible[key]
        elif other_slots:
            other_slots -= 1
        else:
            continue
        shown.add(key)
        title = str(web.get("title") or "검색 출처")[:140]
        if kind == "flight" and not re.fullmatch(r"[\w.-]+\.[A-Za-z]{2,}", title):
            title = "항공 운임 조회 출처"
        sources.append({"url": url, "title": title, "excerpt": "" if kind == "flight" else text[:650],
                        "matched": False, "quote": None, "venue": ""})
        if len(sources) == MAX_SEARCH_SOURCES:
            break
    return sources, segments, fares


def review_citations(adapter, evidence, segments, fares):
    if not segments:
        return
    kind, criteria = evidence["kind"], evidence["review_context"]
    try:
        reply = adapter.generate(EVIDENCE_REVIEW_PROMPT, {"kind": kind, "criteria": criteria, "segments": segments})
    except ModelError:
        return
    reviews = reply.get("reviews") if isinstance(reply, dict) else None
    if not isinstance(reviews, list) or len(reviews) > len(segments):
        return
    texts = {segment["id"]: segment["text"] for segment in segments}
    by_id = {}
    for review in reviews:
        index = review.get("id") if isinstance(review, dict) else None
        if type(index) is not int or index not in texts or index in by_id:
            return
        by_id[index] = review
    for index, review in by_id.items():
        if review.get("supported") is not True:
            continue
        source = evidence["sources"][index]
        if kind in ("activity", "lodging"):
            venue = review.get("venue")
            if not isinstance(venue, str) or not venue.strip() or len(venue) > 100 or venue not in texts[index]:
                continue
            source["venue"] = venue
        source.update(matched=True, quote=fares.get(index))
        source["review_proof"] = review_signature(kind, criteria, source)


def grounded_search(adapter, kind, context):
    result = {"kind": kind, "field": SEARCH_TOPICS[kind], "status": "verify", "sources": [],
              "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "reason": "조건에 맞는 출처를 확인하지 못했어요.", "entry": "",
              "destination": context.get("destination", ""), "review_context": dict(context)}
    if kind == "restaurant":
        result["restaurant_criteria"] = {key: context.get(key) for key in ("lodging", "food")}
    if kind == "flight" and not all(context.get(k) for k in ("origin", "destination", "dates", "departure_time", "currency")):
        result["reason"] = "노선·날짜·출발 시간대·통화를 모두 알아야 운임을 비교할 수 있어요."
        return result
    if kind == "restaurant" and not all(context.get(k) for k in ("lodging", "food")):
        result["reason"] = "숙소 주변 식당을 찾으려면 숙소 위치와 원하는 음식 종류가 필요해요."
        return result
    if kind in ("lodging", "activity") and not context.get("destination"):
        result["reason"] = "장소가 여행지 안에 있는지 확인할 수 있도록 도시가 필요해요."
        return result
    try:
        candidate = adapter.generate(SEARCH_PROMPTS[kind], context, search=True)
    except ModelError as error:
        result["reason"] = "검색 연결을 확인해 주세요. " + str(error)
        return result
    metadata = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
    if not isinstance(metadata, dict) or not isinstance(metadata.get("webSearchQueries"), list) or not metadata["webSearchQueries"]:
        return result
    entry_point = metadata.get("searchEntryPoint")
    entry = entry_point.get("renderedContent") if isinstance(entry_point, dict) else None
    if isinstance(entry, str) and len(entry) <= 30000:
        result["entry"] = entry
    sources, segments, fares = cited_sources(metadata, kind, context)
    result["sources"] = sources
    review_citations(adapter, result, segments, fares)
    supported = any(s["matched"] for s in result["sources"])
    if supported:
        result.update(status="observed", reason="출처와 조회 시각을 기록했어요.")
    elif kind == "flight":
        result["reason"] = "같은 노선·날짜·시간대·통화의 왕복 운임 조건을 출처에서 함께 확인하지 못했어요."
    elif kind in ("lodging", "activity"):
        result["reason"] = "같은 출처에서 구체적인 장소와 여행지 내 위치를 함께 확인하지 못했어요."
    return result


FIELD_GUIDE = {k: ({"amount": "양의 정수", "currency": "ISO 통화"} if k == "budget"
                    else {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} if k == "dates"
                    else v["options"] or v["label"]) for k, v in BY_KEY.items()}
