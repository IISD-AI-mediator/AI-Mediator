"""Validate generated proposals against shared facts and structured constraints."""

import json
import re
from datetime import date

from .domain import BY_KEY, Problem, display, value_for
from .models import located_venue


def private_texts(room):
    texts = []
    for member in room["members"]:
        if member["profile"] and member["profile"]["extra"]:
            texts.append(member["profile"]["extra"])
        if member["profile"] and isinstance(member["profile"]["persona"], dict):
            texts.append(member["profile"]["persona"].get("instruction", ""))
        texts.extend(n["text"] for n in member["notes"])
    return texts


def safe_text(value, private=(), limit=260):
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())[:limit].strip()
    normalized = re.sub(r"\W+", "", value).casefold()
    for text in private:
        secret = re.sub(r"\W+", "", text).casefold()
        if secret and secret in normalized:
            return ""
        if len(secret) >= 12 and any(secret[i:i + 12] in normalized for i in range(len(secret) - 11)):
            return ""
    # Prices from model prose have no verifiable fare conditions. The evidence panel
    # has a separate, source-bound renderer for observed flight quotes.
    if re.search(r"최저가|최저\s*운임|[$¥€₩]\s*\d|\d[\d,.\s]*(?:만\s*)?(?:원|엔|달러|유로|USD|KRW|JPY|EUR|CNY|GBP|THB|VND)", value, re.I):
        return ""
    return value


def generated_value(key, value, private=()):
    try:
        result = value_for(key, value)
    except (Problem, TypeError, ValueError):
        return None
    if isinstance(result, str) and BY_KEY[key]["kind"] in ("text", "schedule"):
        return safe_text(result, private, 400 if key == "flight_schedule" else 160) or None
    return result


