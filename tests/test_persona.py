"""Public persona speech through the room API, with deterministic provider responses."""

import copy
import io
import json
import secrets
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, patch

from travel_app.models import Gemini, ModelError
from travel_app.prompts import OPENING_REVIEW_PROMPT, OPENING_VOICE_PROMPT
from travel_app.tone import opening_frame_template, proposal_message, public_speech, render_speech, supported_speech, voice_template
from semantic_fixtures import speech_review
from test_group_travel import MemberResponses, MediatorResponses
from test_room_recovery import RoomScenario


RADIO = {"preset": "차분한 분석가", "aggression": 3, "politeness": 9, "mz": 2,
         "instruction": "새벽 방송을 마치는 라디오 진행자처럼\n낮은 목소리로 마지막에 질문해 줘."}
FRIEND = {"preset": "다정한 협상가", "aggression": 6, "politeness": 1, "mz": 8,
          "instruction": "같이 동네를 걸어 온 소꿉친구처럼 내게 반말로 말을 걸어 줘."}
CHAIR = {"preset": "간결한 진행자", "aggression": 7, "politeness": 8, "mz": 4,
         "instruction": "회의에 참석한 모두를 배웅하는 의장처럼 짧고 또렷하게 발표해 줘."}


def opening_review(message, speech, assessment="own_offer"):
    return {**speech_review(message, speech), "opening_assessment": assessment}


class RecordedProvider:
    def __init__(self):
        self.voices = []
        self.semantic = []
        self.tasks = []

    def generate(self, instruction, data, *, search=False):
        self.tasks.append((search, copy.deepcopy(data)))
        return super().generate(instruction, data, search=search)

    def generate_voice(self, instruction, data):
        if "candidate_speech" in data:
            self.semantic.append(copy.deepcopy(data))
            if instruction == OPENING_REVIEW_PROMPT:
                return opening_review(data["public_message"], data["candidate_speech"])
            return speech_review(**data)
        self.voices.append(copy.deepcopy(data))
        if data["persona"] == RADIO:
            if "쪽으로 양보할게요." in data["public_message"]:
                return {"speech": "그러면 {value} 쪽으로 제가 양보할게요."}
            if "유지할게요." in data["public_message"]:
                return {"core_speech": "저는 아까 말씀드린 {value} 쪽을 고수하고 싶어요."}
            return {"speech": "오늘은 {value} 타고 가 보실래요?"}
        if data["persona"] == FRIEND:
            if "유지할게요." in data["public_message"]:
                return {"speech": "난 아까처럼 {value} 타는 쪽이야!"}
            return {"speech": "야, 우리 {value} 타고 다니자!"}
        if data["persona"] == CHAIR:
            if data["event"] == "fight":
                return {"speech": "파이터 모드를 엽니다. 현지 이동수단에 관한 의견을 차례로 듣겠습니다."}
            if "파이터 모드" in data["public_message"]:
                return {"speech": "이동 방법에 이견이 있습니다. 다음 토론에서 논의하겠습니다."}
            return {"speech": "모든 위원의 제안을 검토했습니다. 이로써 결정을 알립니다."}
        raise AssertionError("Unexpected persona passed to the speech provider")


class Members(RecordedProvider, MemberResponses):
    pass


class Judge(RecordedProvider, MediatorResponses):
    pass


