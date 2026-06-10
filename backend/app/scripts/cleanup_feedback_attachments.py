from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import settings
from app.services.feedback_retention import delete_feedback_attachments, find_stale_feedback_attachments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or remove stale private feedback attachments."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete matching files. Without this flag the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=settings.FEEDBACK_ATTACHMENT_RETENTION_DAYS,
        help="Delete files older than this many days.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of file paths to print.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(settings.FEEDBACK_ATTACHMENT_LOCAL_DIR)
    stale_files = find_stale_feedback_attachments(
        root,
        retention_days=args.older_than_days,
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    total_bytes = sum(item.size_bytes for item in stale_files)
    print(
        f"[{mode}] {len(stale_files)} feedback attachment(s) older than "
        f"{args.older_than_days} day(s) in {root} ({total_bytes} bytes)"
    )

    for item in stale_files[: max(args.limit, 0)]:
        print(
            f"- {item.path} | age={item.age_days:.1f}d | size={item.size_bytes}B"
        )

    if len(stale_files) > args.limit:
        print(f"... {len(stale_files) - args.limit} more omitted")

    if not args.apply:
        print("No files deleted. Re-run with --apply to remove these files.")
        return 0

    deleted = delete_feedback_attachments(stale_files)
    print(f"Deleted {deleted} feedback attachment(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
