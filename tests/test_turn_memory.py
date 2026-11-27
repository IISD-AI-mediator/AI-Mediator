"""Continuity is derived from committed public turns across HTTP reads and worker restarts."""

import json
import unittest

from travel_app import create_app
from travel_app.graph import Workflow
from travel_app.models import ModelError
from travel_app.store import actor, event, public_turn_memory
from test_group_travel import MemberResponses, MediatorResponses
from test_room_recovery import RoomScenario


class OfflineVoices(MemberResponses):
    def __init__(self):
        self.voice_requests = []
        self.debate_requests = []

    def generate_voice(self, instruction, data):
        self.voice_requests.append(data)
        raise ModelError("표현 모델 연결 오류", transient=True)

    def generate(self, instruction, data, *, search=False):
        if "disputed" in data:
            self.debate_requests.append(data)
        return super().generate(instruction, data, search=search)


class CommittedTurnTests(RoomScenario):
    def test_restart_uses_only_published_turns_and_projects_same_words_to_each_session(self):
        first = OfflineVoices()
        self.open_room(first, MediatorResponses(), conflict=True,
                       host_extra="공개할 수 없는 서윤의 개인 조건", guest_extra="공개할 수 없는 민재의 개인 조건")
        store = self.app.extensions["travel_store"]
        flow = self.app.extensions["travel_workflow"]
        stale = store.claim(self.invite, "propose")
        delayed_publication = flow.propose(stale)
        self.assertFalse(any(e["kind"] == "proposal" for e in self.host.request(self.path)[1]["events"]))
        self.clock.offset += store.lease_seconds + 1
        fresh = store.claim(self.invite, "propose")
        self.assertTrue(store.complete(fresh, flow.propose(fresh)))
        self.assertFalse(store.complete(stale, delayed_publication))
        before = self.host.request(self.path)[1]["events"]
        offers = [e for e in before if e["kind"] == "proposal"]
        self.assertEqual([e["speaker"] for e in offers], ["방장의 에이전트", "친구의 에이전트"])
        self.assertEqual(len(first.voice_requests), 4)
        self.assertTrue(all(req.get("public_turn_memory", {"recent": [], "previous_own": None}) ==
                            {"recent": [], "previous_own": None} for req in first.voice_requests))

        new = OfflineVoices()
        restarted = create_app(self.config, member_model=new, mediator_model=MediatorResponses())
        self.advance(restarted)
        after = self.host.request(self.path)[1]["events"]
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(after, self.guest.request(self.path)[1]["events"])
        self.assertTrue(all("position" not in e for e in after))
        speeches = [e for e in after if e["kind"] == "speech"]
        self.assertEqual(len(speeches), 2)
        for index, value in enumerate(("택시", "대중교통")):
            memory = new.debate_requests[index]["public_turn_memory"]
            self.assertEqual(memory, new.voice_requests[index]["public_turn_memory"])
            self.assertEqual(memory["previous_own"], {"act": "defend", "topic": "local_transport",
                                                       "value": value, "speech": offers[index]["text"]})
            self.assertIn(offers[index]["text"], [e["speech"] for e in memory["recent"]])
            self.assertNotIn("개인 조건", json.dumps(memory, ensure_ascii=False))
            self.assertEqual(speeches[index]["voice_source"], "baseline")
            self.assertNotEqual(offers[index]["text"], speeches[index]["text"])
            self.assertIn(value, speeches[index]["text"])
            self.assertIn("유지", speeches[index]["text"])
        room = store.read(self.invite)
        for seat, value in enumerate(("택시", "대중교통"), 1):
            self.assertEqual(room["proposals"][str(seat)]["stance"], "defend")
            self.assertEqual(public_turn_memory(room, seat, "local_transport")["previous_own"]["act"], "maintain")
        self.advance(restarted)
        self.assertEqual(after, self.host.request(self.path)[1]["events"])


class PositionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workflow = Workflow(None, OfflineVoices(), MediatorResponses())
        self.room = {"round": 1, "events": [], "mediator": {"instruction": ""}, "members": [
            {"name": name, "profile": {"persona": {"instruction": ""}, "extra": ""}, "notes": []}
            for name in ("서윤", "민재")]}
        self.value = {"amount": 350000, "currency": "KRW"}

    def turn(self, action, *, seat=1, topic="budget", value=None, kind="speech", room=None):
        room = self.room if room is None else room
        publish = self.workflow.participant_turn(room, seat, kind, topic, value or self.value, action)
        publish(room)
        return room["events"][-1]["position"]["act"]

    def test_same_value_depends_on_latest_own_action_topic_and_seat(self):
        self.turn("defend", kind="proposal", seat=2)
        self.turn("defend", topic="food", value="채식")
        self.assertEqual(self.turn("defend"), "defend")
        self.assertEqual(self.turn("defend"), "maintain")
        self.assertEqual(self.turn("defend"), "maintain")
        for act in ("verify", "alternative", "yield"):
            self.assertEqual(self.turn(act), act)
            self.assertEqual(self.turn("defend"), "defend")
        for value in ({"amount": 350000, "currency": "JPY"}, {"amount": 340000, "currency": "KRW"}):
            self.assertEqual(self.turn("defend", value=value), "defend")
        self.assertEqual(self.turn("defend"), "defend")
        separate_room = {**self.room, "events": []}
        self.assertEqual(self.turn("defend", room=separate_room), "defend")

    def test_legacy_unknown_latest_turn_supersedes_older_known_position(self):
        for legacy_topic in ("budget", ""):
            self.turn("defend", kind="proposal")
            event(self.room, "speech", actor(self.room, 1), "예전 방에서 전한 말", legacy_topic)
            self.assertIsNone(public_turn_memory(self.room, 1, "budget")["previous_own"])
            self.assertEqual(self.turn("defend"), "defend")

    def test_recent_context_is_bounded_while_own_latest_same_topic_turn_survives(self):
        self.turn("defend", kind="proposal")
        first = self.room["events"][-1]["text"]
        for number in range(6):
            event(self.room, "speech", actor(self.room, 2), f"다른 사람의 예산 발언 {number}", "budget")
        event(self.room, "decision", "판사 에이전트", "다른 안건의 중재", "activities")
        memory = public_turn_memory(self.room, 1, "budget")
        self.assertEqual([e["speech"] for e in memory["recent"]],
                         [f"다른 사람의 예산 발언 {i}" for i in range(3, 6)] + ["다른 안건의 중재"])
        self.assertEqual([e["topic"] for e in memory["recent"]], ["budget"] * 3 + ["activities"])
        self.assertEqual(memory["previous_own"]["speech"], first)
        self.assertEqual(self.turn("defend"), "maintain")
