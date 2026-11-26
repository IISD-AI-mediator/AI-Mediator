"""One short transaction per room update. Both backends persist the same state."""

import copy
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .domain import AGENT_STYLES, MEDIATOR_STYLES, Problem, choice, conditions, plain, profile, request_key


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False))


def credential(invite, key):
    # The client's pre-generated 128-bit retry key is also a one-use recovery capability.
    return digest("travel-member/v1|" + invite + "|" + key)


def new_member(invite, key, name, seat, signature):
    return {"seat": seat, "name": name, "join_hash": digest(key), "signature": signature,
            "session_hash": digest(credential(invite, key)), "ready": False,
            "profile": None, "notes": [], "handled": 0}


def member_for(room, token):
    hashed = digest(token) if token else ""
    for member in room["members"]:
        if secrets.compare_digest(member["session_hash"], hashed):
            return member
    return None


def require_member(room, token):
    member = member_for(room, token)
    if not member:
        raise Problem("이 방에 입장한 브라우저에서 다시 열어 주세요.", 403)
    return member


def event(room, kind, actor, text, topic=""):
    room["events"].append({"id": len(room["events"]) + 1, "kind": kind, "speaker": actor,
                           "text": text, "topic": topic, "round": room["round"], "at": time.time()})


def wakeup(room):
    if room["mode"] in ("waiting", "done", "error"):
        return None
    return max(room["next_at"], room["lease"]["until"] if room["lease"] else 0)


