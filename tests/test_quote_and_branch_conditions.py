import copy
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from travel_app import create_app
from travel_app.models import grounded_search
from semantic_fixtures import SearchExchange


DATES = {"start": "2027-04-03", "end": "2027-04-08"}
FLIGHT = {"origin": "인천", "destination": "오사카", "dates": DATES, "departure_time": "오전", "currency": "KRW"}
FOOD = {"lodging": "난바역", "food": "삼겹살"}
PAIR_FARE = "2인 왕복 총액, 세금 포함, 위탁 수하물 2개"
ONE_WAY = "1인 편도 (왕복 아님), 세금 포함, 위탁 수하물 1개"
FARE = "성인 1명 왕복 총액, 세금 포함, 위탁 수하물 1개, 예매 가능"
OTHER_BRANCH = "난바역 지점은 초밥만 판매합니다. 삼겹살은 서울 지점에서만 판매합니다."
SOLE_BRANCH = "난바역 인근에서 운영하는 식당입니다. 삼겹살을 판매하는 곳은 서울점뿐입니다."
LOCAL_MENU = "난바역 인근에서 운영하는 식당입니다. 삼겹살을 판매합니다."


def search(kind, detail, supported=False):
    if kind == "flight":
        detail = ("출발지=인천|도착지=오사카|가는날=2027-04-03|오는날=2027-04-08|"
                  "출발시각=09:15|금액=640000|통화=KRW|조건=" + detail)
    context = FLIGHT if kind == "flight" else FOOD
    adapter = SearchExchange(kind, context, [detail], [{"id": 0, "supported": supported}])
    return grounded_search(adapter, kind, context)


def old_observation(kind, detail, stamp):
    item = search(kind, detail)
    item.pop("review_context")
    item.pop("restaurant_criteria", None)  # v1.0.0 did not persist individual search criteria.
    item.update(status="observed", reason="출처와 조회 시각을 기록했어요.", checked_at=stamp)
    source = item["sources"][0]
    source["matched"] = True
    if kind == "flight":
        source["quote"] = {"amount":640000, "currency":"KRW", "origin":"인천", "destination":"오사카",
                           "time":"09:15", "dates":DATES, "terms":detail}
    return item


