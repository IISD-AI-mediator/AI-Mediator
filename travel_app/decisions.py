"""Validate generated proposals against shared facts and structured constraints."""

import json
import re
from datetime import date

from .activity_review import review_activities
from .domain import BY_KEY, Problem, display, value_for
from .evidence_compat import checked_evidence
from .models import reviewed_source
from .participant_intent import participant_condition


def private_texts(room):
    texts = []
    for member in room["members"]:
        if member["profile"] and member["profile"]["extra"]:
            texts.append(member["profile"]["extra"])
        if member["profile"] and isinstance(member["profile"]["persona"], dict):
            texts.append(member["profile"]["persona"].get("instruction", ""))
        texts.extend(n["text"] for n in member["notes"])
    return texts


def overlaps_private_text(value, private, *, joined_at=()):
    normalized = re.sub(r"\W+", "", value).casefold()
    joins = [len(re.sub(r"\W+", "", value[:i]).casefold()) for i in joined_at]
    for text in private:
        secret = re.sub(r"\W+", "", text).casefold()
        if not secret:
            continue
        width = min(12, len(secret))
        # A width-character match in this window necessarily spans the join.
        # This excludes overlaps entirely inside an already-public value.
        windows = [normalized[max(0, j - width + 1):j + width - 1] for j in joins] if joins else [normalized]
        if any(secret[i:i + width] in window for window in windows for i in range(len(secret) - width + 1)):
            return True
    return False


def safe_text(value, private=(), limit=260, *, voice_review=False):
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())[:limit].strip()
    if overlaps_private_text(value, private):
        return ""
    # Prices from model prose have no verifiable fare conditions. The evidence panel
    # has a separate, source-bound renderer for observed flight quotes.
    if not voice_review and re.search(r"최저가|최저\s*운임", value):
        return ""
    if re.search(r"[$¥€₩]\s*\d|\d[\d,.\s]*(?:만\s*)?(?:원|엔|달러|유로|USD|KRW|JPY|EUR|CNY|GBP|THB|VND)", value, re.I):
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
            evidence = checked_evidence(evidence)
            identity = json.dumps([evidence["kind"], evidence.get("review_context"), evidence["reason"], evidence["sources"]],
                                  sort_keys=True, ensure_ascii=False)
            if identity not in seen:
                result.append(evidence)
                seen.add(identity)
    return result


def personal_budget_ceiling(member, proposal):
    condition = participant_condition(member, proposal, "budget")
    if condition:
        return condition["value"]
    if "budget" in proposal.get("overrides", []):
        # Older proposals stored the authorized limit in values alone.
        return proposal.get("budget_ceiling") or proposal["values"].get("budget", {}).get("value")
    return None


def within_budget(value, ceiling):
    return value is not None and value["currency"] == ceiling["currency"] and value["amount"] <= ceiling["amount"]


def preferences_for(room, key):
    stated, protected, changed_by_agent = [], [], []
    for member in room["members"]:
        proposal = room["proposals"].get(str(member["seat"]), {})
        current = proposal.get("values", {}).get(key)
        condition = participant_condition(member, proposal, key)
        if condition:
            if condition["priority"] == "must":
                protected.append(condition["value"])
            if ((current and current["value"] == condition["value"]) or
                    condition["priority"] == "must" or key == "budget"):
                stated.append(condition)
            elif current:
                changed_by_agent.append(condition["value"])
        if current and key in proposal.get("overrides", []) and current["priority"] == "must":
            protected.append(current["value"])
    return stated, distinct(protected), changed_by_agent


def policy(room, key, value, stated, needs):
    if key in room["fixed"]:
        return room["fixed"][key], "fixed", "방을 만들 때 확정한 조건이에요."
    if key == "budget":
        caps = []
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
            return value, "agreed", "참가자가 정한 1인 예산 한도 안으로 맞췄어요."
    if len(needs) > 1:
        return None, "unresolved", "서로 다른 필수 조건을 모두 충족할 한 가지 값을 확정할 수 없어요."
    if needs:
        return needs[0], "agreed", "참여자가 꼭 지켜야 한다고 정한 조건을 우선했어요."
    # A personal agent may explicitly yield a soft preference during debate.
    important = distinct(p["value"] for p in stated if p["priority"] == "important")
    if len(important) == 1 and value != important[0]:
        return important[0], "agreed", "일반 선호보다 높은 중요도로 제출한 조건을 우선했어요."
    if value is None:
        return None, "verify", "구체적인 값을 확인할 정보가 더 필요해요."
    return value, "agreed", ""


