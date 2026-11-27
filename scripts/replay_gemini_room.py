"""Replay the Seoul room using the configured live Gemini models and two HTTP sessions.

Run from the project virtual environment. Pass --browser to also open the finished
room in two isolated headless Chrome contexts (requires Playwright and Chrome).
Observations contain only synthetic test inputs and are saved under instance/.
"""

import argparse
import hashlib
import json
import secrets
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from travel_app import create_app, prompts
from travel_app.domain import BY_KEY, display
from travel_app.models import Gemini, ModelError
from travel_app.tone import proposal_message, supported_speech, voice_template


def identity():
    return secrets.token_hex(16)


class SilentRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass  # The room invite is part of the URL.


class Session:
    def __init__(self, base):
        self.base = base
        self.cookies = CookieJar()
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        with self.client.open(req, timeout=12) as response:
            return json.load(response)


def browser_results(sessions, room_path):
    from playwright.sync_api import sync_playwright

    views = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        for session in sessions:
            context = browser.new_context(viewport={"width": 360, "height": 800})
            context.add_cookies([{"name": c.name, "value": c.value, "domain": "127.0.0.1",
                                  "path": c.path, "httpOnly": True} for c in session.cookies])
            page = context.new_page()
            page.goto(session.base + room_path, wait_until="domcontentloaded")
            page.get_by_role("heading", name="항목별 결정과 이유").wait_for()
            summaries = page.locator("main details > summary")
            for summary in summaries.all():
                if summary.is_visible() and not summary.evaluate("el => el.parentElement.open"):
                    summary.focus()
                    summary.press("Enter")
                    assert summary.evaluate("el => el.parentElement.open")
            views.append({
                "decisions": page.locator(".decision-row").all_inner_texts(),
                "schedule": page.locator("section").filter(has=page.get_by_role("heading", name="날짜별 일정")).last.inner_text(),
                "speakers": page.locator(".chat-log .chat-head strong").all_inner_texts(),
                "speech": page.locator(".chat-log .chat-line > p").all_inner_texts(),
                "overflow": page.evaluate("document.documentElement.scrollWidth > innerWidth"),
            })
            context.close()
        browser.close()
    return views


def verify_opening(name, persona, event, topic, value, calls):
    assert event["speaker"] == name + "의 에이전트" and event["topic"] == topic
    fields = {"generated": "speech", "generated_core": "core_speech", "generated_frame": "opening_frame"}
    assert event.get("voice_source") in fields, f"{name} used {event.get('voice_source')}"
    assert value is not None, f"{name} has no proposal value"
    approved = proposal_message("defend", topic, value)
    public_value, label = display(value), BY_KEY[topic]["label"]
    field = fields[event["voice_source"]]
    generated = []
    reviewed = []
    for index, call in enumerate(calls, 1):
        if not isinstance(call.get("response"), dict):
            continue
        request = call["request"]
        if (call["prompt"] == "OPENING_VOICE_PROMPT" and request.get("event") == "proposal"
                and request.get("persona") == persona and request.get("topic") == label):
            candidate = call["response"].get(field)
            if field == "opening_frame":
                if not isinstance(candidate, dict) or set(candidate) != {"before_value", "after_value"}:
                    continue
                before, after = candidate["before_value"], candidate["after_value"]
                if not isinstance(before, str) or not isinstance(after, str):
                    continue
                published = before + public_value + after
            else:
                template = voice_template(candidate, public_value, "proposal", label, one_line=True)
                published = template.replace("{value}", public_value) if template else None
            if published == event["text"]:
                generated.append(index)
        if (call["prompt"] == "OPENING_REVIEW_PROMPT" and request.get("public_message") == approved
                and request.get("candidate_speech") == event["text"]
                and supported_speech(call["response"], approved, event["text"], action="defend",
                                     value=public_value, label=label, opening=True)):
            reviewed.append(index)
    assert any(g < v for g in generated for v in reviewed), f"{name} lacks matching real generation and review"
    print(name, event["voice_source"], event["text"], "generation", generated, "review", reviewed, flush=True)


def verify_generated_openings(trace):
    calls = trace["calls"]
    judge = next(call for call in calls if call["prompt"] == "JUDGE_PROMPT")
    opening_calls = [c for c in calls if c["start"] < judge["start"]]
    positions = {p["seat"]: p for p in judge["request"]["proposals"]}
    openings = [e for e in trace["events"] if e["kind"] == "proposal"]
    assert len(openings) == len(trace["sessions"]) == 2
    for seat, (name, event) in enumerate(zip(trace["sessions"], openings), 1):
        position = positions[seat]
        topic = position["focus"]
        value = position["values"].get(topic, {}).get("value", trace["scenario"]["fixed"].get(topic))
        verify_opening(name, trace["scenario"][name]["persona"], event, topic, value, opening_calls)


