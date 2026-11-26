import unittest
from datetime import datetime
from unittest.mock import Mock

from travel_app.models import grounded_search


class FlightEvidenceTests(unittest.TestCase):
    def test_only_matching_cited_round_trip_fare_is_published(self):
        dates = {"start": "2027-04-03", "end": "2027-04-08"}
        context = {"origin": "인천", "destination": "오사카", "dates": dates,
                   "departure_time": "오전", "currency": "KRW"}
        parts = {"출발지": "인천", "도착지": "오사카", "가는날": dates["start"],
                 "오는날": dates["end"], "출발시각": "09:15", "금액": "320000", "통화": "KRW",
                 "조건": "1인 왕복, 세금 포함, 위탁 수하물 1개"}
        url = "https://example.org/round-trip"
        cases = [
            ("일치", {}, True),
            ("출발 공항", {"출발지": "김포"}, False),
            ("도착 도시", {"도착지": "도쿄"}, False),
            ("가는 날", {"가는날": "2027-04-04"}, False),
            ("오는 날", {"오는날": "2027-04-09"}, False),
            ("시간대 경계", {"출발시각": "12:00"}, False),
            ("다른 통화", {"통화": "JPY"}, False),
            ("수하물 누락", {"조건": "1인 왕복, 세금 포함"}, False),
            ("세금 미확인", {"조건": "1인 왕복, 세금 미확인, 수하물 별도"}, False),
        ]
        for label, changes, confirmed in cases:
            with self.subTest(label=label):
                citation = "|".join(f"{k}={v}" for k, v in (parts | changes).items())
                search = Mock()
                search.generate.return_value = {"groundingMetadata": {
                    "webSearchQueries": ["인천 오사카 4월 왕복 항공권"],
                    "groundingChunks": [{"web": {"title": "예시 운임", "uri": url}}],
                    "groundingSupports": [{"segment": {"text": citation}, "groundingChunkIndices": [0]}],
                }}
                result = grounded_search(search, "flight", context)
                self.assertTrue(search.generate.call_args.kwargs["search"])
                self.assertIsNotNone(datetime.fromisoformat(result["checked_at"]).tzinfo)
                self.assertEqual(result["sources"][0]["url"], url)
                self.assertEqual(result["status"], "observed" if confirmed else "verify")
                quote = result["sources"][0]["quote"]
                if confirmed:
                    self.assertEqual((quote["amount"], quote["currency"], quote["dates"]), (320000, "KRW", dates))
                else:
                    self.assertIsNone(quote)

    def test_missing_route_or_currency_does_not_request_a_fare(self):
        search = Mock()
        result = grounded_search(search, "flight", {"destination": "오사카", "departure_time": "오전"})
        search.generate.assert_not_called()
        self.assertEqual((result["status"], result["sources"]), ("verify", []))
