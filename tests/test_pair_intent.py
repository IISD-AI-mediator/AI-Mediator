"""PAIR-02 participant decisions through the room and private request boundaries."""

import copy
import json
import secrets
import unittest
from unittest.mock import Mock

from test_group_travel import MemberResponses, MediatorResponses
from test_room_recovery import RoomScenario
from travel_app.models import ModelError
from travel_app.participant_intent import review_requests


ACCESS = "무장애 객실 권장"


class AgreesWithAgent(MediatorResponses):
    def __init__(self):
        self.judgments = []

    def generate(self, instruction, data, *, search=False):
        self.judgments.append(copy.deepcopy(data))
        return {"entries": {"local_transport": {"value": "대중교통", "status": "agreed"},
                            "accessibility": {"value": ACCESS, "status": "agreed",
                                              "reason": "참가자 전원이 동의했어요."}}}


class PairIntentRoomTests(RoomScenario):
    def test_conflict_and_missing_evidence_remain_visible_to_both_seats(self):
        class LodgingJudge(AgreesWithAgent):
            def generate(self, instruction, data, *, search=False):
                return {"entries": {"lodging": {"status": "verify", "value": None,
                                                "reason": "후보 숙소의 조건을 확인해야 해요."}},
                        "conflicts": ["lodging"]}

        self.config["MAX_FIGHTS"] = 1
        self.open_room(MemberResponses(), LodgingJudge(), host_preferences={"lodging": {"value": "강남", "priority": "must"}},
                       guest_preferences={"lodging": {"value": "종로", "priority": "must"}})
        self.advance()
        self.clock.offset += 46
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        self.assertEqual(final["result"], self.guest.request(self.path)[1]["result"])
        for record in [*final["history"], final["result"]]:
            entry = record["entries"]["lodging"]
            self.assertEqual((entry["status"], entry["value"]), ("unresolved", None))
            self.assertIn("서로 다른 필수", entry["reason"])
            self.assertEqual(entry["verification_reason"], "후보 숙소의 조건을 확인해야 해요.")

    def test_budget_explicitly_given_in_extra_still_caps_the_final_result(self):
        limit = {"amount": 350000, "currency": "KRW"}
        extra = "우리끼리 첫 여행에 내가 쓸 상한은 35만 원이야."

        class Members(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "evidence" in data and data["my_profile"]["extra"] == extra:
                    return {"values": {"budget": limit}}
                if "private_request" in data:
                    return {"requests": [{"field": "budget", "value": limit, "priority": "prefer",
                                          "explicit": True, "quote": "내가 쓸 상한은 35만 원"}]}
                return super().generate(instruction, data, search=search)

        class OverBudget(MediatorResponses):
            def generate(self, instruction, data, *, search=False):
                return {"entries": {"budget": {"value": {"amount": 900000, "currency": "KRW"}, "status": "agreed"}}}

        self.open_room(Members(), OverBudget(), host_extra=extra)
        self.advance()
        final = self.guest.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        entry = final["result"]["entries"]["budget"]
        self.assertEqual((entry["value"], entry["status"]), (limit, "agreed"))

    def test_only_supported_extra_is_a_participants_position(self):
        extra = "동네를 오갈 때는 버스와 지하철로만 다니고 싶어."
        other = "박물관이 어느 동네에 있는지 알아봐 주세요."
        original = "버스와 지하철로만 다니고 싶어"

        class Members(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "evidence" in data:
                    return {"values": {"local_transport": "대중교통", "accessibility": ACCESS},
                            "required": ["accessibility"]}
                if "private_request" in data:
                    if data["private_request"] == extra:
                        return {"requests": [{"field": "local_transport", "value": "대중교통", "priority": "prefer",
                                              "explicit": True, "quote": original}]}
                    return {"requests": []}
                return super().generate(instruction, data, search=search)

        judge = AgreesWithAgent()
        self.open_room(Members(), judge, host_extra=extra, guest_extra=other,
                       guest_preferences={"local_transport": {"value": "대중교통", "priority": "prefer"}})
        self.advance()
        final = self.guest.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        self.assertEqual(final["result"], self.host.request(self.path)[1]["result"])
        self.assertEqual(final["history"][0]["entries"], final["result"]["entries"])
        entries = final["result"]["entries"]
        self.assertEqual((entries["local_transport"]["value"], entries["local_transport"]["status"]), ("대중교통", "agreed"))
        self.assertEqual((entries["accessibility"]["value"], entries["accessibility"]["status"]), (ACCESS, "suggested"))
        self.assertNotIn("전원이 동의", entries["accessibility"]["reason"])
        self.assertEqual([p["participant_fields"] for p in judge.judgments[0]["proposals"]],
                         [["local_transport"], ["local_transport"]])
        for secret in (extra, other, original):
            self.assertNotIn(secret, json.dumps([judge.judgments, final["history"], final["events"], final["result"]],
                                                ensure_ascii=False))

    def test_autonomous_yield_and_legacy_override_do_not_grant_human_provenance(self):
        old_extra = "숙소에서 점자 안내판을 이용하고 싶어요."

        class Members(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "evidence" in data and data["my_profile"]["extra"] == old_extra:
                    return {"values": {"accessibility": "점자 안내판"}}
                if "private_request" in data:
                    assert data["private_request"] == old_extra
                    return {"requests": [{"field": "accessibility", "value": "점자 안내판", "priority": "prefer",
                                          "quote": "점자 안내판을 이용하고 싶어요", "explicit": True}]}
                if "my_new_private_instructions" in data:
                    assert data["my_new_private_instructions"] == []
                    return {"focus": "accessibility", "stance": "yield", "new_value": ACCESS, "priority": "prefer"}
                return super().generate(instruction, data, search=search)

        self.config["MAX_FIGHTS"] = 1
        judge = AgreesWithAgent()
        self.open_room(Members(), judge, conflict=True, guest_extra=old_extra)
        self.advance()
        self.assertEqual(self.host.request(self.path)[1]["mode"], "fight")
        self.assertIn("accessibility", judge.judgments[0]["proposals"][1]["participant_fields"])
        store = self.app.extensions["travel_store"]
        store.update(self.invite, lambda room: room["proposals"]["1"]["overrides"].append("accessibility"))
        self.clock.offset += 46
        self.advance()
        result = self.guest.request(self.path)[1]
        self.assertEqual(result["mode"], "done")
        self.assertTrue(any(e["kind"] == "speech" and e["topic"] == "accessibility" for e in result["events"]))
        for proposal in judge.judgments[-1]["proposals"]:
            self.assertEqual(proposal["values"]["accessibility"]["value"], ACCESS)
            self.assertNotIn("accessibility", proposal["participant_fields"])
        self.assertEqual(result["result"]["entries"]["accessibility"]["status"], "suggested")

    def test_one_seats_preference_does_not_authorize_the_other_agents_concession(self):
        class AutoYield(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "my_new_private_instructions" in data and data["my_values"]["local_transport"]["value"] == "택시":
                    return {"focus": "local_transport", "stance": "yield", "new_value": "대중교통", "priority": "prefer"}
                return super().generate(instruction, data, search=search)

        self.config["MAX_FIGHTS"] = 1
        judge = AgreesWithAgent()
        self.open_room(AutoYield(), judge,
                       host_preferences={"local_transport": {"value": "택시", "priority": "prefer"}},
                       guest_preferences={"local_transport": {"value": "대중교통", "priority": "prefer"}})
        self.advance()
        self.assertEqual(self.host.request(self.path)[1]["mode"], "fight")
        self.clock.offset += 46
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        first, second = judge.judgments[-1]["proposals"]
        self.assertEqual(first["values"]["local_transport"], second["values"]["local_transport"])
        self.assertNotIn("local_transport", first["participant_fields"])
        self.assertIn("local_transport", second["participant_fields"])
        entry = final["result"]["entries"]["local_transport"]
        self.assertEqual((entry["value"], entry["status"]), ("대중교통", "suggested"))

    def test_note_review_outage_leaves_the_receipt_pending_for_retry(self):
        attempts = []

        class Interrupted(MemberResponses):
            def generate(self, instruction, data, *, search=False):
                if "private_request" in data:
                    attempts.append(data["private_request"])
                    if len(attempts) == 1:
                        raise ModelError("비공개 요청 확인 연결 오류", transient=True)
                return super().generate(instruction, data, search=search)

        self.open_room(Interrupted(), AgreesWithAgent(), conflict=True)
        self.advance()
        before = self.host.request(self.path)[1]
        note = "내 택시 필수를 대중교통 선호로 바꿔 줘."
        self.assertEqual(self.host.request(self.path + "/notes", {"request_id": secrets.token_hex(16), "text": note}),
                         (200, {"seq": 1}))
        self.clock.offset += 46
        self.advance()
        pending = self.host.request(self.path)[1]
        self.assertEqual(attempts, [note])
        self.assertEqual(pending["events"], before["events"])
        self.assertFalse(pending["member"]["notes"][0]["handled"])
        self.clock.offset += 5
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual(attempts, [note, note])
        self.assertTrue(final["member"]["notes"][0]["handled"])
        speeches = [e for e in final["events"][len(before["events"]):] if e["kind"] == "speech"]
        self.assertEqual([(e["speaker"], e["topic"]) for e in speeches], [("방장의 에이전트", "local_transport")])
        self.assertEqual(final["result"]["entries"]["local_transport"]["status"], "agreed")


class PrivateReviewTests(unittest.TestCase):
    def test_mismatched_quotes_values_and_duplicate_verdicts_cannot_describe_a_request(self):
        note = "대중교통으로 양보할게."
        candidates = {"local_transport": "대중교통"}
        item = {"field": "local_transport", "value": "대중교통", "priority": "prefer", "quote": note, "explicit": True}
        for reviews in ([{**item, "value": "택시"}], [{**item, "quote": "택시를 권해요"}],
                        [{**item, "explicit": False}], [item, item], [{**item, "field": "accessibility"}]):
            with self.subTest(reviews=reviews):
                provider = Mock()
                provider.generate.return_value = {"requests": reviews}
                self.assertEqual(review_requests(provider, note, candidates), {})

    def test_an_unrelated_quote_and_unspecified_amount_do_not_authorize_the_proposed_value(self):
        amount = {"amount": 700000, "currency": "KRW"}
        for field, value, note in (("accessibility", ACCESS, "공항에서 만나기로 해요."),
                                   ("budget", amount, "내 여행 한도를 더 올려 줘."),
                                   ("budget", amount, "상한은 70만 엔으로 바꿀게.")):
            with self.subTest(field=field, note=note):
                provider = Mock()
                provider.generate.return_value = {"requests": [{"field": field, "value": value, "priority": "prefer",
                                                                "explicit": True, "quote": note}]}
                self.assertEqual(review_requests(provider, note, {field: value}), {})
                payload = provider.generate.call_args.args[1]
                self.assertEqual(payload["candidates"], [field])
                self.assertNotIn(str(value), str(payload))