class PersonaRoomTests(RoomScenario):
    def test_rejected_host_overclaim_and_guest_concession_keep_distinct_public_voices(self):
        offers = []
        class RejectedProse(MemberResponses):
            def generate_voice(self, instruction, data):
                if "candidate_speech" in data:
                    return {"faithful": False}
                offers.append((data["persona"]["instruction"], data.get("repair", False)))
                if data["persona"] == RADIO:
                    return {"speech": "{value} 방식을 제안합니다. 가장 효율적인 경로임을 보장합니다.",
                            "rendering": {"register": "formal_polite", "opening": "none"}}
                return {"speech": "오, 내가 {value} 쪽으로 양보할게.",
                        "rendering": {"register": "informal", "opening": "attention"}}

        prefs = {"local_transport": {"value": "대중교통", "priority": "prefer"}}
        self.open_room(RejectedProse(), MediatorResponses(), host_persona=RADIO, guest_persona=FRIEND,
                       host_preferences=prefs, guest_preferences=prefs)
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        self.assertEqual(final["events"], self.guest.request(self.path)[1]["events"])
        proposals = [e for e in final["events"] if e["kind"] == "proposal"]
        self.assertEqual([(e["voice_source"], e["text"]) for e in proposals], [
            ("structured", "현지에서는 ‘대중교통’ 이용을 제안합니다."),
            ("structured", "오, 현지에서는 ‘대중교통’ 이용을 제안할게.")])
        self.assertCountEqual(offers, [(p["instruction"], repair) for p in (RADIO, FRIEND) for repair in (False, True)])
        self.assertEqual(final["result"]["entries"]["local_transport"]["status"], "agreed")

    def test_raw_personas_on_agreement_and_after_private_instruction(self):
        for debate in (False, True):
            with self.subTest(debate=debate):
                members, judge = Members(), Judge()
                preferences = {"food": {"value": "삼겹살", "priority": "prefer"},
                               "local_transport": {"value": "대중교통", "priority": "prefer"}}
                self.open_room(members, judge, conflict=debate, host_persona=RADIO, guest_persona=FRIEND,
                               mediator_persona=CHAIR, host_preferences=preferences, guest_preferences=preferences,
                               fixed={"lodging": "해운대역"})
                self.advance()
                note = "우리만 보는 쪽지. 택시 필수에서 대중교통 선호로 양보해 줘."
                if debate:
                    first = self.host.request(self.path)[1]
                    self.assertEqual(first["mode"], "fight")
                    receipt = self.host.request(self.path + "/notes", {"text": note, "request_id": secrets.token_hex(16)})
                    self.assertEqual(receipt, (200, {"seq": 1}))
                    def legacy_cache(room):
                        room["mediator_tone"] = {"preset": CHAIR["preset"], "flavor": "old"}
                        room["proposals"]["1"]["tone"] = {"flavor": "old"}
                    self.app.extensions["travel_store"].update(self.invite, legacy_cache)
                    self.clock.offset += 46
                    self.advance()
                final = self.host.request(self.path)[1]
                self.assertEqual(final["mode"], "done")
                self.assertEqual(final["events"], self.guest.request(self.path)[1]["events"])
                self.assertEqual(final["result"]["entries"]["local_transport"]["value"], "대중교통")
                events = final["events"]
                proposals = [e["text"] for e in events if e["kind"] == "proposal"]
                first_value = "택시" if debate else "대중교통"
                self.assertEqual(proposals, [f"오늘은 {first_value} 타고 가 보실래요?", "야, 우리 대중교통 타고 다니자!"])
                announcements = [e["text"] for e in events if e["kind"] == "decision"]
                self.assertEqual(len(announcements), 2 if debate else 1)
                self.assertEqual(announcements[-1], "모든 위원의 제안을 검토했습니다. 이로써 결정을 알립니다.")
                if debate:
                    self.assertEqual(announcements[0], "이동 방법에 이견이 있습니다. 다음 토론에서 논의하겠습니다.")
                    self.assertEqual(next(e["text"] for e in events if e["kind"] == "fight"),
                                     "파이터 모드를 엽니다. 현지 이동수단에 관한 의견을 차례로 듣겠습니다.")
                    host_speeches = [e["text"] for e in events if e["kind"] == "speech" and e["speaker"] == "방장의 에이전트"]
                    self.assertEqual(host_speeches, ["저는 아까 말씀드린 택시 쪽을 고수하고 싶어요.", "그러면 대중교통 쪽으로 제가 양보할게요."])
                    self.assertTrue(final["member"]["notes"][0]["handled"])
                self.assertCountEqual([v["persona"] for v in members.voices if v["event"] == "proposal"], [RADIO, FRIEND])
                self.assertTrue(all(v["persona"] in (RADIO, FRIEND) and v["speaker_role"] == "participant" for v in members.voices))
                self.assertTrue(all(v["persona"] == CHAIR and v["speaker_role"] == "judge" for v in judge.voices))
                for v in members.voices + judge.voices:
                    expected = {"event", "speaker_role", "persona", "topic", "value", "public_message"}
                    if v["event"] == "proposal":
                        self.assertEqual(v["action"], "defend")
                        expected.add("action")
                    if "public_turn_memory" in v:
                        self.assertEqual(v["speaker_role"], "participant")
                        expected.add("public_turn_memory")
                    self.assertEqual(set(v), expected)
                    self.assertNotIn(note, str(v))
                self.assertTrue(any(search for search, _ in members.tasks))
                for _, data in members.tasks + judge.tasks:
                    for actor in (RADIO, FRIEND, CHAIR):
                        self.assertNotIn(actor["instruction"], json.dumps(data, ensure_ascii=False).replace("\\n", "\n"))
                for data in members.semantic + judge.semantic:
                    self.assertEqual(set(data), {"candidate_speech", "public_message"})
                    self.assertNotIn(note, str(data))

    def test_fixed_and_maintained_proposals_get_their_owners_voice(self):
        class RemainingMembers(Members):
            def generate(self, instruction, data, *, search=False):
                if "my_new_private_instructions" in data:
                    if data["my_values"]["local_transport"]["value"] == "택시":
                        return {"focus": "destination"}
                    return {"focus": None}
                return super().generate(instruction, data, search=search)

            def generate_voice(self, instruction, data):
                if data.get("event") == "speech":
                    if data["persona"] == RADIO and data["topic"] == "여행지":
                        return {"speech": "이미 정한 여행지를 그대로 두고 다음 이야기로 넘어갈까요?"}
                    if data["persona"] == FRIEND and data["topic"] == "현지 이동수단":
                        return {"speech": "나는 아까 제안한 대로 갈래."}
                return super().generate_voice(instruction, data)

        self.open_room(RemainingMembers(), Judge(), conflict=True, host_persona=RADIO, guest_persona=FRIEND, mediator_persona=CHAIR)
        self.advance()
        room = self.host.request(self.path)[1]
        self.assertEqual([(e["speaker"], e["text"]) for e in room["events"] if e["kind"] == "speech"], [
            ("방장의 에이전트", "이미 정한 여행지를 그대로 두고 다음 이야기로 넘어갈까요?"),
            ("친구의 에이전트", "나는 아까 제안한 대로 갈래."),
        ])
        self.assertEqual(room["fixed"]["destination"], "부산")

    def test_bad_voice_responses_still_publish_once(self):
        class UnavailableMembers(MemberResponses):
            def generate_voice(self, instruction, data):
                raise ModelError("일시 오류", transient=True)

        class MalformedJudge(MediatorResponses):
            def generate_voice(self, instruction, data):
                return {"speech": []}

        self.open_room(UnavailableMembers(), MalformedJudge())
        self.advance()
        self.advance()
        room = self.host.request(self.path)[1]
        self.assertEqual(room["mode"], "done")
        self.assertEqual([e["kind"] for e in room["events"] if e["kind"] != "phase"],
                         ["proposal", "proposal", "decision", "final"])
        self.assertIn("최종 결정", next(e["text"] for e in room["events"] if e["kind"] == "decision"))


