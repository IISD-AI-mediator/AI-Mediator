"""Run from the repository root with Python, Playwright and installed Chrome."""

import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_group_travel import MemberResponses, MediatorResponses
from test_room_recovery import QuietRequests
from travel_app import create_app


def create_form(page, base, name):
    page.goto(base)
    create = page.get_by_role("button", name=re.compile("여행방 만들기"))
    create.click()
    expect(page.get_by_text(re.compile("팀 개설 코드"))).to_have_count(0)
    page.get_by_label("내 닉네임").fill(name)
    expect(page.get_by_label("총인원")).to_have_value("2")
    return create


def room_state(page, endpoint):
    response = page.request.get(endpoint)
    assert response.ok
    return response.json()


def expect_heading(page, name):
    expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()


def wait_for_polls(page, endpoint):
    # The second scheduled GET proves that the first refresh finished rendering.
    for _ in range(2):
        response = page.wait_for_event("response", predicate=lambda r: r.url == endpoint, timeout=10000)
        assert response.ok


def ready(page):
    page.get_by_role("button", name=re.compile("제출 내용 확인")).click()
    page.get_by_role("button", name="준비 완료", exact=True).click()


def join(page):
    page.get_by_label("내 닉네임").fill("동행")
    page.get_by_role("button", name=re.compile("입장하기")).click()
    expect_heading(page, "내 여행 조건")


def check_sharing(browser, base, app):
    context = browser.new_context(viewport={"width": 360, "height": 740})
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    host = context.new_page()
    create_form(host, base, "방장").click()
    expect(host).to_have_url(re.compile(re.escape(base) + r"/r/[A-Za-z0-9_-]{24}/share$"))
    share = host.url
    canonical = share.removesuffix("/share")
    invite = canonical.rsplit("/", 1)[1]
    endpoint = base + "/api/rooms/" + invite
    expect_heading(host, "여행방을 만들었어요")
    host.reload()
    url = host.get_by_role("textbox", name="여행방 초대 링크")
    copy = host.get_by_role("button", name="링크 복사")
    forward = host.get_by_role("link", name="내 여행 조건 입력")
    status = host.locator("main").get_by_role("status")
    expect(url).to_have_value(canonical)
    assert url.evaluate("e => e.readOnly")
    assert host.evaluate("document.documentElement.scrollWidth === innerWidth && innerWidth === 360")
    for control in (url, copy, forward):
        expect(control).to_be_in_viewport()
        host.keyboard.press("Tab")
        expect(control).to_be_focused()
    host.keyboard.press("Enter")
    expect(host).to_have_url(canonical)
    extra = host.get_by_label(re.compile("내 에이전트만 읽는 추가 요청"))
    extra.fill("일요일은 오후에 출발하고 싶어요.")
    host.get_by_role("link", name="초대 링크 공유").click()
    expect(url).to_have_value(canonical)
    host.evaluate("navigator.clipboard.writeText('before-sharing')")
    copy.click()
    expect(status).to_have_text("초대 링크를 복사했어요.")
    copied = host.evaluate("navigator.clipboard.readText()")
    assert copied == canonical
    expect(copy).to_be_focused()
    wait_for_polls(host, endpoint)
    expect(copy).to_be_focused()
    expect(status).to_have_text("초대 링크를 복사했어요.")

    def deny_clipboard(route):
        document = route.fetch()
        route.fulfill(response=document, headers={**document.headers, "permissions-policy": "clipboard-write=()"})

    host.route(share, deny_clipboard, times=1)
    host.reload()
    assert not host.evaluate("document.featurePolicy.allowsFeature('clipboard-write')")
    copy.click()
    fallback = "링크 전체를 선택했어요. 복사해서 공유해 주세요."
    expect(status).to_have_text(fallback)
    expect(url).to_be_focused()
    wait_for_polls(host, endpoint)
    expect(url).to_be_focused()
    assert url.evaluate("e => e.selectionStart === 0 && e.selectionEnd === e.value.length")
    expect(status).to_have_text(fallback)
    forward.click()
    expect(extra).to_have_value("일요일은 오후에 출발하고 싶어요.")
    print("PASS 360px, keyboard, retained draft, real clipboard, denied fallback and polling")

    guest = browser.new_context().new_page()
    guest.goto(share)
    expect(guest).to_have_url(copied)
    expect_heading(guest, "여행방에 초대됐어요.")
    assert room_state(guest, endpoint)["member"] is None
    guest.goto(copied)
    expect(guest.get_by_text("입장 1/2명", exact=True)).to_be_visible()
    join(guest)
    for page, seat in ((host, 1), (guest, 2)):
        state = room_state(page, endpoint)
        assert (state["invite"], state["member"]["seat"], state["joined"]) == (invite, seat, 2)
    visitor = browser.new_context().new_page()
    visitor.goto(copied)
    expect(visitor.get_by_role("button", name="입장이 마감됐어요")).to_be_disabled()
    ready(host)
    expect_heading(host, "친구들을 기다려요.")
    expect(host.get_by_text(re.compile("입장 2/2명.*준비 1/2명"))).to_be_visible()
    host.get_by_role("link", name="초대 링크 공유").click()
    host.get_by_role("link", name="대기 화면으로").click()
    expect(host).to_have_url(copied)
    expect_heading(host, "친구들을 기다려요.")
    ready(guest)
    for page in (host, guest):
        page.goto(share)
        expect(page).to_have_url(copied)
        expect_heading(page, "여행을 조율하고 있어요.")
    app.extensions["travel_workflow"].compiled.invoke({"invite": invite}, {"recursion_limit": 240})
    for page in (host, guest):
        page.goto(share)
        expect(page).to_have_url(copied)
        expect_heading(page, "최종 여행안")
        assert room_state(page, endpoint)["mode"] == "done"
    visitor.goto(base + "/r/missing/share")
    expect_heading(visitor, "여행방을 찾지 못했어요.")
    visitor.get_by_role("button", name="처음으로").click()
    expect(visitor).to_have_url(base + "/")
    assert visitor.goto(base + "/r/bad%24/share").status == 404
    print("PASS guest join from copied URL, full room, host waiting, both active/result routes, missing room")
    for page in (visitor, guest, host):
        page.context.close()


