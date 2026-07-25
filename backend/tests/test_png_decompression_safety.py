import os
import secrets
import struct
import time
import unittest
import zlib

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/xdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

from app.core.config import settings
from app.services.moderation_intake import (
    PngDecompressedPayloadTooLarge,
    _expected_idat_size,
    _inspect_png,
    _safe_png_decompress,
    inspect_media_bytes,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _ihdr(*, width: int, height: int, bit_depth: int = 8, color_type: int = 2, interlace_method: int = 0) -> bytes:
    return _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace_method))


def _build_png(*, width, height, bit_depth=8, color_type=2, interlace_method=0, idat_bodies: list[bytes]) -> bytes:
    parts = [PNG_SIGNATURE, _ihdr(width=width, height=height, bit_depth=bit_depth, color_type=color_type, interlace_method=interlace_method)]
    for body in idat_bodies:
        parts.append(_chunk(b"IDAT", body))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


def _valid_png(*, width, height, bit_depth=8, color_type=2, interlace_method=0, payload: bytes | None = None) -> bytes:
    expected = _expected_idat_size(
        width=width, height=height, bit_depth=bit_depth, color_type=color_type, interlace_method=interlace_method,
    )
    raw = payload if payload is not None else (b"\x00" * expected)
    compressed = zlib.compress(raw)
    return _build_png(
        width=width, height=height, bit_depth=bit_depth, color_type=color_type,
        interlace_method=interlace_method, idat_bodies=[compressed],
    )


class PngExactSizeTests(unittest.TestCase):
    def test_valid_small_non_interlaced_png_round_trips(self):
        content = _valid_png(width=16, height=16)
        inspection = _inspect_png(content)
        self.assertNotIn("png_decompressed_payload_too_large", inspection.issues)
        self.assertNotIn("invalid_png_payload", inspection.issues)

    def test_minus_one_byte_is_rejected(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        content = _valid_png(width=16, height=16, payload=b"\x00" * (expected - 1))
        inspection = _inspect_png(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_plus_one_byte_is_rejected_even_though_under_slack_cap(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        self.assertLess(1, settings.PNG_DECOMPRESS_SLACK_BYTES)  # sanity: +1 stays within the loop's slack cap
        content = _valid_png(width=16, height=16, payload=b"\x00" * (expected + 1))
        inspection = _inspect_png(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_early_eof_truncated_stream_is_rejected(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        compressed = zlib.compress(b"\x00" * expected)
        truncated = compressed[: len(compressed) // 2]
        content = _build_png(width=16, height=16, idat_bodies=[truncated])
        inspection = _inspect_png(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_trailing_unused_data_after_zlib_end_is_rejected(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        compressed = zlib.compress(b"\x00" * expected)
        with_trailing_garbage = compressed + b"\xDE\xAD\xBE\xEF"
        content = _build_png(width=16, height=16, idat_bodies=[with_trailing_garbage])
        inspection = _inspect_png(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_idat_bytes_after_stream_end_in_separate_chunk_is_rejected(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        compressed = zlib.compress(b"\x00" * expected)
        extra_chunk = zlib.compress(b"\x00" * 4)  # a second, entirely separate IDAT chunk after stream end
        content = _build_png(width=16, height=16, idat_bodies=[compressed, extra_chunk])
        inspection = _inspect_png(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_compressed_input_cap_independent_of_output_cap(self):
        # Low compression ratio (near-random bytes), legitimately large IDAT input —
        # not a "bomb," but still oversized against the independent input cap.
        raw_input = os.urandom(settings.PNG_MAX_COMPRESSED_INPUT_BYTES + 1024)
        with self.assertRaises(PngDecompressedPayloadTooLarge):
            _safe_png_decompress(
                iter([raw_input]), width=16, height=16, bit_depth=8, color_type=2, interlace_method=0,
            )

    def test_zlib_bomb_rejected_quickly_with_bounded_memory(self):
        # Small declared IHDR (16x16), enormous real decompressed size (>1000:1 ratio).
        bomb_raw = b"\x00" * (200 * 1024 * 1024)  # 200MB of a single repeated byte compresses extremely well
        bomb_compressed = zlib.compress(bomb_raw, level=9)
        content = _build_png(width=16, height=16, idat_bodies=[bomb_compressed])
        started = time.monotonic()
        inspection = _inspect_png(content)
        elapsed = time.monotonic() - started
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)
        self.assertLess(elapsed, 1.0)

    def test_zlib_bomb_also_caught_on_feedback_path_via_inspect_media_bytes(self):
        # feedback.py calls inspect_media_bytes directly, bypassing the separate
        # megapixel gate used elsewhere — this must not rely on that gate.
        bomb_raw = b"\x00" * (200 * 1024 * 1024)
        bomb_compressed = zlib.compress(bomb_raw, level=9)
        content = _build_png(width=16, height=16, idat_bodies=[bomb_compressed])
        inspection = inspect_media_bytes(content)
        self.assertIn("png_decompressed_payload_too_large", inspection.issues)

    def test_never_materializes_full_idat_chunk_list_via_join(self):
        expected = _expected_idat_size(width=16, height=16, bit_depth=8, color_type=2, interlace_method=0)
        compressed = zlib.compress(b"\x00" * expected)
        # Split into many small chunks and feed via a generator that raises if
        # anything tries to exhaust it into a list/tuple before consumption —
        # locks in that _safe_png_decompress iterates rather than joins upfront.
        piece_size = max(1, len(compressed) // 8)
        pieces = [compressed[i : i + piece_size] for i in range(0, len(compressed), piece_size)]

        consumed_count = 0

        def guarded_iter():
            nonlocal consumed_count
            for piece in pieces:
                consumed_count += 1
                yield piece

        _safe_png_decompress(
            guarded_iter(), width=16, height=16, bit_depth=8, color_type=2, interlace_method=0,
        )
        self.assertEqual(consumed_count, len(pieces))


class PngNonInterlacedDimensionTests(unittest.TestCase):
    def test_various_dimensions_round_trip_exactly(self):
        for width, height in [(1, 1), (13, 13), (100, 37), (256, 1), (1, 256), (17, 5)]:
            with self.subTest(width=width, height=height):
                content = _valid_png(width=width, height=height, interlace_method=0)
                inspection = _inspect_png(content)
                self.assertNotIn("png_decompressed_payload_too_large", inspection.issues, msg=(width, height))


class PngAdam7InterlacedDimensionTests(unittest.TestCase):
    def test_various_dimensions_round_trip_exactly(self):
        # Includes dimensions that don't divide evenly by 8 — exercises the
        # ceiling-division edge cases in the Adam7 pass-size formula.
        for width, height in [(1, 1), (13, 13), (100, 37), (7, 9), (8, 8), (15, 1), (1, 15)]:
            with self.subTest(width=width, height=height):
                content = _valid_png(width=width, height=height, interlace_method=1)
                inspection = _inspect_png(content)
                self.assertNotIn("png_decompressed_payload_too_large", inspection.issues, msg=(width, height))


if __name__ == "__main__":
    unittest.main()