class QuoteAndBranchTests(unittest.TestCase):
    def test_fare_requires_explicit_one_passenger_return_and_conditions(self):
        cases = [
            (FARE, True), ("1인 왕복, 세금 포함, 위탁 수하물 별도", True),
            ("한 사람이 다녀오는 여정, 세금이 포함된 가격, 부치는 짐은 15kg까지", True),
            (PAIR_FARE, False), (ONE_WAY, False), ("왕복, 세금 포함, 위탁 수하물 1개", False),
            ("성인 1인 왕복 여부 미정, 세금 포함, 위탁 수하물 1개", False),
            ("1인 왕복, 세금, 위탁 수하물 1개", False), ("1인 왕복, 세금 포함, 수하물", False),
            ("1인 왕복 아님, 세금 포함, 위탁 수하물 1개", False),
            ("1인 왕복, 세금 포함, 위탁 수하물 1개|실제 기준=2인 총액", False),
        ]
        for terms, confirmed in cases:
            with self.subTest(terms=terms):
                result = search("flight",terms,confirmed)
                self.assertEqual(result["status"], "observed" if confirmed else "verify")
                source = result["sources"][0]
                if confirmed:
                    self.assertEqual((source["quote"]["amount"],source["quote"]["terms"]), (640000,terms))
                    self.assertNotIn("최저",result["reason"])
                else:
                    self.assertIsNone(source["quote"])
                    self.assertFalse(source["matched"])
                    self.assertEqual(source["excerpt"],"")

    def test_menu_must_be_served_at_requested_location(self):
        for excerpt, expected in [(LOCAL_MENU,True),("난바역 지점은 삼겹살을 판매합니다.",True),
                (OTHER_BRANCH,False),("난바역 지점은 초밥을 판매합니다. 서울점에서는 삼겹살을 팝니다.",False),
                ("난바역 인근 식당입니다. 삼겹살은 서울 지점에서만 판매합니다.",False),
                (SOLE_BRANCH, False), ("난바역 인근 식당입니다. 삼겹살을 제공하는 지점은 서울 지점뿐이에요.",False),
                ("난바역 지점은 삼겹살을 판매합니다. 실제로는 서울점에서만 판매합니다.",False),
                ("난바역 지점은 삼겹살을 판매하고 있습니다.",True)]:
            with self.subTest(excerpt=excerpt):
                result = search("restaurant",excerpt,expected)
                self.assertEqual((result["status"], result["sources"][0]["matched"]),
                                 ("observed" if expected else "verify",expected))

    def test_completed_v100_room_is_corrected_on_public_read_and_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"DATABASE_URL":str(Path(directory)/"old.db"),"START_WORKER":False})
            member = app.test_client()
            invite = member.post("/api/rooms",json={"name":"여행자","capacity":2,"request_id":secrets.token_hex(16)}).get_json()["invite"]
            endpoint = "/api/rooms/" + invite
            member.post(endpoint+"/ready",json={"preferences":{k:{"priority":"prefer","value":v} for k,v in FOOD.items()}})
            database = app.extensions["travel_store"]
            evidence = [old_observation("flight",PAIR_FARE,"a"),old_observation("restaurant",OTHER_BRANCH,"b"),
                        old_observation("flight",FARE,"c"),old_observation("restaurant",LOCAL_MENU,"d"),
                        old_observation("restaurant",SOLE_BRANCH,"e"),
                        search("flight",FARE,True),search("restaurant",LOCAL_MENU,True)]
            def populate(room):
                entries = {k:{"value":v,"status":"agreed","reason":"이전 판단"} for k,v in {"transport":"항공","food":"삼겹살"}.items()}
                decision = {"entries": entries, "round":1,"conflicts":[],"evidence":copy.deepcopy(evidence),"itinerary":[]}
                room.update(mode="done",proposals={"1":{"values":{},"search_context":{},"evidence":copy.deepcopy(evidence)}},
                            draft=copy.deepcopy(decision),result=decision,history=[{"round":1,"entries":copy.deepcopy(entries)}])
            database.update(invite,populate)
            for _ in range(2):
                with patch("travel_app.models.Gemini.generate", side_effect=AssertionError("Model called during read")):
                    response = member.get(endpoint)
                self.assertEqual(response.status_code,200)
                public = response.get_json()
                current = public["result"]["evidence"]
                self.assertEqual([item["status"] for item in current],["verify"]*5 + ["observed","observed"])
                self.assertIsNone(current[0]["sources"][0]["quote"])
                self.assertFalse(current[1]["sources"][0]["matched"])
                self.assertIsNone(current[2]["sources"][0]["quote"])
                self.assertFalse(current[3]["sources"][0]["matched"])
                self.assertEqual(current[5]["sources"][0]["quote"]["amount"],640000)
                self.assertTrue(current[6]["sources"][0]["matched"])
                self.assertNotIn("review_context",current[6])
                self.assertNotIn("review_proof",current[6]["sources"][0])
                self.assertFalse(current[4]["sources"][0]["matched"])
                self.assertNotIn("restaurant_criteria",current[1])
                for key in ("transport","food"):
                    self.assertEqual(public["result"]["entries"][key]["status"],"verify")
                    self.assertEqual(public["history"][0]["entries"][key]["status"],"verify")
            self.assertNotIn("result",app.test_client().get(endpoint).get_json())
            restored = database.read(invite)
            self.assertIsNone(restored["proposals"]["1"]["evidence"][0]["sources"][0]["quote"])
            self.assertEqual(restored["draft"]["evidence"][1]["status"],"verify")


if __name__ == "__main__":
    unittest.main()
