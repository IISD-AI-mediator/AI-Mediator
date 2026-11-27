"""Validate saved evidence without calling the model while a room is being read."""

from .models import reviewed_source


def checked_evidence(item):
    sources = []
    for source in item.get("sources", []):
        if item.get("status") == "observed" and reviewed_source(item, source):
            sources.append(source)
        else:
            sources.append({**source, "matched": False, "quote": None, "venue": ""})
    checked = {**item, "sources": sources}
    if item.get("status") == "observed" and not any(s["matched"] for s in sources):
        checked.update(status="verify", reason="이 검색 조건과 출처에 대해 다시 확인해야 해요.")
    return checked


def refresh_evidence(owner):
    withdrawn = set()
    for i, previous in enumerate(owner.get("evidence", [])):
        checked = checked_evidence(previous)
        owner["evidence"][i] = checked
        if previous["status"] == "observed" and checked["status"] == "verify":
            withdrawn.add(previous["field"])
    return withdrawn


def mark_unverified(entries, fields):
    for field in fields:
        entry = entries.get(field)
        if not entry:
            continue
        reason = "당시 검색 근거를 다시 확인해야 해요."
        if entry["status"] == "unresolved":
            entry.setdefault("verification_reason", reason)
        elif entry["status"] in ("agreed", "suggested"):
            entry.update(status="verify", reason=reason)


def recheck_room(room):
    withdrawn = set()
    for proposal in room.get("proposals", {}).values():
        withdrawn.update(refresh_evidence(proposal))
    for decision in (room.get("draft"), room.get("result")):
        if not decision:
            continue
        fields = refresh_evidence(decision)
        withdrawn.update(fields)
        entries = decision.get("entries", {})
        mark_unverified(entries, fields)
        destination = entries.get("destination", {}).get("value")
        venues = {s["venue"].casefold() for e in decision.get("evidence", [])
                  if e.get("destination") == destination and e.get("status") == "observed"
                  for s in e["sources"] if s.get("matched") and s.get("venue")}
        for day in decision.get("itinerary", []):
            if day.get("place_status") == "observed" and str(day.get("place", "")).casefold() not in venues:
                day.update(place=destination or "", place_status="verify")
                if day.get("activity_status") and day.get("activity"):
                    # Do not retain wording that asserted facts about the withdrawn place.
                    day.update(activity="활동 후보", activity_status="candidate",
                               activity_reason="이 장소와 여행지의 관계를 다시 확인해야 해요.")
                else:
                    day["activity"] = ""
            if day.get("activity_status") == "planned" and any(
                    venue.casefold() not in venues for venue in day.get("activity_venues", [])):
                day.update(activity="활동 후보", activity_status="candidate",
                           activity_reason="활동 장소의 출처를 다시 확인해야 해요.")
            if day.get("activity_status") == "candidate":
                day.pop("activity_venues", None)
    # Historical summaries have no source records of their own.
    for decision in room.get("history", []):
        mark_unverified(decision.get("entries", {}), withdrawn)
