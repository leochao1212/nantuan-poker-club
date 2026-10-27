"""Bounded, single-flight cache for committed public read models.

Keys use revision counters in the SAME SQLite read transaction as the data.
Only query_only transactions may populate/read this cache; uncommitted writes,
private hands, legal actions, operation receipts and voice inboxes never do.
"""
from collections import OrderedDict
import secrets
import threading

TABLES=('users','poker_rooms','poker_results','poker_hands','wallets','member_profiles',
        'market_positions','market_orders','market_quotes','account_states','cosmetic_items','cosmetic_equipped','room_chat','voice_members')


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS view_versions(name TEXT PRIMARY KEY,version INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO view_versions VALUES(?,?)',('_database',secrets.randbits(63)))
    for table in TABLES:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        db.execute('INSERT OR IGNORE INTO view_versions VALUES(?,0)',(table,))
        for verb in ('INSERT','UPDATE','DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS view_version_{table}_{verb.lower()}
                AFTER {verb} ON {table} BEGIN
                UPDATE view_versions SET version=version+1 WHERE name='{table}'; END''')


def clone(value):
    # These models contain only acyclic JSON-like public records (plus tuples
    # and integer map keys). Avoid deepcopy's memo bookkeeping on every leaf.
    kind=type(value)
    if kind is dict:return {key:clone(item) for key,item in value.items()}
    if kind is list:return [clone(item) for item in value]
    if kind is tuple:return tuple(clone(item) for item in value)
    return value


class ViewCache:
    def __init__(self,limit=128):
        self.limit=limit
        self.condition=threading.Condition()
        self.entries=OrderedDict()
        self.pending=set()
        self.hits=self.misses=0

    def get(self,key,build):
        with self.condition:
            self.condition.wait_for(lambda:key not in self.pending)
            if key in self.entries:
                self.hits+=1
                self.entries.move_to_end(key)
                value=self.entries[key]
                found=True
            else:
                self.misses+=1
                self.pending.add(key)
                value=None
                found=False
        if found:return clone(value)
        try:
            value=build()
            stored=clone(value)
            with self.condition:
                self.entries[key]=stored
                while len(self.entries)>self.limit:self.entries.popitem(last=False)
            return value
        finally:
            with self.condition:
                self.pending.remove(key)
                self.condition.notify_all()

    def stats(self):
        with self.condition:return dict(hits=self.hits,misses=self.misses,entries=len(self.entries),pending=len(self.pending))


CACHE=ViewCache()


def shared(db,name,tables,build):
    # Transactions that may roll back can reuse their revision number later.
    # Never cache those values. Read transactions pin counters and data together.
    if not db.in_transaction or not db.execute('PRAGMA query_only').fetchone()[0]:return build()
    domains=('_database',*tables)
    try:
        versions=tuple(sorted((r[0],r[1]) for r in db.execute(
            'SELECT name,version FROM view_versions WHERE name IN ('+','.join('?' for _ in domains)+')',domains)))
    except Exception as error:
        import sqlite3
        if isinstance(error,sqlite3.OperationalError) and 'no such table' in str(error):return build()
        raise
    if len(versions)!=len(domains):return build()
    return CACHE.get((name,versions),build)