def decide(room, raw, *, activity_judge=None):
    private = private_texts(room)
    evidence = public_sources(room["proposals"])
    missing = {e["field"] for e in evidence if e["status"] != "observed"}
    conflicts = {k for k in (raw.get("conflicts") or []) if isinstance(k, str) and k in BY_KEY and k not in room["fixed"]}
    entries = dict.fromkeys(BY_KEY)
    raw_entries = raw.get("entries") if isinstance(raw.get("entries"), dict) else {}
    # A per-day activity is evidence of a compromise only after its dates and location are checked.
    other_fields = [key for key in BY_KEY if key != "activities"]
    days, approved_days = [], {}
    for key in [*other_fields, "activities"]:
        entry = raw_entries.get(key)
        entry = entry if isinstance(entry, dict) else {}
        candidate = generated_value(key, entry.get("value"), private)
        stated, needs, changed_by_agent = preferences_for(room, key)
        val, status, reason = policy(room, key, candidate, stated, needs)
        human_values = distinct(p["value"] for p in stated)
        supported = val is not None and val in human_values and all(old == val for old in changed_by_agent)
        if key == "activities":
            requested = [room["fixed"][key]] if key in room["fixed"] else human_values
            days = checked_days(entries, raw.get("itinerary"), private, evidence, requested=requested)
            required = needs if key not in room["fixed"] else []
            plan = candidate if required else val
            review = review_activities(activity_judge, required, plan, days)
            if review is not None:
                approved_days = review.approved_days
            if required:
                val = None
                if review is not None and review.complete:
                    if review.all_in_plan and any(plan == sep.join(required) for sep in (" 후 ", " · ", ", ")):
                        val = plan
                    else:
                        val = generated_value(key, " · ".join(required), private) or f"필수 활동 {len(required)}개 포함"
                if val:
                    supported = all(activity in human_values for activity in required)
                    status, reason = "agreed", "제안과 유효한 일정에서 모든 필수 활동을 확인했어요."
                else:
                    status, reason = "unresolved", "모든 필수 활동을 함께 이행할 제안이나 일정을 확인하지 못했어요."
        if status == "unresolved" or entry.get("status") == "unresolved" and status != "fixed":
            conflicts.add(key)
        if (not room["history"] and key not in room["fixed"] and
                key not in ("budget", "accessibility", "activities", "food") and len(human_values) > 1):
            conflicts.add(key)
        verification = ""
        if key not in room["fixed"] and (key in missing or entry.get("status") == "verify"):
            verification = ("관련 검색에서 조건과 근거를 함께 확인하지 못했어요." if key in missing
                            else safe_text(entry.get("reason"), private) or "결정에 필요한 사실을 더 확인해야 해요.")
        if key in conflicts:
            if status != "unresolved":
                reason = (safe_text(entry.get("reason"), private) if entry.get("status") == "unresolved" else
                          "제안이 서로 달라 함께 수용할 조건을 정하지 못했어요.")
            status = "unresolved"
        elif verification:
            status, reason = "verify", verification
        elif status == "agreed" and not supported:
            status, reason = "suggested", "참가자가 수용한 결정으로 확인되지 않아 에이전트의 제안으로 남겼어요."
        if status == "agreed" and not reason:
            reason = "참가자가 제출하거나 수용한 조건을 반영했어요."
        entries[key] = {"value": val, "status": status,
                        "reason": reason or "함께 수용할 조건을 더 조율해야 해요."}
        if val is not None:
            entries[key]["origin"] = "host" if status == "fixed" else "participant" if supported else "agent"
        if verification and status == "unresolved":
            entries[key]["verification_reason"] = verification
    return {"round": room["round"], "entries": entries,
            "conflicts": [k for k in BY_KEY if k in conflicts],
            "evidence": evidence, "itinerary": schedule_activities(days, entries["activities"], approved_days)}


def itinerary(entries, rows, private, evidence=(), *, activity_judge=None):
    entry = entries["activities"]
    requested = [entry["value"]] if entry["status"] in ("fixed", "agreed") else []
    days = checked_days(entries, rows, private, evidence, requested=requested)
    review = review_activities(activity_judge, [], entry["value"], days)
    return schedule_activities(days, entry, review.approved_days if review else {})


def checked_days(entries, rows, private, evidence, requested=()):
    dates = entries["dates"]
    if not dates["value"] or dates["status"] not in ("fixed", "agreed") or not isinstance(rows, list):
        return []
    first, last = (date.fromisoformat(dates["value"][k]) for k in ("start", "end"))
    destination = entries["destination"]
    venues = {s["venue"] for e in evidence if e.get("destination") == destination["value"] and e["status"] == "observed"
              for s in e["sources"] if reviewed_source(e, s) and s.get("venue")}
    names = {name.casefold() for name in venues}
    requests = [text for value in requested if (text := safe_text(value, private, 160))]
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
        offered_place = place
        place_status = "base"
        if not place and row.get("base") == destination["value"]:
            place = destination["value"] or ""
        if destination["status"] not in ("agreed", "fixed"):
            place, place_status = "", "verify"
        elif destination["value"] and place != destination["value"]:
            verified = place and row.get("base") == destination["value"] and place.casefold() in names
            if verified:
                place_status = "observed"
            else:
                place, place_status = destination["value"], "verify"
        local = entries.get("local_transport", {})
        if local.get("status") in ("fixed", "agreed"):
            transport = display(local["value"])
        elif local.get("status") == "unresolved":
            transport = ""
        if destination["status"] not in ("agreed", "fixed") or row.get("base") not in (None, destination["value"]):
            activity = ""
        day = {"date": when.isoformat(), "place": place, "place_status": place_status,
               "transport": transport, "activity": activity}
        if place_status == "verify" and offered_place:
            day["candidate_place"] = offered_place
        day["_verified_venues"] = venues
        day["_requests"] = requests
        result.append(day)
    return sorted(result, key=lambda r: r["date"])


def schedule_activities(days, entry, approved_days=()):
    result = []
    for i, day in enumerate(days):
        public = {k: day[k] for k in ("date", "place", "place_status", "transport")}
        decision = approved_days.get(i) if approved_days else None
        if decision:
            public.update(decision)
        else:
            public.update(activity="", activity_status="undecided")
        result.append(public)
    return result
