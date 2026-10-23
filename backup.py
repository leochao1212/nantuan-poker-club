"""Create a consistent SQLite backup, including committed WAL data."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3


def backup(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise FileNotFoundError("Source database does not exist")
    if source == target:
        raise ValueError("Backup must use a different file")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite an existing backup or database.
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as destination:
            original.backup(destination)
            check = destination.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError("Backup integrity check failed")
            counts = {"users": destination.execute("SELECT count(*) FROM users").fetchone()[0],
                      "games": destination.execute("SELECT count(*) FROM games").fetchone()[0]}
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consistent poker database backup")
    parser.add_argument("--database", default=os.environ.get("POKER_SOURCE_DB") or os.environ.get("POKER_DB") or str(Path(__file__).parent/"data"/"poker.sqlite3"))
    parser.add_argument("--output", default=str(Path(os.environ.get("POKER_DB", "/data/poker.sqlite3")).parent/"backups"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+".sqlite3")))
    args = parser.parse_args()
    result = backup(args.database, args.output)
    print(json.dumps({"backup": str(Path(args.output).resolve()), "integrity": "ok", **result}))
