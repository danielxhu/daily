"""Reset local data (M9.6) — wipe the local SQLite DB, Chroma vector store, and
extracted frames so a trial can start clean. Single-operator local wipe: no backup,
no multi-user/auth (out of scope). Destructive and irreversible — it asks to confirm
unless --yes.

    cd backend && .venv/bin/python ../scripts/reset_local.py         # prompts to confirm
    cd backend && .venv/bin/python ../scripts/reset_local.py --yes   # no prompt (scripts)
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reset_local", description="wipe local daily data (SQLite + Chroma + frames)"
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    from app.core.config import get_settings
    from app.reset import reset_local_data

    settings = get_settings()
    targets = [settings.sqlite_path, settings.chroma_path, settings.frames_path]
    print("This permanently deletes local data (no backup):")
    for target in targets:
        print(f"  - {target}")

    if not args.yes:
        if input("Type 'yes' to confirm: ").strip().lower() != "yes":
            print("aborted.", file=sys.stderr)
            return 1

    removed = reset_local_data(settings)
    if removed:
        print("removed:")
        for path in removed:
            print(f"  - {path}")
    else:
        print("nothing to remove (already clean).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