class OpeningProposalTests(unittest.TestCase):
    def test_malformed_live_verdict_cannot_authorize_a_model_frame(self):
        message = proposal_message("defend", "local_transport", "택시")
        frame = {"before_value": "아, ", "after_value": " 타고 다니자."}
        words = "아, 택시 타고 다니자."
        # Unconstrained Gemini response in awbnb2of despite the positive boolean and exact match.
        actions = {"source": {"kind": "own_offer", "quote": "이용을 제안해요"},
                   "candidate": {"kind": "own_offer", "quote": "타고 다니자"}}
        malformed = {
            "opening_assessment": "두 제안은 이동 수단으로 '택시' 이용을 공통으로 제안하고 있으며, 실질적인 조건의 변경이나 추가 없이 표현 방식만 구어체로 변화했으므로 내용이 동일합니다.",
            "faithful": True, "added": [], "missing": [], "actions": [actions],
            "matches": [{"candidate": words, "source": message}]}
        for verdict in (malformed, {**malformed, "opening_assessment": "own_offer"},
                        {**malformed, "opening_assessment": "own_offer", "actions": actions}):
            with self.subTest(verdict=verdict):
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"opening_frame": frame}, verdict, {"opening_frame": frame}]
                result = render_speech(provider, "participant", "proposal", FRIEND, message, [],
                                       topic="local_transport", value="택시", action="defend")
                self.assertEqual(result, (message, "baseline"))
                self.assertEqual(provider.generate.call_args_list[1].args[1], {"public_message": message, "candidate_speech": words})

    def test_model_frames_bind_the_real_value_and_verify_the_exact_words(self):
        # These optional cores guessed a different value or claimed an advantage in the second live run/controls.
        for persona, topic, value, literal, before, after, act, guessed in (
            (RADIO, "budget", {"amount": 350000, "currency": "KRW"}, "350,000 KRW",
             "한 분이 쓰실 경비는 ", " 이내로 잡았으면 합니다.", "잡았으면 합니다",
             "1인 예산을 최대 50만 원으로 설정하여 운영하는 안을 제안합니다."),
            (RADIO, "activities", "국립중앙박물관 전시 관람", "국립중앙박물관 전시 관람",
             "이번 여행의 활동으로는 ", "을 진행했으면 합니다.", "진행했으면 합니다",
             "이번 여행의 활동으로는 {value}을 제안하며, 예산과 일정을 고려했을 때 가장 효율적인 선택이 될 것으로 보입니다."),
            (FRIEND, "local_transport", "택시", "택시", "와, 난 현지에서 ", " 타고 다니고 싶어.", "다니고 싶어",
             "아, 그거 좋겠다. 현지에서는 렌터카를 이용하자."),
        ):
            with self.subTest(topic=topic):
                message = proposal_message("defend", topic, value)
                frame = {"before_value": before, "after_value": after}
                words = before + literal + after
                review = opening_review(message, words)
                review["actions"] = {"source": {"kind": "defend", "quote": "제안해요"},
                                     "candidate": {"kind": "defend", "quote": act}}
                if topic == "activities":
                    # The second museum control dropped the closing quote in the source predicate.
                    faulty = {**review, "actions": {**review["actions"], "source": {
                        "kind": "defend", "quote": literal + " 안을 제안해요"}}}
                    self.assertFalse(supported_speech(faulty, message, words, action="defend", opening=True))
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"opening_frame": frame, "core_speech": guessed}, review]
                result = render_speech(provider, "participant", "proposal", persona, message, [persona["instruction"]],
                                       topic=topic, value=value, action="defend")
                self.assertEqual(result, (words, "generated_frame"))
                self.assertEqual(provider.generate.call_args.args,
                                 (OPENING_REVIEW_PROMPT, {"public_message": message, "candidate_speech": words}))
                self.assertEqual(opening_frame_template(frame), before + "{value}" + after)

    def test_only_verbatim_frames_receive_the_frame_source(self):
        message = proposal_message("defend", "local_transport", "택시")
        for before, after, source in (("난 ", "를 타고 싶어.", "generated_frame"),
                                      ("난  ", "를 타고 싶어.", "generated_core"),
                                      ("난 ", "을(를) 타고 싶어.", "generated_core"),
                                      ("난  ", "을(를) 타고 싶어.", "generated_core")):
            with self.subTest(before=before, after=after):
                frame = {"before_value": before, "after_value": after}
                core = "나는 {value}을(를) 이용하고 싶어."
                words = before + "택시" + after if source == "generated_frame" else "나는 택시를 이용하고 싶어."
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"opening_frame": frame, "core_speech": core}, opening_review(message, words)]
                result = render_speech(provider, "participant", "proposal", FRIEND, message, [],
                                       topic="local_transport", value="택시", action="defend")
                self.assertEqual(result, (words, source))
                self.assertEqual(provider.generate.call_args.args[1], {"public_message": message, "candidate_speech": words})

    def test_reject_frame_then_review_an_independent_core_without_rechecking_duplicate_words(self):
        source = proposal_message("defend", "local_transport", "택시")
        before, after = "오, 그거 좋겠다, 현지에서는 ", " 타고 다니자."
        frame = {"before_value": before, "after_value": after}
        core = "난 {value} 타고 다니고 싶어."
        good = core.replace("{value}", "택시")
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                rejected = opening_review(source, before + "택시" + after, "assumes_prior_turn")
                first = {"opening_frame": frame, "core_speech": before + "{value}" + after if duplicate else core}
                retry = [{"opening_frame": frame, "core_speech": core}] if duplicate else []
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [first, rejected, *retry, opening_review(source, good)]
                self.assertEqual(render_speech(provider, "participant", "proposal", FRIEND, source, [],
                                               topic="local_transport", value="택시", action="defend"),
                                 (good, "generated_core"))
                checks = [data["candidate_speech"] for prompt, data in (c.args for c in provider.generate.call_args_list)
                          if prompt == OPENING_REVIEW_PROMPT]
                self.assertEqual(checks, [before + "택시" + after, good])
                if duplicate:
                    first_request, _, repair, _ = [c.args[1] for c in provider.generate.call_args_list]
                    self.assertEqual(repair, {**first_request, "repair": True, "repair_reason": "assumes_prior_turn"})

    def test_only_four_distinct_candidates_can_reach_opening_review(self):
        source = proposal_message("defend", "activities", "산책")
        calls = []
        def reply(prompt, data):
            calls.append(prompt)
            if prompt == OPENING_VOICE_PROMPT:
                before = "네 말대로 " if data.get("repair") else "네 말도 맞지만 "
                return {"opening_frame": {"before_value": before, "after_value": " 가자."},
                        "core_speech": before + "{value} 하고 싶어.", "speech": before + "{value} 하자."}
            return opening_review(source, data["candidate_speech"], "assumes_prior_turn")
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = reply
        self.assertEqual(render_speech(provider, "participant", "proposal", FRIEND, source, [], topic="activities",
                                       value="산책", action="defend"), (source, "baseline"))
        self.assertEqual(calls, [OPENING_VOICE_PROMPT, OPENING_REVIEW_PROMPT, OPENING_REVIEW_PROMPT] * 2)

    def test_frame_joins_cannot_create_an_unapproved_amount_or_private_phrase(self):
        provider = Mock(spec=["generate"])
        value = {"amount": 350000, "currency": "KRW"}
        source = proposal_message("defend", "budget", value)
        # "1" appears legitimately in the source's "1인" but changes the amount at the value boundary.
        bad = {"before_value": "예산은 1", "after_value": " 이내로 합시다."}
        good = {"before_value": "한 사람당 ", "after_value": " 이내로 잡으면 어떨까요?"}
        words = "한 사람당 350,000 KRW 이내로 잡으면 어떨까요?"
        provider.generate.side_effect = [{"opening_frame": bad}, {"opening_frame": good}, opening_review(source, words)]
        self.assertEqual(render_speech(provider, "participant", "proposal", RADIO, source, [], topic="budget",
                                       value=value, action="defend"), (words, "generated_frame"))
        first, second, _ = [c.args[1] for c in provider.generate.call_args_list]
        self.assertEqual(second, {**first, "repair": True, "repair_reason": "unsupported_claim"})
        for secret in ("몰래 약국", "약국 방문할게", "몰래 방문할게"):
            with self.subTest(secret=secret):
                source = proposal_message("defend", "activities", "약국")
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"opening_frame": {"before_value": "몰래 ", "after_value": " 방문할게."}}]
                self.assertEqual(render_speech(provider, "participant", "proposal", FRIEND, source, [secret],
                                               topic="activities", value="약국", action="defend"), (source, "baseline"))
                self.assertEqual(provider.generate.call_count, 1)
        for frame in (None, [], {"before_value": "자"}, {"before_value": "", "after_value": ["가자"]},
                      {"before_value": "{value}", "after_value": " 가자"}, {"before_value": " ", "after_value": ""}):
            self.assertIsNone(opening_frame_template(frame))

    def test_accountant_off_topic_amount_gets_one_clean_activity_rewrite(self):
        seoul = json.loads((Path(__file__).resolve().parents[1] / "scripts/two_person_seoul.json").read_text("utf-8"))
        persona = seoul["서윤"]["persona"]
        value = seoul["서윤"]["preferences"]["activities"]["value"]
        message = proposal_message("defend", "activities", value)
        # Replay 8bsuhklj, call 8: an opening for a museum visit invented a separate spending limit.
        original = "이번 여행에서 즐길 활동으로 {value}을 제안하며, 해당 항목에 대해 인당 예산을 10만 원 이내로 정하고 진행하는 것은 어떨까요?"
        clean = "저는 이번 활동으로 {value} 일정을 제안드립니다."
        words = clean.replace("{value}", value)
        style = {"register": "formal_polite", "opening": "none"}
        fallback = proposal_message("defend", "activities", value).replace("제안해요.", "제안합니다.")
        self.assertNotIn("예산", OPENING_VOICE_PROMPT)
        for corrected in (True, False):
            with self.subTest(corrected=corrected):
                provider = Mock(spec=["generate"])
                replies = [{"core_speech": original, "rendering": style},
                           {"core_speech": clean if corrected else "{value} 쪽에 5만 원을 배정하면 어떨까요?"}]
                if corrected:
                    replies.append(opening_review(message, words))
                provider.generate.side_effect = replies
                result = render_speech(provider, "participant", "proposal", persona, message,
                                       [persona["instruction"], seoul["guest_note"]], topic="activities",
                                       value=value, action="defend")
                self.assertEqual(result, (words, "generated_core") if corrected else (fallback, "structured"))
                first, repair, *reviews = [c.args for c in provider.generate.call_args_list]
                self.assertEqual(first, (OPENING_VOICE_PROMPT, {
                    "speaker_role": "participant", "event": "proposal", "persona": persona,
                    "public_message": message.replace(value, "{value}"), "topic": "하고 싶은 활동",
                    "value": "{value}", "action": "defend"}))
                self.assertEqual(repair, (OPENING_VOICE_PROMPT, {**first[1], "repair": True,
                                                                "repair_reason": "unsupported_claim"}))
                self.assertEqual(reviews, [(OPENING_REVIEW_PROMPT, {"public_message": message, "candidate_speech": words})]
                                 if corrected else [])

    def test_new_number_and_private_overlap_in_the_same_opening_do_not_trigger_rewrite(self):
        message = proposal_message("defend", "food", "초밥")
        note = "처방을 받은 약 때문에 피하는 음식이 있어"
        for overlap in (note, "처방을 받은 약 때문에 피하는 음식"):
            with self.subTest(overlap=overlap):
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"core_speech": overlap + ", {value} 쪽으로 7만 원 쓰자."}]
                result = render_speech(provider, "participant", "proposal", FRIEND, message, [note],
                                       topic="food", value="초밥", action="defend")
                self.assertEqual(result, (message, "baseline"))
                self.assertEqual(provider.generate.call_count, 1)
                self.assertNotIn(note, json.dumps(provider.generate.call_args.args[1], ensure_ascii=False))

    def test_failed_seoul_candidates_get_a_new_offer_using_only_safe_feedback(self):
        seoul = json.loads((Path(__file__).resolve().parents[1] / "scripts/two_person_seoul.json").read_text("utf-8"))
        amount = {"amount": 350000, "currency": "KRW"}
        budget = "한 분이 쓰실 여행 경비는 {value} 이내로 잡으면 어떨까요?"
        taxi = "자, 난 현지에선 {value} 타고 다니고 싶어."
        # The first four candidates are the original cores from replay 2yxh6ndi, calls 9, 14, 10, 13.
        cases = [
            ("서윤", "budget", amount, "350,000 KRW", budget,
             "전체적인 효율성을 고려해서 1인당 예산을 {value} 이내로 설정하는 안을 제안합니다.", "unsupported_claim"),
            ("서윤", "budget", amount, "350,000 KRW", budget,
             "1인 예산은 {value} 이내로 설정하는 것이 가장 효율적일 것 같습니다.", "unsupported_claim"),
            ("민재", "local_transport", "택시", "택시", taxi,
             "오, 그거 괜찮네! 현지에서는 {value} 이용을 제안할게.", "assumes_prior_turn"),
            ("민재", "local_transport", "택시", "택시", taxi,
             "오, 그건 좀 아닌 거 같아. 현지에서는 {value} 이용을 제안해.", "assumes_prior_turn"),
            ("민재", "local_transport", "택시", "택시", taxi,
             "네 말도 일리가 있지만 난 현지에서 {value} 타고 싶어.", "assumes_prior_turn"),
        ]
        for name, topic, value, literal, revised, candidate, reason in cases:
            with self.subTest(candidate=candidate):
                message = proposal_message("defend", topic, value)
                persona = seoul[name]["persona"]
                note = seoul["guest_note"]
                prior = {"recent": [{"speech": "다른 사람의 예전 말"}], "previous_own": None}

                def provider_reply(prompt, data):
                    if prompt == OPENING_VOICE_PROMPT:
                        if data.get("repair_reason") == reason:
                            return {"core_speech": revised}
                        return {"core_speech": candidate}
                    self.assertEqual(prompt, OPENING_REVIEW_PROMPT)
                    words = data["candidate_speech"]
                    if words == revised.replace("{value}", literal):
                        return opening_review(message, words)
                    self.assertEqual(words, candidate.replace("{value}", literal))
                    # As in the original taxi verdict, all of the broad alignment fields
                    # can approve the whole candidate, including an imagined reply.
                    verdict = opening_review(message, words, reason)
                    if reason == "unsupported_claim":
                        verdict.update(faithful=False, added=[words])
                    return verdict

                provider = Mock(spec=["generate"])
                provider.generate.side_effect = provider_reply
                result = render_speech(provider, "participant", "proposal", persona, message,
                                       [persona["instruction"], note], topic=topic, value=value, action="defend",
                                       public_turn_memory=prior)
                words = revised.replace("{value}", literal)
                self.assertEqual(result, (words, "generated_core"))
                first, check, repair, last_check = [c.args[1] for c in provider.generate.call_args_list]
                self.assertEqual(first["persona"], persona)
                self.assertEqual(first["action"], "defend")
                if topic == "budget":
                    self.assertEqual(first["value_meaning"], "한 사람당 쓸 수 있는 최대 금액")
                else:
                    self.assertNotIn("value_meaning", first)
                self.assertEqual((first["public_message"], first["value"]), (message.replace(literal, "{value}"), "{value}"))
                self.assertNotIn(literal, json.dumps(first, ensure_ascii=False))
                self.assertNotIn("public_turn_memory", first)
                self.assertEqual(repair, {**first, "repair": True, "repair_reason": reason})
                self.assertNotIn(note, json.dumps(repair, ensure_ascii=False))
                self.assertEqual(check, {"public_message": message, "candidate_speech": candidate.replace("{value}", literal)})
                self.assertEqual(last_check, {"public_message": message, "candidate_speech": words})

    def test_opening_requires_own_offer_assessment_and_every_existing_alignment_check(self):
        message = proposal_message("defend", "lodging", "역 앞")
        candidate = "거긴 별로라니 저는 역 앞에 묵고 싶습니다."
        broad = speech_review(message, candidate)
        self.assertTrue(supported_speech(broad, message, candidate, action="defend"))
        verdicts = [broad, {**broad, "opening_assessment": "assumes_prior_turn"},
                    {**broad, "opening_assessment": "검토자의 자유 문구"},
                    {**broad, "opening_assessment": "own_offer", "matches": []},
                    {**broad, "opening_assessment": "own_offer", "added": ["거긴 별로라니"]}]
        for verdict in verdicts:
            with self.subTest(verdict=verdict):
                self.assertFalse(supported_speech(verdict, message, candidate, action="defend", opening=True))
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = [{"speech": candidate}, verdicts[2], {"speech": candidate}]
        self.assertEqual(render_speech(provider, "participant", "proposal", RADIO, message, [], topic="lodging",
                                      value="역 앞", action="defend"), (message, "baseline"))
        first, _, repair = [c.args[1] for c in provider.generate.call_args_list]
        self.assertEqual(repair, {**first, "repair": True, "repair_reason": "single_offer"})


