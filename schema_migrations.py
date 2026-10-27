"""One-time data close-outs. Retired engines and their tests are not shipped."""
import json
import wallet


def apply(db,clock):
    key='content-closeout-20261027'
    if db.execute('SELECT 1 FROM wallet_meta WHERE key=?',(key,)).fetchone():return
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.execute('SAVEPOINT close_retired_content')
    try:
        # Paid, unresolved operations are refunded, never replayed as a game.
        if 'fishing_projectiles' in tables:
            for r in db.execute("SELECT id,user_id,data FROM fishing_projectiles WHERE state='flying'").fetchall():
                amount=int(json.loads(r['data']).get('stake',0))
                if amount>0 and not db.execute('SELECT 1 FROM wallet_ledger WHERE user_id=? AND event_key=?',(r['user_id'],'fish:projectile:'+str(r['id']))).fetchone():
                    wallet.transfer(db,r['user_id'],amount,'feature_closeout','closeout:projectile:'+str(r['id']),clock,game=True)
            db.execute("UPDATE fishing_projectiles SET state='retired' WHERE state='flying'")
        if 'fishing_collection' in tables:
            # The old stored inventory's fixed cash-out values, not game odds.
            prices={'sardine':2,'clownfish':3,'mackerel':5,'snapper':8,'tuna':15,'ray':25,'swordfish':50,'goldfish':100}
            amounts={}
            for r in db.execute('SELECT user_id,species,stored FROM fishing_collection WHERE stored>0'):
                amounts[r['user_id']]=amounts.get(r['user_id'],0)+r['stored']*prices.get(r['species'],0)
            for uid,amount in amounts.items():
                if amount:wallet.transfer(db,uid,amount,'feature_closeout','closeout:inventory',clock)
            db.execute('UPDATE fishing_collection SET stored=0 WHERE stored>0')
        if 'fishing_casts' in tables:
            for r in db.execute('SELECT id,user_id,data FROM fishing_casts WHERE collected_at IS NULL').fetchall():
                amount=int(json.loads(r['data']).get('reward',0))
                if amount>0:wallet.transfer(db,r['user_id'],amount,'feature_closeout','fish:cast:'+r['id'],clock)
            db.execute('UPDATE fishing_casts SET collected_at=? WHERE collected_at IS NULL',(clock,))
        if 'fishing_bonus_events' in tables:
            for r in db.execute("SELECT * FROM fishing_bonus_events WHERE status='ready'").fetchall():
                data=json.loads(r['data']);pool=data['pool'];weights=sum(p['weight'] for p in pool)
                # Close an unclaimed random bonus at its recorded expected value.
                # No old RNG/bonus engine is retained or executed during removal.
                amount=data['stake']*data['rounds']*sum(p['weight']*p['multiplier'] for p in pool)//weights
                wallet.transfer(db,r['user_id'],amount,'feature_closeout','fish:bonus:'+r['id'],clock,game=True)
                data.update(gross=amount,draws=[],item=None,settled_at=clock,closed_by='feature_retirement')
                db.execute("UPDATE fishing_bonus_events SET status='settled',data=? WHERE id=?",(json.dumps(data),r['id']))
        if 'fishing_members' in tables:db.execute('DELETE FROM fishing_members')
        db.execute('INSERT INTO wallet_meta VALUES(?,?)',(key,'complete'))
        db.execute('RELEASE SAVEPOINT close_retired_content')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT close_retired_content');db.execute('RELEASE SAVEPOINT close_retired_content');raise
