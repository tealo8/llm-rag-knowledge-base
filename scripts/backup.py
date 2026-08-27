"""Create a consistent local backup of SQLite metadata and file-backed indexes."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=root / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"backup directory already exists: {output}")
    output.mkdir(parents=True)
    db_path = root / os.getenv("DATABASE_PATH", "backend/data/knowledge.db")
    if db_path.exists():
        destination = output / "knowledge.db"
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    for name in ("uploads", "chroma"):
        source_dir = root / "backend" / "data" / name
        if source_dir.exists():
            shutil.copytree(source_dir, output / name)
    (output / "manifest.json").write_text(
        json.dumps({"created_at": datetime.now(UTC).isoformat(), "database": str(db_path), "format": 1}, indent=2),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
