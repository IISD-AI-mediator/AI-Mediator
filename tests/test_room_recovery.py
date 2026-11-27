"""Real loopback HTTP, isolated cookies, SQLite and the production room graph."""

import json
import os
import secrets
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from werkzeug.serving import WSGIRequestHandler, make_server

from travel_app import create_app
from travel_app.models import ModelError
from test_group_travel import MemberResponses, MediatorResponses, TestClock


class QuietRequests(WSGIRequestHandler):
    def log_request(self, *args):
        pass


class BrowserSession:
    def __init__(self, base_url):
        self.base_url = base_url
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def request(self, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        request = Request(self.base_url + path, data=body, headers={"Content-Type": "application/json"})
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)


class InProcessSession:
    def __init__(self, app):
        self.client = app.test_client()

    def request(self, path, data=None):
        response = self.client.get(path) if data is None else self.client.post(path, json=data)
        return response.status_code, response.get_json()


class RoomScenario(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.clock = TestClock()
        for module in ("travel_app.store.time", "travel_app.graph.time"):
            self.enterContext(patch(module, self.clock))
        self.config = {"DATABASE_URL": str(Path(folder) / "rooms.sqlite"), "START_WORKER": False,
                       "ROOM_CREATE_CODE": "test-team", "FIGHT_SECONDS": 45, "COOKIE_SECURE": False}

    def sessions(self):
        if os.environ.get("TRAVEL_TEST_TRANSPORT", "http") == "wsgi":
            return [InProcessSession(self.app) for _ in range(3)]
        server = make_server("127.0.0.1", 0, self.app, threaded=True, request_handler=QuietRequests)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        serving.start()
        self.addCleanup(server.server_close)
        self.addCleanup(serving.join, 5)
        self.addCleanup(server.shutdown)
        base_url = f"http://127.0.0.1:{server.server_port}"
        return [BrowserSession(base_url) for _ in range(3)]

    def open_room(self, member, judge, *, conflict=False, host_persona=None, mediator_persona=None,
                  host_preferences=None, guest_preferences=None, fixed=None, guest_name="친구"):
        self.app = create_app(self.config, member_model=member, mediator_model=judge)
        self.host, self.guest, self.visitor = self.sessions()
        payload = {"name": "방장", "capacity": 2, "request_id": secrets.token_hex(16),
                   "team_code": "test-team", "fixed": {"destination": "부산", **(fixed or {})}}
        if mediator_persona:
            payload["mediator"] = mediator_persona
        code, created = self.host.request("/api/rooms", payload)
        self.assertEqual(code, 200)
        self.invite = created["invite"]
        self.path = "/api/rooms/" + self.invite
        self.advance()
        host_agent = self.host.request(self.path)[1]["member"]["agent"]
        invitation = self.visitor.request(self.path)[1]
        self.assertEqual((invitation["member"], invitation["ready"], invitation["fixed"]),
                         (None, 0, payload["fixed"]))
        join = {"name": guest_name, "request_id": secrets.token_hex(16)}
        self.assertEqual(self.guest.request(self.path + "/join", join), (200, created))
        self.assertEqual(self.guest.request(self.path + "/join", join), (200, created))
        self.assertNotEqual(self.guest.request(self.path)[1]["member"]["agent"]["agent_id"], host_agent["agent_id"])
        self.assertEqual(self.visitor.request(self.path + "/join", {**join, "request_id": secrets.token_hex(16)})[0], 409)
        self.host_profile = {"preferences": dict(host_preferences or {})}
        guest_profile = {"preferences": dict(guest_preferences or {})}
        if conflict:
            self.host_profile["preferences"]["local_transport"] = {"value": "택시", "priority": "must"}
            guest_profile["preferences"]["local_transport"] = {"value": "대중교통", "priority": "must"}
        if host_persona:
            self.host_profile["persona"] = host_persona
        self.assertEqual(self.host.request(self.path + "/ready", self.host_profile)[0], 200)
        self.assertEqual(self.host.request(self.path)[1]["mode"], "waiting")
        self.assertEqual(self.guest.request(self.path + "/ready", guest_profile)[0], 200)

    def advance(self, app=None):
        flow = (app or self.app).extensions["travel_workflow"].compiled
        return flow.invoke({"invite": self.invite}, {"recursion_limit": 240})


class RoomRecoveryTests(RoomScenario):
    def test_retry_resumes_only_failed_decision(self):
        class Judge(MediatorResponses):
            calls = 0

            def generate(self, instruction, data, *, search=False):
                self.calls += 1
                if self.calls == 1:
                    raise ModelError("결정 모델의 응답을 복구해 주세요.")
                return super().generate(instruction, data, search=search)

        judge = Judge()
        self.open_room(MemberResponses(), judge)
        self.advance()
        failed = self.host.request(self.path)[1]
        self.assertEqual((failed["mode"], failed["can_retry"]), ("error", True))
        self.assertIn("결정 모델", failed["error"])
        proposals = [e for e in failed["events"] if e["kind"] == "proposal"]
        self.assertEqual(len(proposals), 2)
        self.assertEqual(self.visitor.request(self.path + "/retry", {})[0], 403)
        self.assertEqual(self.guest.request(self.path + "/retry", {}), (200, {"ok": True}))
        self.advance()
        self.assertEqual(self.guest.request(self.path + "/retry", {})[0], 409)
        self.assertEqual(self.host.request(self.path + "/ready", self.host_profile)[0], 200)
        self.assertEqual(self.host.request(self.path + "/ready", {"preferences": {}, "extra": "다른 조건"})[0], 409)
        final = self.host.request(self.path)[1]
        self.assertEqual([e for e in final["events"] if e["kind"] == "proposal"], proposals)
        self.assertEqual((final["mode"], len(final["history"]), judge.calls), ("done", 1, 2))
        self.assertEqual(self.guest.request(self.path)[1]["result"], final["result"])
        self.assertEqual(final["result"]["entries"]["destination"]["value"], "부산")

    def test_expired_lease_resumes_once_and_discards_original_late_response(self):
        entered, release = threading.Event(), threading.Event()

        class SlowJudge(MediatorResponses):
            def generate(self, instruction, data, *, search=False):
                entered.set()
                if not release.wait(10):
                    raise AssertionError("The second worker never released the delayed model.")
                return {"entries": {"food": {"value": "옛 제안", "status": "agreed"}}}

        self.open_room(MemberResponses(), SlowJudge())
        restarted = create_app(self.config, member_model=MemberResponses(), mediator_model=MediatorResponses())
        with ThreadPoolExecutor(max_workers=1) as pool:
            old_worker = pool.submit(self.advance)
            try:
                self.assertTrue(entered.wait(5))
                self.advance(restarted)
                before_expiry = self.guest.request(self.path)[1]
                self.assertEqual((before_expiry["mode"], before_expiry["history"]), ("negotiating", []))
                self.clock.offset += self.app.extensions["travel_store"].lease_seconds + 1
                self.advance(restarted)
                before_old_reply = self.host.request(self.path)[1]
                self.assertEqual(before_old_reply["mode"], "done")
                self.assertEqual(before_old_reply["result"]["entries"]["food"]["value"], "삼겹살")
            finally:
                release.set()
            old_worker.result(5)
        after = self.guest.request(self.path)[1]
        self.assertEqual(after["result"], before_old_reply["result"])
        self.assertEqual(after["events"], before_old_reply["events"])
        self.assertEqual((len(after["history"]), sum(e["kind"] == "final" for e in after["events"])), (1, 1))

    def test_incompatible_musts_remain_unresolved_at_round_limit(self):
        self.open_room(MemberResponses(), MediatorResponses(), conflict=True)
        for turn in (1, 2):
            self.advance()
            current = self.guest.request(self.path)[1]
            self.assertEqual((current["mode"], current["round"], current["floor"]["open"]), ("fight", turn, True))
            self.clock.offset += 46
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual((final["mode"], len(final["history"])), ("done", 3))
        transport = final["result"]["entries"]["local_transport"]
        self.assertEqual((transport["value"], transport["status"]), (None, "unresolved"))
        self.assertEqual([e["round"] for e in final["events"] if e["kind"] == "fight"], [1, 2])
        self.assertEqual(self.guest.request(self.path)[1]["result"], final["result"])

    def test_accepted_note_during_speech_is_drained_after_cutoff(self):
        entered, release = threading.Event(), threading.Event()

        class SpeakingMember(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "tone_instruction" in data:
                    return {"flavor": "question", "suffix": "갈까"}
                if "my_new_private_instructions" in data and not entered.is_set():
                    entered.set()
                    if not release.wait(10):
                        raise AssertionError("The pending speaker was never released.")
                return super().generate(instruction, data, search=search)

        class SpeakingMediator(MediatorResponses):
            def generate(self, instruction, data, *, search=False):
                if "tone_instruction" in data:
                    return {"flavor": "warm", "suffix": "천천히"}
                return super().generate(instruction, data, search=search)

        self.open_room(SpeakingMember(), SpeakingMediator(), conflict=True,
                       host_persona={"aggression": 10, "politeness": 0, "mz": 10, "instruction": "갈까"},
                       mediator_persona={"aggression": 0, "politeness": 10, "mz": 0, "instruction": "천천히"})
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(self.advance)
            try:
                self.assertTrue(entered.wait(5))
                opened = self.host.request(self.path)[1]
                self.assertTrue(opened["floor"]["open"])
                prompt = {"text": "비공개 표식. 내 택시 필수를 대중교통 선호로 바꿔 줘.", "request_id": secrets.token_hex(16)}
                endpoint = self.path + "/notes"
                self.assertEqual(self.host.request(endpoint, prompt), (200, {"seq": 1}))
                pending = self.host.request(self.path)[1]["member"]["notes"]
                self.assertEqual((pending[0]["text"], pending[0]["handled"]), (prompt["text"], False))
                self.clock.offset += 46
                self.assertEqual(self.host.request(endpoint, prompt), (200, {"seq": 1}))
                self.assertEqual(self.guest.request(endpoint, {**prompt, "request_id": secrets.token_hex(16)})[0], 409)
            finally:
                release.set()
            running.result(5)
        final = self.host.request(self.path)[1]
        self.assertEqual((final["mode"], len(final["history"])), ("done", 2))
        self.assertEqual(final["member"]["notes"], [{"seq": 1, "round": 1, "text": prompt["text"], "handled": True}])
        self.assertEqual(final["result"]["entries"]["local_transport"]["value"], "대중교통")
        guest = self.guest.request(self.path)[1]
        self.assertEqual(guest["member"]["notes"], [])
        self.assertNotIn("비공개 표식", json.dumps(guest, ensure_ascii=False))
        opening = next(e["text"] for e in guest["events"] if e["kind"] == "fight")
        speeches = [e["text"] for e in guest["events"] if e["kind"] == "speech" and e["speaker"] == "방장의 에이전트"]
        self.assertIn("감사하겠습니다", opening)
        self.assertTrue(opening.endswith("천천히"))
        self.assertEqual(len(speeches), 2)
        self.assertIn("같이 가보자고", speeches[-1])
        self.assertTrue(speeches[-1].endswith("갈까"))
        self.assertIn("대중교통", speeches[-1])
