import unittest
from unittest.mock import patch

from services.register import mail_provider, openai_register


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *args, **kwargs):
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return FakeResponse(data={"success": True})

    def close(self):
        self.closed = True


class FakeProvider:
    name = "fake"
    provider_ref = "fake#1"

    def __init__(self):
        self.deleted = None
        self.closed = False

    def delete_mailbox(self, mailbox):
        self.deleted = mailbox
        return True

    def close(self):
        self.closed = True


class MailProviderCleanupTests(unittest.TestCase):
    def test_moemail_delete_mailbox_calls_delete_endpoint(self):
        session = FakeSession()
        entry = {"api_base": "https://mail.example", "api_key": "key", "domain": ["moemail.app"], "provider_ref": "moemail#1"}
        with patch.object(mail_provider.curl_requests, "Session", return_value=session):
            provider = mail_provider.MoEmailProvider(entry, {"request_timeout": 30, "user_agent": "test-agent"})

        self.assertTrue(provider.delete_mailbox({"email_id": "email-123"}))
        self.assertEqual(len(session.requests), 1)
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, "https://mail.example/api/emails/email-123")
        self.assertEqual(kwargs["headers"]["X-API-Key"], "key")

    def test_delete_mailbox_closes_provider(self):
        provider = FakeProvider()
        mailbox = {"provider": "fake", "provider_ref": "fake#1", "email_id": "email-123"}
        with patch.object(mail_provider, "_create_provider", return_value=provider) as create_provider:
            self.assertTrue(mail_provider.delete_mailbox({"providers": []}, mailbox))

        create_provider.assert_called_once_with({"providers": []}, "fake", "fake#1")
        self.assertIs(provider.deleted, mailbox)
        self.assertTrue(provider.closed)

    def test_register_deletes_moemail_mailbox_after_code_is_received(self):
        order = []
        mailbox = {"provider": "moemail", "provider_ref": "moemail#1", "address": "user@moemail.app", "email_id": "email-123"}
        registrar = object.__new__(openai_register.PlatformRegistrar)
        registrar._platform_authorize = lambda email, index: order.append("authorize") or "verifier"
        registrar._register_user = lambda email, password, index: order.append("register_user")
        registrar._send_otp = lambda index: order.append("send_otp")
        registrar._validate_otp = lambda code, index: order.append("validate_otp")
        registrar._create_account = lambda name, birthdate, index: order.append("create_account") or "continue-url"
        registrar._finish_registration_and_exchange_tokens = lambda verifier, continue_url, index: order.append("finish") or {
            "access_token": "access",
            "refresh_token": "refresh",
            "id_token": "id",
        }

        with (
            patch.object(openai_register, "create_mailbox", side_effect=lambda: order.append("create_mailbox") or mailbox),
            patch.object(openai_register, "wait_for_code", side_effect=lambda value: order.append("wait_for_code") or "123456"),
            patch.object(openai_register, "delete_moemail_mailbox", side_effect=lambda value, index: order.append("delete_mailbox")),
            patch.object(openai_register, "_random_password", return_value="Password1!"),
            patch.object(openai_register, "_random_name", return_value=("Test", "User")),
            patch.object(openai_register, "_random_birthdate", return_value="2000-01-01"),
        ):
            result = registrar.register(1)

        self.assertEqual(result["email"], "user@moemail.app")
        self.assertLess(order.index("wait_for_code"), order.index("delete_mailbox"))
        self.assertLess(order.index("delete_mailbox"), order.index("validate_otp"))


if __name__ == "__main__":
    unittest.main()
