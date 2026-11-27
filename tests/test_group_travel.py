"""Four independent HTTP sessions exercise the real scheduler, graph and database."""

import json
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from travel_app import create_app
from semantic_fixtures import speech_review


ACTIVITIES = ("박물관 관람", "해변 산책")
DATES = ("2027-04-03", "2027-04-04")
SOURCE = "https://example.org/restaurant-menu"


class VoiceResponses:
    def generate_voice(self, instruction, data):
        if "candidate_speech" in data:
            return speech_review(**data)
        message = data["public_message"]
        if data["value"] is not None:
            message = message.replace(data["value"], "{value}")
        opening = {"균형 잡힌 진행자": "의견을 모아 볼게요.",
                   "다정한 진행자": "편하게 함께 얘기해요.",
                   "간결한 진행자": "요점을 짚겠습니다."}
        return {"speech": opening.get(data["persona"]["preset"], "") + message}


class MemberResponses(VoiceResponses):
    """Only the external generation and Google response boundary is substituted."""

    def generate(self, instruction, data, *, search=False):
        if "private_request" in data:
            note = data["private_request"]
            cases = (
                ("택시 필수를 대중교통 선호로", "local_transport", "대중교통", "prefer"),
                ("택시 필수 조건을 대중교통 선호로", "local_transport", "대중교통", "prefer"),
                ("택시 필수에서 대중교통 선호로", "local_transport", "대중교통", "prefer"),
                ("대중교통 필수를 택시 선호로", "local_transport", "택시", "prefer"),
                ("음식 필수를 초밥으로", "food", "초밥", "must"),
                ("예산 상한을 70만 원으로", "budget", {"amount": 700000, "currency": "KRW"},
                 data["previous_conditions"].get("budget", {}).get("priority", "prefer")),
            )
            return {"requests": [{"field": field, "value": value, "priority": priority, "explicit": True, "quote": note}
                                 for phrase, field, value, priority in cases
                                 if phrase in note and field in data["candidates"]]}
        if "segments" in data:
            meal = data["criteria"]["food"]
            assert data["kind"] == "restaurant" and data["criteria"]["lodging"] == "해운대역"
            affirmative = {f"해운대역 인근 이 식당은 {meal} 메뉴를 판매합니다.",
                           f"해운대역 인근 이 식당은 {meal}을 판매합니다."}
            return {"reviews": [{"id": s["id"], "supported": s["text"] in affirmative} for s in data["segments"]]}
        if search:
            if data.get("food") != "삼겹살" or data.get("lodging") != "해운대역":
                raise AssertionError("The search agent lost the traveller's meal or hotel.")
            return {"groundingMetadata": {
                "webSearchQueries": ["해운대역 삼겹살"],
                "groundingChunks": [{"web": {"title": "시험 식당 메뉴", "uri": SOURCE}}],
                "groundingSupports": [{"segment": {"text": "해운대역 인근 이 식당은 삼겹살을 판매합니다."},
                                       "groundingChunkIndices": [0]}],
            }}
        if "seats" in data:
            return {"assignments": {str(seat): "local_transport" for seat in data["seats"]}}
        if "organizer_focus" in data:
            return {"focus": "local_transport", "searches": []}
        if "my_new_private_instructions" in data:
            topic = "local_transport"
            notes = data["my_new_private_instructions"]
            if notes:
                return {"focus": topic, "stance": "yield", "new_value": "대중교통",
                        "priority": "prefer", "authorized_note_seq": notes[-1]["seq"]}
            current = data["my_values"].get(topic, {}).get("value")
            options = data["public_options"][topic]
            return {"focus": topic, "stance": "defend",
                    "choice": options.index(current) if current in options else None}
        if "evidence" in data:
            return {"values": {}}
        raise AssertionError("Unexpected member generation step")


