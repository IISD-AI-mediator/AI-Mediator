"""Generate a speaker's public words after the travel decision has been made."""

import re
from typing import NamedTuple

from .decisions import overlaps_private_text, private_texts, safe_text
from .domain import BY_KEY, display
from .models import ModelError
from .prompts import (FAITHFULNESS_PROMPT, OPENING_REVIEW_PROMPT, OPENING_VOICE_PROMPT,
                      QUOTE_PERMISSION_PROMPT, VOICE_PROMPT)


QUOTED_TEXT = re.compile(r"‘([^‘’]+)’|“([^“”]+)”|'([^']+)'|" r'"([^"]+)"')
JOSA_PAIRS = (("을", "를"), ("은", "는"), ("이", "가"), ("과", "와"), ("으로", "로"))
JOSA_FORMS = {"(으)로": ("으로", "로")}
JOSA_MARKERS = [r"[(（]\s*으\s*[)）]\s*로"]
for consonant, vowel in JOSA_PAIRS:
    for first, second in ((consonant, vowel), (vowel, consonant)):
        JOSA_FORMS[f"{first}({second})"] = JOSA_FORMS[f"{first}/{second}"] = (consonant, vowel)
        JOSA_MARKERS.append(rf"{first}\s*(?:[(（]\s*{second}\s*[)）]|[/／·]\s*{second})")
PAIRED_JOSA = re.compile("|".join(JOSA_MARKERS))
OTHER_SLOT_PAIR = re.compile(
    r"""\{value\}[’”'"]?(?:[가-힣]{1,4}\s*(?:[(（]\s*[가-힣]{1,4}\s*[)）]|[/／·]\s*[가-힣])|[(（][가-힣]{1,3}[)）][가-힣])""")
QUOTED_JOSA = re.compile(QUOTED_TEXT.pattern + r"|「[^」]*」|『[^』]*』")
PARTICIPANT_ACTS = ("defend", "yield", "alternative", "verify", "maintain")
SPEECH_ACTS = (*PARTICIPANT_ACTS, "continue_debate", "open", "announce")
_UNSPECIFIED_VALUE = object()


class Speech(NamedTuple):
    text: str
    source: str


def proposal_template(action, topic, register):
    label = BY_KEY[topic]["label"]
    # A value slot may end in Korean, a currency code or a date. The following
    # noun, rather than a guessed particle on that slot, carries the case.
    value = "‘{value}’"
    earlier = "아까 말한" if register == "informal" else "앞서 말씀드린"
    if topic == "budget":
        offer = f"1인 예산은 {value} 이내로 잡는 안을 "
        keep = f"1인 예산은 {earlier} 대로 {value} 이내로 "
    elif topic == "local_transport":
        offer = f"현지에서는 {value} 이용을 "
        keep = f"현지 이동수단은 {earlier} {value} 안을 "
    else:
        offer = f"{label}에 대해서는 {value} 안을 "
        keep = f"{label}에 대해서는 {earlier} {value} 안을 "
    forms = {
        "defend": (offer, ("제안합니다.", "제안해요.", "제안할게.")),
        "maintain": (keep, ("유지하겠습니다.", "유지할게요.", "유지할게.")),
        "yield": (f"{label}에 대해서는 {value} 쪽으로 ", ("양보하겠습니다.", "양보할게요.", "양보할게.")),
        "alternative": (f"{label} 대안으로 {value} 안을 ", ("검토해 주시겠습니까?", "검토해 주세요.", "검토해 줘.")),
        "verify": (f"{label} 후보 {value}의 근거를 ", ("확인하고 싶습니다.", "확인하고 싶어요.", "확인하고 싶어.")),
    }
    body, endings = forms[action]
    return body + endings[("formal_polite", "polite", "informal").index(register)]


def proposal_message(stance, topic, value):
    if value is not None:
        return proposal_template(stance, topic, "polite").replace("{value}", display(value))
    label = BY_KEY[topic]["label"]
    return {"defend": f"{label}에 대해서는 제 입장을 지키고 싶어요.",
            "yield": f"{label}에 대해서는 다른 제안에 양보할게요.",
            "alternative": f"{label}의 대안을 함께 검토해 주세요.",
            "verify": f"{label}의 근거를 먼저 확인하고 싶어요."}[stance]


