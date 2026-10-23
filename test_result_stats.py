"""Read projections must match authoritative results without moving any chips."""
import json,sqlite3,unittest
import result_stats,rewards,wallet,online

class ResultProjections(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE poker_hands(id INTEGER PRIMARY KEY,public_state TEXT,finished_at REAL);
          CREATE TABLE poker_results(hand_id INTEGER,user_id INTEGER,profit INTEGER,payout INTEGER,rank TEXT,PRIMARY KEY(hand_id,user_id));''')
        self.now=1792512000
        result_stats.initialize(self.db)

    def record(self,ident=1,uid=1,profit=10,kind='slot',contribution=10,selected=None,clock=None):
        hand=dict(game_type=kind,players=[dict(user_id=uid,contribution=contribution)],selected=selected)
        self.db.execute('INSERT INTO poker_hands VALUES(?,?,?)',(ident,json.dumps(hand),self.now if clock is None else clock))
        self.db.execute('INSERT INTO poker_results VALUES(?,?,?,?,?)',(ident,uid,profit,profit+contribution,'fixture'))

    def check_totals(self):
        expected={r['user_id']:dict(r) for r in self.db.execute('SELECT user_id,count(*) AS hands,sum(profit) AS profit,sum(profit>0) AS wins FROM poker_results GROUP BY user_id')}
        self.assertEqual(result_stats.players(self.db),expected)

    def test_insert_update_delete_and_rollback_follow_authority(self):
        self.record();self.record(2,profit=-5);self.record(3,uid=2,profit=0);self.check_totals();self.db.commit()
        self.db.execute('UPDATE poker_results SET user_id=2,profit=-100 WHERE hand_id=1');self.check_totals()
        self.db.execute('DELETE FROM poker_results WHERE hand_id=2');self.check_totals()
        self.db.rollback();self.check_totals()
        self.db.execute('DELETE FROM poker_results');self.check_totals();self.assertEqual(self.db.execute('SELECT count(*) FROM result_facts').fetchone()[0],0)

    def test_daily_missions_preserve_eligibility_and_taipei_boundary(self):
        self.record(1,kind='slot');self.record(2,kind='tower',selected=[0]);self.record(3,kind='mines',selected=[])
        self.record(4,kind='baccarat',contribution=0);self.record(5,kind='big2',profit=-10)
        start=__import__('datetime').datetime.fromisoformat(wallet.day(self.now)).replace(tzinfo=wallet.TAIPEI).timestamp()
        self.record(6,clock=start-1);self.record(7,clock=start+86400)
        self.assertEqual(rewards._progress(self.db,1,self.now),dict(play3=3,variety=3,win1=2))
        self.assertEqual(rewards._progress(self.db,1,start+86400),dict(play3=1,variety=1,win1=1))
        self.check_totals()

    def test_hand_corrections_invalidate_qualified_facts(self):
        self.record(kind='tower',selected=[])
        self.assertEqual(rewards._progress(self.db,1,self.now)['play3'],0)
        hand={'game_type':'tower','players':[{'user_id':1,'contribution':10}],'selected':[2]}
        self.db.execute('UPDATE poker_hands SET public_state=? WHERE id=1',(json.dumps(hand),))
        self.assertEqual(rewards._progress(self.db,1,self.now)['play3'],1);self.check_totals()
        self.db.execute('UPDATE poker_hands SET finished_at=? WHERE id=1',(self.now+86400,))
        self.assertEqual(rewards._progress(self.db,1,self.now)['play3'],0)

    def test_existing_history_backfill_is_idempotent_and_read_only_to_originals(self):
        self.record();self.record(2,uid=2,profit=-10);self.db.commit()
        originals=list(self.db.execute('SELECT * FROM poker_results'))
        self.db.execute('DELETE FROM result_projection_state');self.db.execute('DELETE FROM result_facts');self.db.commit()
        result_stats.initialize(self.db);self.check_totals();self.assertEqual(list(self.db.execute('SELECT * FROM poker_results')),originals)
        before=[tuple(r) for r in self.db.execute('SELECT * FROM result_facts')]
        result_stats.initialize(self.db);self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM result_facts')],before);self.check_totals()

    def test_projected_reads_avoid_history_json_and_use_daily_index(self):
        self.record();queries=[];self.db.set_trace_callback(queries.append)
        rewards._progress(self.db,1,self.now);result_stats.players(self.db)
        self.assertFalse(any('json_' in q.lower() or 'poker_hands' in q.lower() for q in queries))
        plan=' '.join(r[3] for r in self.db.execute('EXPLAIN QUERY PLAN SELECT * FROM result_facts WHERE user_id=? AND finished_at>=? AND finished_at<?',(1,self.now,self.now+86400)))
        self.assertIn('result_facts_daily',plan)

    def test_room_money_projection_matches_stacks_and_committed_pots(self):
        self.db.execute('CREATE TABLE poker_rooms(id INTEGER PRIMARY KEY,status TEXT,state TEXT)')
        fixtures=[dict(status='playing',seats=[dict(user_id=1,stack=100),dict(user_id=2,stack=70)],hand=dict(players=[dict(user_id=1,contribution=30),dict(user_id=2,contribution=60)])),
                  dict(status='waiting',seats=[dict(user_id=3,stack=500)],hand=dict(players=[dict(user_id=3,contribution=999)])),
                  dict(status='closed',seats=[dict(user_id=4,stack=700)],hand={})]
        for i,r in enumerate(fixtures,1):self.db.execute('INSERT INTO poker_rooms VALUES(?,?,?)',(i,r['status'],json.dumps(r)))
        self.assertEqual(wallet._in_play(self.db),{1:130,2:130,3:500})
        self.assertEqual(online.current_room(self.db,1),1);self.assertEqual(online.current_room(self.db,3),2)
        self.assertIsNone(online.current_room(self.db,4));self.assertIsNone(online.current_room(self.db,99))

if __name__=='__main__':unittest.main()
