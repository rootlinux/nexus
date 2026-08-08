"""Keeps public-facing claims and repository hygiene honest.

Two jobs:

1. **Counts in the README are real.** A number typed into a README is stale the day after
   it is written unless something checks it. These assertions fail the build instead.
2. **Retired names stay retired.** Legacy `xplatform` branding, the removed all-powerful
   admin service token, and internal milestone/AI-tooling artifacts were cleaned out of the
   tree once; without a guard they drift back in one paste at a time.

The sweep runs over `git ls-files`, so it only ever inspects tracked, publicly visible
content — never a local venv, build output, or scratch directory.
"""

import re
import subprocess
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
README = REPO_ROOT / "README.md"
SECURITY_POLICY = REPO_ROOT / "SECURITY.md"

# Binary and vendored content the text sweep cannot meaningfully read.
SKIPPED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".zip", ".lock",
}
SKIPPED_NAMES = {"package-lock.json"}


def tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Exported tarball or a copied tree with no .git — there is no "tracked" set to
        # sweep. Skip rather than fail: CI always has the real repository.
        raise unittest.SkipTest("not a git work tree; cannot enumerate tracked files")
    files = []
    for name in result.stdout.split("\0"):
        if not name:
            continue
        path = REPO_ROOT / name
        if path.suffix.lower() in SKIPPED_SUFFIXES or path.name in SKIPPED_NAMES:
            continue
        if not path.is_file():
            continue
        files.append(path)
    return files


def scan(needle: str, *, allowed: set[str]) -> list[str]:
    """Relative paths of tracked files containing `needle`, minus the justified ones."""
    hits = []
    for path in tracked_text_files():
        try:
            contents = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if needle.lower() in contents.lower():
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative not in allowed:
                hits.append(relative)
    return sorted(hits)


class ReadmeCountAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.readme = README.read_text(encoding="utf-8")

    def test_backend_test_module_count_matches_the_tree(self):
        claimed = re.search(r"\*\*(\d+) backend test modules\*\*", self.readme)
        self.assertIsNotNone(claimed, "README no longer states a backend test module count")
        actual = len(list((BACKEND_ROOT / "tests").glob("test_*.py")))
        self.assertEqual(
            int(claimed.group(1)),
            actual,
            f"README claims {claimed.group(1)} backend test modules; the tree has {actual}",
        )

    def test_migration_count_matches_the_tree(self):
        claimed = re.search(r"(\d+) Alembic migration files", self.readme)
        self.assertIsNotNone(claimed, "README no longer states an Alembic migration count")
        actual = len(list((BACKEND_ROOT / "alembic" / "versions").glob("*.py")))
        self.assertEqual(
            int(claimed.group(1)),
            actual,
            f"README claims {claimed.group(1)} migration files; the tree has {actual}",
        )

    def test_every_test_module_named_in_the_readme_exists(self):
        named = set(re.findall(r"`(test_[a-z0-9_]+)`", self.readme))
        self.assertTrue(named, "README no longer points at any specific test module")
        for module in sorted(named):
            with self.subTest(module=module):
                self.assertTrue(
                    (BACKEND_ROOT / "tests" / f"{module}.py").exists(),
                    f"README references {module}, which does not exist",
                )

    def test_readme_links_to_a_workflow_that_exists(self):
        if "actions/workflows/" not in self.readme:
            self.skipTest("README has no CI badge")
        for workflow in set(re.findall(r"actions/workflows/([\w.-]+\.yml)", self.readme)):
            with self.subTest(workflow=workflow):
                self.assertTrue((REPO_ROOT / ".github" / "workflows" / workflow).exists())


class PublicHygieneTests(unittest.TestCase):
    def test_no_placeholder_contact_address_in_the_security_policy(self):
        # example.com is IANA-reserved and accepts no mail: a security policy pointing at
        # one tells a reporter to send findings into a void.
        policy = SECURITY_POLICY.read_text(encoding="utf-8")
        self.assertNotIn("example.com", policy)
        self.assertNotIn("example.org", policy)
        self.assertIn("security/advisories/new", policy)

    def test_legacy_xplatform_branding_only_survives_in_migration_guidance(self):
        allowed = {
            # The one-time rename procedure has to name the old database to be usable.
            "deploy/RUNBOOK.md",
            "deploy/scripts/rename-legacy-database.sh",
            "deploy/docker-compose.yml",
            "deploy/.env.local-smoke.example",
            "README.md",
            "backend/tests/test_readme_claims.py",
        }
        self.assertEqual([], scan("xplatform", allowed=allowed))

    def test_removed_admin_service_token_is_not_referenced_as_a_live_mechanism(self):
        allowed = {
            # Removal notes and the tests that prove the credential no longer authenticates.
            "README.md",
            "deploy/RUNBOOK.md",
            "backend/tests/test_service_auth_scopes.py",
            "backend/tests/test_admin_service_scoped_auth.py",
            "backend/tests/test_readme_claims.py",
        }
        self.assertEqual([], scan("ADMIN_SERVICE_TOKEN", allowed=allowed))

    def test_no_internal_milestone_names_in_test_module_filenames(self):
        # Alembic revision filenames keep their milestone wording — renaming one breaks the
        # migration chain for every existing deployment — but test modules should describe
        # behaviour, not the plan that produced them.
        offenders = [
            path.name
            for path in (BACKEND_ROOT / "tests").glob("test_*.py")
            if re.search(r"phase\d|stabilization|task\d|round\d", path.name, re.IGNORECASE)
        ]
        self.assertEqual([], offenders)

    def test_no_ai_tooling_artifacts_in_tracked_files(self):
        allowed = {"backend/tests/test_readme_claims.py"}
        for marker in ("testsprite", "generated by ai", "co-authored-by: claude"):
            with self.subTest(marker=marker):
                self.assertEqual([], scan(marker, allowed=allowed))


if __name__ == "__main__":
    unittest.main()