class MediatorResponses(VoiceResponses):
    def generate(self, instruction, data, *, search=False):
        if "requirements" in data:
            rows = data["days"]
            assert [(r["date"], r["place"], r["activity"]) for r in rows] == [
                (date, "부산", activity) for date, activity in zip(DATES, ACTIVITIES)]
            assert [r["text"] for r in data["requirements"]] == list(ACTIVITIES)
            return {"plan_valid": False, "approved_days": [0, 1],
                    "day_venues": [{"id": 0, "names": []}, {"id": 1, "names": []}],
                    "coverage": [{"requirement_id": 0, "sources": [0]}, {"requirement_id": 1, "sources": [1]}]}
        if "proposals" not in data:
            raise AssertionError("Unexpected mediator generation step")
        return {"entries": {
            "destination": {"value": "서울", "status": "agreed"},
            "food": {"value": "삼겹살", "status": "agreed"},
            "local_transport": {"value": "대중교통", "status": "agreed"},
        }, "conflicts": [], "itinerary": [
            {"date": day, "base": "부산", "place": "부산", "activity": activity}
            for day, activity in zip(DATES, ACTIVITIES)
        ]}


class TestClock:
    def __init__(self):
        self.offset = 0

    def time(self):
        return time.time() + self.offset


class GroupTravelTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.clock = TestClock()
        for module in ("travel_app.graph.time", "travel_app.store.time"):
            self.enterContext(patch(module, self.clock))
        self.config = {"DATABASE_URL": str(Path(self.temp) / "room.sqlite"),
                       "ROOM_CREATE_CODE": "travel-team", "FIGHT_SECONDS": 45}
        self.app = create_app(self.config, member_model=MemberResponses(), mediator_model=MediatorResponses())
        runner = self.app.extensions["travel_runner"]
        self.addCleanup(runner.thread.join, 5)
        self.addCleanup(runner.close)
        self.clients = [self.app.test_client() for _ in range(4)]
        self.outsider = self.app.test_client()

    def state(self, condition):
        until = time.monotonic() + 12
        while time.monotonic() < until:
            state = self.clients[0].get(self.room).get_json()
            if state["mode"] == "error":
                self.fail(state["error"])
            if condition(state):
                return state
            time.sleep(.035)
        self.fail(f"Unexpected state after waiting: {state['mode']}, {state['ready']} ready")

    def start_room(self, *, conflict):
        host = self.clients[0]
        fixed = {"destination": "부산", "lodging": "해운대역",
                 "dates": {"start": DATES[0], "end": DATES[1]}}
        payload = {"team_code": "travel-team", "request_id": secrets.token_hex(16),
                   "name": "방장", "capacity": 4, "fixed": fixed}
        self.assertEqual(self.outsider.post("/api/rooms", json={**payload, "team_code": ""}).status_code, 403)
        created = host.post("/api/rooms", json=payload)
        self.assertEqual(created.status_code, 200)
        invite = created.get_json()["invite"]
        self.assertEqual(host.post("/api/rooms", json=payload).get_json()["invite"], invite)
        self.room = "/api/rooms/" + invite
        self.assertEqual(host.get("/").status_code, 200)
        self.assertEqual(self.outsider.get("/r/" + invite).status_code, 200)
        self.assertEqual(self.outsider.get(self.room).get_json()["fixed"], fixed)
        for index, client in enumerate(self.clients[1:], start=1):
            response = client.post(self.room + "/join", json={"request_id": secrets.token_hex(16), "name": f"팀원{index}"})
            self.assertEqual(response.status_code, 200)
        agents = {client.get(self.room).get_json()["member"]["agent"]["agent_id"] for client in self.clients}
        self.assertEqual(len(agents), 4)
        bad = host.post(self.room + "/ready", json={"preferences": {"destination": {"value": "서울", "priority": "must"}}})
        self.assertEqual(bad.status_code, 409)
        preferences = [{"activities": {"value": activity, "priority": "must"}} for activity in ACTIVITIES]
        if conflict:
            preferences[0]["local_transport"] = {"value": "택시", "priority": "must"}
            preferences[1]["local_transport"] = {"value": "대중교통", "priority": "must"}
        preferences.extend([{"food": {"value": "삼겹살", "priority": "prefer"}}, {}])
        for i in range(2):
            self.assertEqual(self.clients[i].post(self.room + "/ready", json={"preferences": preferences[i]}).status_code, 200)
        waiting = host.get(self.room).get_json()
        self.assertEqual((waiting["mode"], waiting["ready"]), ("waiting", 2))
        with ThreadPoolExecutor(max_workers=2) as pool:
            submissions = [pool.submit(self.clients[i].post, self.room + "/ready", json={"preferences": preferences[i]})
                           for i in (2, 3)]
            self.assertEqual([f.result().status_code for f in submissions], [200, 200])

    def verify_shared_result(self, expected_rounds):
        state = self.state(lambda s: s["mode"] == "done")
        result = state["result"]
        self.assertEqual(len(state["history"]), expected_rounds)
        self.assertEqual(sum(e["kind"] == "proposal" for e in state["events"]), 4)
        self.assertEqual(result["entries"]["destination"]["value"], "부산")
        self.assertEqual(result["entries"]["destination"]["status"], "fixed")
        self.assertEqual(result["entries"]["activities"]["status"], "agreed")
        self.assertEqual([(d["date"], d["activity"]) for d in result["itinerary"]], list(zip(DATES, ACTIVITIES)))
        self.assertTrue(any(e["status"] == "observed" and e["checked_at"] and any(s["url"] == SOURCE for s in e["sources"])
                            for e in result["evidence"]))
        for client in self.clients[1:]:
            self.assertEqual(client.get(self.room).get_json()["result"], result)
        restarted = create_app({**self.config, "START_WORKER": False},
                               member_model=MemberResponses(), mediator_model=MediatorResponses())
        restored = restarted.test_client()
        saved = self.clients[0].get_cookie("travel_member", path=self.room)
        restored.set_cookie("travel_member", saved.value, path=self.room)
        self.assertEqual(restored.get(self.room).get_json()["result"], result)
        return state

    def test_compatible_activities_and_restaurant_search_finish_directly(self):
        self.start_room(conflict=False)
        final = self.verify_shared_result(1)
        self.assertFalse(any(e["kind"] == "fight" for e in final["events"]))

    def test_private_fight_instruction_revises_conflicting_transport(self):
        self.start_room(conflict=True)
        opened = self.state(lambda s: s["mode"] == "fight" and s["floor"]["open"])
        self.assertIn("local_transport", opened["history"][0]["conflicts"])
        self.assertTrue(any(e["kind"] == "fight" for e in opened["events"]))
        private = {"request_id": secrets.token_hex(16), "text": "우리끼리만 쓰는 쪽지. 내 택시 필수 조건을 대중교통 선호로 바꿔 줘."}
        endpoint = self.room + "/notes"
        self.assertEqual(self.outsider.post(endpoint, json=private).status_code, 403)
        for _ in range(2):
            sent = self.clients[0].post(endpoint, json=private)
            self.assertEqual((sent.status_code, sent.get_json()), (200, {"seq": 1}))
        self.state(lambda s: s["member"]["notes"] and s["member"]["notes"][0]["handled"])
        for client in self.clients[1:]:
            other = client.get(self.room).get_json()
            self.assertEqual(other["member"]["notes"], [])
            self.assertNotIn(private["text"], json.dumps(other, ensure_ascii=False))
        self.clock.offset += 46
        final = self.verify_shared_result(2)
        self.assertEqual(final["history"][0]["entries"]["local_transport"]["status"], "unresolved")
        self.assertEqual(final["result"]["entries"]["local_transport"]["value"], "대중교통")
        self.assertEqual(final["result"]["entries"]["local_transport"]["status"], "agreed")
        self.assertTrue(any(e["kind"] == "speech" for e in final["events"]))
        late = self.clients[0].post(endpoint, json={"text": "마감 후 추가 지시", "request_id": secrets.token_hex(16)})
        self.assertEqual(late.status_code, 409)
