import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from web import create_app


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("test-password")

    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-session-secret",
                               "PASSWORD_HASH": self.password_hash,
                               "SESSION_COOKIE_SECURE": False})
        self.client = self.app.test_client()

    def csrf(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            return session["csrf"]

    def login(self):
        return self.client.post("/login", data={"csrf": self.csrf(), "username": "leadsicon", "password": "test-password"})

    def test_wrong_username_rejected(self):
        response = self.client.post("/login", data={"csrf": self.csrf(), "username": "other", "password": "test-password"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_private_routes_require_login(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/ads").status_code, 302)
        self.assertEqual(self.client.post("/api/runs", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/runs/private-id").status_code, 401)

    def test_login_and_logout(self):
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn(b'UGC Studio', self.client.get("/").data)
        self.assertEqual(self.client.get("/ads").status_code, 200)
        with self.client.session_transaction() as session:
            token = session["csrf"]
        self.client.post("/logout", data={"csrf": token})
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_wrong_password_and_rate_limit(self):
        token = self.csrf()
        for _ in range(10):
            self.assertEqual(self.client.post("/login", data={"csrf": token, "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/login", data={"csrf": token, "password": "wrong"}).status_code, 429)

    def test_csrf_blocks_run(self):
        self.login()
        with patch("web.ApifyClient.request") as request:
            self.assertEqual(self.client.post("/api/runs", json={}).status_code, 403)
            request.assert_not_called()

    def test_apify_start_poll_and_ownership(self):
        self.login()
        with self.client.session_transaction() as session:
            token = session["csrf"]
        with patch.dict("os.environ", {"APIFY_TOKEN": "test-token", "APIFY_FACEBOOK_ACTOR": "owner/actor"}), patch("web.ApifyClient.request", side_effect=[
            {"data": {"id": "r1", "status": "RUNNING"}},
            {"data": {"id": "r1", "status": "SUCCEEDED", "defaultDatasetId": "d1"}},
            [{"ad": "example"}],
        ]) as request:
            response = self.client.post("/api/runs", json={"platform": "facebook", "input": {"query": "test"}}, headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.client.get("/api/runs/r1").json["items"], [{"ad": "example"}])
            self.assertEqual(self.client.get("/api/runs/other").status_code, 404)
            self.assertEqual(request.call_count, 3)

    def test_secure_cookie_default_and_missing_config(self):
        app = create_app({"SECRET_KEY": "test", "PASSWORD_HASH": self.password_hash, "SESSION_COOKIE_SECURE": True})
        cookie = app.test_client().get("/login").headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)
        with self.assertRaises(RuntimeError):
            create_app({"SECRET_KEY": None, "PASSWORD_HASH": None})


if __name__ == "__main__":
    unittest.main()
