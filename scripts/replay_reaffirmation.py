"""Exercise the same approved budget twice with real Gemini speech and a fresh worker.

The initial topics and second negotiation action are fixed to reproduce TURN-03.
Pass --openings-only to verify the original opening topics, or --openings-only activities
to exercise the museum offer observed in the first OPEN-04 room.
Run replay_gemini_room.py separately for the uncontrolled end-to-end scenario.
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from replay_gemini_room import ROOT, create_app, prompts, verify_opening
from travel_app.models import Gemini
from travel_app.store import event


class OpeningPositions:
    """Only the pre-speech proposal data is controlled in this diagnostic."""

    def __init__(self, host_topic):
        self.host_topic = host_topic

    def invoke(self, inputs, config):
        answers = []
        for packet in inputs["packets"]:
            seat = packet["seat"]
            answers.append({"seat": seat, "focus": self.host_topic if seat == 1 else "local_transport",
                            "stance": "defend", "values": packet["profile"]["preferences"],
                            "evidence": [], "search_context": {}, "accepted": {}, "overrides": []})
        return {"answers": answers}


def configured(db_path):
    return create_app({"DATABASE_URL": db_path, "START_WORKER": False,
                       "COOKIE_SECURE": False})


def worker(options):
    app = configured(options["database"])
    flow = app.extensions["travel_workflow"]
    store = app.extensions["travel_store"]
    stage, invite = options["stage"], options["invite"]
    model = flow.member
    assert type(model) is Gemini and model.key
    names = {v: k for k, v in vars(prompts).items() if k.endswith("_PROMPT") and isinstance(v, str)}
    send = model._generate
    calls = []

    def observe(instruction, data, search, max_tokens, timeout):
        rec = {"prompt": names[instruction], "request": data}
        calls.append(rec)
        before = time.monotonic()
        try:
            rec["response"] = send(instruction, data, search, max_tokens, timeout)
            return rec["response"]
        finally:
            rec["seconds"] = round(time.monotonic() - before, 3)

    model._generate = observe
    controlled = {}
    if stage == "propose":
        flow.panel = OpeningPositions(options["host_topic"])
        store.update(invite, lambda room: room.update(step="propose", next_at=0))
    else:
        def return_budget_action(instruction, data, *, search=False):
            assert instruction == prompts.DEBATE_PROMPT
            controlled["debate_input"] = data
            return {"focus": "budget", "stance": "defend", "choice": 0, "new_value": None,
                    "priority": None, "authorized_note_seq": None, "searches": [], "search_context": {}}

        model.generate = return_budget_action  # generate_voice still calls the real HTTPS adapter.

        def open_budget_floor(room):
            room.update(mode="fight", step="speak", next_at=0, round=1)
            room["floor"] = {"topic": "budget", "speaker": 1, "round": 1, "queue": [], "closed": False,
                             "deadline": time.time() + 45, "cutoff": {}}
            event(room, "fight", "판사 에이전트", "이번 안건은 1인 예산 상한입니다.", "budget")

        store.update(invite, open_budget_floor)
    flow.bound_node(stage)({"invite": invite})
    snapshot = store.read(invite)
    output = {"stage": stage, "worker_pid": os.getpid(), "model": model.model, "next_step": snapshot["step"],
              "calls": calls, **controlled}
    Path(options["archive"], stage + ".json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf8")
    assert snapshot["step"] == {"propose": "judge", "speak": "floor"}[stage], "Stage did not commit"


def run(*, opening_topic=None):
    data = json.loads((ROOT / "scripts" / "two_person_seoul.json").read_text(encoding="utf8"))
    directory = ROOT / "instance"
    directory.mkdir(exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix="fixed-openings-" if opening_topic else "budget-reaffirm-", dir=directory))
    with tempfile.TemporaryDirectory() as tmp:
        database = str(Path(tmp, "room.sqlite"))
        app = configured(database)
        host, guest = app.test_client(), app.test_client()
        new_room = host.post("/api/rooms", json={"request_id": secrets.token_hex(16), "name": "서윤",
                             "capacity": 2, "fixed": data["fixed"], "mediator": data["judge"]})
        invite = new_room.get_json()["invite"]
        path = "/api/rooms/" + invite
        assert guest.post(path + "/join", json={"name": "민재", "request_id": secrets.token_hex(16)}).status_code < 300
        for name, client in (("서윤", host), ("민재", guest)):
            assert client.post(path + "/ready", json=data[name]).status_code < 300
        for stage in (("propose",) if opening_topic else ("propose", "speak")):
            options = {"stage": stage, "database": database, "invite": invite, "archive": str(archive),
                       "host_topic": opening_topic or "budget"}
            subprocess.run([sys.executable, "-B", "-X", "utf8", __file__, "--worker"],
                           input=json.dumps(options).encode(), check=True)
        views = [client.get(path).get_json() for client in (host, guest)]
        assert [v["member"]["name"] for v in views] == ["서윤", "민재"]
        assert views[0]["events"] == views[1]["events"]
        events = views[0]["events"]
        files = [*sorted((ROOT / "travel_app").glob("*.py")), Path(__file__).resolve(), ROOT / "scripts" / "replay_gemini_room.py",
                 ROOT / "scripts" / "two_person_seoul.json"]
        record = {"views": [v["events"] for v in views], "budget": data["서윤"]["preferences"]["budget"],
                  "hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
        (archive / "public.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
        if opening_topic:
            print("Evidence", archive.name, flush=True)
            openings = [e for e in events if e["kind"] == "proposal"]
            assert len(openings) == 2
            calls = json.loads((archive / "propose.json").read_text(encoding="utf8"))["calls"]
            for (name, topic), published in zip((("서윤", opening_topic), ("민재", "local_transport")), openings):
                verify_opening(name, data[name]["persona"], published, topic, data[name]["preferences"][topic]["value"], calls)
            return
        pair = [e for e in events if e["speaker"] == "서윤의 에이전트" and e["topic"] == "budget"]
        assert len(pair) == 2
        for e in pair:
            print(e["kind"], e.get("voice_source"), e["text"], flush=True)
        print("Evidence", archive.name, flush=True)
        assert pair[0]["text"] != pair[1]["text"], "The same public sentence was repeated"
        stages = [json.loads((archive / f"{stage}.json").read_text(encoding="utf8")) for stage in ("propose", "speak")]
        assert stages[0]["worker_pid"] != stages[1]["worker_pid"], "Expected a fresh worker"
        for turn, result, act in zip(pair, stages, ("defend", "maintain")):
            assert turn.get("voice_source") in ("generated", "generated_core", "generated_frame"), "A fallback supplied the public sentence"
            review_prompt = "OPENING_REVIEW_PROMPT" if turn["kind"] == "proposal" else "FAITHFULNESS_PROMPT"
            assert any(call["prompt"] == review_prompt
                       and call["request"]["candidate_speech"] == turn["text"]
                       and call["response"].get("faithful") is True
                       and call["response"]["actions"]["candidate"]["kind"] == act
                       for call in result["calls"]), f"Missing real semantic review for {act}"
        previous = stages[1]["debate_input"]["public_turn_memory"]["previous_own"]
        assert previous == {"act": "defend", "topic": "budget", "value": record["budget"]["value"], "speech": pair[0]["text"]}


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker(json.load(sys.stdin))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--openings-only", nargs="?", const="budget", choices=("budget", "activities"))
        run(opening_topic=parser.parse_args().openings_only)
