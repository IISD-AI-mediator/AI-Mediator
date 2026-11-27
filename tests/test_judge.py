"""Judge acceptance through room endpoints, durable graph nodes and isolated cookies."""

import copy
import json
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from travel_app import create_app
from travel_app.models import ModelError
from test_group_travel import MemberResponses, MediatorResponses
from test_room_recovery import RoomScenario


def preference(value, priority="prefer"):
    return {"value": value, "priority": priority}


def money(amount, currency="KRW"):
    return {"amount": amount, "currency": currency}


def menu_response(food):
    return {"groundingMetadata": {
        "webSearchQueries": [food],
        "groundingChunks": [{"web": {"title": food, "uri": "https://example.org/menu"}}],
        "groundingSupports": [{"segment": {"text": f"해운대역 인근 이 식당은 {food} 메뉴를 판매합니다."},
                               "groundingChunkIndices": [0]}]}}


class RecordingJudge(MediatorResponses):
    def __init__(self):
        self.decisions = []

    def generate(self, instruction, data, *, search=False):
        if "tone_instruction" in data:
            return {"flavor": "plain"}
        self.decisions.append(copy.deepcopy(data))
        result = super().generate(instruction, data, search=search)
        # Exceed every test traveller's budget to exercise the final decision guard.
        result["entries"]["budget"] = {"value": money(900000), "status": "agreed"}
        # The insufficient-fare case must override an explicit agreement.
        result["entries"]["transport"] = {"value": "항공", "status": "agreed"}
        return result