class Store:
    def __init__(self, location, *, room_limit=20, lease_seconds=420):
        self.postgres = location.startswith(("postgresql://", "postgres://"))
        if "://" in location and not self.postgres:
            raise RuntimeError("DATABASE_URL에는 PostgreSQL 연결 주소를 설정해 주세요.")
        self.location = location
        self.room_limit = room_limit
        self.lease_seconds = lease_seconds
        if not self.postgres:
            Path(location).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if not self.postgres:
                db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS travel_rooms (invite TEXT PRIMARY KEY, create_hash TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, wakeup DOUBLE PRECISION)")
            db.execute("CREATE INDEX IF NOT EXISTS travel_due ON travel_rooms(wakeup)")
            db.execute("CREATE TABLE IF NOT EXISTS travel_creation_lock (id INTEGER PRIMARY KEY)")
            db.execute("INSERT INTO travel_creation_lock (id) VALUES (1) ON CONFLICT(id) DO NOTHING")
            db.commit()

    @contextmanager
    def connection(self):
        if self.postgres:
            import psycopg
            db = psycopg.connect(self.location, connect_timeout=10)
        else:
            db = sqlite3.connect(self.location, timeout=15, isolation_level=None)
        try:
            yield db
        finally:
            db.close()

    def execute(self, db, query, args=()):
        return db.execute(query.replace("?", "%s") if self.postgres else query, args)

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            try:
                db.execute("BEGIN" if self.postgres else "BEGIN IMMEDIATE")
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def load(self, db, invite, *, lock=False):
        suffix = " FOR UPDATE" if lock and self.postgres else ""
        row = self.execute(db, "SELECT payload FROM travel_rooms WHERE invite=?" + suffix, (invite,)).fetchone()
        if not row:
            raise Problem("초대 링크에 해당하는 방을 찾을 수 없어요.", 404)
        return json.loads(row[0])

    def read(self, invite):
        with self.connection() as db:
            return self.load(db, invite)

    def update(self, invite, change):
        with self.transaction() as db:
            room = self.load(db, invite, lock=True)
            result = change(room)
            self.execute(db, "UPDATE travel_rooms SET payload=?, wakeup=? WHERE invite=?",
                         (json.dumps(room, ensure_ascii=False), wakeup(room), invite))
            return result

    def create(self, data):
        key = request_key(data.get("request_id"))
        name = plain(data.get("name"), 24, "name")
        size = data.get("capacity")
        if type(size) is not int or not 2 <= size <= 8:
            raise Problem("방장 포함 2~8명으로 정해 주세요.", field="capacity")
        fixed = conditions(data.get("fixed", {}))
        mediator = choice(data.get("mediator", MEDIATOR_STYLES[0]), MEDIATOR_STYLES, "mediator")
        sig = fingerprint([name, size, fixed, mediator])
        with self.transaction() as db:
            if self.postgres:
                db.execute("SELECT id FROM travel_creation_lock WHERE id=1 FOR UPDATE")
            row = self.execute(db, "SELECT invite,payload FROM travel_rooms WHERE create_hash=?", (digest(key),)).fetchone()
            if row:
                if json.loads(row[1])["members"][0]["signature"] != sig:
                    raise Problem("같은 전송 번호로 다른 방을 만들 수 없어요.", 409)
                return row[0], credential(row[0], key)
            if db.execute("SELECT count(*) FROM travel_rooms").fetchone()[0] >= self.room_limit:
                raise Problem("현재 팀의 시험용 방 개설 한도에 도달했어요.", 429)
            invite = secrets.token_urlsafe(18)
            room = {"invite": invite, "capacity": size, "fixed": fixed, "mediator": mediator,
                    "seats": list(range(1, size + 1)), "members": [new_member(invite, key, name, 1, sig)],
                    "mode": "waiting", "step": "team", "revision": 0, "round": 0,
                    "next_at": 0, "lease": None, "attempts": 0, "retries": 0, "error": None,
                    "events": [], "history": [], "proposals": {}, "result": None, "floor": None}
            self.execute(db, "INSERT INTO travel_rooms(invite,create_hash,payload,wakeup) VALUES(?,?,?,NULL)",
                         (invite, digest(key), json.dumps(room, ensure_ascii=False)))
        return invite, credential(invite, key)

    def join(self, invite, data, current):
        key = request_key(data.get("request_id"))
        name = plain(data.get("name"), 24, "name")

        def join_room(room):
            for member in room["members"]:
                if secrets.compare_digest(member["join_hash"], digest(key)):
                    if name != member["name"]:
                        raise Problem("같은 전송 번호로 다른 이름을 등록할 수 없어요.", 409)
                    return credential(invite, key)
            if member_for(room, current):
                return current
            if room["mode"] != "waiting" or len(room["members"]) >= room["capacity"]:
                raise Problem("정원이 차서 입장이 마감됐어요.", 409)
            if any(m["name"].casefold() == name.casefold() for m in room["members"]):
                raise Problem("방에서 이미 사용하는 이름이에요.", 409, "name")
            room["members"].append(new_member(invite, key, name, len(room["members"]) + 1, fingerprint(name)))
            return credential(invite, key)

        return self.update(invite, join_room)

    def ready(self, invite, token, data):
        def submit(room):
            member = require_member(room, token)
            submitted = profile(data, room["fixed"])
            if member["ready"]:
                if submitted != member["profile"]:
                    raise Problem("이미 준비를 마쳤어요. 제출한 조건을 확인해 주세요.", 409)
                return
            member["profile"], member["ready"] = submitted, True
            if len(room["members"]) == room["capacity"] and all(m["ready"] for m in room["members"]):
                room["mode"], room["round"] = "negotiating", 1
                event(room, "phase", "중재자", "모두 준비됐어요. 각자의 에이전트가 조건을 살펴봅니다.")
        self.update(invite, submit)

    def note(self, invite, token, data):
        key = request_key(data.get("request_id"))
        text = plain(data.get("text"), 400, "text")

        def accept(room):
            member = require_member(room, token)
            for existing in member["notes"]:
                if existing["key"] == key:
                    if text != existing["text"]:
                        raise Problem("같은 전송 번호에는 같은 지시만 보낼 수 있어요.", 409)
                    return existing["seq"]
            floor = room["floor"]
            if room["mode"] != "fight" or not floor or floor["closed"] or time.time() >= floor["deadline"]:
                raise Problem("이번 회차의 개인 지시가 마감됐어요.", 409)
            if sum(n["round"] == room["round"] for n in member["notes"]) >= 4:
                raise Problem("이번 회차에는 한 사람당 지시를 4개까지 보낼 수 있어요.", 429)
            seq = len(member["notes"]) + 1
            member["notes"].append({"seq": seq, "key": key, "text": text, "round": room["round"]})
            if room["step"] == "floor":
                room["next_at"] = 0
            return seq
        return self.update(invite, accept)

    def due(self):
        with self.connection() as db:
            return [row[0] for row in self.execute(db, "SELECT invite FROM travel_rooms WHERE wakeup<=? ORDER BY wakeup LIMIT 12", (time.time(),))]

    def claim(self, invite):
        def acquire(room):
            now = time.time()
            due_at = wakeup(room)
            if due_at is None or due_at > now:
                return None
            floor = room["floor"]
            if room["mode"] == "fight" and floor and not floor["closed"] and now >= floor["deadline"]:
                floor["closed"] = True
                floor["cutoff"] = {str(m["seat"]): len(m["notes"]) for m in room["members"]}
            room["lease"] = {"id": secrets.token_hex(16), "until": now + self.lease_seconds,
                             "revision": room["revision"], "step": room["step"]}
            return copy.deepcopy(room)
        return self.update(invite, acquire)

    def complete(self, snapshot, apply):
        def commit(room):
            if (room["lease"] != snapshot["lease"] or not room["lease"] or
                    room["lease"]["until"] <= time.time() or room["revision"] != snapshot["revision"] or
                    room["step"] != snapshot["step"]):
                return False
            room["lease"], room["next_at"] = None, 0
            apply(room)
            room["revision"] += 1
            return True
        return self.update(snapshot["invite"], commit)

    def retry(self, invite, token):
        def resume(room):
            require_member(room, token)
            if room["mode"] != "error":
                raise Problem("재시도할 오류가 없어요.", 409)
            if room["retries"] >= 3:
                raise Problem("이 방의 수동 재시도 한도에 도달했어요.", 429)
            room["retries"] += 1
            room["mode"] = room["resume_mode"]
            room["attempts"], room["error"], room["next_at"] = 0, None, 0
        self.update(invite, resume)


def view(room, token):
    me = member_for(room, token)
    public = {"invite": room["invite"], "capacity": room["capacity"], "fixed": room["fixed"],
              "mediator": room["mediator"], "joined": len(room["members"]),
              "ready": sum(m["ready"] for m in room["members"]), "member": None}
    if not me:
        public["can_join"] = room["mode"] == "waiting" and public["joined"] < room["capacity"]
        return public
    public.update({key: room[key] for key in ("mode", "round", "events", "history", "result", "error")})
    public["members"] = [{k: m[k] for k in ("seat", "name", "ready")} for m in room["members"]]
    public["member"] = {k: me[k] for k in ("seat", "name", "ready", "profile")}
    public["member"]["notes"] = [
        {"seq": n["seq"], "text": n["text"], "round": n["round"], "handled": n["seq"] <= me["handled"]}
        for n in me["notes"]]
    floor = room["floor"]
    public["floor"] = None if not floor else {"deadline": floor["deadline"], "topic": floor["topic"],
        "open": room["mode"] == "fight" and not floor["closed"] and time.time() < floor["deadline"]}
    public["can_retry"] = room["mode"] == "error" and room["retries"] < 3
    return public
