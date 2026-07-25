import secrets
import subprocess
import sys
import unittest
from pathlib import Path


class RedisTlsPolicyTests(unittest.TestCase):
    @staticmethod
    def _production_env(**overrides: str) -> dict[str, str]:
        import os

        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb",
                "REDIS_URL": "rediss://:testpassword@redis.example.com:6380/0",
                "SECRET_KEY": secrets.token_hex(64),
                "APP_ENV": "production",
                "DEBUG": "false",
                "ALLOWED_HOSTS": "api.example.com",
                "CORS_ALLOWED_ORIGINS": "https://app.example.com",
                "MAIL_PROVIDER": "capture",
                "WEB_BASE_URL": "https://app.example.com",
            }
        )
        env.pop("REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK", None)
        env.pop("REDIS_PLAINTEXT_ALLOWED_HOSTS", None)
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

    def test_rediss_with_credentials_is_accepted(self):
        result = self._load_settings_process(self._production_env())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_rediss_without_credentials_is_rejected(self):
        result = self._load_settings_process(
            self._production_env(REDIS_URL="rediss://redis.example.com:6380/0")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Redis must use authentication in production", result.stderr)

    def test_plain_redis_is_rejected_without_the_private_network_opt_in(self):
        result = self._load_settings_process(
            self._production_env(REDIS_URL="redis://:testpassword@redis.example.com:6379/0")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Redis must use TLS in production", result.stderr)
        self.assertIn("REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK", result.stderr)

    def test_plain_redis_is_accepted_for_a_private_ip_with_the_opt_in_and_credentials(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://:testpassword@10.0.4.12:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
            )
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_plain_redis_is_accepted_for_loopback_with_the_opt_in_and_credentials(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://:testpassword@127.0.0.1:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
            )
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_plain_redis_still_requires_credentials_even_with_the_opt_in(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://10.0.4.12:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Redis must use authentication in production", result.stderr)

    def test_plain_redis_with_a_public_ip_is_rejected_even_with_the_opt_in(self):
        # The whole point of REDIS_PLAINTEXT_ALLOWED_HOSTS / the private-IP check: setting
        # REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK=true must not, by itself, wave through a
        # fully public remote Redis host over plaintext.
        result = self._load_settings_process(
            self._production_env(
                # A real, globally-routable public IP (Google public DNS) — not an
                # RFC 5737 documentation range, which Python's ipaddress module
                # classifies as "private" for non-routability reasons even though
                # it's a public-facing example range, not an actual private network.
                REDIS_URL="redis://:testpassword@8.8.8.8:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a private/loopback IP", result.stderr)

    def test_plain_redis_with_an_unlisted_hostname_is_rejected_even_with_the_opt_in(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://:testpassword@redis:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REDIS_PLAINTEXT_ALLOWED_HOSTS", result.stderr)

    def test_plain_redis_with_an_allowlisted_hostname_is_accepted(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://:testpassword@redis:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
                REDIS_PLAINTEXT_ALLOWED_HOSTS="redis",
            )
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK", result.stdout)

    def test_plain_redis_with_a_hostname_not_in_the_allowlist_is_rejected(self):
        result = self._load_settings_process(
            self._production_env(
                REDIS_URL="redis://:testpassword@redis:6379/0",
                REDIS_ALLOW_PLAINTEXT_PRIVATE_NETWORK="true",
                REDIS_PLAINTEXT_ALLOWED_HOSTS="some-other-host",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REDIS_PLAINTEXT_ALLOWED_HOSTS", result.stderr)


if __name__ == "__main__":
    unittest.main()
