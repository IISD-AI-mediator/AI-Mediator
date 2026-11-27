import unittest
from semantic_fixtures import SearchExchange
from travel_app.models import grounded_search


class RestaurantGroundingTests(unittest.TestCase):
    def test_requested_dish_needs_affirmative_source(self):
        context = {"lodging": "난바역", "food": "삼겹살"}
        cases = [
            ("삼겹살을 판매합니다.", True),
            ("삼겹살을 팝니다.", True),
            ("삼겹살을 판매하지 않습니다.", False),
            ("삼겹살은 취급하지 않아요.", False),
            ("삼겹살을 제공하지 못합니다.", False),
            ("삼겹살은 안 팝니다.", False),
            ("삼겹살을 팔지 않습니다.", False),
            ("삼겹살 판매를 중단했습니다.", False),
            ("초밥을 판매합니다.", False),
        ]
        for menu, available in cases:
            with self.subTest(menu=menu):
                excerpt = f"난바역 인근에서 운영하는 식당입니다. {menu}"
                adapter = SearchExchange("restaurant", context, [excerpt], [{"id": 0, "supported": available}])
                result = grounded_search(adapter, "restaurant", context)
                self.assertEqual(adapter.calls[1][1]["segments"], [{"id": 0, "text": excerpt}])
                self.assertEqual(result["status"], "observed" if available else "verify")
                self.assertEqual(result["sources"][0]["matched"], available)
