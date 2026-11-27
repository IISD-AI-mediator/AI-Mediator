import copy
import unittest
from unittest.mock import Mock

from semantic_fixtures import SearchExchange, speech_review
from travel_app.agents import model_evidence
from travel_app.decisions import decide, public_sources
from travel_app.models import ModelError, grounded_search
from travel_app.prompts import ACTIVITY_REVIEW_PROMPT
from travel_app.tone import public_speech
from test_persona import RADIO


DIET = {"destination": "오사카", "lodging": "난바역", "food": "채식 라멘"}
MUSEUM, WALK = "미술관 관람", "강변 산책"


class CitationReviewTests(unittest.TestCase):
    def test_mixed_results_are_bound_to_original_segments_and_forwarded_to_judge(self):
        texts = ["난바역 지점에서 라멘을 판매합니다.", "다른 지점에서만 채식 라멘을 판매합니다.",
                 "난바역 지점은 다음 달에 채식 라멘을 출시할 예정입니다.",
                 "난바역 지점의 채식 라멘은 채소 육수와 식물성 재료로 만듭니다. 주차장은 없습니다."]
        reviews = [{"id": 3, "supported": True}, {"id": 0, "supported": False},
                   {"id": 2, "supported": False}, {"id": 1, "supported": False}]
        provider = SearchExchange("restaurant", DIET, texts, reviews)
        result = grounded_search(provider, "restaurant", DIET)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1][1]["segments"], [{"id": i, "text": t} for i, t in enumerate(texts)])
        self.assertEqual(result["status"], "observed")
        for sources in (result["sources"], model_evidence([result])[0]["sources"]):
            self.assertEqual([s["matched"] for s in sources], [False, False, False, True])
            self.assertEqual([s["excerpt"] for s in sources], texts)
        for key, mutation in (("url", "https://example.org/other"), ("excerpt", texts[0])):
            changed = copy.deepcopy(result)
            changed["sources"][3][key] = mutation
            self.assertEqual(public_sources({"1": {"evidence": [changed]}})[0]["status"], "verify")
        different_query = copy.deepcopy(result)
        different_query["review_context"]["food"] = "냉면"
        self.assertEqual(public_sources({"1": {"evidence": [different_query]}})[0]["status"], "verify")

    def test_duplicate_multi_and_single_source_segments_do_not_hide_valid_support(self):
        excerpt = "난바역 지점에서는 두부와 채소 육수로 채식 라멘을 만듭니다."
        for refs in ([[0,1],[0]], [[0],[0,1]]):
            with self.subTest(refs=refs):
                provider = SearchExchange("restaurant", DIET, [excerpt], [{"id":0, "supported":True}])
                meta = provider.candidate["groundingMetadata"]
                meta["groundingChunks"].append({"web": {"uri": "https://example.org/secondary"}})
                meta["groundingSupports"] = [{"segment": {"text": excerpt}, "groundingChunkIndices": indices}
                                             for indices in refs]
                result = grounded_search(provider, "restaurant", DIET)
                self.assertEqual(result["status"], "observed")
                self.assertEqual([s["url"] for s in result["sources"] if s["matched"]], ["https://example.org/source/0"])
                self.assertEqual(provider.calls[1][1]["segments"], [{"id": 0, "text": excerpt}])

    def test_unavailable_malformed_or_unlinked_search_never_confirms(self):
        text = "난바역 지점에서 채식 라멘을 판매합니다."
        for reviews in (None, [], [{"id":7,"supported":True}], [{"id":False,"supported":True}],
                        [{"id":0,"supported":"true"}], [{"id":0,"supported":True},{"id":0,"supported":True}],
                        ModelError("검토 응답 없음")):
            with self.subTest(reviews=reviews):
                provider = SearchExchange("restaurant", DIET, [text], reviews)
                result = grounded_search(provider, "restaurant", DIET)
                self.assertEqual(result["status"], "verify")
                self.assertFalse(result["sources"][0]["matched"])
        for refs in ([], [4], [0,1]):
            with self.subTest(refs=refs):
                provider = SearchExchange("restaurant", DIET, [text], [{"id":0,"supported":True}])
                meta = provider.candidate["groundingMetadata"]
                meta["groundingChunks"].append({"web":{"uri":"https://example.org/secondary"}})
                meta["groundingSupports"][0]["groundingChunkIndices"] = refs
                result = grounded_search(provider, "restaurant", DIET)
                self.assertEqual((result["status"], len(provider.calls)), ("verify", 1))

    def test_six_ineligible_citations_cannot_crowd_out_a_single_valid_source(self):
        texts = [f"복수 출처 조각 {i}" for i in range(6)] + ["난바역의 라멘은 동물성 재료 없이 만듭니다."]

        def review(segments):
            self.assertEqual([s["text"] for s in segments], texts[-1:])
            return [{"id":segments[0]["id"], "supported":True}]

        provider = SearchExchange("restaurant", DIET, texts, review)
        supports = provider.candidate["groundingMetadata"]["groundingSupports"]
        for i in range(6):
            supports[i]["groundingChunkIndices"] = [i, (i+1) % 6]
        result = grounded_search(provider, "restaurant", DIET)
        self.assertEqual(result["status"], "observed")
        self.assertLessEqual(len(result["sources"]), 6)
        self.assertEqual([s["url"] for s in result["sources"] if s["matched"]], ["https://example.org/source/6"])