def participant_rendering(raw, action, topic, public_value, private):
    choice = raw.get("rendering") if isinstance(raw, dict) else None
    if not isinstance(choice, dict) or set(choice) - {"register", "opening"}:
        return None
    register, opening = choice.get("register"), choice.get("opening", "none")
    registers = ("formal_polite", "polite", "informal")
    if register not in registers or opening not in ("none", "attention", "thought"):
        return None
    prefix = {"none": "", "attention": "오, ", "thought": "음, "}[opening]
    # The provider selects only grammatical forms. Its candidate, explanation
    # and private instruction never enter this publication path.
    template = prefix + proposal_template(action, topic, register)
    text = template.replace("{value}", public_value)
    if (len(text) > 280 or text.count(public_value) != 1 or
            not safe_text(template.replace("{value}", ""), private, 280, voice_review=True)):
        return None
    return Speech(text, "structured")


def speech_secrets(room):
    return [*private_texts(room), room["mediator"]["instruction"]]


def review_public_prose(generate, prose, instruction, private):
    """Return the explicitly cleared quotations, or None if prose must stay private."""
    # Exemptions apply only to the speaker's instruction, never a matching note.
    secrets = list(private)
    if instruction in secrets:
        secrets.remove(instruction)
    if not safe_text(prose, secrets, 280, voice_review=True):
        return None
    if re.fullmatch(r"[가-힣A-Za-zㅋㅎ!?~]{1,10}", instruction) or safe_text(prose, [instruction], 280, voice_review=True):
        return ()

    # Only an exact quoted phrase can explain a longer overlap. Check everything
    # around it before asking whether the speaker explicitly wanted it spoken.
    quoted = []
    unquoted = []
    end = 0
    for match in QUOTED_TEXT.finditer(instruction):
        phrase = next(part for part in match.groups() if part is not None)
        if phrase in prose:
            quoted.append(phrase)
            unquoted.append(instruction[end:match.start()])
            end = match.end()
    if not quoted:
        return None
    unquoted.append(instruction[end:])
    remaining = prose
    for phrase in quoted:
        remaining = remaining.replace(phrase, "")
    if remaining.strip() and not safe_text(remaining, [instruction, *unquoted], 280, voice_review=True):
        return None
    permission = generate(QUOTE_PERMISSION_PROMPT, {"persona_instruction": instruction, "requested_quotes": quoted})
    return tuple(quoted) if isinstance(permission, dict) and permission.get("publish_quotes") is True else None


def voice_template(candidate, public_value, event_kind, label, *, one_line=False):
    if not isinstance(candidate, str) or not 0 < len(candidate) <= 280:
        return None
    if one_line and public_value and len(candidate.replace(public_value, "{value}", 1).strip().splitlines()) > 1:
        return None
    template = " ".join(candidate.split())
    if public_value and "{value}" not in template and template.count(public_value) == 1:
        template = template.replace(public_value, "{value}", 1)
    prose = template.replace("{value}", "")
    if (template.count("{value}") != int(public_value is not None) or
            "{" in prose or "}" in prose or (public_value and public_value in prose) or
            (event_kind == "fight" and label not in template)):
        return None
    # Inflect only an explicit slot suffix. Quoted prose and the value itself
    # remain intact. The meaning reviewer receives the fully rendered sentence.
    pair = PAIRED_JOSA.search(template)
    if pair:
        if (not public_value or pair.group() not in JOSA_FORMS or not template[:pair.start()].endswith("{value}")
                or any(m.start() < pair.start() < m.end() for m in QUOTED_JOSA.finditer(template))
                or not "가" <= public_value[-1] <= "힣"):
            return None
        consonant, vowel = JOSA_FORMS[pair.group()]
        jongseong = (ord(public_value[-1]) - ord("가")) % 28
        suffix = consonant if jongseong and not (consonant == "으로" and jongseong == 8) else vowel
        template = template[:pair.start()] + suffix + template[pair.end():]
    if PAIRED_JOSA.search(template) or OTHER_SLOT_PAIR.search(template):
        return None
    return template


def opening_frame_template(frame):
    """Bind only the value slot; words, spacing and punctuation belong to the author."""
    if not isinstance(frame, dict) or set(frame) != {"before_value", "after_value"}:
        return None
    before, after = frame["before_value"], frame["after_value"]
    if not all(isinstance(side, str) and len(side) <= 280 and not re.search(r"[{}\r\n]", side)
               for side in (before, after)) or not (before.strip() or after.strip()):
        return None
    return before + "{value}" + after


def turn_sentences(text, value):
    # Periods, punctuation and line breaks in the traveller's value are data.
    marked = text.replace(value, "{value}", 1)
    return [part.strip() for part in re.split(r"[.!?。！？…~;；\r\n]+", marked) if re.search(r"\w", part)]


