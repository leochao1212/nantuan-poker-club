"""Restore a backup into an isolated temporary SQLite file; never open production for writing."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile


def verify(backup, directory=None):
    source = Path(backup).resolve()
    if not source.is_file():
        raise ValueError('Backup file does not exist')
    with tempfile.TemporaryDirectory(prefix='poker-restore-', dir=directory) as folder:
        restored = Path(folder)/'restored.sqlite3'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(restored)) as dst:
                src.backup(dst)
                integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
                tables = ('users', 'wallets', 'wallet_ledger', 'poker_hands', 'market_orders', 'market_contract_orders')
                counts = {t: dst.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
                invalid_wallets = dst.execute('SELECT count(*) FROM wallets WHERE balance<0').fetchone()[0]
        return dict(passed=integrity=='ok' and not invalid_wallets, integrity=integrity,
                    counts=counts, negative_wallets=invalid_wallets, restored_bytes=restored.stat().st_size)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup')
    parser.add_argument('--temp-dir')
    args = parser.parse_args()
    result = verify(args.backup, args.temp_dir)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
