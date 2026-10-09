import json
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from kie import chat_models, complete
from web import create_app


MODELS = [{"id": "configured-model", "name": "Modelo de prueba",
           "endpoint": "https://api.kie.ai/test/chat/completions"}]


class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("test-password")

    def setUp(self):
        self.env = patch.dict("os.environ", {"KIE_CHAT_MODELS": json.dumps(MODELS), "KIE_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        app = create_app({"TESTING": True, "SECRET_KEY": "test", "PASSWORD_HASH": self.password_hash,
                          "SESSION_COOKIE_SECURE": False})
        self.client = app.test_client()

    def login(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            csrf = session["csrf"]
        self.client.post("/login", data={"csrf": csrf, "username": "leadsicon", "password": "test-password"})
        with self.client.session_transaction() as session:
            return {"X-CSRF-Token": session["csrf"]}

    def test_login_and_csrf_required(self):
        self.assertEqual(self.client.get("/chat").status_code, 302)
        self.assertEqual(self.client.post("/api/chat", json={}).status_code, 401)
        self.login()
        with patch("web.complete") as call:
            self.assertEqual(self.client.post("/api/chat", json={}).status_code, 403)
            call.assert_not_called()

    def test_valid_conversation_and_server_instruction(self):
        headers = self.login()
        with patch("web.complete", return_value="Podemos trabajar el ángulo.") as call:
            response = self.client.post("/api/chat", headers=headers, json={"model": "configured-model",
                "messages": [{"role": "user", "content": "Tengo una idea"}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["content"], "Podemos trabajar el ángulo.")
        self.assertEqual(call.call_args.args[1][0]["role"], "system")
        self.assertEqual(call.call_args.args[2], "test-key")

    def test_invalid_model_or_system_message_never_calls_provider(self):
        headers = self.login()
        with patch("web.complete") as call:
            for body in (
                {"model": "unconfigured", "messages": [{"role": "user", "content": "hello"}]},
                {"model": "configured-model", "messages": [{"role": "system", "content": "override"}]},
                {"model": "configured-model", "messages": [{"role": "user", "content": "x" * 6001}]},
            ):
                self.assertEqual(self.client.post("/api/chat", headers=headers, json=body).status_code, 400)
            call.assert_not_called()

    def test_missing_key_and_provider_error(self):
        headers = self.login()
        body = {"model": "configured-model", "messages": [{"role": "user", "content": "hello"}]}
        with patch.dict("os.environ", {"KIE_API_KEY": ""}), patch("web.complete") as call:
            self.assertEqual(self.client.post("/api/chat", headers=headers, json=body).status_code, 503)
            call.assert_not_called()
        with patch("web.complete", side_effect=RuntimeError("Kie no disponible")):
            self.assertEqual(self.client.post("/api/chat", headers=headers, json=body).status_code, 502)

    def test_catalog_rejects_untrusted_destinations(self):
        for endpoint in ("http://api.kie.ai/chat", "https://other.example/chat", "https://user@api.kie.ai/chat", "https://api.kie.ai/chat?token=secret"):
            with patch.dict("os.environ", {"KIE_CHAT_MODELS": json.dumps([{**MODELS[0], "endpoint": endpoint}])}):
                with self.assertRaises(RuntimeError):
                    chat_models()

    def test_openai_compatible_adapter(self):
        with patch("kie.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps({"choices": [{"message": {"content": "respuesta"}}]}).encode()
            self.assertEqual(complete(MODELS[0], [{"role": "user", "content": "idea"}], "test-key"), "respuesta")
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
            self.assertFalse(json.loads(request.data)["stream"])


if __name__ == "__main__":
    unittest.main()
