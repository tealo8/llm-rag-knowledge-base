"""Restore a local backup. Requires --force and an application outage."""
from __future__ import annotations

import argparse
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--force", action="store_true", help="confirm overwrite of current data")
    args = parser.parse_args()
    if not args.force:
        raise SystemExit("restore is destructive; stop the app and pass --force")
    backup = args.backup.resolve()
    if not backup.is_dir() or not (backup / "manifest.json").exists():
        raise SystemExit("invalid backup directory or missing manifest.json")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    db_path = root / os.getenv("DATABASE_PATH", "backend/data/knowledge.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        shutil.copy2(db_path, db_path.with_suffix(f".pre-restore-{stamp}.db"))
    shutil.copy2(backup / "knowledge.db", db_path)
    for name in ("uploads", "chroma"):
        source_dir = backup / name
        target_dir = root / "backend" / "data" / name
        if source_dir.exists():
            if target_dir.exists():
                shutil.move(str(target_dir), str(target_dir.with_name(f"{name}.pre-restore-{stamp}")))
            shutil.copytree(source_dir, target_dir)
    print(f"restored {backup} to {root}")


if __name__ == "__main__":
    main()
