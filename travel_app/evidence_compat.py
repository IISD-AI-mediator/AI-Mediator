"""Recheck old fare and branch assertions before a saved room is used or shown."""

from .models import confirmed_fare_terms, public_context, restaurant_match


def _key(evidence):
    return (evidence.get("kind"), evidence.get("checked_at"),
            tuple((s.get("url"), s.get("excerpt")) for s in evidence.get("sources", [])))


def _recheck(item, restaurant_criteria):
    kind = item.get("kind")
    if kind not in ("restaurant", "flight"):
        return False
    before = item.get("status")
    if kind == "restaurant":
        criteria = item.get("restaurant_criteria") or restaurant_criteria or {}
        item["restaurant_criteria"] = {k: criteria.get(k) for k in ("lodging", "food")}
    for source in item.get("sources", []):
        if kind == "flight":
            quote = source.get("quote")
            valid = (before == "observed" and source.get("matched", True) and isinstance(quote, dict)
                     and confirmed_fare_terms(quote.get("terms")))
            if not valid:
                source["quote"] = None
        else:
            valid = restaurant_match(source.get("excerpt"), criteria)
        # A later recheck can withdraw an old assertion. It cannot manufacture
        # a new observation from a previously unconfirmed search.
        source["matched"] = bool(source.get("matched", before == "observed") and valid)
    if before == "observed" and not any(s["matched"] for s in item.get("sources", [])):
        item.update(status="verify", reason=("출처의 금액이 세금을 포함한 1인 왕복 운임인지 다시 확인해야 해요."
                                           if kind == "flight" else "해당 지점에서 원하는 음식을 판매하는지 다시 확인해야 해요."))
        return True
    return False


def recheck_room(room):
    owners, corrected = {}, set()
    for seat, proposal in room.get("proposals", {}).items():
        preferences = room["members"][int(seat) - 1].get("profile") or {}
        criteria = public_context("restaurant", room["fixed"], preferences.get("preferences", {}) | proposal.get("values", {}),
                                  proposal.get("search_context", {}))
        criteria = {k: criteria.get(k) for k in ("lodging", "food")}
        for item in proposal.get("evidence", []):
            if item.get("kind") == "restaurant":
                key = _key(item)
                actual = item.get("restaurant_criteria") or criteria
                if key not in owners:
                    owners[key] = actual
                elif owners[key] != actual:
                    owners[key] = None
            if _recheck(item, criteria):
                corrected.add(item["field"])

    fixed_criteria = {k: room["fixed"].get(k) for k in ("lodging", "food")}
    for snapshot in (room.get("draft"), room.get("result")):
        if not snapshot:
            continue
        for item in snapshot.get("evidence", []):
            if _recheck(item, owners.get(_key(item), fixed_criteria)):
                corrected.add(item["field"])
    if corrected:
        for decision in [*room.get("history", []), room.get("draft"), room.get("result")]:
            if not decision:
                continue
            for field in corrected:
                entry = decision.get("entries", {}).get(field)
                if entry and entry.get("status") == "agreed":
                    entry.update(status="verify", reason="당시 검색 근거를 다시 확인해야 해요.")
