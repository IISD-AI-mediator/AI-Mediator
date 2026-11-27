import hmac
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .domain import AGENT_STYLES, CURRENCIES, FIELDS, MEDIATOR_STYLES, Problem
from .graph import Workflow
from .models import Gemini
from .runner import Runner
from .store import Store, view


def create_app(config=None, *, member_model=None, mediator_model=None):
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=32768, DATABASE_URL=os.environ.get("DATABASE_URL") or os.environ.get("TRAVEL_DB_PATH") or str(Path(app.instance_path) / "travel.sqlite3"),
        GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", ""), MEMBER_MODEL=os.environ.get("MEMBER_MODEL", "gemini-3.1-flash-lite"),
        MEDIATOR_MODEL=os.environ.get("MEDIATOR_MODEL", "gemini-3.8-flash"), ROOM_CREATE_CODE=os.environ.get("ROOM_CREATE_CODE", ""),
        ROOM_LIMIT=int(os.environ.get("ROOM_LIMIT", "20")), FIGHT_SECONDS=int(os.environ.get("FIGHT_SECONDS", "45")),
        MAX_FIGHTS=2, START_WORKER=True, COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1")
    if config:
        app.config.update(config)
    c = app.config
    if os.environ.get("RENDER") and (not c["ROOM_CREATE_CODE"] or not c["DATABASE_URL"].startswith(("postgresql://", "postgres://"))):
        raise RuntimeError("Render의 ROOM_CREATE_CODE와 지속 저장용 PostgreSQL DATABASE_URL을 설정해 주세요.")
    if c["MEMBER_MODEL"] == c["MEDIATOR_MODEL"]:
        raise RuntimeError("개인 에이전트와 판사 에이전트에 서로 다른 Gemini 모델을 설정해 주세요.")
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip() or "development"
    except FileNotFoundError:
        version = "development"
    release = {"status": "ok", "version": version}
    revision = os.environ.get("RENDER_GIT_COMMIT", "")
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
        release["revision"] = revision
    store = Store(c["DATABASE_URL"], room_limit=c["ROOM_LIMIT"])
    member = member_model or Gemini(c["GEMINI_API_KEY"], c["MEMBER_MODEL"])
    mediator = mediator_model or Gemini(c["GEMINI_API_KEY"], c["MEDIATOR_MODEL"])
    flow = Workflow(store, member, mediator, fight_seconds=c["FIGHT_SECONDS"], max_fights=c["MAX_FIGHTS"])
    runner = Runner(store, flow.compiled)
    app.extensions.update(travel_store=store, travel_workflow=flow, travel_runner=runner)
    if c["START_WORKER"]:
        runner.thread.start()

    @app.before_request
    def protect():
        if request.method == "POST":
            if not request.is_json:
                raise Problem("JSON 형식의 요청이 필요해요.", 415)
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc.casefold() != request.host.casefold():
                raise Problem("이 여행방에서 연 화면을 이용해 주세요.", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-src 'self' about:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if request.path.startswith(("/api/", "/r/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Problem)
    def known_error(error):
        return jsonify(error=str(error), field=error.field), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            message = {400: "요청 본문을 다시 확인해 주세요.", 413: "보낼 수 있는 입력 크기를 초과했어요."}.get(error.code, "요청 경로를 확인해 주세요.")
            return jsonify(error=message), error.code
        return error

    def data():
        body = request.get_json()
        if not isinstance(body, dict):
            raise Problem("입력 항목을 다시 확인해 주세요.")
        return body

    def session_token():
        return request.cookies.get("travel_member", "")

    def joined(invite, token):
        response = jsonify(invite=invite)
        response.set_cookie("travel_member", token, httponly=True, secure=c["COOKIE_SECURE"], samesite="Lax",
                            path=f"/api/rooms/{invite}", max_age=60 * 60 * 24 * 30)
        return response

    @app.get("/healthz")
    def health():
        with store.connection() as db:
            db.execute("SELECT 1").fetchone()
        return jsonify(release)

    @app.get("/")
    @app.get("/r/<invite>")
    def index(invite=None):
        if invite and (len(invite) > 64 or not all(ch.isalnum() or ch in "_-" for ch in invite)):
            abort(404)
        return render_template("index.html", setup={"invite": invite, "fields": FIELDS, "currencies": CURRENCIES,
            "agentStyles": AGENT_STYLES, "mediatorStyles": MEDIATOR_STYLES, "needsCode": bool(c["ROOM_CREATE_CODE"])})

    @app.post("/api/rooms")
    def create():
        body = data()
        code = body.get("team_code", "")
        if c["ROOM_CREATE_CODE"] and (not isinstance(code, str) or not hmac.compare_digest(code.encode(), c["ROOM_CREATE_CODE"].encode())):
            raise Problem("팀에서 공유한 방 개설 코드를 확인해 주세요.", 403, "team_code")
        created = store.create(body)
        runner.wake.set()
        return joined(*created)

    @app.get("/api/rooms/<invite>")
    def state(invite):
        return jsonify(view(store.read(invite), session_token()))

    @app.post("/api/rooms/<invite>/join")
    def join(invite):
        return joined(invite, store.join(invite, data(), session_token()))

    @app.post("/api/rooms/<invite>/ready")
    def ready(invite):
        store.ready(invite, session_token(), data())
        runner.wake.set()
        return jsonify(ok=True)

    @app.post("/api/rooms/<invite>/notes")
    def note(invite):
        number = store.note(invite, session_token(), data())
        runner.wake.set()
        return jsonify(seq=number)

    @app.post("/api/rooms/<invite>/retry")
    def retry(invite):
        data()
        store.retry(invite, session_token())
        runner.wake.set()
        return jsonify(ok=True)

    return app
