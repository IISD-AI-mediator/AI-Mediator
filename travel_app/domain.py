"""Travel fields shared by the form, agent prompts, and final decision guard."""

import re
from datetime import date


def field(key, label, kind="text", *, options=(), hint=""):
    return {"key": key, "label": label, "kind": kind, "options": list(options), "hint": hint}


FIELDS = [
    field("destination", "여행지", hint="예: 일본 오사카"),
    field("origin", "출발지", hint="예: 인천국제공항"),
    field("dates", "여행 날짜", "dates"),
    field("budget", "1인 예산 상한", "money"),
    field("transport", "장거리 이동", "select", options=("항공", "기차", "버스", "자동차", "선박", "도보·자전거")),
    field("flight_schedule", "항공편 일정", "schedule", hint="예: 가는 편 KE721, 5월 3일 인천 09:00 → 오사카 10:50. 오는 편은 마지막 날 저녁."),
    field("local_transport", "현지 이동수단", "select", options=("대중교통", "택시", "렌터카", "도보·자전거", "혼합 이용")),
    field("departure_time", "출발 시간대", "select", options=("새벽", "오전", "오후", "저녁", "심야")),
    field("lodging", "숙소 위치", hint="예: 난바역에서 걸어서 10분 이내"),
    field("food", "음식·식당", hint="예: 채식 메뉴를 제공하는 식당"),
    field("activities", "하고 싶은 활동", hint="예: 미술관 관람과 강변 산책"),
    field("accessibility", "이동·접근성 조건", hint="예: 계단 없이 이동할 수 있는 경로"),
]
BY_KEY = {item["key"]: item for item in FIELDS}
CURRENCIES = ("KRW", "JPY", "USD", "EUR", "CNY", "GBP", "THB", "VND")
PRIORITIES = ("prefer", "important", "must")
AGENT_STYLES = ("차분한 분석가", "다정한 협상가", "당당한 대변인")
JUDGE_NAME = "판사 에이전트"
MEDIATOR_STYLES = ("균형 잡힌 진행자", "다정한 진행자", "간결한 진행자")
AXES = ("aggression", "politeness", "mz")


class Problem(Exception):
    def __init__(self, message, status=400, field=None):
        super().__init__(message)
        self.status, self.field = status, field


def plain(value, maximum, key, *, required=True):
    if not isinstance(value, str):
        raise Problem("글자로 입력해 주세요.", field=key)
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise Problem(f"1~{maximum}자 이내로 입력해 주세요." if required else f"{maximum}자 이내로 입력해 주세요.", field=key)
    if any(ord(char) < 32 and char not in "\r\n\t" for char in value):
        raise Problem("사용할 수 없는 문자가 포함되어 있어요.", field=key)
    return value


def choice(value, choices, key):
    if value not in choices:
        raise Problem("목록에서 하나를 골라 주세요.", field=key)
    return value


def request_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", value):
        raise Problem("전송 번호가 올바르지 않아요. 화면을 새로 열어 주세요.", field="request_id")
    return value


def persona(value, presets, field_name):
    if isinstance(value, str):
        value = {"preset": value}
    if not isinstance(value, dict):
        raise Problem("에이전트의 성격과 말투 설정을 확인해 주세요.", field=field_name)
    result = {"preset": choice(value.get("preset", presets[0]), presets, field_name),
              "instruction": plain(value.get("instruction", ""), 180, field_name, required=False)}
    for key in AXES:
        score = value.get(key, 5)
        if type(score) is not int or not 0 <= score <= 10:
            raise Problem("공격성·예의·MZ 감성은 각각 0~10 사이 정수로 정해 주세요.", field=field_name)
        result[key] = score
    return result


def create_roles(fixed, capacity):
    # Real agent definitions exist as part of the create transaction, including
    # while the optional model refinement is pending or unavailable.
    open_fields = [key for key in BY_KEY if key not in fixed] or list(BY_KEY)
    return {str(seat): {"seat": seat, "agent_id": f"agent-{seat}", "focus": open_fields[(seat-1) % len(open_fields)],
                       "mission": f'{BY_KEY[open_fields[(seat-1) % len(open_fields)]]["label"]} 제안을 비교하고 이 여행자의 필수 조건을 대변해요.',
                       "fixed_fields": list(fixed)} for seat in range(1, capacity + 1)}


def value_for(key, value):
    item = BY_KEY[key]
    kind = item["kind"]
    if kind == "dates":
        try:
            start, end = (date.fromisoformat(value[k]) for k in ("start", "end"))
            if start > end or (end - start).days > 365:
                raise ValueError
        except (TypeError, KeyError, ValueError):
            raise Problem("시작일부터 1년 이내의 종료일을 골라 주세요.", field=key) from None
        return {"start": start.isoformat(), "end": end.isoformat()}
    if kind == "money":
        if not isinstance(value, dict):
            raise Problem("금액과 통화를 입력해 주세요.", field=key)
        amount = value.get("amount")
        if type(amount) is not int or not 0 < amount <= 10**10:
            raise Problem("금액을 1 이상 100억 이하의 정수로 입력해 주세요.", field=key)
        return {"amount": amount, "currency": choice(value.get("currency"), CURRENCIES, key)}
    if kind == "select":
        return choice(value, item["options"], key)
    if kind == "schedule":
        return plain(value, 400, key)
    return plain(value, 160, key)


def conditions(data, fixed=None):
    if not isinstance(data, dict):
        raise Problem("항목별 조건을 다시 확인해 주세요.")
    result = {}
    for key, item in data.items():
        if key not in BY_KEY:
            raise Problem("알 수 없는 여행 항목이에요.")
        if fixed is not None and key in fixed:
            raise Problem("방장이 확정한 항목은 바꿀 수 없어요.", 409, key)
        if fixed is None:
            result[key] = value_for(key, item)
        else:
            if not isinstance(item, dict):
                raise Problem("값과 중요도를 입력해 주세요.", field=key)
            result[key] = {"value": value_for(key, item.get("value")),
                           "priority": choice(item.get("priority"), PRIORITIES, key)}
    return result


def profile(data, fixed):
    return {"preferences": conditions(data.get("preferences", {}), fixed),
            "extra": plain(data.get("extra", ""), 600, "extra", required=False),
            "persona": persona(data.get("persona", AGENT_STYLES[0]), AGENT_STYLES, "persona")}


def display(value):
    if isinstance(value, dict) and "currency" in value:
        return f'{value["amount"]:,} {value["currency"]}'
    if isinstance(value, dict) and "start" in value:
        return f'{value["start"]} ~ {value["end"]}'
    return str(value) if value is not None else "미정"