def distinct(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def public_sources(proposals):
    result, seen = [], set()
    for proposal in proposals.values():
        for evidence in proposal.get("evidence", []):
            if evidence["kind"] in ("lodging", "activity") and evidence["status"] == "observed":
                sources = [{**s, "matched": s.get("matched", True) and bool(located_venue(s.get("excerpt"), evidence.get("destination")))}
                           for s in evidence["sources"]]
                evidence = {**evidence, "sources": sources}
                if not any(s["matched"] for s in sources):
                    evidence.update(status="verify", reason="출처에서 이 장소가 여행지 안에 있는지 확인해야 해요.")
            identity = json.dumps([evidence["kind"], evidence["reason"], evidence["sources"]],
                                  sort_keys=True, ensure_ascii=False)
            if identity not in seen:
                result.append(evidence)
                seen.add(identity)
    return result


def activity_items(text):
    """Recognize explicit additive lists, never treat alternatives or exclusions as plans."""
    if not isinstance(text, str) or re.search(
        r"또는|혹은|아니면|대신|말고|제외|금지|불가|불참|취소|택일|택\s*1|중\s*(하나|한)|"
        r"싫|않|안\s*(?:가|갈|해|하|함)|못\s*(?:가|갈|해|하)|하지\s*말|피하|빼|없이|만(?:\s|$|[,·+&])|"
        r"/|\b(?:or|no|not|without|avoid|only|skip|except|instead)\b", text, re.I
    ):
        return set()
    parts = re.split(r"\s*(?:[,·;+&]|\s+(?:그리고|및|and)\s+|(?<=\S)(?:과|와)\s+)\s*", text, flags=re.I)
    return {" ".join(part.casefold().split()) for part in parts if part.strip()}


def combined_activities(needs, value, days, private):
    required_groups = [activity_items(need) for need in needs]
    proposed = activity_items(value)
    if not all(required_groups) or (value and not proposed):
        return None
    required = set.union(*required_groups)
    scheduled = set()
    for day in days:
        activity = day["activity"]
        items = activity_items(activity)
        if activity and not items and any(required_item in activity.casefold() for required_item in required):
            return None
        scheduled.update(items)
    if required <= proposed:
        return value
    if required <= scheduled:
        return generated_value("activities", " · ".join(needs), private)
    return None


def personal_budget_ceiling(member, proposal):
    if "budget" in proposal.get("overrides", []):
        # Older proposals stored the authorized limit in values alone.
        return proposal.get("budget_ceiling") or proposal["values"].get("budget", {}).get("value")
    return member["profile"]["preferences"].get("budget", {}).get("value")


def within_budget(value, ceiling):
    return value is not None and value["currency"] == ceiling["currency"] and value["amount"] <= ceiling["amount"]


def policy(room, key, raw_value, private, days=()):
    if key in room["fixed"]:
        return room["fixed"][key], "fixed", "방을 만들 때 확정한 조건이에요."
    stated = [m["profile"]["preferences"][key] for m in room["members"] if key in m["profile"]["preferences"]
              and key not in room["proposals"].get(str(m["seat"]), {}).get("overrides", [])]
    proposals = [p["values"][key] for p in room["proposals"].values() if key in p.get("values", {})]
    needs = distinct(p["value"] for p in stated + proposals if p["priority"] == "must")
    value = generated_value(key, raw_value, private)
    if key == "budget":
        caps = [p["value"] for p in proposals if p["priority"] != "delegate"]
        for member in room["members"]:
            limit = personal_budget_ceiling(member, room["proposals"].get(str(member["seat"]), {}))
            if limit:
                caps.append(limit)
        currencies = {cap["currency"] for cap in caps}
        if len(currencies) > 1:
            return None, "verify", "통화가 달라 같은 기준으로 비교할 환율과 시점이 필요해요."
        if caps:
            ceiling = min(caps, key=lambda x: x["amount"])
            if not within_budget(value, ceiling):
                value = ceiling
            return value, "agreed", "각자가 제시한 1인 예산 상한 안으로 맞췄어요."
    if len(needs) > 1:
        if key == "activities":
            combined = combined_activities(needs, value, days, private)
            if combined:
                return combined, "agreed", "제안에서 각 참여자의 필수 활동을 모두 확인했어요."
            return None, "unresolved", "참여자의 필수 활동을 모두 담은 제안이나 일정을 확인하지 못했어요."
        return None, "unresolved", "서로 다른 필수 조건을 모두 충족할 한 가지 값을 확정할 수 없어요."
    if needs:
        return needs[0], "agreed", "참여자가 꼭 지켜야 한다고 정한 조건을 우선했어요."
    # A personal agent may explicitly yield a soft preference during debate.
    important = distinct(p["value"] for p in proposals if p["priority"] == "important")
    if len(important) == 1 and value != important[0]:
        return important[0], "agreed", "일반 선호보다 높은 중요도로 제출한 조건을 우선했어요."
    if value is None:
        return None, "verify", "구체적인 값을 확인할 정보가 더 필요해요."
    return value, "agreed", ""


def decide(room, raw):
    private = private_texts(room)
    evidence = public_sources(room["proposals"])
    missing = {e["field"] for e in evidence if e["status"] != "observed"}
    conflicts = {k for k in (raw.get("conflicts") or []) if isinstance(k, str) and k in BY_KEY and k not in room["fixed"]}
    entries = dict.fromkeys(BY_KEY)
    raw_entries = raw.get("entries") if isinstance(raw.get("entries"), dict) else {}
    # A per-day activity is evidence of a compromise only after its dates and location are checked.
    other_fields = [key for key in BY_KEY if key != "activities"]
    days = []
    for key in [*other_fields, "activities"]:
        if key == "activities":
            days = checked_days(entries, raw.get("itinerary"), private, evidence)
        entry = raw_entries.get(key)
        entry = entry if isinstance(entry, dict) else {}
        val, status, reason = policy(room, key, entry.get("value"), private, days)
        if status == "unresolved":
            conflicts.add(key)
        if status != "fixed" and key in missing and status != "unresolved":
            status, reason = "verify", "관련 검색에서 조건과 근거를 함께 확인하지 못했어요."
        if status == "agreed" and entry.get("status") in ("unresolved", "verify"):
            if entry["status"] == "unresolved":
                conflicts.add(key)
                # Let the next round consider the proposed alternative before finalizing.
            status = entry["status"]
            reason = reason or ("추가 확인이 필요해요." if status == "verify" else "함께 수용할 조건을 더 조율해야 해요.")
        if not room["history"] and key not in room["fixed"] and key not in ("budget", "accessibility", "activities", "food"):
            preferences = [m["profile"]["preferences"][key] for m in room["members"] if key in m["profile"]["preferences"]]
            if len(distinct(p["value"] for p in preferences)) > 1:
                conflicts.add(key)
        if key in conflicts and status == "agreed":
            status = "unresolved"
        entries[key] = {"value": val, "status": status,
                        "reason": reason or safe_text(entry.get("reason"), private) or "제안과 중요도를 함께 검토했어요."}
    return {"round": room["round"], "entries": entries,
            "conflicts": [k for k in BY_KEY if k in conflicts],
            "evidence": evidence, "itinerary": schedule_activities(days, entries["activities"])}


def itinerary(entries, rows, private, evidence=()):
    return schedule_activities(checked_days(entries, rows, private, evidence), entries["activities"])


def checked_days(entries, rows, private, evidence):
    dates = entries["dates"]
    if not dates["value"] or dates["status"] not in ("fixed", "agreed") or not isinstance(rows, list):
        return []
    first, last = (date.fromisoformat(dates["value"][k]) for k in ("start", "end"))
    result = []
    for row in rows[:40]:
        if not isinstance(row, dict):
            continue
        try:
            when = date.fromisoformat(row["date"])
        except (ValueError, TypeError, KeyError):
            continue
        if not first <= when <= last:
            continue
        # Structured shared constraints always win over invented itinerary details.
        place = safe_text(row.get("place"), private, 100)
        activity = safe_text(row.get("activity"), private, 180)
        transport = safe_text(row.get("transport"), private, 80)
        destination = entries["destination"]
        place_status = "base"
        if not place and row.get("base") == destination["value"]:
            place = destination["value"] or ""
        if destination["status"] not in ("agreed", "fixed"):
            place, place_status = "", "verify"
        elif destination["value"] and place != destination["value"]:
            verified = place and row.get("base") == destination["value"] and any(
                e.get("destination") == destination["value"] and e["status"] == "observed" and
                any(s.get("matched", True) and located_venue(s.get("excerpt"), destination["value"]).casefold() == place.casefold()
                    for s in e["sources"]) for e in evidence)
            if verified:
                place_status = "observed"
            else:
                place, place_status = destination["value"], "verify"
        local = entries.get("local_transport", {})
        if local.get("status") in ("fixed", "agreed"):
            transport = display(local["value"])
        elif local.get("status") == "unresolved":
            transport = ""
        if place_status == "verify" or row.get("base") not in (None, destination["value"]):
            activity = ""
        result.append({"date": when.isoformat(), "place": place, "place_status": place_status,
                       "transport": transport, "activity": activity})
    return sorted(result, key=lambda r: r["date"])


def schedule_activities(days, entry):
    approved = entry["value"] if entry["status"] in ("fixed", "agreed") else None
    items = activity_items(approved)
    result = []
    for day in days:
        activity = approved or ""
        if len(items) > 1:
            scheduled = activity_items(day["activity"])
            activity = day["activity"] if scheduled and scheduled <= items else ""
        if day["place"] or day["transport"] or activity:
            result.append({**day, "activity": activity})
    return result
