"""Actual LangGraph fan-out and per-member conditional search subgraph."""

import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .decisions import generated_value
from .domain import BY_KEY, CURRENCIES
from .models import FIELD_GUIDE, SEARCH_FIELDS, grounded_search, public_context
from .participant_intent import review_requests
from .prompts import INTERPRET_PROMPT, PROPOSE_PROMPT


class PersonalState(TypedDict, total=False):
    packet: dict
    focus: str
    searches: list[str]
    context: dict
    evidence: list[dict]
    answers: list[dict]


class PanelState(TypedDict, total=False):
    packets: list[dict]
    answers: Annotated[list[dict], operator.add]


def search_facts(raw, private):
    """Only structured travel entities reach Google. Never forward the note body."""
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key in set().union(*SEARCH_FIELDS.values()):
        value = generated_value(key, raw.get(key), private)
        if value is None:
            continue
        if isinstance(value, str) and (len(value) > 70 or re.search(r"[@\n<>]|https?://|\b\d{3}[- ]\d{3,4}[- ]\d{4}\b", value)):
            continue
        result[key] = value
    if raw.get("currency") in CURRENCIES:
        result["currency"] = raw["currency"]
    return result


def search_kinds(raw):
    kinds = raw.get("searches")
    return list(dict.fromkeys(k for k in kinds if isinstance(k, str) and k in SEARCH_FIELDS))[:2] if isinstance(kinds, list) else []


def search_for(member, kinds, fixed, prefs, facts):
    return [grounded_search(member, kind, public_context(kind, fixed, prefs, facts)) for kind in kinds]


def debate_evidence(member, kinds, fixed, proposal, values, facts, private):
    old_facts = proposal.get("search_context", {})

    def current_query(kind):
        return search_facts(public_context(kind, fixed, values, facts), private)

    evidence = []
    for item in proposal["evidence"]:
        kind = item["kind"]
        if kind in kinds:
            continue
        query = current_query(kind)
        previous_query = item.get("review_context")
        if previous_query is None:
            previous_query = public_context(kind, fixed, proposal["values"], old_facts)
        if query != previous_query:
            # No new lookup for this kind. Withdraw sources and prices from the previous criteria.
            item = {**item, "status": "verify", "reason": "여행 조건이 바뀌어 새 조건에 맞는 근거를 확인해야 해요.",
                    "sources": [], "entry": "", "destination": query.get("destination", ""), "review_context": query}
            if kind == "restaurant":
                item["restaurant_criteria"] = {key: query.get(key) for key in ("lodging", "food")}
        evidence.append(item)
    evidence.extend(grounded_search(member, kind, current_query(kind)) for kind in kinds)
    return evidence


def build_agents(member):
    def interpret(state):
        packet = state["packet"]
        profile = packet["profile"]
        raw = member.generate(
            INTERPRET_PROMPT,
            {"fixed": packet["fixed"], "my_profile": {"preferences":profile["preferences"], "extra":profile["extra"]},
             "organizer_focus": packet["assignment"], "role": packet.get("role"), "fields": FIELD_GUIDE})
        focus = raw.get("focus")
        focus = focus if isinstance(focus, str) and focus in BY_KEY else packet["assignment"]
        prefs = profile["preferences"]
        facts = search_facts(raw.get("search_context"), [profile["extra"]])
        context = {k: v["value"] for k, v in prefs.items()} | facts | packet["fixed"]
        searches = []
        if context.get("transport") == "항공":
            searches.append("flight")
        if context.get("food"):
            searches.append("restaurant")
        for kind in search_kinds(raw):
            if kind not in searches:
                searches.append(kind)
        return {"focus": focus, "searches": searches[:2], "evidence": [], "context": facts}

    def search(state):
        packet = state["packet"]
        return {"evidence": search_for(member, state["searches"], packet["fixed"], packet["profile"]["preferences"], state["context"])}

    def propose(state):
        packet = state["packet"]
        profile = packet["profile"]
        raw = member.generate(
            PROPOSE_PROMPT,
            {"fields": FIELD_GUIDE, "fixed": packet["fixed"], "my_profile": {"preferences":profile["preferences"],"extra":profile["extra"]}, "focus": state["focus"],
             "evidence": model_evidence(state["evidence"])})
        raw_values = raw.get("values", {})
        values = {}
        if isinstance(raw_values, dict):
            for key, raw_value in raw_values.items():
                if key not in BY_KEY or key in packet["fixed"]:
                    continue
                value = generated_value(key, raw_value, [profile["extra"]])
                if value is not None:
                    values[key] = {"value": value, "priority": "delegate"}
        candidates = {k: p["value"] for k, p in values.items() if k not in profile["preferences"]}
        requested = review_requests(member, profile["extra"], candidates)
        values.update(requested)
        # A public agent cannot de-prioritize its person's submitted structured choices.
        values.update(profile["preferences"])
        return {"answers": [{"seat": packet["seat"], "focus": state["focus"], "values": values,
                             "stance": "defend", "evidence": state["evidence"], "search_context": state["context"],
                             "accepted": {k: {**p, "source": "extra"} for k, p in requested.items()}, "overrides": []}]}

    personal = StateGraph(PersonalState)
    personal.add_node("interpret", interpret)
    personal.add_node("search", search)
    personal.add_node("propose", propose)
    personal.add_edge(START, "interpret")
    personal.add_conditional_edges("interpret", lambda s: "search" if s["searches"] else "propose", ["search", "propose"])
    personal.add_edge("search", "propose")
    personal.add_edge("propose", END)
    individual = personal.compile(name="personal_agent")

    def fan_out(state):
        return [Send("personal_agent", {"packet": packet}) for packet in state["packets"]]

    panel = StateGraph(PanelState)
    panel.add_node("personal_agent", individual)
    panel.add_conditional_edges(START, fan_out, ["personal_agent"])
    panel.add_edge("personal_agent", END)
    return panel.compile(name="parallel_agents"), individual


def model_evidence(items):
    return [{"field": e["field"], "status": e["status"], "reason": e["reason"], "checked_at": e["checked_at"],
             "sources": [{"title": s["title"], "excerpt": s["excerpt"], "quote": s["quote"],
                          "matched": s.get("matched") is True, "venue": s.get("venue", "")}
                         for s in e["sources"]]} for e in items]
