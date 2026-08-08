import os
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nexus")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ["DEBUG"] = "false"

from app.storage.local import LocalStorageProvider


class StorageAsyncOffloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_file_write_happens_off_the_event_loop_thread(self):
        event_loop_thread = threading.current_thread()
        recorded_threads: list[threading.Thread] = []
        real_write_bytes = Path.write_bytes

        def _spy_write_bytes(self, data):
            recorded_threads.append(threading.current_thread())
            return real_write_bytes(self, data)

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LocalStorageProvider(upload_dir=temp_dir, url_prefix="/uploads")
            with patch.object(Path, "write_bytes", _spy_write_bytes):
                stored = await provider.save_file(content=b"hello", content_type="image/png")

        self.assertEqual(len(recorded_threads), 1)
        self.assertIsNot(recorded_threads[0], event_loop_thread)
        self.assertTrue(stored.storage_key.endswith(".png"))

    async def test_delete_file_unlink_happens_off_the_event_loop_thread(self):
        event_loop_thread = threading.current_thread()
        recorded_threads: list[threading.Thread] = []
        real_unlink = Path.unlink

        def _spy_unlink(self, missing_ok=False):
            recorded_threads.append(threading.current_thread())
            return real_unlink(self, missing_ok=missing_ok)

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LocalStorageProvider(upload_dir=temp_dir, url_prefix="/uploads")
            stored = await provider.save_file(content=b"hello", content_type="image/png")

            with patch.object(Path, "unlink", _spy_unlink):
                await provider.delete_file(storage_key=stored.storage_key)

        self.assertEqual(len(recorded_threads), 1)
        self.assertIsNot(recorded_threads[0], event_loop_thread)

    async def test_save_file_still_cleans_up_partial_write_on_failure(self):
        # Behavior-preserving check: the existing "delete partial file on
        # write failure" logic must survive the move into a background
        # thread unchanged.
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LocalStorageProvider(upload_dir=temp_dir, url_prefix="/uploads")

            real_write_bytes = Path.write_bytes

            def _failing_write_bytes(self, data):
                real_write_bytes(self, b"partial")
                raise OSError("disk full (simulated)")

            with patch.object(Path, "write_bytes", _failing_write_bytes):
                with self.assertRaises(OSError):
                    await provider.save_file(content=b"hello", content_type="image/png")

            remaining_files = list(Path(temp_dir).iterdir())
            self.assertEqual(remaining_files, [])

    async def test_save_file_and_delete_file_still_work_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LocalStorageProvider(upload_dir=temp_dir, url_prefix="/uploads")
            stored = await provider.save_file(content=b"real content", content_type="image/jpeg")
            file_path = Path(temp_dir) / stored.storage_key
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.read_bytes(), b"real content")

            await provider.delete_file(storage_key=stored.storage_key)
            self.assertFalse(file_path.exists())


if __name__ == "__main__":
    unittest.main()
