import io
import json
import unittest
from unittest.mock import patch

from travel_app.models import Gemini, ModelError
from travel_app.prompts import ACTIVITY_REVIEW_PROMPT, FAITHFULNESS_PROMPT, JUDGE_PROMPT, QUOTE_PERMISSION_PROMPT, VOICE_PROMPT


class JudgeTransportTests(unittest.TestCase):
    def test_only_supported_decision_requests_use_low_thinking(self):
        entries = {"local_transport": {"value": "대중교통", "status": "agreed"}}
        response = {"entries": entries, "conflicts": [], "itinerary": []}
        reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(response)}]}}]}
        payload = {"proposals": [{"seat": 2, "values": entries, "participant_fields": ["local_transport"]}],
                   "previous": [{"round": 1, "conflicts": ["local_transport"]}], "remaining_fights": 0}
        for model, prompt, expected_thinking in [
            ("gemini-3.8-flash", JUDGE_PROMPT, {"thinkingLevel": "LOW"}),
            ("gemini-3.8-flash", ACTIVITY_REVIEW_PROMPT, None),
            ("custom-mediator", JUDGE_PROMPT, None),
        ]:
            with self.subTest(model=model, prompt=prompt.splitlines()[0]), patch(
                "travel_app.models.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())
            ) as send:
                self.assertEqual(Gemini("test", model).generate(prompt, payload), response)
                request, = send.call_args.args
                body = json.loads(request.data)
                self.assertEqual(send.call_args.kwargs["timeout"], 45)
                self.assertIn(f"/models/{model}:generateContent", request.full_url)
                self.assertEqual(body["generationConfig"].get("thinkingConfig"), expected_thinking)
                self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
                self.assertEqual(json.loads(body["contents"][0]["parts"][0]["text"]), payload)

    def test_truncated_decision_is_retryable(self):
        reply = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"entries":'}]}}]}
        with patch("travel_app.models.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())):
            with self.assertRaises(ModelError) as raised:
                Gemini("test", "gemini-3.8-flash").generate(JUDGE_PROMPT, {})
        self.assertTrue(raised.exception.transient)

    def test_optional_expression_and_review_have_bounded_request_budgets(self):
        for model, prompt, timeout, limit, thinking in [
            ("gemini-3.8-flash", VOICE_PROMPT, 12, 1024, {"thinkingLevel": "LOW"}),
            ("gemini-3.8-flash", QUOTE_PERMISSION_PROMPT, 12, 1024, {"thinkingLevel": "LOW"}),
            ("gemini-3.8-flash", FAITHFULNESS_PROMPT, 16, 3072, {"thinkingLevel": "LOW"}),
            ("gemini-3.1-flash-lite", FAITHFULNESS_PROMPT, 12, 1024, None),
        ]:
            reply = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
            with self.subTest(model=model, prompt=prompt.splitlines()[0]), patch(
                "travel_app.models.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())
            ) as send:
                Gemini("test", model).generate_voice(prompt, {"public_message": "최종 결정을 알립니다."})
                request, = send.call_args.args
                config = json.loads(request.data)["generationConfig"]
                self.assertEqual((send.call_args.kwargs["timeout"], config["maxOutputTokens"]), (timeout, limit))
                self.assertEqual(config.get("thinkingConfig"), thinking)

    def test_incomplete_optional_review_is_rejected_even_with_larger_budget(self):
        malformed = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"faithful":'}]}}]}
        with patch("travel_app.models.urlopen", return_value=io.BytesIO(json.dumps(malformed).encode())) as send:
            with self.assertRaises(ModelError):
                Gemini("test", "gemini-3.8-flash", timeout=5).generate_voice(FAITHFULNESS_PROMPT, {})
        self.assertEqual(send.call_args.kwargs["timeout"], 5)
