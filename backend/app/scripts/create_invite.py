"""Create an invite code from the command line.

Nexus is invite-only, so a freshly migrated database cannot register anybody: `/register`
demands a valid code and there are none. This is the supported way to mint the first one.

    python -m app.scripts.create_invite
    python -m app.scripts.create_invite --created-by <username> --max-uses 5 --expires-days 7

Attribution rules differ by environment, deliberately:

* Outside production the invite may be created **unattributed** (`created_by_id IS NULL`,
  which the schema has allowed since migration `037_invite_created_by_nullable`). That is
  honest about what happened — an operator ran a script — and is far better than the old
  README workaround of fabricating a placeholder "seed owner" user account, which left a
  real, loginable row behind that looked like a legitimate member.
* In production `--created-by` is **required**. Real invites must trace back to a real
  accountable staff member; silently dropping that link would put a hole in the audit
  trail rather than in a test fixture.

Nothing here relaxes the invite model itself: the code is generated with `secrets`, stored
hashed exactly as the API stores it, and is subject to the same expiry and use-count
columns the normal flow uses.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_invite_code
# Registers every model class the declarative registry needs to resolve
# string-referenced relationships. A bare `import app.models` is not enough —
# webauthn_credential is not imported there, and User.webauthn_credentials would
# fail to resolve the moment any User query is configured.
import app.models  # noqa: F401
import app.models.webauthn_credential  # noqa: F401
from app.models.invite import InviteCode, InviteType
from app.models.user import User

CODE_ALPHABET = string.ascii_letters + string.digits


def generate_code(length: int) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


async def _unique_code(session, length: int) -> str:
    # The column is unique; retry rather than surface an IntegrityError for a collision
    # that is astronomically unlikely but trivially recoverable.
    for _ in range(10):
        code = generate_code(length)
        existing = await session.scalar(select(InviteCode).where(InviteCode.code == code))
        if existing is None:
            return code
    raise RuntimeError("Could not generate a unique invite code after 10 attempts")


async def create_invite(
    *,
    created_by_username: str | None,
    max_uses: int,
    expires_days: int,
    note: str | None,
) -> str:
    async with AsyncSessionLocal() as session:
        creator_id: int | None = None
        if created_by_username:
            creator = await session.scalar(
                select(User).where(User.username == created_by_username)
            )
            if creator is None:
                raise SystemExit(f"No user named {created_by_username!r} exists.")
            creator_id = creator.id

        code = await _unique_code(session, settings.INVITE_CODE_LENGTH)
        session.add(
            InviteCode(
                code=code,
                code_hash=hash_invite_code(code),
                invite_type=InviteType.GENERIC,
                created_by_id=creator_id,
                internal_note=note,
                max_uses=max_uses,
                current_uses=0,
                expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
                is_active=True,
            )
        )
        await session.commit()
        return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.create_invite",
        description="Create an invite code for local development or operational bootstrap.",
    )
    parser.add_argument(
        "--created-by",
        metavar="USERNAME",
        default=None,
        help="Attribute the invite to this existing user. Required when APP_ENV is production.",
    )
    parser.add_argument("--max-uses", type=int, default=1, help="Redemptions allowed (default: 1).")
    parser.add_argument(
        "--expires-days", type=int, default=30, help="Days until the code expires (default: 30)."
    )
    parser.add_argument("--note", default=None, help="Internal note stored with the invite.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.max_uses < 1:
        raise SystemExit("--max-uses must be at least 1")
    if args.expires_days < 1:
        raise SystemExit("--expires-days must be at least 1")

    if settings.is_production and not args.created_by:
        raise SystemExit(
            "Refusing to create an unattributed invite in production. Pass --created-by "
            "<username> so the invite traces back to an accountable staff account."
        )

    code = asyncio.run(
        create_invite(
            created_by_username=args.created_by,
            max_uses=args.max_uses,
            expires_days=args.expires_days,
            note=args.note,
        )
    )

    # Printed in full and exactly once: this is the only moment the plaintext code exists.
    # Only its hash is persisted, so a lost code cannot be recovered — mint a new one.
    print(f"INVITE_CODE={code}")
    if not args.created_by:
        print(
            "(unattributed: created_by_id is NULL — expected for a local bootstrap invite)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
