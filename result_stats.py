"""Transactional projections of settled results; never used to settle a wager.

The original hands/results remain authoritative. Triggers project their public
statistics in the same SQLite transaction, including rollback, edits and deletes.
"""

FACTS = '''SELECT r.hand_id,r.user_id,r.profit,h.finished_at,
    COALESCE(json_extract(h.public_state,'$.game_type'),'holdem'),
    CASE WHEN EXISTS (
      SELECT 1 FROM json_each(h.public_state,'$.players') p
      WHERE json_extract(p.value,'$.user_id')=r.user_id
        AND COALESCE(json_extract(p.value,'$.contribution'),0)>0
    ) AND (COALESCE(json_extract(h.public_state,'$.game_type'),'holdem') NOT IN ('mines','tower')
       OR COALESCE(json_array_length(h.public_state,'$.selected'),0)>0)
    THEN 1 ELSE 0 END
    FROM poker_results r JOIN poker_hands h ON h.id=r.hand_id'''


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS result_projection_state(version INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS result_facts(
      hand_id INTEGER NOT NULL,user_id INTEGER NOT NULL,profit INTEGER NOT NULL,
      finished_at REAL NOT NULL,game_type TEXT NOT NULL,qualified INTEGER NOT NULL,
      PRIMARY KEY(hand_id,user_id));
    CREATE INDEX IF NOT EXISTS result_facts_daily ON result_facts(user_id,finished_at);
    CREATE TABLE IF NOT EXISTS player_result_totals(
      user_id INTEGER PRIMARY KEY,hands INTEGER NOT NULL,profit INTEGER NOT NULL,wins INTEGER NOT NULL);
    CREATE TRIGGER IF NOT EXISTS result_facts_insert AFTER INSERT ON result_facts BEGIN
      INSERT INTO player_result_totals VALUES(NEW.user_id,1,NEW.profit,NEW.profit>0)
      ON CONFLICT(user_id) DO UPDATE SET hands=hands+1,profit=profit+NEW.profit,wins=wins+(NEW.profit>0);
    END;
    CREATE TRIGGER IF NOT EXISTS result_facts_delete AFTER DELETE ON result_facts BEGIN
      UPDATE player_result_totals SET hands=hands-1,profit=profit-OLD.profit,wins=wins-(OLD.profit>0)
        WHERE user_id=OLD.user_id;
      DELETE FROM player_result_totals WHERE user_id=OLD.user_id AND hands=0;
    END;
    ''')
    for verb in ('INSERT', 'UPDATE', 'DELETE'):
        remove = '' if verb == 'INSERT' else 'DELETE FROM result_facts WHERE hand_id=OLD.hand_id AND user_id=OLD.user_id;'
        insert = '' if verb == 'DELETE' else 'INSERT INTO result_facts '+FACTS+' WHERE r.hand_id=NEW.hand_id AND r.user_id=NEW.user_id;'
        db.execute(f'CREATE TRIGGER IF NOT EXISTS project_result_{verb.lower()} AFTER {verb} ON poker_results BEGIN {remove} {insert} END')
    db.execute('''CREATE TRIGGER IF NOT EXISTS project_hand_update AFTER UPDATE OF public_state,finished_at ON poker_hands BEGIN
        DELETE FROM result_facts WHERE hand_id=OLD.id;
        INSERT INTO result_facts '''+FACTS+''' WHERE r.hand_id=NEW.id;
        END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS project_hand_delete AFTER DELETE ON poker_hands BEGIN
        DELETE FROM result_facts WHERE hand_id=OLD.id;
        END''')
    if not db.execute('SELECT 1 FROM result_projection_state WHERE version=1').fetchone():
        # A crash before commit leaves no migration marker; restart can safely
        # rebuild from authoritative records without awarding or deducting chips.
        with db:
            db.execute('DELETE FROM result_facts')
            db.execute('DELETE FROM player_result_totals')
            db.execute('INSERT INTO result_facts '+FACTS)
            db.execute('INSERT INTO result_projection_state VALUES(1)')

    initialize_game_totals(db)


def players(db):
    return {r['user_id']:dict(r) for r in db.execute('SELECT * FROM player_result_totals')}


def progress(db,uid,start):
    row=db.execute('''SELECT count(*) AS play3,count(DISTINCT game_type) AS variety,
        COALESCE(sum(profit>0),0) AS win1 FROM result_facts
        WHERE user_id=? AND finished_at>=? AND finished_at<? AND qualified=1''',(uid,start,start+86400)).fetchone()
    return dict(row)


def initialize_game_totals(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS player_game_totals(user_id INTEGER NOT NULL,game_type TEXT NOT NULL,
        hands INTEGER NOT NULL CHECK(hands>=0),PRIMARY KEY(user_id,game_type));
    CREATE TRIGGER IF NOT EXISTS project_game_insert AFTER INSERT ON result_facts WHEN NEW.qualified=1 BEGIN
        INSERT INTO player_game_totals VALUES(NEW.user_id,NEW.game_type,1)
        ON CONFLICT(user_id,game_type) DO UPDATE SET hands=hands+1;
    END;
    CREATE TRIGGER IF NOT EXISTS project_game_delete AFTER DELETE ON result_facts WHEN OLD.qualified=1 BEGIN
        UPDATE player_game_totals SET hands=hands-1 WHERE user_id=OLD.user_id AND game_type=OLD.game_type;
        DELETE FROM player_game_totals WHERE user_id=OLD.user_id AND game_type=OLD.game_type AND hands=0;
    END;
    """)
    if not db.execute('SELECT 1 FROM result_projection_state WHERE version=2').fetchone():
        with db:
            db.execute('DELETE FROM player_game_totals')
            db.execute('INSERT INTO player_game_totals SELECT user_id,game_type,count(*) FROM result_facts WHERE qualified=1 GROUP BY user_id,game_type')
            db.execute('INSERT INTO result_projection_state VALUES(2)')


def game_counts(db,uid):
    return {r['game_type']:r['hands'] for r in db.execute('SELECT game_type,hands FROM player_game_totals WHERE user_id=?',(uid,))}
