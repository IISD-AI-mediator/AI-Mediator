"""Durable room graph. Each node claims, computes outside the lock, then commits."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import build_agents, debate_evidence, model_evidence, search_facts, search_kinds
from .decisions import decide, distinct, generated_value, personal_budget_ceiling, private_texts, safe_text, within_budget
from .domain import BY_KEY, JUDGE_NAME
from .models import FIELD_GUIDE, ModelError
from .participant_intent import participant_condition, review_requests
from .prompts import DEBATE_PROMPT, JUDGE_PROMPT, TEAM_PROMPT
from .store import actor, event, public_turn_memory, wakeup
from .tone import proposal_message, render_speech, speech_secrets


class RunState(TypedDict, total=False):
    invite: str
    next_step: str


def speaking_options(room, topic):
    candidates = [p["values"][topic]["value"] for p in room["proposals"].values() if topic in p["values"]]
    if topic in room["fixed"]:
        candidates.insert(0, room["fixed"][topic])
    return distinct(candidates)


class Workflow:
    def __init__(self, store, member, mediator, *, fight_seconds=45, max_fights=2):
        self.store, self.member, self.mediator = store, member, mediator
        self.fight_seconds = max(20, fight_seconds)
        self.max_fights = max(1, min(max_fights, 3))
        self.panel, self.individual = build_agents(member)
        self.compiled = self.build()

    def build(self):
        # A restarted process may enter at any previously committed node.
        routes = {"team": ["propose"], "propose": ["judge"], "judge": ["open", "final"],
                  "open": ["floor"], "floor": ["speak", "judge", "floor"], "speak": ["floor"], "final": []}
        graph = StateGraph(RunState)
        graph.add_node("resume", self.resume)
        graph.add_edge(START, "resume")
        graph.add_conditional_edges("resume", lambda s: s["next_step"], [*routes, END])
        for step, following in routes.items():
            graph.add_node(step, self.bound_node(step))
            graph.add_conditional_edges(step, lambda s: s["next_step"], [*following, END])
        return graph.compile(name="travel_negotiation")

    def resume(self, state):
        room = self.store.read(state["invite"])
        due = wakeup(room)
        return {"next_step": room["step"] if due is not None and due <= time.time() else END}

    def bound_node(self, step):
        def run(state):
            snapshot = self.store.claim(state["invite"], step)
            if not snapshot:
                return {"next_step": END}
            try:
                change = getattr(self, step)(snapshot)
            except Exception as error:
                if not isinstance(error, ModelError):
                    logging.getLogger(__name__).exception("Room stage %s failed", step)
                    error = ModelError("협상 단계를 처리하지 못했어요. 잠시 후 다시 시도해 주세요.", transient=True)
                self.store.complete(snapshot, lambda room: self.fail(room, error))
                return {"next_step": END}
            following = END

            def commit(room):
                nonlocal following
                room["attempts"], room["error"] = 0, None
                change(room)
                due = wakeup(room)
                if due is not None and due <= time.time():
                    following = room["step"]
            self.store.complete(snapshot, commit)
            return {"next_step": following}
        return run

    @staticmethod
    def fail(room, error):
        if room["step"] == "team" and room["mode"] == "waiting":
            room["roles_status"], room["step"], room["error"] = "initial", "propose", None
            return
        room["attempts"] += 1
        room["error"] = str(error)
        if error.transient and room["attempts"] < 3:
            room["next_at"] = time.time() + 4 * room["attempts"]
        else:
            room["resume_mode"], room["mode"] = room["mode"], "error"
            event(room, "error", JUDGE_NAME, room["error"])

    def team(self, snapshot):
        raw = self.member.generate(
            TEAM_PROMPT,
            {"seats": snapshot["seats"], "fixed": snapshot["fixed"], "initial_roles":snapshot["roles"], "fields": FIELD_GUIDE})
        assignments = raw.get("assignments")
        assignments = assignments if isinstance(assignments, dict) else {}
        missions = raw.get("missions") if isinstance(raw.get("missions"),dict) else {}

        def apply(room):
            room["assignments"] = {}
            for seat in room["seats"]:
                focus = assignments.get(str(seat))
                role = room["roles"][str(seat)]
                focus = focus if isinstance(focus, str) and focus in BY_KEY else role["focus"]
                role.update(focus=focus, mission=safe_text(missions.get(str(seat)),limit=120) or role["mission"])
                room["assignments"][str(seat)] = focus
            room["roles_status"] = "refined"
            room["step"] = "propose"
            event(room, "phase", "생성자", f'{len(room["seats"])}명의 개인 에이전트가 여행 조건을 나누어 검토해요.')
        return apply

    def participant_turn(self, snapshot, seat, kind, topic, value, stance, *, message=None):
        memory = public_turn_memory(snapshot, seat, topic)
        previous = memory["previous_own"]
        action = stance
        if (kind == "speech" and stance == "defend" and value is not None and previous
                and previous["act"] in ("defend", "maintain") and previous["value"] == value):
            action = "maintain"
        content = message if message is not None else proposal_message(action, topic, value)
        persona = snapshot["members"][seat - 1]["profile"]["persona"]
        speech = render_speech(self.member, "participant", kind, persona, content, speech_secrets(snapshot),
                               topic=topic, value=value, action=action, public_turn_memory=memory)

        def publish(room):
            event(room, kind, actor(room, seat), speech.text, topic, voice_source=speech.source,
                  position={"seat": seat, "value": value, "act": action})
        return publish

    def propose(self, snapshot):
        packets = [{"seat": m["seat"], "profile": m["profile"], "fixed": snapshot["fixed"],
                    "assignment": snapshot["roles"][str(m["seat"])]["focus"], "role": snapshot["roles"][str(m["seat"])]} for m in snapshot["members"]]
        answer = self.panel.invoke({"packets": packets, "answers": []}, {"max_concurrency": 8})
        proposals = sorted(answer["answers"], key=lambda p: p["seat"])
        if [p["seat"] for p in proposals] != snapshot["seats"]:
            raise ModelError("일부 에이전트의 제안이 도착하지 않았어요.", transient=True)

        def first_speech(proposal):
            topic = proposal["focus"]
            value = proposal["values"].get(topic, {}).get("value", snapshot["fixed"].get(topic))
            return self.participant_turn(snapshot, proposal["seat"], "proposal", topic, value, "defend")

        with ThreadPoolExecutor(max_workers=min(8, len(proposals))) as pool:
            speeches = list(pool.map(first_speech, proposals))

        def apply(room):
            for p, publish in zip(proposals, speeches):
                room["proposals"][str(p["seat"])] = p
                publish(room)
            room["step"] = "judge"
        return apply

    def judge(self, snapshot):
        # The initial judgment and the first debate both use round number one.
        completed = snapshot["floor"]["round"] if snapshot["floor"] else 0
        remaining = max(0, self.max_fights - completed)
        proposals = []
        for member in snapshot["members"]:
            p = snapshot["proposals"].get(str(member["seat"]))
            if p:
                participant_fields = [key for key, current in p["values"].items()
                                      if participant_condition(member, p, key) == current]
                proposals.append({"seat": member["seat"], "focus": p["focus"], "values": p["values"],
                                  "participant_fields": participant_fields, "stance": p["stance"],
                                  "evidence": model_evidence(p["evidence"])})
        raw = self.mediator.generate(
            JUDGE_PROMPT,
            {"fixed": snapshot["fixed"], "fields": FIELD_GUIDE, "proposals": proposals,
             "previous": snapshot["history"], "round": snapshot["round"],
             "mode": "파이터 모드" if completed else "조율 모드", "remaining_fights": remaining})
        if not isinstance(raw.get("entries"), dict) or not (set(raw["entries"]) & BY_KEY.keys()):
            raise ModelError("판사 에이전트가 항목별 결정을 보내지 못했어요.", transient=True)
        draft = decide(snapshot, raw, activity_judge=self.mediator)
        conflict = draft["conflicts"]
        topic = conflict[0] if conflict else ""
        if conflict and remaining:
            next_step = "open"
            message = f'{BY_KEY[topic]["label"]}에 대한 제안이 갈려요. 파이터 모드에서 의견을 더 듣겠습니다.'
        else:
            next_step = "final"
            message = "전원의 제안을 검토해 최종 결정을 내렸어요."
            if conflict:
                message += f' {BY_KEY[topic]["label"]} 등 마지막 토론까지 합의하지 못한 항목은 여행안에 따로 표시해요.'
        speech = render_speech(self.mediator, "judge", "decision", snapshot["mediator"], message,
                             speech_secrets(snapshot), topic=topic, action="continue_debate" if next_step == "open" else "announce")

        def apply(room):
            room["draft"] = draft
            room["history"].append({k: draft[k] for k in ("round", "entries", "conflicts")})
            room["step"] = next_step
            event(room, "decision", JUDGE_NAME, speech.text, topic, voice_source=speech.source)
        return apply

    def open(self, snapshot):
        topic = snapshot["draft"]["conflicts"][0]
        message = f'파이터 모드가 열렸어요. {BY_KEY[topic]["label"]}에 대해 차례로 의견을 들어요.'
        speech = render_speech(self.mediator, "judge", "fight", snapshot["mediator"], message,
                             speech_secrets(snapshot), topic=topic, action="open")

        def apply(room):
            number = room["floor"]["round"] + 1 if room["floor"] else 1
            room["mode"], room["round"], room["step"] = "fight", number, "floor"
            room["floor"] = {"round": number, "deadline": time.time() + self.fight_seconds, "closed": False,
                             "cutoff": {}, "topic": topic, "queue": room["seats"].copy(), "speaker": None}
            event(room, "fight", JUDGE_NAME, speech.text, topic, voice_source=speech.source)
        return apply

    def floor(self, snapshot):
        def apply(room):
            floor = room["floor"]
            pending = [m["seat"] for m in room["members"] if len(m["notes"]) > m["handled"]]
            if floor["queue"] or pending:
                floor["speaker"] = floor["queue"].pop(0) if floor["queue"] else pending[0]
                room["step"] = "speak"
            elif floor["closed"]:
                room["mode"], room["step"] = "negotiating", "judge"
                event(room, "phase", JUDGE_NAME, "토론을 마쳤어요. 각 에이전트의 최신 제안과 앞선 판단을 다시 살펴볼게요.", floor["topic"])
            else:
                room["next_at"] = floor["deadline"]
        return apply

    def speak(self, snapshot):
        floor = snapshot["floor"]
        seat, original_topic = floor["speaker"], floor["topic"]
        member = snapshot["members"][seat - 1]
        personal = snapshot["proposals"][str(seat)]
        ceiling = personal_budget_ceiling(member, personal)
        # A speaking action changes one field. Leave later instructions for their own turns.
        note = next((n for n in member["notes"] if n["seq"] > member["handled"]), None)
        alternatives = {k: speaking_options(snapshot, k) for k in BY_KEY}
        raw = self.member.generate(
            DEBATE_PROMPT,
            {"disputed": original_topic, "fixed_fields": list(snapshot["fixed"]), "my_values": personal["values"], "my_budget_ceiling": ceiling,
             "my_new_private_instructions": [{"seq": note["seq"], "text": note["text"]}] if note else [], "fields": FIELD_GUIDE,
             "public_options": alternatives, "positions":[{"focus":p["focus"],"stance":p["stance"]} for p in snapshot["proposals"].values()],
             "public_turn_memory": public_turn_memory(snapshot, seat, original_topic)})

        def speech(topic, value=None, *, action="maintain", message=None):
            publish_turn = self.participant_turn(snapshot, seat, "speech", topic, value, action, message=message)

            def publish(room):
                publish_turn(room)
                if note:
                    room["members"][seat - 1]["handled"] = note["seq"]
                room["floor"]["speaker"], room["step"] = None, "floor"
            return publish

        topic = raw.get("focus")
        if not isinstance(topic, str) or topic not in BY_KEY:
            if note:
                raise ModelError("개인 에이전트가 지시를 반영할 여행 항목을 지정하지 못했어요.", transient=True)
            return speech(original_topic, message=f'{BY_KEY[original_topic]["label"]}에 대한 기존 제안을 유지할게요.')
        if topic in snapshot["fixed"]:
            return speech(topic, message=f'{BY_KEY[topic]["label"]} 항목은 방장이 미리 확정했어요. 기존 제안을 유지할게요.')
        options = alternatives[topic]
        stance = raw.get("stance")
        if stance not in ("defend", "yield", "alternative", "verify"):
            raise ModelError("개인 에이전트가 협상 행동을 정하지 못했어요.", transient=True)
        index = raw.get("choice")
        current = personal["values"].get(topic, {}).get("value")
        private = private_texts(snapshot)
        new_value = generated_value(topic, raw.get("new_value"), private)
        selection = options[index] if type(index) is int and 0 <= index < len(options) else current
        value = new_value if new_value is not None else selection
        offered = value
        prior = personal["values"].get(topic, {})
        requested_priority = raw.get("priority")
        valid_priority = requested_priority in ("prefer", "important", "must")
        receipt = raw.get("authorized_note_seq")
        reviewed = {}
        if note and value is not None and (receipt is None or type(receipt) is int and receipt == note["seq"]):
            previous = participant_condition(member, personal, topic)
            reviewed = review_requests(self.member, note["text"], {topic: value}, {topic: previous} if previous else {})
        requested = reviewed.get(topic)
        # Changing a protected condition also requires the action model to address
        # the current receipt; matching a receipt alone never authorizes its value.
        addressed = bool(note and type(receipt) is int and receipt == note["seq"] and valid_priority and
                         requested and requested_priority == requested["priority"])
        authorized = bool(requested and (addressed or prior.get("priority") != "must" and topic != "budget"))
        protected = prior.get("priority") == "must" and not authorized
        if protected:
            value = prior["value"]
            if stance in ("yield","alternative"):
                stance = "defend"
        if topic == "budget" and ceiling and not authorized and not within_budget(value, ceiling):
            value = current if within_budget(current, ceiling) else ceiling
            stance = "defend"
        values = personal["values"].copy()
        if value is not None and not protected:
            priority = prior.get("priority", "prefer") if current == value and stance != "yield" else "prefer"
            if authorized:
                priority = requested["priority"]
            values[topic] = {"value": value, "priority": priority}
        new_facts = search_facts(raw.get("search_context"), private)
        old_facts = personal.get("search_context", {})
        facts = old_facts | new_facts
        kinds = search_kinds(raw) if note else []
        if note and facts.get("food") and new_facts and "restaurant" not in kinds:
            kinds.append("restaurant")
        # Keep context such as a particular branch for unchanged, broad preferences.
        # An inferred term cannot override a revised value or bypass a protected condition.
        if value != current or offered != value or authorized:
            facts.pop(topic, None)
        for key in new_facts:
            protected_fact = (values.get(key, {}).get("priority") == "must" or key in personal.get("overrides", [])
                              or key == "budget" and ceiling)
            if protected_fact and new_facts[key] != old_facts.get(key):
                facts.pop(key, None)
        evidence = debate_evidence(self.member, kinds[:2], snapshot["fixed"], personal, values, facts, private)
        publish = speech(topic, value, action=stance)

        def apply(room):
            p = room["proposals"][str(seat)]
            p.update(stance=stance, focus=topic, search_context=facts, values=values, evidence=evidence)
            if value is not None and not protected:
                if authorized and topic not in p.setdefault("overrides", []):
                    p["overrides"].append(topic)
                if authorized:
                    p.setdefault("accepted", {})[topic] = {**requested, "source": "note", "seq": note["seq"]}
                if topic == "budget" and topic in p.get("overrides", []):
                    # A cheaper proposal can coexist with the owner's authorized spending limit.
                    p["budget_ceiling"] = value if authorized else ceiling
            publish(room)
        return apply

    def final(self, snapshot):
        def apply(room):
            final = room["draft"]
            for key in final["conflicts"]:
                entry = final["entries"][key]
                if key not in room["fixed"]:
                    if entry["status"] == "verify":
                        # A persisted draft from the earlier format may only have its search reason.
                        entry.setdefault("verification_reason", entry["reason"])
                        entry["reason"] = "조율 회차 안에 함께 수용할 조건을 확정하지 못했어요."
                    entry.update(status="unresolved", value=None)
                    entry.pop("origin", None)
            for key, value in room["fixed"].items():
                if final["entries"][key]["value"] != value or final["entries"][key]["status"] != "fixed":
                    final["entries"][key] = {"value": value, "status": "fixed", "reason": "방을 만들 때 확정한 조건이에요."}
            room["result"] = final
            room["mode"] = "done"
            event(room, "final", JUDGE_NAME, "최종 여행안을 공개합니다. 항목별 결정과 그 이유를 확인해 주세요.")
        return apply