class ActivityReviewTests(unittest.TestCase):
    def room(self, needs=(MUSEUM, WALK)):
        profiles = [{"preferences": {"activities": {"value": need, "priority": "must"}},
                     "extra": "", "persona": {}} for need in needs]
        return {"fixed": {"destination":"부산","dates":{"start":"2027-04-01","end":"2027-04-02"}},
                "members": [{"seat": i, "profile": profile, "notes": []} for i, profile in enumerate(profiles, 1)],
                "history": [], "round": 1, "proposals": {
                    str(i): {"values":{"activities":{"value":need,"priority":"must"}}, "evidence":[]}
                    for i, need in enumerate(needs, 1)}}

    def test_coverage_requires_every_travellers_requirement_and_existing_reference(self):
        both, either = "미술관 관람 후 강변 산책", "두 활동 가운데 하나를 투표로 결정"
        coverage = [{"requirement_id": i, "sources":["plan"]} for i in (0, 1)]
        valid = {"plan_valid":True, "approved_days":[], "coverage":coverage}
        for plan, response, expected in (
            (both, valid, "agreed"),
            (either, {"plan_valid":False, "approved_days":[], "coverage":[]}, "unresolved"),
            (both, {**valid, "coverage":coverage[:1]}, "unresolved"),
            (both, {**valid, "coverage":[coverage[0], coverage[0]]}, "unresolved"),
            (both, {**valid, "coverage":[coverage[0], {"requirement_id":True,"sources":["plan"]}]}, "unresolved"),
            (both, {**valid, "approved_days":[1]}, "unresolved"),
            (both, {**valid, "plan_valid":"true"}, "unresolved"),
            (both, ModelError("검토 연결 실패"), "unresolved"),
        ):
            with self.subTest(plan=plan,response=response):
                judge = Mock()
                judge.generate.side_effect = [response]
                raw = {"entries":{"activities":{"value":plan,"status":"agreed"}}}
                final = decide(self.room(), raw, activity_judge=judge)
                judge.generate.assert_called_once_with(ACTIVITY_REVIEW_PROMPT, {
                    "requirements":[{"id":0,"text":MUSEUM},{"id":1,"text":WALK}], "plan":plan,"days":[]})
                self.assertEqual(final["entries"]["activities"]["status"], expected)
                self.assertEqual(final["entries"]["activities"]["value"], plan if expected == "agreed" else None)
                self.assertEqual("activities" in final["conflicts"], expected == "unresolved")

    def test_only_checked_days_can_witness_required_place_date_and_transport(self):
        need = "4월 1일 대중교통으로 동백공원에 가서 산책"
        room = self.room([need])
        room["fixed"]["local_transport"] = "대중교통"
        criteria = {"destination":"부산", "activities":"산책"}
        provider = SearchExchange("activity", criteria, ["동백공원의 소재지는 부산이다. 산책로가 있다."],
                                  [{"id":0, "supported":True, "venue":"동백공원"}])
        evidence = grounded_search(provider,"activity",criteria)
        room["proposals"]["1"]["evidence"] = [evidence]
        row = {"date":"2027-04-01","base":"부산","place":"동백공원","activity":"산책"}
        raw = {"entries":{}, "itinerary":[{**row,"date":"2027-03-31"},row,{**row,"date":"2027-04-02","place":"다른 공원"}]}
        judge = Mock()
        judge.generate.return_value = {"plan_valid":False,"approved_days":[0],"day_venues":[{"id":0,"names":[]}],
                                       "coverage":[{"requirement_id":0,"sources":[0]}]}
        final = decide(room,raw,activity_judge=judge)
        actual = judge.generate.call_args.args[1]
        self.assertIsNone(actual["plan"])
        self.assertEqual(actual["days"], [
            {"id":0, "place_status":"observed","date":"2027-04-01","place":"동백공원","transport":"대중교통","activity":"산책"},
            {"id":1, "place_status":"verify","date":"2027-04-02","place":"부산","candidate_place":"다른 공원",
             "transport":"대중교통","activity":"산책"},
        ])
        self.assertEqual(final["entries"]["activities"]["status"],"agreed")
        self.assertEqual([d["activity"] for d in final["itinerary"]], ["산책",""])
        judge.generate.return_value["coverage"] = [{"requirement_id":0,"sources":[1]}]
        final = decide(room,raw,activity_judge=judge)
        self.assertEqual(final["entries"]["activities"]["status"],"unresolved")

    def test_missing_museum_does_not_hide_independently_reviewed_walk(self):
        museum, walk = "국립중앙박물관 전시 관람", "한강 산책"
        room = self.room([museum, walk])
        room["fixed"].update(destination="서울", local_transport="대중교통")
        criteria = {"destination": "서울", "activities": walk}
        found = SearchExchange("activity", criteria, ["한강은 서울의 산책 장소다."],
                               [{"id": 0, "supported": True, "venue": "한강"}])
        room["proposals"]["2"]["evidence"] = [grounded_search(found, "activity", criteria)]
        missing = {"destination": "서울", "activities": museum}
        no_source = SearchExchange("activity", missing, ["전시 안내"], [{"id": 0, "supported": False}])
        room["proposals"]["1"]["evidence"] = [grounded_search(no_source, "activity", missing)]
        raw = {"entries": {}, "itinerary": [
            {"date": "2027-04-01", "base": "서울", "place": "국립중앙박물관", "activity": "국립중앙박물관 무료입장 확정"},
            {"date": "2027-04-02", "base": "서울", "place": "서울", "activity": walk},
        ]}
        judge = Mock()
        judge.generate.return_value = {
            "plan_valid": False, "approved_days": [1], "day_venues": [{"id": 1, "names": ["한강"]}],
            "candidate_days": [{"day_id": 0, "requirement_id": 0, "anchor": "국립중앙박물관"}],
            "coverage": [{"requirement_id": 1, "sources": [1]}],
        }
        result = decide(room, raw, activity_judge=judge)
        first, second = result["itinerary"]
        self.assertEqual(result["entries"]["activities"]["status"], "unresolved")
        self.assertEqual((first["date"], first["activity"], first["activity_status"]), ("2027-04-01", museum, "candidate"))
        self.assertEqual((first["place"], first["place_status"], first["transport"]), ("서울", "verify", "대중교통"))
        self.assertTrue(first["activity_reason"])
        self.assertEqual((second["date"], second["activity"], second["activity_status"]), ("2027-04-02", walk, "planned"))
        self.assertEqual(second["activity_venues"], ["한강"])
        self.assertFalse(any(k.startswith("_") or k == "candidate_place" for day in (first, second) for k in day))

        raw["entries"]["activities"] = {"value": "첫날 박물관 관람은 미정, 다음날 한강 산책", "status": "agreed"}
        partial = decide(room, raw, activity_judge=judge)
        self.assertIsNone(partial["entries"]["activities"]["value"])
        self.assertEqual(partial["entries"]["activities"]["status"], "unresolved")
        self.assertEqual(partial["itinerary"], [first, second])

    def test_city_base_cannot_verify_embedded_venue_and_exact_requests_survive_omission(self):
        museum, walk = "국립중앙박물관 전시 관람", "한강 산책"
        room = self.room([museum, walk])
        rows = [{"date": date, "place": "부산", "base": "부산", "activity": text}
                for date, text in zip(("2027-04-01", "2027-04-02"), (museum, walk))]
        judge = Mock()
        judge.generate.return_value = {"plan_valid": False, "approved_days": [0],
                                       "day_venues": [{"id": 0, "names": ["국립중앙박물관"]}],
                                       "coverage": [{"requirement_id": 0, "sources": [0]}]}
        days = decide(room, {"entries": {}, "itinerary": rows}, activity_judge=judge)["itinerary"]
        self.assertEqual([(d["activity"], d["activity_status"]) for d in days], [(museum, "candidate"), (walk, "candidate")])
        judge.generate.return_value["day_venues"] = [{"id": 3, "names": []}]
        days = decide(room, {"entries": {}, "itinerary": rows}, activity_judge=judge)["itinerary"]
        self.assertEqual([d["activity_status"] for d in days], ["undecided", "undecided"])

    def test_paraphrased_neutral_activity_keeps_only_travellers_words_on_that_day(self):
        request = "가벼운 스트레칭"
        room = self.room([request])
        raw = {"entries": {}, "itinerary": [
            {"date": "2027-04-01", "base": "부산", "place": "부산", "activity": "숙소에서 몸 풀기"},
            {"date": "2027-04-02", "base": "부산", "place": "부산", "activity": ""},
        ]}
        judge = Mock()
        judge.generate.return_value = {"plan_valid": False, "approved_days": [0],
                                       "day_venues": [{"id": 0, "names": []}],
                                       "coverage": [{"requirement_id": 0, "sources": [0]}]}
        days = decide(room, raw, activity_judge=judge)["itinerary"]
        self.assertEqual([(d["activity"], d["activity_status"]) for d in days], [(request, "candidate"), ("", "undecided")])


class VoiceReviewTests(unittest.TestCase):
    def test_price_enquiry_and_new_price_guarantee_reach_meaning_review(self):
        statement = "운임을 먼저 알아볼게요."
        for candidate, verdict in (("최저가를 확인해 볼게요.",True),("이 표가 최저가라고 보장해요.",False)):
            with self.subTest(candidate=candidate):
                provider = Mock(spec=["generate"])
                review = speech_review(statement, candidate)
                if not verdict:
                    review.update(faithful=False, added=["최저가라고 보장해요."])
                provider.generate.side_effect = [{"speech":candidate},review,{"speech":candidate},review]
                speech = public_speech(provider,"participant","speech",RADIO,statement,[RADIO["instruction"]])
                self.assertEqual(provider.generate.call_args.args[1], {"public_message":statement,"candidate_speech":candidate})
                self.assertEqual(speech, candidate if verdict else statement)
