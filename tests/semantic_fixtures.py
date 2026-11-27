"""Scripted provider responses for grounded-search contract tests."""

from travel_app.prompts import EVIDENCE_REVIEW_PROMPT, SEARCH_PROMPTS


def speech_review(public_message, candidate_speech):
    # Supply expected model classifications for the scripted canonical events.
    cases = {"쪽으로 양보할게요.": "yield", "안을 검토해 주세요.": "alternative", "대안을 함께 검토해 주세요.": "alternative",
             "근거를 확인하고 싶어요.": "verify", "결정 전에 근거를 더 확인하고 싶어요.": "verify", "유지할게요.": "maintain",
             "파이터 모드에서 의견을 더 듣겠습니다.": "continue_debate", "차례로 의견을 들어요.": "open",
             "최종 결정을 내렸어요.": "announce", "운임을 먼저 알아볼게요.": "verify"}
    phrase, kind = next(((phrase, kind) for phrase, kind in cases.items() if phrase in public_message),
                        (public_message, "defend"))
    return {"faithful": True, "added": [], "missing": [],
            "actions": {"source": {"kind": kind, "quote": phrase},
                        "candidate": {"kind": kind, "quote": candidate_speech}},
            "matches": [{"candidate": candidate_speech, "source": public_message}]}


def cited_result(texts, urls=None):
    urls = urls or [f"https://example.org/source/{i}" for i in range(len(texts))]
    return {"groundingMetadata": {
        "webSearchQueries": ["여행 자료"],
        "groundingChunks": [{"web": {"title": f"출처 {i}", "uri": url}} for i, url in enumerate(urls)],
        "groundingSupports": [{"segment": {"text": text}, "groundingChunkIndices": [i]} for i, text in enumerate(texts)],
    }}


class SearchExchange:
    def __init__(self, kind, criteria, texts, reviews):
        self.kind, self.criteria = kind, criteria
        self.texts, self.reviews = texts, reviews
        self.candidate = cited_result(texts)
        self.calls = []

    def generate(self, instruction, data, *, search=False):
        self.calls.append((instruction, data, search))
        if search:
            if instruction != SEARCH_PROMPTS[self.kind] or data != self.criteria:
                raise AssertionError("Unexpected search instructions or criteria")
            return self.candidate
        if instruction != EVIDENCE_REVIEW_PROMPT or data["criteria"] != self.criteria or data["kind"] != self.kind:
            raise AssertionError("Unexpected evidence review instructions or criteria")
        for segment in data["segments"]:
            if segment["text"] not in self.texts:
                raise AssertionError("The reviewer did not receive the cited text")
        if isinstance(self.reviews, Exception):
            raise self.reviews
        if callable(self.reviews):
            return {"reviews": self.reviews(data["segments"])}
        return {"reviews": self.reviews}