def opening_repair_reason(verdict):
    """Translate review output into a fixed instruction without echoing its quotations."""
    if isinstance(verdict, dict):
        assessment = verdict.get("opening_assessment")
        if assessment in ("assumes_prior_turn", "unsupported_claim", "changed_offer"):
            return assessment
        if isinstance(verdict.get("added"), list) and verdict["added"]:
            return "unsupported_claim"
        if isinstance(verdict.get("missing"), list) and verdict["missing"]:
            return "changed_offer"
    return "single_offer"


def supported_speech(verdict, message, speech, *, action=None, value=_UNSPECIFIED_VALUE, label="", approved_quotes=(),
                     opening=False):
    """Check both classifications against the event, plus the quoted support in both directions."""
    if value is _UNSPECIFIED_VALUE:
        # Stored canonical proposals quote the server's value. Offline review can
        # reconstruct that single slot without attempting to interpret free prose.
        quotes = QUOTED_TEXT.findall(message)
        value = next(part for part in quotes[0] if part) if len(quotes) == 1 else None
    if value and speech.count(value) != 1:
        return False
    fields = {"faithful", "added", "missing", "matches", "actions"}
    if opening:
        fields.add("opening_assessment")
    if not isinstance(verdict, dict) or set(verdict) != fields:
        return False
    if opening and verdict["opening_assessment"] != "own_offer":
        return False
    if verdict["faithful"] is not True or verdict["added"] != [] or verdict["missing"] != []:
        return False
    actions = verdict["actions"]
    if not isinstance(actions, dict) or set(actions) != {"source", "candidate"}:
        return False
    for side, original in (("source", message), ("candidate", speech)):
        item = actions[side]
        if not isinstance(item, dict) or set(item) != {"kind", "quote"} or item["kind"] not in SPEECH_ACTS:
            return False
        phrase = item["quote"]
        if not isinstance(phrase, str) or phrase not in original:
            return False
        # A value or field name alone never witnesses a negotiation act.
        words = "".join(char for char in phrase.casefold() if char.isalnum())
        for context in (value, label):
            if context:
                term = "".join(char for char in context.casefold() if char.isalnum())
                if words in term:
                    return False
                words = words.replace(term, "")
        if sum(char.isalpha() for char in words) < 2:
            return False
    kind = actions["source"]["kind"]
    if kind != actions["candidate"]["kind"] or (action is not None and kind != action) or (opening and kind != "defend"):
        return False
    if value and kind in PARTICIPANT_ACTS and len(turn_sentences(message, value)) == 1:
        parts = turn_sentences(speech, value)
        if len(parts) != 1:
            # A verifier sometimes attributes two independent sentences wholesale to
            # one proposal. Only a reaction sound or a cleared greeting may precede it.
            if (len(parts) != 2 or "{value}" not in parts[-1] or
                    not (parts[0] in approved_quotes or re.fullmatch(r"([가-힣ㅋㅎ])\1{0,2}", parts[0]))):
                return False
    matches = verdict["matches"]
    if not isinstance(matches, list) or not matches:
        return False
    remaining = speech
    source_coverage = set()
    aligned_action = False
    for match in matches:
        if not isinstance(match, dict) or set(match) != {"candidate", "source"}:
            return False
        candidate, source = match["candidate"], match["source"]
        if not isinstance(source, str) or not re.search(r"\w", source) or source not in message:
            return False
        if not isinstance(candidate, str) or not candidate.strip() or not remaining.startswith(candidate):
            return False
        start = message.index(source)
        source_coverage.update(range(start, start + len(source)))
        if actions["source"]["quote"] in source and actions["candidate"]["quote"] in candidate:
            aligned_action = True
        remaining = remaining[len(candidate):].lstrip()
    return not remaining and aligned_action and all(i in source_coverage for i, c in enumerate(message) if c.isalnum())


