"""A presentation-only adapter. Its outputs are never decision inputs."""

import re

from .models import ModelError

MEDIATOR_OPENINGS = {
    "균형 잡힌 진행자": {"gentle":"양쪽이 편하게 받아들일 기준을 찾아볼게요.", "balanced":"각자의 조건을 같은 기준으로 살펴볼게요.", "firm":"공정한 기준부터 분명히 하겠습니다."},
    "다정한 진행자": {"gentle":"걱정되는 점부터 천천히 들려주세요.", "balanced":"한 분씩 편하게 이야기해 주세요.", "firm":"모두의 목소리가 들리도록 차례를 지킬게요."},
    "간결한 진행자": {"gentle":"요점부터 함께 볼까요?", "balanced":"논점을 짚겠습니다.", "firm":"핵심부터 말씀해 주세요."},
}


def tone_settings(adapter, persona):
    style = {"register": "formal" if persona["politeness"] >= 7 else "casual" if persona["politeness"] <= 3 else "polite",
             "manner": "firm" if persona["aggression"] >= 7 else "gentle" if persona["aggression"] <= 3 else "balanced",
             "modern": persona["mz"] >= 7, "flavor":"plain", "suffix":"", "preset":persona.get("preset","")}
    if not persona["instruction"]:
        return style
    try:
        raw = adapter.generate(
            "여행방 화자의 자유 말투를 표현 기법 하나로 분류한다. 여행 조건이나 판단을 다루지 않는다. "
            "질문형=question, 간결=short, 유머=humor, 따뜻한 공감=warm, 기본=plain. "
            '요청한 말버릇이나 종결어가 원문에 있다면 짧게 추출하라. JSON {"flavor":"question|short|humor|warm|plain","suffix":"말버릇 또는 빈 문자열"}로 답하라.', {"tone_instruction":persona["instruction"]})
        if raw.get("flavor") in ("question","short","humor","warm","plain"):
            style["flavor"] = raw["flavor"]
        suffix = raw.get("suffix")
        if isinstance(suffix,str) and suffix in persona["instruction"] and re.fullmatch(r"[가-힣A-Za-zㅋㅎ!?~ ]{1,10}",suffix):
            style["suffix"] = suffix
    except ModelError:
        pass
    return style


def expression(style, content):
    manner = {"firm":"제 입장을 분명히 전할게요.", "gentle":"서로 편한 방법을 찾고 싶어요.", "balanced":"의견을 나눠 볼게요."}[style["manner"]]
    moderator = MEDIATOR_OPENINGS.get(style.get("preset"))
    if moderator:
        manner = moderator[style["manner"]]
    closing = {"formal":"검토해 주시면 감사하겠습니다.", "polite":"함께 살펴봐요.", "casual":"어떤지 같이 보자!"}[style["register"]]
    flavor = {"question":"이 방향은 어떨까요?", "humor":"여행 가방보다 의견부터 잘 챙겨 볼게요.", "warm":"각자의 마음도 소중해요.", "plain":"", "short":""}[style["flavor"]]
    pieces = [manner, content, closing, flavor, "같이 가보자고!" if style["modern"] else ""]
    if style["flavor"] == "short":
        pieces = [manner if moderator else "", content, closing, "좋아요!" if style["modern"] else ""]
    return " ".join(p for p in [*pieces, style.get("suffix","")] if p)