class SpeechGuardTests(unittest.TestCase):
    def test_live_wholesale_positive_verdict_does_not_publish_the_extra_taxi_claim(self):
        source = proposal_message("defend", "local_transport", "택시")
        bad = "아, 딴 건 몰라도 현지에서는 택시 이용하자. 이게 제일 편하잖아."
        # The actual provider matched both sentences to one offer, including in its action quote.
        wrong = {"faithful": True, "added": [], "missing": [],
                 "actions": {"source": {"kind": "defend", "quote": "현지에서는 ‘택시’ 이용을 제안해요."},
                             "candidate": {"kind": "defend", "quote": bad}},
                 "matches": [{"candidate": bad, "source": "현지에서는 ‘택시’ 이용을 제안해요."}]}
        self.assertFalse(supported_speech(wrong, source, bad, action="defend", value="택시"))
        self.assertFalse(supported_speech({**wrong, "opening_assessment": "own_offer"}, source, bad,
                                          action="defend", value="택시", opening=True))
        repaired = "아, 현지에선 택시 타고 다니자!"
        for key in ("core_speech", "speech"):
            for repeats in (True, False):
                with self.subTest(key=key, repeats=repeats):
                    provider = Mock(spec=["generate"])
                    repair = [{key: bad}] if repeats else [{"core_speech": repaired}, opening_review(source, repaired)]
                    provider.generate.side_effect = [{key: bad}, wrong, *repair]
                    result = render_speech(provider, "participant", "proposal", FRIEND, source, [],
                                           topic="local_transport", value="택시", action="defend")
                    self.assertEqual(result, (source, "baseline") if repeats else (repaired, "generated_core"))
                    self.assertEqual(provider.generate.call_count, 3 if repeats else 4)

    def test_a_reaction_can_open_the_act_and_punctuation_inside_the_value_stays_intact(self):
        value = "St. Louis 전시 관람"
        source = proposal_message("defend", "activities", value)
        candidate = "오! St. Louis 전시 관람 같이 할래?"
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = [{"speech": candidate}, opening_review(source, candidate)]
        self.assertEqual(render_speech(provider, "participant", "proposal", FRIEND, source, [],
                                       topic="activities", value=value, action="defend"), (candidate, "generated"))
        for bad in ("그게 제일 편해! " + candidate.split("! ", 1)[1], candidate + " 맛도 좋아!",
                    candidate.replace("오!", "모두가 동의해…"), candidate + "무조건 괜찮아!"):
            with self.subTest(bad=bad):
                self.assertFalse(supported_speech(speech_review(source, bad), source, bad, action="defend", value=value))
        self.assertIsNone(voice_template("{value} 같이 갈래\n모두가 동의해", value, "proposal", "활동", one_line=True))

    def test_live_activity_particle_is_resolved_before_the_actual_words_are_reviewed(self):
        value = "국립중앙박물관 전시 관람"
        message = proposal_message("defend", "activities", value)
        candidate = "하고 싶은 활동으로는 {value}을(를) 제안합니다."
        expected = "하고 싶은 활동으로는 국립중앙박물관 전시 관람을 제안합니다."
        for extra in ("", " 참가자 모두에게 가장 좋은 선택입니다."):
            with self.subTest(extra=extra):
                verdict = opening_review(message, expected + extra)
                if extra:
                    verdict["added"] = [extra.strip()]
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"core_speech": candidate + extra}, verdict] * 2
                result = render_speech(provider, "participant", "proposal", RADIO, message, [],
                                       topic="activities", value=value, action="defend")
                self.assertEqual(result, (message, "baseline") if extra else (expected, "generated_core"))
                checks = [c.args[1] for c in provider.generate.call_args_list if c.args[0] == OPENING_REVIEW_PROMPT]
                self.assertEqual(checks, [{"public_message": message, "candidate_speech": expected + extra}])

    def test_only_an_explicit_unquoted_particle_on_a_hangul_value_can_be_inflected(self):
        for value, pair, suffix in (("택시", "을(를)", "를"), ("버스", "는(은)", "는"), ("부산", "는(은)", "은"),
                                    ("여행", "이/가", "이"), ("숙소", "가(이)", "가"), ("박물관", "와(과)", "과"),
                                    ("바다", "과/와", "와"), ("서울", "(으)로", "로"), ("강릉", "로(으로)", "으로"),
                                    ("제주", "으로(로)", "로"), ("‘을(를)’ 연습하기", "을(를)", "를")):
            with self.subTest(value=value, pair=pair):
                self.assertEqual(voice_template(f"{value}{pair} 갈까요?", value, "speech", "후보"),
                                 "{value}" + suffix + " 갈까요?")
        for candidate in ("‘{value}을(를)’ 그대로 말해요.", "「{value}을(를)」이라고 해요.", "‘{value}’을(를) 원해요.",
                          "{value}이랑(랑) 가요.", "{value}(을)를 봐요.", "{value}을 / 를 원해요.",
                          "{value}을(를) 저는(은) 원해요.", "저는(은) {value} 좋아요."):
            self.assertIsNone(voice_template(candidate, "택시", "speech", "후보"))

    def test_unknown_final_pronunciation_requires_complete_rewording_and_review(self):
        for value, topic, display_value in (({"amount": 350000, "currency": "KRW"}, "budget", "350,000 KRW"),
                                            ("City A", "destination", "City A")):
            message = proposal_message("maintain", topic, value)
            repaired = "저는 앞서 말씀드린 {value} 안을 유지하고 싶습니다."
            expected = repaired.replace("{value}", display_value)
            for still_bad in (True, False):
                with self.subTest(value=value, still_bad=still_bad):
                    bad = {"core_speech": "저는 {value}을(를) 유지합니다."}
                    provider = Mock(spec=["generate"])
                    provider.generate.side_effect = [bad, bad] if still_bad else [
                        bad, {"core_speech": repaired}, speech_review(message, expected)]
                    result = render_speech(provider, "participant", "speech", RADIO, message, [],
                                           topic=topic, value=value, action="maintain")
                    self.assertEqual(result, (message, "baseline") if still_bad else (expected, "generated_core"))
                    self.assertNotIn("(를)", result.text)
                    checks = [c.args[1] for c in provider.generate.call_args_list if "candidate_speech" in c.args[1]]
                    self.assertEqual(checks, [] if still_bad else [{"public_message": message, "candidate_speech": expected}])

    def test_spaced_particle_markers_are_rejected_on_first_generation_and_repair(self):
        value = "국립중앙박물관 전시 관람"
        message = proposal_message("defend", "activities", value)
        for template in ("{value} 을 / 를", "{value} 을 (를)", "‘{value}’ 을 / 를", "「{value}」 을 ( 를 )",
                         "{value} ( 으 ) 로", "{value} 을 （ 를 ）", "{value} 을 ／ 를"):
            with self.subTest(template=template):
                candidate = template + " 제안합니다."
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"core_speech": candidate}, {"speech": candidate}]
                result = render_speech(provider, "participant", "proposal", RADIO, message, [],
                                       topic="activities", value=value, action="defend")
                self.assertEqual(result, (message, "baseline"))
                first, repair = [c.args[1] for c in provider.generate.call_args_list]
                self.assertEqual(repair, {**first, "repair": True, "repair_reason": "value_and_form"})

    def test_complete_core_is_checked_on_its_own_before_the_optional_explanation(self):
        value = {"amount": 350000, "currency": "KRW"}
        first = "1인당 350,000 KRW 이내로 잡으면 어떨까요?"
        memory = {"recent": [{"speaker": "서윤의 에이전트", "topic": "budget", "speech": first}],
                  "previous_own": {"topic": "budget", "value": value, "act": "defend", "speech": first}}
        source = proposal_message("maintain", "budget", value)
        core = "앞서 말씀드린 대로, 저는 1인당 {value} 이내를 고수하고 싶습니다."
        full = core + " 모든 경비를 이 안에서 해결할 수 있습니다."
        core_public = core.replace("{value}", "350,000 KRW")
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = [{"speech": full, "core_speech": core}, speech_review(source, core_public)]
        utterance = render_speech(provider, "participant", "speech", RADIO, source, [RADIO["instruction"]],
                                  topic="budget", value=value, action="maintain", public_turn_memory=memory)
        self.assertEqual(utterance, (core_public, "generated_core"))
        generation, core_check = [c.args[1] for c in provider.generate.call_args_list]
        self.assertEqual(generation["public_turn_memory"], memory)
        self.assertEqual(core_check, {"candidate_speech": core_public, "public_message": source})

    def test_second_review_goes_to_the_rewritten_budget_core_when_both_long_versions_overclaim(self):
        value = {"amount": 350000, "currency": "KRW"}
        source = proposal_message("maintain", "budget", value)
        original = source.replace("350,000 KRW", "{value}")
        repaired = "1인 예산은 말씀드린 대로 {value} 이내로 유지하겠습니다."
        repaired_public = repaired.replace("{value}", "350,000 KRW")
        # Both generations and their extra claims are from the live budget replay.
        extra = "정해진 범위 내에서 효율적인 일정을 구성하는 것이 무엇보다 중요하다고 판단됩니다."
        longer_repair = repaired + " 전체적인 여행 비용의 효율을 생각했을 때 이 정도 규모가 가장 적정하다고 판단됩니다."
        for copied, persona in ((True, RADIO), (False, RADIO), (True, {**RADIO, "instruction": ""})):
            with self.subTest(copied=copied, instruction=persona["instruction"]):
                initial = original if copied else "제가 {value} 한도를 유지할 수도 있습니다."
                initial_long = initial + " " + extra
                checked = initial_long if copied else initial
                rejected = {**speech_review(source, checked.replace("{value}", "350,000 KRW")), "faithful": False}
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [
                    {"core_speech": initial, "speech": initial_long}, rejected,
                    {"core_speech": repaired, "speech": longer_repair}, speech_review(source, repaired_public)]
                utterance = render_speech(provider, "participant", "speech", persona, source, [],
                                          topic="budget", value=value, action="maintain")
                self.assertEqual(utterance, (repaired_public, "generated_core"))
                generation, first_check, repair, last_check = [c.args[1] for c in provider.generate.call_args_list]
                self.assertEqual(repair, {**generation, "repair": True})
                self.assertEqual([first_check, last_check], [{"public_message": source, "candidate_speech": text}
                                                            for text in (checked.replace("{value}", "350,000 KRW"),
                                                                         repaired_public)])

    def test_a_full_candidate_can_still_be_reviewed_if_repair_supplies_no_core(self):
        source = proposal_message("yield", "local_transport", "대중교통")
        full = "오, 그럼 내가 대중교통 쪽으로 양보할게."
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = [{"core_speech": "제가 {value} 이용을 제안해요.", "speech": full},
                                         {"faithful": False}, {}, speech_review(source, full)]
        result = render_speech(provider, "participant", "speech", FRIEND, source, [],
                               topic="local_transport", value="대중교통", action="yield")
        self.assertEqual(result, (full, "generated"))
        self.assertEqual(provider.generate.call_args.args[1], {"public_message": source, "candidate_speech": full})

    def test_core_cannot_repeat_old_offer_leak_private_text_introduce_a_price_or_change_act(self):
        value = "대중교통"
        message = proposal_message("maintain", "local_transport", value)
        first = "현지에서는 대중교통 타고 다니면 어때요?"
        private = "이건 우리 둘만 아는 비밀 쿠폰"
        memory = {"recent": [], "previous_own": {"act": "defend", "topic": "local_transport", "speech": first, "value": value}}
        for candidate, needs_review in [(first, False), (private + ". 대중교통 그대로 갈게.", False),
                                        ("대중교통 한 번에 9달러면 돼.", False),
                                        ("역시 대중교통 쪽이긴 해. 그렇다고 그걸 고수하겠다는 뜻은 아니야.", True),
                                        ("대중교통 쪽에 양보할게.", True)]:
            with self.subTest(candidate=candidate):
                checks = []
                def reply(prompt, data):
                    if "candidate_speech" in data:
                        checks.append(data["candidate_speech"])
                        review = speech_review(message, candidate)
                        if "양보" in candidate:
                            # A flawed reviewer agrees with itself that both are yields;
                            # the canonical act at this call site is actually maintain.
                            for part in review["actions"].values():
                                part["kind"] = "yield"
                        else:
                            review.update(faithful=False, missing=["유지할게요."])
                        return review
                    return {"core_speech": candidate}
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = reply
                utterance = render_speech(provider, "participant", "speech", FRIEND, message, [private],
                                          topic="local_transport", value=value, action="maintain", public_turn_memory=memory)
                self.assertEqual(utterance, (message, "baseline"))
                self.assertEqual(checks, [candidate, candidate] if needs_review else [])

    def test_a_rejected_compound_sentence_is_never_cut_even_with_plausible_positive_prefix(self):
        message = proposal_message("yield", "local_transport", "대중교통")
        full = "제가 대중교통 쪽으로 양보할게요. 숙소가 확정된다면 말이에요."
        reject = {**speech_review(message, full), "faithful": False, "added": ["숙소가 확정된다면 말이에요."]}
        provider = Mock(spec=["generate"])
        provider.generate.side_effect = [{"speech": full}, reject] * 2
        utterance = render_speech(provider, "participant", "speech", RADIO, message, [],
                                  topic="local_transport", value="대중교통", action="yield")
        self.assertEqual(utterance, (message, "baseline"))
        self.assertEqual([c.args[1]["candidate_speech"] for c in provider.generate.call_args_list
                          if "candidate_speech" in c.args[1]], [full, full])

    def test_offline_and_structured_budget_fallback_distinguish_first_offer_from_maintaining_the_ceiling(self):
        value = {"amount": 350000, "currency": "KRW"}
        for expected_source in ("baseline", "structured"):
            words = []
            for action, ending in (("defend", "제안"), ("maintain", "유지")):
                provider = Mock(spec=["generate"])
                if expected_source == "baseline":
                    provider.generate.side_effect = ModelError("발언 생성 지연")
                else:
                    provider.generate.return_value = {"rendering": {"register": "formal_polite", "opening": "none"}}
                message = proposal_message(action, "budget", value)
                utterance = render_speech(provider, "participant", "speech", RADIO, message, [],
                                          topic="budget", value=value, action=action)
                self.assertEqual(utterance.source, expected_source)
                self.assertIn("350,000 KRW’ 이내", utterance.text)
                self.assertIn(ending, utterance.text)
                words.append(utterance.text)
            self.assertNotEqual(*words)

    def test_recovery_is_limited_to_valid_style_choices_and_full_canonical_stance(self):
        value = "대중교통"
        reg = {"register": "informal", "opening": "thought"}
        for action, predicate in (("defend", "제안할게."), ("yield", "양보할게."),
                                  ("alternative", "검토해 줘."), ("verify", "확인하고 싶어.")):
            provider = Mock(spec=["generate"])
            provider.generate.side_effect = [{"speech": "{value}로 확정해!", "rendering": reg}, ModelError("검토 응답 없음")]
            message = proposal_message(action, "local_transport", value)
            utterance = render_speech(provider, "participant", "speech", FRIEND, message, [],
                                      topic="local_transport", value=value, action=action)
            self.assertEqual(utterance.source, "structured")
            self.assertEqual((utterance.text.count(value), utterance.text.startswith("음, "), utterance.text.endswith(predicate)),
                             (1, True, True))
        for invalid in ({}, {"register": "비공개", "opening": "none"}, {**reg, "opening": "비공개"},
                        {**reg, "text": "직접 쓴 약속"}):
            provider = Mock(spec=["generate"])
            provider.generate.return_value = {"speech": "", "rendering": invalid}
            utterance = render_speech(provider, "participant", "speech", FRIEND, message, [],
                                      topic="local_transport", value=value, action="verify")
            self.assertEqual(utterance, (message, "baseline"))
        qualified = message + " 날짜가 정해진 뒤에 확인할게요."
        provider = Mock(spec=["generate"])
        provider.generate.return_value = {"speech": "", "rendering": reg}
        self.assertEqual(render_speech(provider, "participant", "speech", FRIEND, qualified, [],
                                      topic="local_transport", value=value, action="verify"), (qualified, "baseline"))

    def render(self, responses, instruction="", private=()):
        adapter = Mock(spec=["generate"])
        adapter.generate.side_effect = responses
        actual = public_speech(adapter, "participant", "speech", {**RADIO, "instruction": instruction},
                               "예산은 700,000 KRW로 제안합니다.", [instruction, *private],
                               topic="budget", value={"amount": 700000, "currency": "KRW"})
        return actual, [call.args[1] for call in adapter.generate.call_args_list]

    def test_literal_value_is_normalized_before_private_and_semantic_checks(self):
        message = "현지 이동수단은 ‘대중교통’으로 양보할게요."
        candidate = "그래, 대중교통으로 양보할게!"
        checked = {"faithful": True, "added": [], "missing": [], "matches": [
            {"candidate": candidate, "source": message}],
            "actions": {"source": {"kind": "yield", "quote": "양보할게요"},
                        "candidate": {"kind": "yield", "quote": "양보할게"}}}
        adapter = Mock(spec=["generate"])
        adapter.generate.side_effect = [{"speech": candidate}, checked]
        actual = public_speech(adapter, "participant", "speech", FRIEND, message, [FRIEND["instruction"]],
                               topic="local_transport", value="대중교통")
        self.assertEqual(actual, candidate)
        self.assertEqual(adapter.generate.call_count, 2)
        self.assertEqual(adapter.generate.call_args.args[1], {"candidate_speech": candidate, "public_message": message})

    def test_value_only_witness_and_changed_act_cannot_authorize_a_concession(self):
        message = "현지 이동수단에 대해서는 ‘대중교통’ 쪽으로 양보할게요."
        candidate = "대중교통을 제안해!"
        review = speech_review(message, candidate)
        changed = {"source": {"kind": "yield", "quote": "양보할게요"},
                   "candidate": {"kind": "defend", "quote": "제안해"}}
        for verdict in (
            {**review, "matches": [{"candidate": candidate, "source": "대중교통"}]},
            {**review, "actions": {**changed, "source": {"kind": "defend", "quote": "양보할게요"}}},
            {**review, "actions": {**changed, "source": {"kind": "yield", "quote": "‘대중교통’"},
                                   "candidate": {"kind": "yield", "quote": "제안해"}}},
            {**review, "actions": changed},
        ):
            with self.subTest(verdict=verdict):
                provider = Mock(spec=["generate"])
                provider.generate.side_effect = [{"speech": candidate}, verdict] * 2
                actual = public_speech(provider, "participant", "speech", FRIEND, message, [FRIEND["instruction"]],
                                       topic="local_transport", value="대중교통", action="yield")
                self.assertEqual(actual, message)
                self.assertEqual(provider.generate.call_count, 4)

    def test_resolved_value_cannot_be_repeated_even_if_a_semantic_review_approves(self):
        message = "현지 이동수단 제안은 ‘대중교통’예요."
        bad = "현지 이동수단은 대중교통이 제일 효율적이야. 대중교통 타자."
        verdict = speech_review(message, bad)
        self.assertFalse(supported_speech(verdict, message, bad))
        self.assertFalse(supported_speech(verdict, message, bad, action="defend", value="대중교통"))
        good = "오, 현지 이동은 대중교통으로 가자!"
        self.assertTrue(supported_speech(speech_review(message, good), message, good))

        unbound = "‘토론’을 시작해요."
        paraphrase = "논의를 시작할게요."
        self.assertTrue(supported_speech(speech_review(unbound, paraphrase), unbound, paraphrase, value=None))

    def test_first_speech_and_repair_receive_only_the_symbolic_value(self):
        value = "국립중앙박물관 전시 관람"
        message = f"하고 싶은 활동 제안은 ‘{value}’예요."
        masked = "하고 싶은 활동 제안은 ‘{value}’예요."
        persona_voice = "저는 ‘{value}’ 안을 제안드립니다."
        rendered = persona_voice.replace("{value}", value)
        adapter = Mock(spec=["generate"])
        adapter.generate.side_effect = [{"speech": masked}, {"speech": persona_voice}, opening_review(message, rendered)]
        actual = public_speech(adapter, "participant", "proposal", RADIO, message, [RADIO["instruction"]],
                               topic="activities", value=value, action="defend")
        self.assertEqual(actual, rendered)
        first, repair, check = [c.args[1] for c in adapter.generate.call_args_list]
        self.assertEqual(first["value"], "{value}")
        self.assertEqual(first["public_message"], masked)
        self.assertNotIn(value, str(first))
        self.assertEqual(repair, {**first, "repair": True, "repair_reason": "own_words"})
        self.assertEqual(check, {"public_message": message, "candidate_speech": rendered})

    def test_repair_is_bounded_and_uses_only_the_original_inputs(self):
        message = "예산은 700,000 KRW로 제안합니다."
        bad = "예산은 700,000 KRW를 제안해. 먼저 비용을 검토해 줄게."
        good = "어때, 예산은 700,000 KRW로 하자!"
        review = speech_review(message, bad)
        review["added"] = ["먼저 비용을 검토해 줄게."]
        actual, calls = self.render([{"speech": bad}, review, {"speech": good}, speech_review(message, good)])
        self.assertEqual(actual, good)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[2], {**calls[0], "repair": True})
        self.assertNotIn(bad, str(calls[2]))

    def test_inconsistent_and_unanchored_reviews_cannot_authorize_new_claims(self):
        message = "예산은 700,000 KRW로 제안합니다."
        first = "예산은 700,000 KRW로 하자!"
        extra = " 이 방식이 가장 효율적이야."
        candidate = first + extra
        positive = speech_review(message, candidate)
        for verdict in ({"faithful": True},
                        {**positive, "added": [extra]}, {**positive, "missing": ["제안합니다."]},
                        {**positive, "matches": [{"candidate": first, "source": message}]},
                        {**positive, "matches": [{"candidate": candidate, "source": "이 방식이 가장 효율적입니다."}]},
                        {**positive, "matches": []}):
            with self.subTest(verdict=verdict):
                actual, calls = self.render([{"speech": candidate}, verdict, {"speech": candidate}, verdict])
                self.assertEqual((actual, len(calls)), (message, 4))

    def test_duplicated_values_new_numerals_and_private_notes_fail_closed(self):
        message = "예산은 700,000 KRW로 제안합니다."
        private = "우리끼리만 약속한 비밀 정산 사유야"
        for candidate, retries in (
            ("{value}, 700,000 KRW로 가자.", 1), ("700,000 KRW, 700,000 KRW로 가자.", 1),
            ("700,000 KRW면 9번도 갈 수 있어.", 0), (f"700,000 KRW로 하자. {private}", 0),
        ):
            with self.subTest(candidate=candidate):
                actual, calls = self.render([{"speech": candidate}] * (1 + retries), private=[private])
                self.assertEqual((actual, len(calls)), (message, 1 + retries))

    def test_value_and_meaning_checks_precede_publication(self):
        fallback = "예산은 700,000 KRW로 제안합니다."
        speech = "여행 경비는 {value} 정도로 어때냥?"
        rendered = speech.replace("{value}", "700,000 KRW")
        actual, calls = self.render([{"speech": speech}, speech_review(fallback, rendered)], "냥")
        self.assertEqual(actual, speech.replace("{value}", "700,000 KRW"))
        self.assertEqual(calls[1], {"candidate_speech": actual, "public_message": fallback})
        for responses, expected_calls in (
            ([{"speech": "경비는 7만 원이면 돼요."}, {"speech": "아직 값을 모르겠어."}], 2),
            ([{"speech": "{value}도 좋고, 5만 원도 좋아요."}], 1),
            ([{"speech": ""}, {"speech": ""}], 2),
            ([{"speech": "원래는 {value}지만 그 두 배로 합의했습니다."}, {"faithful": False}, {}], 3),
            ([{"speech": speech}, {"faithful": "true"}, {}], 3),
            ([{"speech": speech}, ModelError("검증 연결 오류")], 2),
        ):
            with self.subTest(responses=responses):
                actual, calls = self.render(responses)
                self.assertEqual((actual, len(calls)), (fallback, expected_calls))

    def test_public_quote_permission_distinguishes_private_examples_and_other_notes(self):
        phrase = "오늘도 여러분과 함께하는 별빛 여행입니다"
        speech = phrase + "! 이번 제안은 {value}입니다."
        allow = f"발언은 ‘{phrase}’로 시작해 줘."
        deny = f"‘{phrase}’는 개인적인 문구라서 절대로 말하지 마."
        fallback = "예산은 700,000 KRW로 제안합니다."
        review = speech_review(fallback, speech.replace("{value}", "700,000 KRW"))
        actual, calls = self.render([{"speech": speech}, {"publish_quotes": True}, review], allow)
        self.assertEqual(actual, speech.replace("{value}", "700,000 KRW"))
        self.assertEqual(calls[1], {"persona_instruction": allow, "requested_quotes": [phrase]})
        self.assertEqual(set(calls[2]), {"candidate_speech", "public_message"})
        for responses, instruction, private, expected_calls in (
            ([{"speech": speech}, {"publish_quotes": False}], deny, [], 2),
            ([{"speech": speech}, {}], allow, [], 2),
            ([{"speech": speech}], allow, [phrase], 1),
            ([{"speech": allow + " 제안은 {value}."}], allow, [], 1),
        ):
            with self.subTest(instruction=instruction, private=private, responses=responses):
                actual, calls = self.render(responses, instruction, private)
                self.assertEqual((actual, len(calls)), (fallback, expected_calls))

    def test_truncated_provider_response_falls_back_to_the_approved_message(self):
        with patch("travel_app.models.urlopen", side_effect=IncompleteRead(b'{"candidates":')):
            text = public_speech(Gemini("test-key", "test-model"), "judge", "decision", CHAIR,
                                 "최종 결정을 알립니다.", [CHAIR["instruction"]])
        self.assertEqual(text, "최종 결정을 알립니다.")

    def test_gemini_http_body_delivers_original_to_generation_and_only_public_facts_to_checker(self):
        bodies = []
        def reply(request, timeout):
            body = json.loads(request.data)
            self.assertEqual(body["contents"][0]["role"], "user")
            self.assertNotIn("tools", body)
            self.assertIn("application/json", body["generationConfig"]["responseMimeType"])
            self.assertTrue(body["systemInstruction"]["parts"][0]["text"])
            bodies.append(json.loads(body["contents"][0]["parts"][0]["text"]))
            answer = ({"speech": "오늘은 {value} 타고 가 보실래요?"} if len(bodies) == 1
                      else opening_review(bodies[-1]["public_message"], bodies[-1]["candidate_speech"]))
            result = {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}
            return io.BytesIO(json.dumps(result).encode())

        message = "이동수단은 대중교통을 제안해요."
        with patch("travel_app.models.urlopen", side_effect=reply):
            actual = public_speech(Gemini("test-key", "test-model"), "participant", "proposal",
                                   RADIO, message, [RADIO["instruction"]], topic="local_transport", value="대중교통")
        self.assertEqual(actual, "오늘은 대중교통 타고 가 보실래요?")
        self.assertEqual(bodies[0]["persona"], RADIO)
        self.assertEqual((bodies[0]["public_message"], bodies[0]["value"]), ("이동수단은 {value}을 제안해요.", "{value}"))
        self.assertEqual(bodies[1], {"public_message": message, "candidate_speech": actual})