def render_speech(adapter, role, event_kind, persona, message, private, *, topic="", value=None, action=None,
                  public_turn_memory=None):
    """Choose reviewed prose or a safe rendition of the original public event."""
    label = BY_KEY[topic]["label"] if topic else ""
    public_value = display(value) if value is not None else None
    opening = role == "participant" and event_kind == "proposal" and action in (None, "defend")
    voice_message, voice_value = message, public_value
    fallback = Speech(message, "baseline")
    can_render = (role == "participant" and public_value and topic and
                  action in PARTICIPANT_ACTS and
                  message == proposal_message(action, topic, value))
    if role == "participant" and public_value:
        if message.count(public_value) != 1:
            return fallback
        voice_message, voice_value = message.replace(public_value, "{value}"), "{value}"
    data = {"speaker_role": role, "event": event_kind, "persona": persona, "public_message": voice_message,
            "topic": label, "value": voice_value}
    previous_words = ""
    if opening:
        data["action"] = "defend"
        if topic == "budget" and public_value:
            data["value_meaning"] = "한 사람당 쓸 수 있는 최대 금액"
    elif role == "participant" and public_turn_memory:
        data["public_turn_memory"] = public_turn_memory
        previous = public_turn_memory.get("previous_own") or {}
        previous_words = " ".join(previous.get("speech", "").split())
    generate = getattr(adapter, "generate_voice", adapter.generate)
    numbers = re.compile(r"\d+(?:[.,:]\d+)*")
    allowed_numbers = numbers.findall(message.replace(public_value, "") if public_value else message)
    reviews_left = 2
    deferred_speech = None
    repair_reason = "value_and_form"
    rejected_openings = set()
    try:
        for attempt in range(2):
            # Repair from the original public event. A rejected candidate or verdict
            # can contain private material and is never fed back to the speaker.
            request = {**data, "repair": True} if attempt else data
            if attempt and opening:
                request["repair_reason"] = repair_reason
            raw = generate(OPENING_VOICE_PROMPT if opening else VOICE_PROMPT, request)
            if not isinstance(raw, dict):
                raw = {}
            if can_render and fallback.source == "baseline":
                fallback = participant_rendering(raw, action, topic, public_value, private) or fallback
            candidates = [(raw.get("speech"), "generated")]
            if role == "participant":
                candidates.insert(0, (raw.get("core_speech"), "generated_core"))
                if attempt and deferred_speech:
                    candidates.append((deferred_speech, "generated"))
            if opening:
                # Give each writing attempt up to two distinct reviewed expressions.
                reviews_left = 2
                if public_value:
                    candidates.insert(0, (opening_frame_template(raw.get("opening_frame")), "generated_frame"))
            seen = set()
            unsafe = False
            for candidate, source in candidates:
                template = voice_template(candidate, public_value, event_kind, label, one_line=bool(can_render or opening))
                if not template or template in seen or (source == "generated_frame" and template != candidate):
                    continue
                seen.add(template)
                speech = template.replace("{value}", public_value or "")
                if len(speech) > 280 or speech in rejected_openings:
                    continue
                if role == "participant" and speech == message:
                    repair_reason = "own_words"
                    continue
                if action == "maintain" and speech == previous_words:
                    continue
                prose = template.replace("{value}", "")
                new_number = any(number not in allowed_numbers for number in numbers.findall(prose))
                if opening and public_value:
                    start = template.index("{value}")
                    joins = (start, start + len(public_value))
                    if overlaps_private_text(speech, private, joined_at=joins):
                        return fallback
                    # A digit next to the slot can alter an authorized amount, even if
                    # that digit occurs elsewhere in the source (e.g. "1인").
                    if any(m.start() < j < m.end() for m in numbers.finditer(speech) for j in joins):
                        new_number = True
                if new_number:
                    if opening:
                        if overlaps_private_text(prose, private):
                            return fallback
                        repair_reason = "unsupported_claim"
                        rejected_openings.add(speech)
                        continue
                    unsafe = True
                    continue
                approved_quotes = review_public_prose(generate, prose, persona["instruction"], private)
                if approved_quotes is None:
                    if opening:
                        return fallback
                    unsafe = True
                    continue
                reviews_left -= 1
                verdict = generate(OPENING_REVIEW_PROMPT if opening else FAITHFULNESS_PROMPT,
                                   {"public_message": message, "candidate_speech": speech})
                if supported_speech(verdict, message, speech, action="defend" if opening else action,
                                    value=public_value, label=label, approved_quotes=approved_quotes, opening=opening):
                    return Speech(speech, source)
                if opening:
                    rejected_openings.add(speech)
                    repair_reason = opening_repair_reason(verdict)
                    if not reviews_left:
                        break
                    continue
                if not reviews_left:
                    return fallback
                if not attempt and source == "generated_core":
                    # Reserve the second check for a newly composed core. Keep the optional
                    # full version available if the repair has no eligible candidate.
                    if raw.get("speech") != candidate:
                        deferred_speech = raw.get("speech")
                    break
            if unsafe:
                return fallback
    except ModelError:
        pass
    return fallback


def public_speech(adapter, role, event_kind, persona, message, private, *, topic="", value=None, action=None,
                  public_turn_memory=None):
    return render_speech(adapter, role, event_kind, persona, message, private, topic=topic, value=value,
                         action=action, public_turn_memory=public_turn_memory).text