class JudgeTests(RoomScenario):
    def shared_final(self):
        host = self.host.request(self.path)[1]
        self.assertEqual(host["mode"], "done")
        for client in (self.guest, self.host):
            refreshed = client.request(self.path)[1]
            for key in ("result", "events", "history"):
                self.assertEqual(refreshed[key], host[key])
        finals = [e for e in host["events"] if e["kind"] == "final"]
        self.assertEqual([e["speaker"] for e in finals], ["판사 에이전트"])
        self.assertEqual(finals[0]["id"], host["events"][-1]["id"])
        decisions = [e for e in host["events"] if e["kind"] == "decision"]
        self.assertEqual([e["speaker"] for e in decisions], ["판사 에이전트"] * len(host["history"]))
        return host

    def test_agreement_uses_each_seats_position_priority_and_evidence(self):
        class LocalMenus(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if search:
                    return menu_response(data["food"])
                return super().generate(instruction, data, search=search)

        judge = RecordingJudge()
        host = {"local_transport": preference("대중교통", "must"), "food": preference("삼겹살")}
        guest = {"local_transport": preference("대중교통"), "food": preference("초밥", "important")}
        self.open_room(LocalMenus(), judge, host_preferences=host, guest_preferences=guest,
                       fixed={"lodging": "해운대역"})
        self.advance()
        final = self.shared_final()
        self.assertEqual([e["kind"] for e in final["events"] if e["kind"] != "phase"],
                         ["proposal", "proposal", "decision", "final"])
        self.assertEqual([e["speaker"] for e in final["events"] if e["kind"] == "proposal"],
                         ["방장의 에이전트", "친구의 에이전트"])
        self.assertEqual(len(judge.decisions), 1)
        first = judge.decisions[0]
        self.assertEqual((first["mode"], first["remaining_fights"], first["previous"]), ("조율 모드", 2, []))
        self.assertEqual([p["seat"] for p in first["proposals"]], [1, 2])
        for proposal, preferences in zip(first["proposals"], [host, guest]):
            self.assertEqual(proposal["values"], preferences)
            self.assertEqual((proposal["focus"], proposal["stance"]), ("local_transport", "defend"))
            evidence, = proposal["evidence"]
            self.assertEqual((evidence["field"], evidence["status"]), ("food", "observed"))
            self.assertTrue(evidence["checked_at"])
            self.assertIn(preferences["food"]["value"], evidence["sources"][0]["excerpt"])
        self.assertEqual(final["result"]["entries"]["local_transport"]["value"], "대중교통")
        self.assertEqual(final["result"]["entries"]["food"]["value"], "초밥")

    def test_changed_dish_search_uses_current_criteria_for_judgment_and_final_evidence(self):
        self.config["MAX_FIGHTS"] = 1
        for new_source in ("초밥", "삼겹살", None):
            with self.subTest(returned_menu=new_source):
                queries = []

                class MenuMember(MemberResponses):
                    def generate(self, instruction, data, *, search=False):
                        if search:
                            queries.append(copy.deepcopy(data))
                            return menu_response("삼겹살" if len(queries) == 1 else new_source)
                        if "organizer_focus" in data and "food" in data["my_profile"]["preferences"]:
                            return {"focus": "food", "searches": ["restaurant"], "search_context": {"food": "삼겹살"}}
                        if data.get("my_new_private_instructions"):
                            return {"focus": "food", "stance": "alternative", "new_value": "초밥", "priority": "must",
                                    "authorized_note_seq": 1, "searches": ["restaurant"] if new_source else []}
                        return super().generate(instruction, data, search=search)

                judge = RecordingJudge()
                self.open_room(MenuMember(), judge, conflict=True, fixed={"lodging": "해운대역"},
                               host_preferences={"food": preference("삼겹살", "must")})
                self.advance()
                text = "음식 필수를 초밥으로 바꿔 줘." + (" 해운대역 주변 식당도 다시 확인해 줘." if new_source else "")
                self.assertEqual(self.host.request(self.path + "/notes", {"text": text, "request_id": secrets.token_hex(16)}),
                                 (200, {"seq": 1}))
                self.clock.offset += 46
                self.advance()
                final = self.shared_final()
                self.assertEqual([q["food"] for q in queries], ["삼겹살", "초밥"] if new_source else ["삼겹살"])
                self.assertTrue(all(q["lodging"] == "해운대역" for q in queries))
                first, second = judge.decisions
                initial = first["proposals"][0]["evidence"][0]
                self.assertEqual((initial["status"], initial["sources"][0]["title"]), ("observed", "삼겹살"))
                host = next(p for p in second["proposals"] if p["seat"] == 1)
                self.assertEqual(host["values"]["food"], preference("초밥", "must"))
                observed = new_source == "초밥"
                target_status = "observed" if observed else "verify"
                judge_evidence, = host["evidence"]
                public_evidence, = final["result"]["evidence"]
                for evidence in (judge_evidence, public_evidence):
                    self.assertEqual((evidence["field"], evidence["status"]), ("food", target_status))
                    self.assertEqual([s["title"] for s in evidence["sources"]], [new_source] if new_source else [])
                    if new_source:
                        self.assertIn(f"{new_source} 메뉴를 판매", evidence["sources"][0]["excerpt"])
                if new_source:
                    self.assertEqual(public_evidence["sources"][0]["matched"], observed)
                entry = final["result"]["entries"]["food"]
                self.assertEqual((entry["value"], entry["status"]), ("초밥", "agreed" if observed else "verify"))

    def test_two_accepted_notes_change_final_transport_and_budget_once_after_retry(self):
        entered, release = threading.Event(), threading.Event()
        attempted = []
        notes = [
            {"text": "비공개내역 가. 내 대중교통 필수를 택시 선호로 바꿔 줘.", "request_id": secrets.token_hex(16)},
            {"text": "비공개내역 나. 내 1인 예산 상한을 70만 원으로 올리고 삼겹살 메뉴를 다시 확인해 줘.", "request_id": secrets.token_hex(16)},
        ]

        class SpeakingMember(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if search:
                    result = super().generate(instruction, data, search=True)
                    if attempted:
                        result["groundingMetadata"]["groundingChunks"][0]["web"]["title"] = "갱신한 식당 메뉴"
                    return result
                if "my_new_private_instructions" in data:
                    if not entered.is_set():
                        entered.set()
                        if not release.wait(10):
                            raise AssertionError("Host speech never released")
                    batch = data["my_new_private_instructions"]
                    if batch:
                        attempted.append(copy.deepcopy(batch))
                        seq = batch[0]["seq"]
                        if seq == 2 and len(attempted) == 2:
                            raise ModelError("두 번째 지시 발언 생성 오류")
                        topic, value = ("local_transport", "택시") if seq == 1 else ("budget", money(700000))
                        return {"focus": topic, "stance": "yield", "priority": "prefer",
                                "new_value": value, "authorized_note_seq": seq,
                                "searches": ["restaurant"] if seq == 2 else []}
                return super().generate(instruction, data, search=search)

        judge = RecordingJudge()
        self.open_room(SpeakingMember(), judge, conflict=True,
                       guest_preferences={"budget": preference(money(500000)), "food": preference("삼겹살")},
                       fixed={"lodging": "해운대역"})
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(self.advance)
            try:
                self.assertTrue(entered.wait(5))
                for seq, note in enumerate(notes, 1):
                    self.assertEqual(self.guest.request(self.path + "/notes", note), (200, {"seq": seq}))
                pending = self.guest.request(self.path)[1]
                self.assertEqual((pending["floor"]["open"], [n["handled"] for n in pending["member"]["notes"]]),
                                 (True, [False, False]))
                self.clock.offset += 46
                self.assertEqual(self.guest.request(self.path + "/notes", notes[1]), (200, {"seq": 2}))
                late = {**notes[1], "request_id": secrets.token_hex(16)}
                self.assertEqual(self.guest.request(self.path + "/notes", late)[0], 409)
            finally:
                release.set()
            running.result(10)
        failed = self.guest.request(self.path)[1]
        self.assertEqual((failed["mode"], failed["error"], failed["floor"]["open"]), ("error", "두 번째 지시 발언 생성 오류", False))
        self.assertEqual([n["handled"] for n in failed["member"]["notes"]], [True, False])
        self.assertEqual(len(judge.decisions), 1)
        self.assertEqual(self.host.request(self.path + "/retry", {}), (200, {"ok": True}))
        self.advance()
        final = self.shared_final()
        self.assertEqual(len(judge.decisions), 2)
        initial, second = judge.decisions
        self.assertEqual((second["mode"], second["remaining_fights"], second["previous"]),
                         ("파이터 모드", 1, final["history"][:1]))
        self.assertEqual([p["seat"] for p in second["proposals"]], [1, 2])
        unchanged, updated = second["proposals"]
        self.assertEqual(unchanged["values"], initial["proposals"][0]["values"])
        self.assertEqual(updated["values"], {"local_transport": preference("택시"), "budget": preference(money(700000)),
                                             "food": preference("삼겹살")})
        self.assertEqual(initial["proposals"][1]["evidence"][0]["sources"][0]["title"], "시험 식당 메뉴")
        self.assertEqual(updated["evidence"][0]["sources"][0]["title"], "갱신한 식당 메뉴")
        self.assertEqual(final["result"]["evidence"][0]["sources"][0]["title"], "갱신한 식당 메뉴")
        self.assertEqual((updated["focus"], updated["stance"]), ("budget", "yield"))
        entries = final["result"]["entries"]
        self.assertEqual((entries["local_transport"]["status"], entries["local_transport"]["value"]), ("agreed", "택시"))
        self.assertEqual((entries["budget"]["status"], entries["budget"]["value"]), ("agreed", money(700000)))
        self.assertEqual(initial["proposals"][1]["values"]["budget"], preference(money(500000)))
        self.assertEqual(final["history"][0]["entries"]["budget"]["value"], money(500000))
        self.assertEqual(final["history"][0]["entries"]["local_transport"]["status"], "unresolved")
        self.assertEqual([[n["seq"] for n in batch] for batch in attempted], [[1], [2], [2]])
        self.assertEqual([batch[0]["text"] for batch in attempted], [notes[i]["text"] for i in (0, 1, 1)])
        speeches = [e for e in final["events"] if e["kind"] == "speech" and e["speaker"] == "친구의 에이전트"]
        self.assertEqual([e["topic"] for e in speeches], ["local_transport", "budget"])
        self.assertIn("택시", speeches[0]["text"])
        self.assertIn("700,000", speeches[1]["text"])
        self.assertEqual(final["events"][:len(failed["events"])], failed["events"])
        self.assertEqual([n["handled"] for n in self.guest.request(self.path)[1]["member"]["notes"]], [True, True])
        self.assertNotIn("비공개내역", json.dumps([judge.decisions, final], ensure_ascii=False))
        self.assertEqual(self.host.request(self.path + "/retry", {})[0], 409)

    def test_persona_independent_judgments_and_remaining_debates(self):
        runs = []
        for preset, level in [("간결한 진행자", 0), ("다정한 진행자", 10)]:
            judge = RecordingJudge()
            voice = {"preset": preset, "instruction": "비밀말투로 끝내줘", "aggression": level, "politeness": level, "mz": level}
            self.open_room(MemberResponses(), judge, conflict=True, mediator_persona=voice)
            for _ in range(2):
                self.advance()
                self.clock.offset += 46
            self.advance()
            final = self.shared_final()
            self.assertEqual([(d["mode"], d["remaining_fights"]) for d in judge.decisions],
                             [("조율 모드", 2), ("파이터 모드", 1), ("파이터 모드", 0)])
            for idx, decision in enumerate(judge.decisions):
                self.assertEqual(decision["previous"], final["history"][:idx])
                self.assertEqual([p["seat"] for p in decision["proposals"]], [1, 2])
            issue = final["result"]["entries"]["local_transport"]
            self.assertEqual((issue["status"], issue["value"]), ("unresolved", None))
            self.assertEqual(final["result"]["entries"]["destination"]["status"], "fixed")
            openings = [e for e in final["events"] if e["kind"] == "fight"]
            self.assertEqual([(e["speaker"], e["topic"]) for e in openings], [("판사 에이전트", "local_transport")] * 2)
            self.assertIn("현지 이동수단", openings[0]["text"])
            self.assertNotIn("비밀말투", json.dumps(judge.decisions, ensure_ascii=False))
            runs.append((judge.decisions, final["result"], openings[0]["text"]))
        self.assertEqual(runs[0][:2], runs[1][:2])
        self.assertNotEqual(runs[0][2], runs[1][2])

    def test_budget_authorization_scope_and_missing_evidence_at_last_judgment(self):
        self.config["MAX_FIGHTS"] = 1
        for label, host_cap, fixed_cap, authorized_seq, currency, expected in [
            ("other traveller", 600000, None, 1, "KRW", 600000),
            ("fixed by host", None, 400000, 1, "KRW", 400000),
            ("stale number", None, None, 4, "KRW", 500000),
            ("other currency without authorization", None, None, 4, "JPY", 500000),
        ]:
            with self.subTest(label=label):
                class BudgetMember(MemberResponses):
                    def generate(self, instruction, data, *, search=False):
                        if "my_new_private_instructions" in data and data["my_values"].get("transport"):
                            return {"focus": "budget", "stance": "alternative", "priority": "prefer",
                                    "new_value": money(700000, currency), "authorized_note_seq": authorized_seq}
                        return super().generate(instruction, data, search=search)

                judge = RecordingJudge()
                host = {"budget": preference(money(host_cap))} if host_cap else {}
                guest = {"transport": preference("항공")}
                if not fixed_cap:
                    guest["budget"] = preference(money(500000))
                self.open_room(BudgetMember(), judge, conflict=True, host_preferences=host, guest_preferences=guest,
                               fixed={"budget": money(fixed_cap)} if fixed_cap else {})
                self.advance()
                if not fixed_cap:
                    opened = self.guest.request(self.path)[1]
                    speeches = [e for e in opened["events"] if e["kind"] == "speech" and e["speaker"] == "친구의 에이전트"]
                    self.assertEqual(len(speeches), 1)
                    self.assertIn("500,000 KRW", speeches[0]["text"])
                sent = {"text": "내 예산 상한을 올려 줘.", "request_id": secrets.token_hex(16)}
                self.assertEqual(self.guest.request(self.path + "/notes", sent), (200, {"seq": 1}))
                self.clock.offset += 46
                self.advance()
                final = self.shared_final()
                self.assertEqual(judge.decisions[-1]["remaining_fights"], 0)
                final_guest = judge.decisions[-1]["proposals"][1]
                if not fixed_cap:
                    accepted = 700000 if authorized_seq == 1 else 500000
                    self.assertEqual(final_guest["values"]["budget"]["value"], money(accepted))
                self.assertEqual(final["result"]["entries"]["budget"]["value"], money(expected))
                self.assertEqual(final["result"]["entries"]["budget"]["status"], "fixed" if fixed_cap else "agreed")
                self.assertEqual(final["result"]["entries"]["local_transport"]["status"], "unresolved")
                self.assertEqual(final["result"]["entries"]["transport"]["status"], "verify")
                self.assertEqual(final_guest["values"]["local_transport"], preference("대중교통", "must"))
                self.assertTrue(any(e["field"] == "transport" and e["status"] == "verify" and not e["sources"]
                                    for e in final_guest["evidence"]))

    def test_malformed_then_valid_note_topic_retries_the_same_receipt(self):
        attempts = []

        class UnrecognizedTopic(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if data.get("my_new_private_instructions"):
                    attempts.append(copy.deepcopy(data["my_new_private_instructions"]))
                    topic = [None, "unexpected_field", "budget"][len(attempts) - 1]
                    return {"focus": topic, "stance": "yield", "priority": "prefer",
                            "new_value": money(700000), "authorized_note_seq": 1}
                return super().generate(instruction, data, search=search)

        self.config["MAX_FIGHTS"] = 1
        judge = RecordingJudge()
        self.open_room(UnrecognizedTopic(), judge, conflict=True,
                       guest_preferences={"budget": preference(money(500000))})
        self.advance()
        before = self.guest.request(self.path)[1]
        note = {"text": "비공개로 내 예산 상한을 70만 원으로 바꿔 줘.", "request_id": secrets.token_hex(16)}
        self.assertEqual(self.guest.request(self.path + "/notes", note), (200, {"seq": 1}))
        for elapsed in (46, 5):
            self.clock.offset += elapsed
            self.advance()
            pending = self.guest.request(self.path)[1]
            self.assertFalse(pending["member"]["notes"][0]["handled"])
            self.assertEqual(pending["events"], before["events"])
            self.assertEqual(len(judge.decisions), 1)
        self.clock.offset += 9
        self.advance()
        final = self.shared_final()
        self.assertEqual(attempts, [[{"seq": 1, "text": note["text"]}]] * 3)
        second = judge.decisions[1]["proposals"][1]
        self.assertEqual(second["values"]["budget"], preference(money(700000)))
        self.assertEqual(second["values"]["local_transport"], preference("대중교통", "must"))
        speeches = [e for e in final["events"][len(before["events"]):] if e["kind"] == "speech"]
        self.assertEqual([(e["speaker"], e["topic"]) for e in speeches], [("친구의 에이전트", "budget")])
        self.assertEqual(final["result"]["entries"]["local_transport"]["status"], "unresolved")
        self.assertTrue(self.guest.request(self.path)[1]["member"]["notes"][0]["handled"])
        self.assertNotIn(note["text"], json.dumps(final, ensure_ascii=False))

    def test_legacy_room_mixed_events_and_mediator_contract_survive_refresh(self):
        self.open_room(MemberResponses(), RecordingJudge(), guest_name="중재자", mediator_persona="간결한 진행자")
        self.advance()
        final = self.shared_final()
        source = [
            ("phase", "생성자", "생성자 발언"),
            ("phase", "중재자", "모두 준비됐어요. 각자의 에이전트가 조건을 살펴봅니다."),
            ("proposal", "중재자의 에이전트", "내가 쓴 파이트 모드 제안"),
            ("fight", "중재자", "요점부터. 파이트 모드가 열렸어요. 현지 이동수단에 대해 차례로 의견을 들어요. 내 말버릇은 파이트 모드"),
            ("speech", "중재자", "파이트 모드가 열렸어요. 현지 이동수단에 대해 차례로 의견을 들어요."),
            ("decision", "중재자", "조율을 마쳤어요. 결정한 사항과 추가 확인 사항을 정리해요."),
            ("error", "중재자", "이전 오류"),
            ("final", "중재자", "최종 여행안이 준비됐어요. 결정과 확인할 항목을 함께 살펴보세요."),
        ]
        old_events = [dict(id=i, round=1, at=1234 + i, topic="local_transport", kind=k, speaker=s, text=t)
                      for i, (k, s, t) in enumerate(source, 1)]
        store = self.app.extensions["travel_store"]

        def load_legacy(room):
            room.update(mediator="간결한 진행자", events=copy.deepcopy(old_events))
            room.pop("roles")
            room["members"][1]["profile"]["persona"] = "다정한 협상가"

        store.update(self.invite, load_legacy)
        expected = copy.deepcopy(old_events)
        for idx in (1, 3, 5, 6, 7):
            expected[idx]["speaker"] = "판사 에이전트"
        expected[3]["text"] = "요점부터. 파이터 모드가 열렸어요. 현지 이동수단에 대해 차례로 의견을 들어요. 내 말버릇은 파이트 모드"
        for client in (self.host, self.guest, self.guest):
            code, room = client.request(self.path)
            self.assertEqual((code, room["events"], room["result"], room["history"]),
                             (200, expected, final["result"], final["history"]))
            self.assertEqual(room["mediator"]["preset"], "간결한 진행자")
            self.assertEqual(room["members"][1]["name"], "중재자")
        guest = self.guest.request(self.path)[1]["member"]
        self.assertEqual((guest["profile"]["persona"]["preset"], guest["agent"]["seat"]), ("다정한 협상가", 2))
        self.assertNotIn("events", self.visitor.request(self.path)[1])
        self.assertEqual(store.read(self.invite)["events"], old_events)
        with patch.dict(os.environ, {"MEDIATOR_MODEL": "legacy-decision-model", "MEMBER_MODEL": "legacy-member-model"}):
            restarted = create_app(self.config)
            workflow = restarted.extensions["travel_workflow"]
            self.assertEqual((workflow.mediator.model, workflow.member.model), ("legacy-decision-model", "legacy-member-model"))

    def test_restart_at_old_floor_uses_saved_authorized_limit(self):
        self.config["MAX_FIGHTS"] = 1
        self.open_room(MemberResponses(), RecordingJudge(), conflict=True,
                       guest_preferences={"budget": preference(money(500000))})
        self.advance()
        opened = self.host.request(self.path)[1]
        self.assertEqual((opened["mode"], opened["floor"]["open"]), ("fight", True))
        note = {"text": "내 예산 상한을 70만 원으로 바꿔 줘.", "request_id": secrets.token_hex(16)}
        self.assertEqual(self.guest.request(self.path + "/notes", note), (200, {"seq": 1}))

        def old_speech_commit(room):
            # The old format kept an authorized limit only in values and overrides.
            room["members"][1]["handled"] = 1
            proposal = room["proposals"]["2"]
            proposal.update(focus="budget", stance="alternative", overrides=["budget"])
            proposal["values"]["budget"] = preference(money(700000))
            room["events"].append(dict(id=room["events"][-1]["id"] + 1, kind="speech", speaker="친구의 에이전트",
                                       text="1인 예산 상한을 조정해요.", topic="budget", round=1, at=self.clock.time()))

        self.app.extensions["travel_store"].update(self.invite, old_speech_commit)
        before = self.host.request(self.path)[1]
        self.clock.offset += 46
        judge = RecordingJudge()
        self.advance(create_app(self.config, member_model=MemberResponses(), mediator_model=judge))
        final = self.shared_final()
        self.assertEqual(len(judge.decisions), 1)
        decision = judge.decisions[0]
        self.assertEqual((decision["mode"], decision["previous"], decision["remaining_fights"]),
                         ("파이터 모드", before["history"], 0))
        self.assertEqual(final["events"][:len(before["events"])], before["events"])
        self.assertEqual(final["result"]["entries"]["budget"]["value"], money(700000))
