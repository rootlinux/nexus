import asyncio
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.main import log_startup_configuration
from app.services.mail import (
    CaptureMailSender,
    MailMessage,
    ResendMailSender,
    build_email_change_message,
    build_email_verification_message,
    build_password_reset_message,
)


class MailConfigTests(unittest.TestCase):
    @staticmethod
    def _production_env(**overrides: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb",
                "REDIS_URL": "redis://localhost:6379/0",
                "SECRET_KEY": secrets.token_hex(64),
                "APP_ENV": "production",
                "DEBUG": "false",
                "ALLOWED_HOSTS": "api.example.com",
                "CORS_ALLOWED_ORIGINS": "https://app.example.com",
                "MAIL_PROVIDER": "resend",
                "RESEND_API_KEY": "re_test_key",
                "MAIL_FROM_EMAIL": "no-reply@example.com",
                "MAIL_FROM_NAME": "Example App",
                "WEB_BASE_URL": "https://app.example.com",
                "ADMIN_SERVICE_TOKEN": secrets.token_hex(32),
            }
        )
        env.update(overrides)
        return env

    @staticmethod
    def _load_settings_process(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", "from app.core.config import Settings; Settings(); print('OK')"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_message_builders_include_from_fields(self):
        with patch("app.services.mail.settings.MAIL_FROM_EMAIL", "no-reply@example.com"), patch(
            "app.services.mail.settings.MAIL_FROM_NAME",
            "Example App",
        ):
            messages = [
                build_email_verification_message(
                    to_email="user@example.com",
                    verification_url="https://example.com/verify",
                ),
                build_password_reset_message(
                    to_email="user@example.com",
                    reset_url="https://example.com/reset",
                ),
                build_email_change_message(
                    to_email="user@example.com",
                    verification_url="https://example.com/change",
                ),
            ]

        for message in messages:
            self.assertEqual(message.from_email, "no-reply@example.com")
            self.assertEqual(message.from_name, "Example App")
            self.assertIsNotNone(message.html_body)
            self.assertIn(message.subject.split(" ", 1)[0], message.text_body)

    def test_capture_sender_writes_from_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sender = CaptureMailSender(temp_dir)
            message = MailMessage(
                to_email="user@example.com",
                from_email="no-reply@example.com",
                from_name="Example App",
                subject="Subject",
                text_body="Body",
                html_body="<p>Body</p>",
            )

            asyncio.run(sender.send(message))

            captured_files = list(Path(temp_dir).glob("*.json"))
            self.assertEqual(len(captured_files), 1)
            payload = json.loads(captured_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["from_email"], "no-reply@example.com")
            self.assertEqual(payload["from_name"], "Example App")
            self.assertEqual(payload["to_email"], "user@example.com")
            self.assertEqual(payload["html_body"], "<p>Body</p>")

    def test_capture_sender_falls_back_when_relative_output_dir_is_unwritable(self):
        original_cwd = os.getcwd()
        original_tmpdir = os.environ.get("TMPDIR")
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as tmp_dir:
            os.chdir(workspace_dir)
            os.chmod(workspace_dir, stat.S_IREAD | stat.S_IEXEC)
            os.environ["TMPDIR"] = tmp_dir
            sender = CaptureMailSender("tmp/mail")
            message = MailMessage(
                to_email="user@example.com",
                from_email="no-reply@example.com",
                from_name="Example App",
                subject="Subject",
                text_body="Body",
                html_body="<p>Body</p>",
            )
            try:
                asyncio.run(sender.send(message))
            finally:
                os.chdir(original_cwd)
                if original_tmpdir is None:
                    os.environ.pop("TMPDIR", None)
                else:
                    os.environ["TMPDIR"] = original_tmpdir
                os.chmod(workspace_dir, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

            captured_files = list(Path(tmp_dir).rglob("*.json"))
            payload = json.loads(captured_files[0].read_text(encoding="utf-8"))

        self.assertEqual(len(captured_files), 1)
        self.assertEqual(payload["to_email"], "user@example.com")

    def test_message_builders_include_matching_text_html_and_logo(self):
        with patch("app.services.mail.settings.MAIL_FROM_EMAIL", "no-reply@example.com"), patch(
            "app.services.mail.settings.MAIL_FROM_NAME",
            "Example App",
        ), patch("app.services.mail.settings.WEB_BASE_URL", "https://app.example.com"):
            cases = [
                build_email_verification_message(
                    to_email="user@example.com",
                    verification_url="https://example.com/verify?token=abc123",
                ),
                build_password_reset_message(
                    to_email="user@example.com",
                    reset_url="https://example.com/reset?token=abc123",
                ),
                build_email_change_message(
                    to_email="user@example.com",
                    verification_url="https://example.com/change?token=abc123",
                ),
            ]

        for message in cases:
            assert message.html_body is not None
            if "Verify" in message.subject:
                expected_label = "Verify email"
                expected_url = "https://example.com/verify?token=abc123"
            elif "Reset" in message.subject:
                expected_label = "Reset password"
                expected_url = "https://example.com/reset?token=abc123"
            else:
                expected_label = "Confirm email change"
                expected_url = "https://example.com/change?token=abc123"

            self.assertIn(expected_url, message.text_body)
            self.assertIn(expected_url, message.html_body)
            self.assertIn(expected_label, message.text_body)
            self.assertIn(expected_label, message.html_body)
            self.assertIn("https://app.example.com/brand/apple-touch-icon.png", message.html_body)
            self.assertNotIn("linusx.xyz", message.html_body)
            self.assertIn("<meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\">", message.html_body)
            self.assertIn("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">", message.html_body)
            self.assertIn('width="600"', message.html_body)
            self.assertIn('align="center"', message.html_body)
            self.assertIn("margin:0 auto 24px auto", message.html_body)

    def test_resend_sender_sends_html_and_text(self):
        send_mock = MagicMock()
        resend_stub = SimpleNamespace(api_key=None, Emails=SimpleNamespace(send=send_mock))
        message = MailMessage(
            to_email="user@example.com",
            from_email="no-reply@example.com",
            from_name="Example App",
            subject="Subject",
            text_body="Text body",
            html_body="<p>HTML body</p>",
        )

        with patch.dict(sys.modules, {"resend": resend_stub}), patch(
            "app.services.mail.settings.RESEND_API_KEY",
            "re_test_key",
        ):
            asyncio.run(ResendMailSender().send(message))

        self.assertEqual(resend_stub.api_key, "re_test_key")
        send_mock.assert_called_once_with(
            {
                "from": "Example App <no-reply@example.com>",
                "to": ["user@example.com"],
                "subject": "Subject",
                "text": "Text body",
                "html": "<p>HTML body</p>",
            }
        )

    def test_startup_fails_fast_for_unsupported_mail_provider(self):
        bootstrap_mock = AsyncMock()
        with patch("app.main.settings.MAIL_PROVIDER", "smtp"), patch(
            "app.main.bootstrap_admin_if_configured",
            bootstrap_mock,
        ), patch("app.main.logger.error") as logger_error:
            with self.assertRaises(RuntimeError) as context:
                asyncio.run(log_startup_configuration())

        self.assertEqual(str(context.exception), "Unsupported MAIL_PROVIDER: smtp")
        logger_error.assert_called_once()
        self.assertIn("Mail configuration error", logger_error.call_args.args[0])
        bootstrap_mock.assert_not_awaited()

    def test_production_resend_config_loads_with_real_values(self):
        result = self._load_settings_process(self._production_env())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_production_like_env_accepts_empty_refresh_cookie_secure_and_uses_safe_default(self):
        result = self._load_settings_process(self._production_env(REFRESH_COOKIE_SECURE=""))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_invalid_refresh_cookie_secure_value_fails_with_clear_error(self):
        result = self._load_settings_process(self._production_env(REFRESH_COOKIE_SECURE="maybe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REFRESH_COOKIE_SECURE must be a boolean value", result.stderr)

    def test_production_resend_requires_api_key(self):
        result = self._load_settings_process(self._production_env(RESEND_API_KEY=""))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESEND_API_KEY must be set when MAIL_PROVIDER=resend", result.stderr)

    def test_production_resend_rejects_dev_web_base_url(self):
        result = self._load_settings_process(self._production_env(WEB_BASE_URL="http://localhost:3000"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WEB_BASE_URL must be an https production URL when using a real mail provider", result.stderr)

    def test_production_resend_requires_real_from_email(self):
        result = self._load_settings_process(self._production_env(MAIL_FROM_EMAIL="no-reply@localhost"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MAIL_FROM_EMAIL must use a real domain when using a real mail provider", result.stderr)

    def test_production_resend_requires_from_name(self):
        result = self._load_settings_process(self._production_env(MAIL_FROM_NAME=""))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MAIL_FROM_NAME must be set when using a real mail provider", result.stderr)

    def test_production_secret_key_rejects_placeholder_value(self):
        result = self._load_settings_process(
            self._production_env(
                SECRET_KEY="replace-with-a-strong-64-plus-character-secret-"
                "replace-with-a-strong-64-plus-character-secret"
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must be a strong non-placeholder value in production", result.stderr)

    def test_production_secret_key_rejects_repeated_pattern(self):
        result = self._load_settings_process(self._production_env(SECRET_KEY="0123456789abcdef" * 4))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must not use a known default or shared example value in production", result.stderr)


if __name__ == "__main__":
    unittest.main()
