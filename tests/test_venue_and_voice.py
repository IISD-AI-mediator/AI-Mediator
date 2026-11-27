import copy
import unittest

from travel_app.decisions import itinerary, public_sources
from travel_app.domain import MEDIATOR_STYLES, persona
from travel_app.graph import Workflow
from travel_app.models import grounded_search
from test_group_travel import VoiceResponses
from semantic_fixtures import SearchExchange


class Judge(VoiceResponses):
    def __init__(self):
        self.inputs = []

    def generate(self, instruction, data, *, search=False):
        self.inputs.append(copy.deepcopy(data))
        return {"entries": {"destination": {"status": "agreed", "value": "오사카"}}, "conflicts": ["activities"]}


class VenueAndVoiceTests(unittest.TestCase):
    def test_supported_city_and_venue_are_required(self):
        cases = [
            ("도톤보리는 일본 오사카시에 위치한 관광지다.", "도톤보리", "observed", "도톤보리"),
            ("도톤보리는 오사카에 위치해 있다.", "도톤보리", "observed", "도톤보리"),
            ("장소=난바 파크스|도시=오사카|정보=상업시설과 정원이 있다.", "난바 파크스", "observed", "난바 파크스"),
            ("제주 협재해변은 제주시 한림읍에 있습니다.", "제주 협재해변", "verify", "오사카"),
            ("제주 협재해변은 오사카에 위치하지 않습니다. 실제 소재지는 제주시 한림읍입니다.", "제주 협재해변", "verify", "오사카"),
            ("제주 협재해변은 오사카에 소재하지 않아요.", "제주 협재해변", "verify", "오사카"),
            ("제주 협재해변은 오사카에 있지 않습니다.", "제주 협재해변", "verify", "오사카"),
            ("제주 협재해변은 오사카에 위치해 있지는 않다.", "제주 협재해변", "verify", "오사카"),
            ("장소=제주 협재해변|도시=오사카|정보=이곳은 오사카에 있지 않습니다.", "제주 협재해변", "verify", "오사카"),
            ("오사카 여행 정보를 살펴봤습니다. 제주 협재해변은 제주시 한림읍에 있습니다.", "제주 협재해변", "verify", "오사카"),
            ("도톤보리에는 산책로가 있습니다.", "도톤보리", "verify", "오사카"),
        ]
        entries = {"dates":{"status":"fixed","value":{"start":"2027-04-01","end":"2027-04-03"}},
                   "destination":{"status":"fixed","value":"오사카"}, "activities":{"status":"agreed","value":"산책"}}
        for kind in ("lodging", "activity"):
            for excerpt, name, status, expected in cases:
                with self.subTest(kind=kind, excerpt=excerpt):
                    criteria = {"destination":"오사카"}
                    result = {"id":0, "supported":status == "observed", "venue":name}
                    adapter = SearchExchange(kind, criteria, [excerpt], [result])
                    evidence = grounded_search(adapter, kind, criteria)
                    self.assertEqual(evidence["status"], status)
                    row = {"date":"2027-04-01","base":"오사카","place":name}
                    day = itinerary(entries,[row],[],[evidence])[0]
                    self.assertEqual((day["place"],day["place_status"]), (expected,status))
                    evidence["status"] = "observed"  # Older persisted searches also pass through the current guard.
                    restored = public_sources({"1":{"evidence":[evidence]}})[0]
                    self.assertEqual(restored["status"],status)

    def test_english_location_requires_an_affirmative_clause(self):
        for kind in ("lodging", "activity"):
            for phrase, expected in (
                ("Dotonbori is located in Osaka.", "observed"),
                ("Hyeopjae Beach is not located in Osaka. It is in Jeju.", "verify"),
                ("Hyeopjae Beach isn't in Osaka.", "verify"),
                ("It is not true that Hyeopjae Beach is in Osaka.", "verify"),
                ("Hyeopjae Beach is located in Osaka?", "verify"),
            ):
                with self.subTest(kind=kind, phrase=phrase):
                    criteria = {"destination":"Osaka"}
                    result = {"id":0, "supported":expected == "observed", "venue":"Dotonbori"}
                    adapter = SearchExchange(kind, criteria, [phrase], [result])
                    self.assertEqual(grounded_search(adapter, kind, criteria)["status"],expected)

    def test_mediator_preset_changes_only_public_expression(self):
        judge = Judge()
        workflow = Workflow(None, None, judge)
        speeches, decisions = [], []
        for preset in MEDIATOR_STYLES:
            room = {"fixed":{"destination":"오사카"},"mediator":persona(preset, MEDIATOR_STYLES,"mediator"),
                    "floor":None,"seats":[1,2],"members":[],"events":[],"proposals":{},"history":[],"round":1}
            workflow.judge(room)(room)
            decisions.append(room["draft"])
            workflow.open(room)(room)
            speeches.append(room["events"][-1]["text"])
        self.assertEqual(len(set(speeches)),len(MEDIATOR_STYLES))
        for actual in judge.inputs[1:]:
            self.assertEqual(judge.inputs[0],actual)
        for decision in decisions[1:]:
            self.assertEqual(decisions[0],decision)


if __name__ == "__main__":
    unittest.main()