def run(use_browser, require_generated_openings=False):
    scenario_file = ROOT / "scripts" / "two_person_seoul.json"
    case = json.loads(scenario_file.read_text(encoding="utf8"))
    directory = ROOT / "instance"
    directory.mkdir(exist_ok=True)
    archive = Path(tempfile.mkdtemp(dir=directory, prefix="gemini-replay-"))
    clock = time.monotonic()

    def elapsed():
        return round(time.monotonic() - clock, 2)

    path_list = [*sorted((ROOT / "travel_app").rglob("*.py")), *sorted((ROOT / "travel_app").rglob("*.js")),
                 Path(__file__).resolve(), scenario_file]
    trace = {"started": datetime.now(timezone.utc).isoformat(), "scenario": case, "calls": [],
             "phases": [], "retries": [], "hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                                     for p in path_list}}
    names = {v: k for k, v in vars(prompts).items() if k.endswith("_PROMPT") and isinstance(v, str)}
    names.update({v: "SEARCH_" + k for k, v in prompts.SEARCH_PROMPTS.items()})
    lock = threading.RLock()

    def save():
        with lock:
            temporary = archive / "trace.tmp"
            temporary.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf8")
            temporary.replace(archive / "trace.json")

    def observe(model):
        assert type(model) is Gemini and model.key, "Configure the real Gemini adapters before running."
        send = model._generate

        def record(instruction, data, search, max_tokens, timeout):
            rec = {"prompt": names.get(instruction, "other"), "model": model.model, "request": data,
                   "start": elapsed(), "timeout": timeout, "output_limit": max_tokens}
            with lock:
                trace["calls"].append(rec)
            try:
                result = send(instruction, data, search, max_tokens, timeout)
                if search:
                    meta = result.get("groundingMetadata", {})
                    observed = {"queries": meta.get("webSearchQueries", []), "chunks": len(meta.get("groundingChunks", []))}
                else:
                    observed = result
                with lock:
                    rec["response"] = observed
                return result
            except ModelError as error:
                with lock:
                    rec["error"] = str(error)
                raise
            finally:
                with lock:
                    rec["end"] = elapsed()
                    save()
                    print(elapsed(), rec["prompt"], rec.get("error", "OK"), flush=True)

        model._generate = record

    with tempfile.TemporaryDirectory() as database:
        app = create_app({"DATABASE_URL": str(Path(database) / "test.sqlite"),
                          "COOKIE_SECURE": False})
        flow, worker = app.extensions["travel_workflow"], app.extensions["travel_runner"]
        observe(flow.member)
        observe(flow.mediator)
        trace.update(models=[flow.member.model, flow.mediator.model], fight_seconds=flow.fight_seconds)
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=SilentRequests)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        sessions = [Session(f"http://127.0.0.1:{server.server_port}") for _ in range(2)]
        host, guest = sessions
        try:
            print("Run record", archive.name, flush=True)
            trace["health"] = host.request("/healthz")
            invite = host.request("/api/rooms", {"capacity": 2, "name": "서윤", "request_id": identity(),
                                                "fixed": case["fixed"], "mediator": case["judge"]})["invite"]
            path = "/api/rooms/" + invite
            guest.request(path + "/join", {"name": "민재", "request_id": identity()})
            trace["sessions"] = [session.request(path)["member"]["name"] for session in sessions]
            assert trace["sessions"] == ["서윤", "민재"]
            for session, name in zip(sessions, trace["sessions"]):
                session.request(path + "/ready", case[name])
            previous = None
            while elapsed() < 1500:
                state = host.request(path)
                phase = (state["mode"], state["round"], len(state["events"]))
                if phase != previous:
                    previous = phase
                    trace["phases"].append([elapsed(), *phase])
                    trace.update(events=state["events"], history=state["history"])
                    save()
                    print(elapsed(), *phase, flush=True)
                if state["mode"] == "done":
                    other = guest.request(path)
                    trace.update(mode="done", elapsed=elapsed(), result=state["result"], notes=other["member"]["notes"])
                    trace["public_views"] = [{k: s[k] for k in ("result", "events", "history")} for s in (state, other)]
                    trace["participants_match"] = trace["public_views"][0] == trace["public_views"][1]
                    trace["host_sees_only_own_notes"] = state["member"]["notes"] == []
                    trace["note_exact_match_in_public"] = case["guest_note"] in json.dumps(trace["public_views"], ensure_ascii=False)
                    save()
                    assert trace["participants_match"] and trace["host_sees_only_own_notes"] and not trace["note_exact_match_in_public"]
                    assert len(trace["notes"]) == 1 and trace["notes"][0]["handled"]
                    if use_browser:
                        trace["browser"] = browser_results(sessions, "/r/" + invite)
                        save()
                        assert trace["browser"][0] == trace["browser"][1] and not trace["browser"][0]["overflow"]
                        assert trace["browser"][0]["speakers"] == [event["speaker"] for event in state["events"]]
                        assert trace["browser"][0]["speech"] == [event["text"] for event in state["events"]]
                    if require_generated_openings:
                        verify_generated_openings(trace)
                    print("DONE", trace["elapsed"], archive.name, flush=True)
                    break
                if "note_sent" not in trace and state.get("floor") and state["floor"]["open"]:
                    receipt = guest.request(path + "/notes", {"request_id": identity(), "text": case["guest_note"]})
                    trace["note_sent"] = {"seq": receipt["seq"], "round": state["round"], "elapsed": elapsed()}
                if state["mode"] == "error":
                    trace["retries"].append({"at": elapsed(), "error": state["error"]})
                    save()
                    if not state["can_retry"]:
                        raise RuntimeError("Room retry limit reached")
                    time.sleep(8)
                    host.request(path + "/retry", {})
                time.sleep(0.7)
            else:
                raise RuntimeError("Room deadline exceeded")
        finally:
            server.shutdown()
            server.server_close()
            worker.close()
            worker.thread.join(50)
            save()


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--browser", action="store_true")
    arguments.add_argument("--require-generated-openings", action="store_true",
                           help="Verify both published proposals against their Gemini generation and semantic review.")
    options = arguments.parse_args()
    run(options.browser, options.require_generated_openings)
