"""Read-only, snapshot-consistent comparison with the pre-deployment backup."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

TABLES = ('users', 'poker_hands', 'poker_results', 'poker_operations',
          'wallet_ledger', 'cosmetic_items', 'milestone_claims')
IMMUTABLE = ('poker_hands', 'poker_results', 'wallet_ledger', 'cosmetic_items', 'milestone_claims')


def market_audit(db):
    """Allow live orders to settle, but preserve ownership and completed history."""
    tables = {r[0] for r in db.execute("SELECT name FROM saved.sqlite_master WHERE type='table'")}
    checks = {}
    for table, active in (('market_orders', 'pending'), ('market_contract_orders', 'pending'),
                          ('market_shorts', 'open'), ('market_contracts', 'open')):
        if table not in tables:
            continue  # Backups made before the exchange was introduced.
        missing = db.execute('SELECT count(*) FROM saved.'+table+' b LEFT JOIN main.'+table+
            ' a USING(id) WHERE a.id IS NULL OR a.user_id!=b.user_id OR a.symbol!=b.symbol').fetchone()[0]
        changed = db.execute('SELECT count(*) FROM (SELECT * FROM saved.'+table+
            ' WHERE status!=? EXCEPT SELECT * FROM main.'+table+')', (active,)).fetchone()[0]
        checks[table] = dict(missing_or_reassigned=missing, changed_completed=changed)
    if 'market_operations' in tables:
        checks['market_operations'] = dict(changed=db.execute('SELECT count(*) FROM '
            '(SELECT * FROM saved.market_operations EXCEPT SELECT * FROM main.market_operations)').fetchone()[0])
    return checks


def blocade_audit(db):
    """Preserve board escrow, operation receipts and completed matches on upgrades."""
    tables = {r[0] for r in db.execute("SELECT name FROM saved.sqlite_master WHERE type='table'")}
    checks = {}
    if 'blocade_rooms' in tables:
        checks['rooms'] = dict(
            missing=db.execute('SELECT count(*) FROM saved.blocade_rooms b LEFT JOIN main.blocade_rooms a USING(id) WHERE a.id IS NULL').fetchone()[0],
            changed_completed=db.execute("SELECT count(*) FROM (SELECT * FROM saved.blocade_rooms WHERE status IN ('finished','cancelled') EXCEPT SELECT * FROM main.blocade_rooms)").fetchone()[0])
    if 'blocade_entries' in tables:
        checks['entries'] = dict(changed=db.execute('''SELECT count(*) FROM saved.blocade_entries b
            LEFT JOIN main.blocade_entries a USING(room_id,user_id)
            WHERE a.user_id IS NULL OR a.stake!=b.stake OR a.joined_at!=b.joined_at
              OR (b.payout IS NOT NULL AND a.payout IS NOT b.payout)''').fetchone()[0])
    if 'blocade_operations' in tables:
        checks['operations'] = dict(changed=db.execute('SELECT count(*) FROM (SELECT * FROM saved.blocade_operations EXCEPT SELECT * FROM main.blocade_operations)').fetchone()[0])
    return checks


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
        result['market'] = market_audit(db)
        result['blocade'] = blocade_audit(db)
    result['passed'] = (result['integrity'] == result['backup_integrity'] == 'ok'
                        and not any(differences.values()) and not missing_users and not unexplained
                        and not any(value for check in result['market'].values() for value in check.values())
                        and not any(value for check in result['blocade'].values() for value in check.values())
                        and all(c['after'] >= c['before'] for c in counts.values()))
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('Expected numeric deployment run ID')
    result = audit('/data/poker.sqlite3', '/data/backups/ci-' + sys.argv[1] + '.sqlite3')
    print(json.dumps(result))
    sys.exit(0 if result['passed'] else 1)
