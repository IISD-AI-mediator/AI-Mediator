"""Judge aggregate coverage and preserve independent, dated activity decisions."""

from dataclasses import dataclass

from .models import ModelError
from .prompts import ACTIVITY_REVIEW_PROMPT


@dataclass
class ActivityReview:
    complete: bool
    all_in_plan: bool
    approved_days: dict


def day_decisions(raw, days, approved, ids, needs):
    decisions, witnesses = {}, set()
    checks = raw.get("day_venues", [])
    if not isinstance(checks, list):
        return None
    mentions = {}
    for check in checks:
        i = check.get("id") if isinstance(check, dict) else None
        if type(i) is not int or i not in approved or i in mentions:
            return None
        venues = check.get("names")
        if not isinstance(venues, list) or any(not isinstance(v, str) or not v.strip()
                                              or v not in days[i]["activity"] for v in venues):
            return None
        mentions[i] = venues
    if set(mentions) != approved:
        return None
    for i in approved:
        day = days[i]
        text = day["activity"]
        verified = day["_verified_venues"]
        grounded = all(name in verified for name in mentions[i])
        specific = day["place_status"] == "observed"
        if day["place_status"] != "verify" and grounded:
            witnesses.add(i)
        # The city in a base row cannot vouch for other places embedded in prose.
        # Keep only the participant's own activity wording as an unverified candidate.
        label = next((request for request in day["_requests"] if request == text), "")
        if not label and day["place_status"] != "verify":
            label = next((request for request in day["_requests"] if request in text), "")
        if not label and specific and any(text in request for request in day["_requests"]):
            label = text
        if grounded and mentions[i] and day["place_status"] != "verify":
            venues = list(dict.fromkeys(mentions[i]))
            activity = label or " · ".join(venues) + " 관련 활동"
            decisions[i] = {"activity": activity, "activity_status": "planned", "activity_venues": venues}
        elif label:
            decisions[i] = candidate(label)
    candidates = raw.get("candidate_days", [])
    if not isinstance(candidates, list):
        return None
    seen = set()
    for item in candidates:
        i = item.get("day_id") if isinstance(item, dict) else None
        if type(i) is not int or i not in ids or i in approved or i in seen:
            return None
        seen.add(i)
        req_id, anchor = item.get("requirement_id"), item.get("anchor")
        if type(req_id) is not int or not 0 <= req_id < len(needs) or not isinstance(anchor, str):
            return None
        day = days[i]
        label = needs[req_id]
        if (label not in day["_requests"] or not anchor.strip() or anchor not in label
                or not any(anchor in day.get(k, "") for k in ("activity", "candidate_place"))):
            return None
        decisions[i] = candidate(label)
    return decisions, witnesses


def candidate(text):
    return {"activity": text, "activity_status": "candidate",
            "activity_reason": "이 날짜의 활동 후보예요. 구체적인 장소와 진행 여부를 확인해 주세요."}


def review_activities(adapter, needs, plan, days):
    rows = [{"id": i, **{k: v for k, v in day.items() if not k.startswith("_")}}
            for i, day in enumerate(days) if day["activity"]]
    requirements = [{"id": i, "text": text} for i, text in enumerate(needs)]
    if adapter is None or not (needs or rows) or not (plan or rows):
        return None
    try:
        raw = adapter.generate(ACTIVITY_REVIEW_PROMPT, {"requirements": requirements, "plan": plan, "days": rows})
    except ModelError:
        return None
    if not isinstance(raw, dict) or type(raw.get("plan_valid")) is not bool:
        return None
    plan_valid = raw["plan_valid"]
    if plan_valid and not plan:
        return None
    approved = raw.get("approved_days")
    ids = {row["id"] for row in rows}
    if not isinstance(approved, list) or any(type(i) is not int or i not in ids for i in approved):
        return None
    if len(approved) != len(set(approved)):
        return None
    reviewed = day_decisions(raw, days, set(approved), ids, needs)
    if reviewed is None:
        return None
    decisions, witnesses = reviewed
    coverage = raw.get("coverage")
    if not isinstance(coverage, list) or len(coverage) > len(needs):
        return None
    covered = set()
    seen = set()
    all_in_plan = plan_valid
    for item in coverage:
        i = item.get("requirement_id") if isinstance(item, dict) else None
        if type(i) is not int or not 0 <= i < len(needs) or i in seen:
            return None
        seen.add(i)
        refs = item.get("sources")
        if not isinstance(refs, list) or not refs:
            return None
        for ref in refs:
            if ref == "plan" and plan_valid:
                continue
            if type(ref) is not int or ref not in approved:
                return None
        if len(set(refs)) != len(refs):
            return None
        if "plan" in refs or all(ref in witnesses for ref in refs):
            covered.add(i)
        if len(refs) == 1 and type(refs[0]) is int:
            day_id = refs[0]
            if day_id not in decisions and needs[i] in days[day_id]["_requests"]:
                decisions[day_id] = candidate(needs[i])
        all_in_plan = all_in_plan and "plan" in refs
    # Keep separately reviewed days, but never use them to certify a rejected
    # aggregate or fill in unreviewed rows from a potentially contradicted plan.
    if plan and not plan_valid:
        return ActivityReview(False, False, decisions)
    # An exact dated request can remain a candidate even when the review cannot
    # confirm it. Never manufacture a date by distributing unmet requirements.
    for i in ids - decisions.keys():
        day = days[i]
        if day["activity"] in day["_requests"]:
            decisions[i] = candidate(day["activity"])
    complete = len(covered) == len(needs)
    return ActivityReview(complete, complete and all_in_plan, decisions)
