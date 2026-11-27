import os
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from travel_app import create_app


class PublicRoomCreationTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"ROOM_CREATE_CODE": "old-deployment-value"}))
        self.config = {"DATABASE_URL": str(Path(folder) / "rooms.sqlite"), "START_WORKER": False,
                       "ROOM_LIMIT": 2, "COOKIE_SECURE": False}
        self.app = create_app(self.config)
        self.body = {"name": "방장", "capacity": 2, "request_id": secrets.token_hex(24)}

    def test_retry_recovers_same_room_and_host_cookie_without_a_creation_code(self):
        clients = [self.app.test_client() for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: client.post("/api/rooms", json=self.body), clients))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        invite = responses[0].get_json()["invite"]
        self.assertRegex(invite, r"^[A-Za-z0-9_-]{24}$")
        path = "/api/rooms/" + invite
        for client, response in zip(clients, responses):
            self.assertEqual(response.get_json(), {"invite": invite})
            cookie = client.get_cookie("travel_member", path=path)
            self.assertTrue(cookie.http_only)
            self.assertEqual(cookie.same_site, "Lax")
            state = client.get(path).get_json()
            self.assertEqual((state["joined"], state["member"]["seat"]), (1, 1))
        self.assertEqual(clients[0].post("/api/rooms", json={**self.body, "name": "다른 이름"}).status_code, 409)

        other = self.app.test_client()
        second = other.post("/api/rooms", json={**self.body, "request_id": secrets.token_hex(24)})
        self.assertEqual(second.status_code, 200)
        second_invite = second.get_json()["invite"]
        self.assertNotEqual(invite, second_invite)
        self.assertIsNone(clients[0].get("/api/rooms/" + second_invite).get_json()["member"])
        self.assertIsNone(other.get(path).get_json()["member"])
        self.assertEqual(other.post(path + "/ready", json={}).status_code, 403)
        self.assertEqual(other.post("/api/rooms", json={**self.body, "request_id": secrets.token_hex(24)}).status_code, 429)
        self.assertEqual(clients[0].post("/api/rooms", json=self.body).get_json(), {"invite": invite})

    def test_opening_either_share_or_guest_link_keeps_visitor_separate_from_host(self):
        host, guest = self.app.test_client(), self.app.test_client()
        invite = host.post("/api/rooms", json=self.body).get_json()["invite"]
        entry, state = "/r/" + invite, "/api/rooms/" + invite
        for path in (entry + "/share", entry):
            response = guest.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Set-Cookie", response.headers)
            self.assertIsNone(guest.get(state).get_json()["member"])
        self.assertEqual(guest.post(state + "/join", json={"name": "친구", "request_id": secrets.token_hex(24)}).status_code, 200)
        self.assertEqual(host.get(state).get_json()["member"]["seat"], 1)
        self.assertEqual(guest.get(state).get_json()["member"]["seat"], 2)
        self.assertFalse(self.app.test_client().get(state).get_json()["can_join"])

    def test_public_create_validates_input_and_origin_before_writing(self):
        client = self.app.test_client()
        for payload, field in [({}, "request_id"), ({**self.body, "name": ""}, "name"),
                               ({**self.body, "capacity": 9}, "capacity")]:
            with self.subTest(field=field):
                response = client.post("/api/rooms", json=payload)
                self.assertEqual((response.status_code, response.get_json()["field"]), (400, field))
        self.assertEqual(client.post("/api/rooms", json=self.body,
                                     headers={"Origin": "https://other.example"}).status_code, 403)
        with self.app.extensions["travel_store"].connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM travel_rooms").fetchone()[0], 0)

    def test_render_still_requires_postgres(self):
        with patch.dict(os.environ, {"RENDER": "true"}), self.assertRaisesRegex(RuntimeError, "PostgreSQL"):
            create_app(self.config)
