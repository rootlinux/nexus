import hashlib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
PUBLIC_ROOT = WEB_ROOT / "public"
BRAND_ROOT = PUBLIC_ROOT / "brand"


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


class ReleaseBrandingAuditTests(unittest.TestCase):
    def test_mail_service_uses_nexus_email_logo_asset(self):
        mail_source = (REPO_ROOT / "backend" / "app" / "services" / "mail.py").read_text(encoding="utf-8")

        self.assertIn("/brand/apple-touch-icon.png", mail_source)
        self.assertIn("settings.WEB_BASE_URL.rstrip('/')", mail_source)
        self.assertNotIn("linusx.xyz/apple-touch-icon.png", mail_source)
        self.assertNotIn("Nexus Beta", mail_source)

    def test_public_icon_entrypoints_match_nexus_brand_assets(self):
        self.assertEqual(sha1(PUBLIC_ROOT / "icon-192.png"), sha1(BRAND_ROOT / "icon-192.png"))
        self.assertEqual(sha1(PUBLIC_ROOT / "icon-512.png"), sha1(BRAND_ROOT / "icon-512.png"))
        self.assertEqual(sha1(PUBLIC_ROOT / "icon-maskable-512.png"), sha1(BRAND_ROOT / "icon-512.png"))
        self.assertEqual(sha1(PUBLIC_ROOT / "apple-touch-icon.png"), sha1(BRAND_ROOT / "apple-touch-icon.png"))

    def test_metadata_and_manifest_use_runtime_icon_entrypoints(self):
        layout_source = (WEB_ROOT / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        manifest_source = (WEB_ROOT / "src" / "app" / "manifest.ts").read_text(encoding="utf-8")

        self.assertIn('"/favicon-16x16.png"', layout_source)
        self.assertIn('"/favicon-32x32.png"', layout_source)
        self.assertIn('"/favicon.ico"', layout_source)
        self.assertIn('"/apple-touch-icon.png"', layout_source)
        self.assertIn("'/icon-192.png'", manifest_source)
        self.assertIn("'/icon-512.png'", manifest_source)
        self.assertIn("'/icon-maskable-512.png'", manifest_source)
        self.assertNotIn('"/brand/apple-touch-icon.png"', layout_source)
        self.assertNotIn('"/icon.svg"', layout_source)
        self.assertNotIn("'/brand/icon-192.png'", manifest_source)
        self.assertNotIn("'/brand/icon-512.png'", manifest_source)

    def test_runtime_pwa_shell_has_no_old_branding(self):
        offline_source = (PUBLIC_ROOT / "offline.html").read_text(encoding="utf-8")

        self.assertIn("Offline · Nexus", offline_source)
        self.assertNotIn("Lukeyz", offline_source)