def check_recovery(browser, base, app):
    host = browser.new_context().new_page()
    create = create_form(host, base, "다시 여는 방장")
    bodies, invites = [], []

    def disrupt(route):
        bodies.append(route.request.post_data_json)
        response = route.fetch()
        assert response.ok
        invites.append(response.json()["invite"])
        if len(invites) == 1:
            route.abort("connectionreset")
        elif len(invites) == 2:
            route.fulfill(response=response, json={"invite": "bad/value"})
        else:
            route.fulfill(response=response)

    host.route(base + "/api/rooms", disrupt)
    for failure in ("연결을 확인해 주세요", "초대 링크를 받지 못했어요"):
        create.click()
        expect(host.get_by_role("alert")).to_contain_text(failure)
        expect(host.get_by_label("내 닉네임")).to_have_value("다시 여는 방장")
        expect(create).to_be_enabled()
        host.context.clear_cookies()
    create.click()
    expect_heading(host, "여행방을 만들었어요")
    assert len(invites) == 3 and len(set(invites)) == 1
    assert bodies[0] == bodies[1] == bodies[2] and bodies[0]["request_id"]
    invite = invites[0]
    canonical = base + "/r/" + invite
    share = canonical + "/share"
    endpoint = base + "/api/rooms/" + invite
    expect(host).to_have_url(share)
    assert room_state(host, endpoint)["member"]["seat"] == 1
    with app.extensions["travel_store"].connection() as db:
        assert db.execute("SELECT COUNT(*) FROM travel_rooms").fetchone()[0] == 2
    host.route(endpoint, lambda route: route.abort("connectionreset"), times=1)
    host.reload()
    expect(host.get_by_text(re.compile("다시 연결되면 여행방을 복원해요"))).to_be_visible()
    expect(host.get_by_role("textbox", name="여행방 초대 링크")).to_have_value(canonical)

    guest = browser.new_context().new_page()
    guest.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    guest.goto(canonical)
    join(guest)
    ready(guest)
    expect_heading(guest, "친구들을 기다려요.")
    guest.goto(share)
    expect(guest).to_have_url(canonical)
    expect_heading(guest, "친구들을 기다려요.")
    guest.get_by_role("button", name="링크 복사").click()
    expect(guest.locator("main").get_by_role("status")).to_have_text("초대 링크를 복사했어요.")
    assert guest.evaluate("navigator.clipboard.readText()") == canonical
    print("PASS committed create retried after lost and malformed replies, GET recovery, ready guest copy")
    guest.context.close()
    host.context.close()


def main():
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, ROOM_CREATE_CODE="old-code"):
        app = create_app({"DATABASE_URL": str(Path(folder) / "rooms.sqlite"), "GEMINI_API_KEY": "",
                          "START_WORKER": False, "COOKIE_SECURE": False},
                         member_model=MemberResponses(), mediator_model=MediatorResponses())
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietRequests)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome")
                base = f"http://127.0.0.1:{server.server_port}"
                print("Chrome", browser.version)
                check_sharing(browser, base, app)
                check_recovery(browser, base, app)
                browser.close()
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    main()
