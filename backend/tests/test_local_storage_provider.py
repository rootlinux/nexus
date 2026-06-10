import os
import secrets
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xplatform")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.storage.local import LocalStorageProvider


class LocalStorageProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_relative_upload_dir_is_anchored_to_backend_root(self):
        backend_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                provider = LocalStorageProvider(upload_dir="uploads-regression", url_prefix="/uploads")
                stored = await provider.save_file(
                    content=b"fake-image-bytes",
                    content_type="image/png",
                    original_filename="composer.png",
                )
            finally:
                os.chdir(original_cwd)

        self.assertEqual(provider.upload_dir, backend_root / "uploads-regression")
        self.assertEqual(stored.public_url, f"/uploads/{stored.storage_key}")
        self.assertTrue((provider.upload_dir / stored.storage_key).exists())

        await provider.delete_file(storage_key=stored.storage_key)
        provider.upload_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
