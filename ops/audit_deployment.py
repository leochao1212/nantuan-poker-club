"""Read-only, snapshot-consistent comparison with the pre-deployment backup."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

TABLES = ('users', 'poker_hands', 'poker_results', 'poker_operations',
          'wallet_ledger', 'cosmetic_items', 'milestone_claims')
IMMUTABLE = ('poker_hands', 'poker_results', 'wallet_ledger', 'cosmetic_items', 'milestone_claims')


def audit(database, backup):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('ATTACH DATABASE ? AS saved', (Path(backup).resolve().as_uri() + '?mode=ro',))
        db.execute('BEGIN')
        counts = {t: {'before': db.execute('SELECT count(*) FROM saved.' + t).fetchone()[0],
                      'after': db.execute('SELECT count(*) FROM main.' + t).fetchone()[0]} for t in TABLES}
        differences = {t: db.execute('SELECT count(*) FROM (SELECT * FROM saved.' + t +
                       ' EXCEPT SELECT * FROM main.' + t + ')').fetchone()[0] for t in IMMUTABLE}
        missing_users = db.execute('SELECT count(*) FROM saved.users b LEFT JOIN main.users a ON a.id=b.id WHERE a.id IS NULL').fetchone()[0]
        last = db.execute('SELECT COALESCE(max(id),0) FROM saved.wallet_ledger').fetchone()[0]
        unexplained = db.execute('''SELECT count(*) FROM saved.wallets b LEFT JOIN main.wallets a
          ON a.user_id=b.user_id WHERE a.user_id IS NULL OR a.balance-b.balance != COALESCE(
          (SELECT sum(amount) FROM main.wallet_ledger l WHERE l.user_id=b.user_id AND l.id>?),0)''', (last,)).fetchone()[0]
        result = dict(integrity=db.execute('PRAGMA main.quick_check').fetchone()[0],
                      backup_integrity=db.execute('PRAGMA saved.quick_check').fetchone()[0], counts=counts,
                      old_record_differences=differences, missing_users=missing_users,
                      unexplained_wallet_changes=unexplained)
    result['passed'] = (result['integrity'] == result['backup_integrity'] == 'ok'
                        and not any(differences.values()) and not missing_users and not unexplained
                        and all(c['after'] >= c['before'] for c in counts.values()))
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('Expected numeric deployment run ID')
    result = audit('/data/poker.sqlite3', '/data/backups/ci-' + sys.argv[1] + '.sqlite3')
    print(json.dumps(result))
    sys.exit(0 if result['passed'] else 1)
