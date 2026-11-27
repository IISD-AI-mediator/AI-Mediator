"""Exercise role routing at the outbound Gemini request boundary."""

import io
import json
import secrets
from contextlib import contextmanager
from unittest.mock import patch

from travel_app import prompts
from travel_app.models import Gemini, grounded_search
from test_group_travel import ACTIVITIES, DATES, MemberResponses, MediatorResponses
from test_judge import money, preference
from test_persona import CHAIR, FRIEND, RADIO, opening_review
from test_quote_and_branch_conditions import FLIGHT, FOOD, LOCAL_MENU
from test_room_recovery import RoomScenario
from semantic_fixtures import cited_result


class AgentPromptTests(RoomScenario):
    def assert_closed_object(self, schema, *fields):
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), set(fields))
        self.assertCountEqual(schema["required"], fields)
        self.assertIs(schema["additionalProperties"], False)
        return schema["properties"]

    def assert_opening_response_schema(self, config, instruction, data):
        if instruction not in (prompts.OPENING_VOICE_PROMPT, prompts.OPENING_REVIEW_PROMPT):
            self.assertNotIn("responseJsonSchema", config)
            return
        self.assertEqual(config["responseMimeType"], "application/json")
        schema = config["responseJsonSchema"]
        string = {"type": "string"}
        if instruction == prompts.OPENING_VOICE_PROMPT:
            if data.get("value") is None:
                self.assertEqual(self.assert_closed_object(schema, "core_speech")["core_speech"], string)
                return
            fields = self.assert_closed_object(schema, "opening_frame", "core_speech", "rendering")
            frame = self.assert_closed_object(fields["opening_frame"], "before_value", "after_value")
            self.assertEqual(frame, {"before_value": string, "after_value": string})
            self.assertEqual(fields["core_speech"], string)
            style = self.assert_closed_object(fields["rendering"], "register", "opening")
            self.assertEqual(style["register"], {"type": "string", "enum": ["formal_polite", "polite", "informal"]})
            self.assertEqual(style["opening"], {"type": "string", "enum": ["none", "attention", "thought"]})
            return
        fields = self.assert_closed_object(schema, "opening_assessment", "faithful", "added", "missing", "actions", "matches")
        self.assertEqual(fields["opening_assessment"]["type"], "string")
        self.assertCountEqual(fields["opening_assessment"]["enum"], ["own_offer", "assumes_prior_turn", "unsupported_claim", "changed_offer"])
        self.assertEqual(fields["faithful"], {"type": "boolean"})
        self.assertEqual(fields["added"], {"type": "array", "items": string})
        self.assertEqual(fields["missing"], {"type": "array", "items": string})
        for action in self.assert_closed_object(fields["actions"], "source", "candidate").values():
            act = self.assert_closed_object(action, "kind", "quote")
            self.assertEqual(act["quote"], string)
            self.assertEqual(act["kind"]["type"], "string")
            self.assertCountEqual(act["kind"]["enum"], ["defend", "alternative", "yield", "verify", "maintain", "other"])
        self.assertEqual(fields["matches"]["type"], "array")
        match = self.assert_closed_object(fields["matches"]["items"], "source", "candidate")
        self.assertEqual(match, {"source": string, "candidate": string})

    @contextmanager
    def record_requests(self, reply):
        calls = []

        def send(request, timeout):
            body = json.loads(request.data)
            message, = body["contents"]
            self.assertEqual(message["role"], "user")
            data = json.loads(message["parts"][0]["text"])
            instruction = body["systemInstruction"]["parts"][0]["text"]
            self.assert_opening_response_schema(body["generationConfig"], instruction, data)
            model = request.full_url.split("/models/")[1].split(":")[0]
            calls.append((instruction, model, data))
            candidate = reply(instruction, data)
            if "groundingMetadata" in candidate:
                self.assertEqual(body["tools"], [{"google_search": {}}])
                self.assertNotIn("responseMimeType", body["generationConfig"])
            else:
                self.assertNotIn("tools", body)
                self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
                candidate = {"content": {"parts": [{"text": json.dumps(candidate)}]}}
            return io.BytesIO(json.dumps({"candidates": [candidate]}).encode())

        with patch("travel_app.models.urlopen", side_effect=send):
            yield calls

    def test_value_free_first_proposal_only_requests_its_free_sentence(self):
        with self.record_requests(lambda instruction, data: {"core_speech": "저는 제 입장을 지키고 싶습니다."}) as calls:
            data = {"value": None, "event": "proposal", "speaker_role": "participant"}
            Gemini("test", "member").generate_voice(prompts.OPENING_VOICE_PROMPT, data)
            self.assertEqual(calls, [(prompts.OPENING_VOICE_PROMPT, "member", data)])

    def test_room_routes_decisions_voice_and_private_instructions(self):
        phrase = "오늘도 여러분과 함께하는 별빛 여행입니다"
        host = {**RADIO, "instruction": f"말을 천천히 해요.\n첫 문장은 ‘{phrase}’로 시작해 줘."}
        note = "내 예산 상한을 70만 원으로 올려 줘."
        member, judge = MemberResponses(), MediatorResponses()

        def reply(instruction, data):
            if instruction == prompts.OPENING_REVIEW_PROMPT:
                return opening_review(data["public_message"], data["candidate_speech"])
            if "requested_quotes" in data:
                self.assertEqual(data, {"persona_instruction": host["instruction"], "requested_quotes": [phrase]})
                return {"publish_quotes": True}
            if "public_message" in data:
                if data.get("persona") == host and data["event"] == "proposal":
                    return {"speech": phrase + "! 현지 이동수단은 {value}로 제안해요."}
                return member.generate_voice(None, data)
            if "proposals" in data or "requirements" in data:
                return judge.generate(None, data)
            if "food" in data:
                return member.generate(None, data, search=True)
            if data.get("my_new_private_instructions"):
                self.assertEqual(data["my_new_private_instructions"], [{"seq": 1, "text": note}])
                self.assertEqual(data["my_values"]["budget"], preference(money(500000), "important"))
                return {"focus": "budget", "stance": "alternative", "new_value": money(700000),
                        "authorized_note_seq": 1, "priority": "important"}
            if "private_request" in data:
                self.assertEqual(data["private_request"], note)
                self.assertEqual(data["candidates"], ["budget"])
                self.assertNotIn("700000", json.dumps(data, ensure_ascii=False))
                self.assertEqual(data["previous_conditions"]["budget"], preference(money(500000), "important"))
            return member.generate(None, data)

        calls = self.enterContext(self.record_requests(reply))
        self.config["MAX_FIGHTS"] = 1
        self.open_room(Gemini("test", "member"), Gemini("test", "judge"), conflict=True, host_persona=host,
                       guest_persona=FRIEND, mediator_persona=CHAIR,
                       fixed={"lodging": "해운대역", "dates":{"start":DATES[0], "end":DATES[1]}},
                       host_preferences={"food": preference("삼겹살"), "activities":preference(ACTIVITIES[0],"must")},
                       guest_preferences={"budget": preference(money(500000), "important"),
                                          "activities":preference(ACTIVITIES[1],"must")})
        self.advance()
        self.assertEqual(self.guest.request(self.path + "/notes", {"request_id": secrets.token_hex(16), "text": note}),
                         (200, {"seq": 1}))
        self.clock.offset += 46
        self.advance()
        final = self.host.request(self.path)[1]
        self.assertEqual(final["mode"], "done")
        self.assertEqual(final["result"]["entries"]["budget"]["value"], money(700000))
        self.assertEqual([day["activity"] for day in final["result"]["itinerary"]], list(ACTIVITIES))
        self.assertTrue(any(phrase in event["text"] for event in final["events"] if event["kind"] == "proposal"))
        expected = {"seats": prompts.TEAM_PROMPT, "organizer_focus": prompts.INTERPRET_PROMPT,
                    "evidence": prompts.PROPOSE_PROMPT, "my_new_private_instructions": prompts.DEBATE_PROMPT,
                    "private_request": prompts.REQUEST_REVIEW_PROMPT,
                    "proposals": prompts.JUDGE_PROMPT, "persona": prompts.VOICE_PROMPT,
                    "candidate_speech": prompts.FAITHFULNESS_PROMPT, "requested_quotes": prompts.QUOTE_PERMISSION_PROMPT,
                    "segments": prompts.EVIDENCE_REVIEW_PROMPT, "requirements": prompts.ACTIVITY_REVIEW_PROMPT,
                    "food": prompts.SEARCH_PROMPTS["restaurant"]}
        self.assertEqual(len(set(expected.values())), len(expected))
        self.assertEqual({instruction for instruction, _, _ in calls},
                         {*expected.values(), prompts.OPENING_VOICE_PROMPT, prompts.OPENING_REVIEW_PROMPT})
        decisions = [data for instruction, _, data in calls if instruction == prompts.JUDGE_PROMPT]
        self.assertEqual([d["remaining_fights"] for d in decisions], [1, 0])
        guest = next(p for p in decisions[-1]["proposals"] if p["seat"] == 2)
        self.assertEqual(guest["values"]["budget"], preference(money(700000), "important"))
        speeches = {(instruction, model, data["public_message"]) for instruction, model, data in calls
                    if instruction in (prompts.VOICE_PROMPT, prompts.OPENING_VOICE_PROMPT)}
        for instruction, model, data in calls:
            key, = expected.keys() & data.keys()
            if key == "persona":
                self.assertEqual(instruction, prompts.OPENING_VOICE_PROMPT if data["event"] == "proposal" else prompts.VOICE_PROMPT)
                self.assertEqual(data["speaker_role"], "judge" if model == "judge" else "participant")
                self.assertIn(data["persona"], [CHAIR] if model == "judge" else [host, FRIEND])
            elif key == "candidate_speech":
                self.assertIn(instruction, (prompts.FAITHFULNESS_PROMPT, prompts.OPENING_REVIEW_PROMPT))
                writer = prompts.OPENING_VOICE_PROMPT if instruction == prompts.OPENING_REVIEW_PROMPT else prompts.VOICE_PROMPT
                self.assertEqual(set(data), {"candidate_speech", "public_message"})
                message = data["public_message"]
                versions = {message, *(message.replace(value, "{value}") for value in ("택시", "대중교통", "700,000 KRW"))}
                self.assertTrue(any((writer, model, version) in speeches for version in versions))
            else:
                self.assertEqual(instruction, expected[key])
                self.assertEqual(model, "judge" if key in ("proposals", "requirements") else "member")
            serialized = json.dumps(data, ensure_ascii=False)
            if key not in ("my_new_private_instructions", "private_request"):
                self.assertNotIn(note, serialized)
            if key not in ("persona", "requested_quotes"):
                for actor in (host, FRIEND, CHAIR):
                    self.assertNotIn(json.dumps(actor["instruction"], ensure_ascii=False), serialized)

    def test_each_search_sends_its_own_instructions_and_uses_grounding(self):
        cases = [
            ("flight", FLIGHT, "출발지=인천|도착지=오사카|가는날=2027-04-03|오는날=2027-04-08|출발시각=09:15|"
                               "금액=640000|통화=KRW|조건=1인 왕복, 세금 포함, 위탁 수하물 1개"),
            ("restaurant", FOOD, LOCAL_MENU),
            ("lodging", {"destination": "오사카", "lodging": "난바역"}, "장소=난바 호텔|도시=오사카|정보=난바역 근처"),
            ("activity", {"destination": "오사카", "activities": "산책"}, "장소=난바 공원|도시=오사카|정보=산책로"),
        ]
        self.assertEqual(len({prompts.SEARCH_PROMPTS[kind] for kind, _, _ in cases}), len(cases))
        for kind, context, excerpt in cases:
            def reply(instruction, data):
                if "segments" in data:
                    venue = {"lodging": "난바 호텔", "activity": "난바 공원"}.get(kind)
                    return {"reviews": [{"id": 0, "supported": True, "venue": venue}]}
                return cited_result([excerpt])

            with self.subTest(kind=kind), self.record_requests(reply) as calls:
                result = grounded_search(Gemini("test", "member"), kind, context)
                self.assertEqual(calls, [(prompts.SEARCH_PROMPTS[kind], "member", context),
                                        (prompts.EVIDENCE_REVIEW_PROMPT, "member", {
                                            "kind": kind, "criteria": context, "segments": [{"id":0,"text":excerpt}]})])
                self.assertEqual(result["status"], "observed")
                source, = result["sources"]
                if kind == "flight":
                    self.assertEqual((source["quote"]["amount"], source["quote"]["currency"]), (640000, "KRW"))
                else:
                    self.assertEqual(source["excerpt"], excerpt)
