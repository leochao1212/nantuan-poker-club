"""Away auto-actions, client-confirmed liveness and offline chip conservation."""
from contextlib import closing
import json,sqlite3,time,unittest
import online,wallet,poker_engine as engine
from .test_app import ServerTestCase,Client
from .test_poker import room_with_players
from .test_realtime import Stream


class AwayTurns(unittest.TestCase):
    def flop(self,count=3):
        room=room_with_players(count);engine.start_hand(room,100)
        while room['hand']['phase']=='preflop':
            uid=room['hand']['actor'];legal=engine.legal_actions(room,uid)
            engine.act(room,uid,'check' if 'check' in legal['actions'] else 'call',101)
        return room

    def test_away_player_checks_without_waiting_another_deadline(self):
        room=self.flop();uid=room['hand']['actor'];seat=engine.seated(room,uid);seat['away']=True
        deadline=room['hand']['deadline'];amount=seat['stack']
        self.assertTrue(engine.tick(room,102))
        self.assertLess(102,deadline)
        player=next(p for p in room['hand']['players'] if p['user_id']==uid)
        self.assertEqual(player['last_action'],'過牌');self.assertFalse(player['folded'])
        self.assertEqual(seat['stack'],amount);self.assertNotEqual(room['hand']['actor'],uid)
        self.assertFalse(engine.tick(room,102))

    def test_away_player_facing_a_bet_folds_without_spending_chips(self):
        room=self.flop();uid=room['hand']['actor']
        engine.act(room,uid,'raise',102,amount=10)
        away=room['hand']['actor'];engine.seated(room,away)['away']=True
        amount=engine.seated(room,away)['stack']
        self.assertTrue(engine.tick(room,102))
        player=next(p for p in room['hand']['players'] if p['user_id']==away)
        self.assertTrue(player['folded']);self.assertEqual(player['last_action'],'棄牌')
        self.assertEqual(engine.seated(room,away)['stack'],amount)

    def test_all_away_players_check_down_without_looping_or_losing_chips(self):
        room=self.flop(6)
        for seat in room['seats']:seat['away']=True
        self.assertTrue(engine.tick(room,102))
        self.assertEqual(room['status'],'waiting');self.assertEqual(len(room['hand']['board']),5)
        self.assertEqual(sum(s['stack'] for s in room['seats']),6000)
        self.assertFalse(engine.tick(room,103))

    def test_timeout_marks_away_then_next_away_turn_needs_no_new_wait(self):
        room=self.flop();uid=room['hand']['actor']
        self.assertTrue(engine.tick(room,room['hand']['deadline']))
        self.assertTrue(engine.seated(room,uid)['away'])
        while room['hand']['actor']!=uid:
            actor=room['hand']['actor'];engine.act(room,actor,'check',132)
        self.assertGreater(room['hand']['deadline'],132)
        self.assertTrue(engine.tick(room,132))
        self.assertNotEqual(room['hand']['actor'],uid)

    def test_away_seat_still_waits_for_return_before_next_hand(self):
        room=self.flop();away=room['hand']['actor'];engine.seated(room,away)['away']=True
        while room['status']=='playing':
            engine.tick(room,102)
            if room['status']=='playing':engine.act(room,room['hand']['actor'],'check',102)
        engine.start_hand(room,106)
        self.assertNotIn(away,[p['user_id'] for p in room['hand']['players']])


class OfflineSeats(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT)')
        self.db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute("INSERT INTO settings VALUES('invite_code','TESTONLY')")
        self.db.executemany('INSERT INTO users VALUES(?,?,?,?)',[(i,f'p{i}',f'P{i}','2026-10-20') for i in range(1,5)])
        online.initialize(self.db)
        # Keep this transaction scenario at a fixed 3,000-point budget.
        from . import scenario_budget
        scenario_budget(self.db)
        self.users={i:{'id':i,'username':f'p{i}','nickname':f'P{i}'} for i in range(1,5)}
        self.rid=online.mutate(self.db,'/api/online/rooms',{'name':'Offline test'},self.users[1],100)['id']
        self.path=f'/api/online/rooms/{self.rid}'
        self.call('join',2,100)
        self.fresh(100)

    def room(self):return online.get_room(self.db,self.rid)
    def call(self,verb,uid,clock,**data):
        room=self.room()
        return online.mutate(self.db,self.path+'/'+verb,{'revision':room['revision'],**data},self.users[uid],clock)
    def fresh(self,clock,except_uid=None):
        for uid in self.users:
            if uid!=except_uid:online.presence(self.db,uid,self.rid,clock)
    def stale(self,uid,at=100):
        self.db.execute('UPDATE poker_presence SET last_seen=? WHERE user_id=?',(at,uid))
    def total(self,clock):return sum(wallet.view(self.db,uid,clock)['total'] for uid in self.users)

    def test_waiting_seat_gets_grace_then_refund_exactly_once(self):
        self.fresh(220,except_uid=2)
        self.assertFalse(online.maintenance(self.db,219.99))
        self.assertIsNotNone(engine.seated(self.room(),2))
        self.assertTrue(online.maintenance(self.db,220))
        self.assertIsNone(engine.seated(self.room(),2));self.assertEqual(wallet.view(self.db,2,220)['balance'],3000)
        online.maintenance(self.db,221)
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_sessions WHERE user_id=2').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=2 AND kind='leave'").fetchone()[0],1)
        self.assertEqual(self.total(221),12000)

    def test_reconnect_and_queued_maintenance_do_not_evict_too_early(self):
        self.fresh(230,except_uid=2)
        self.assertFalse(online.maintenance(self.db,230,due_at=219))
        online.heartbeat(self.db,2,self.rid,219.5)
        self.assertFalse(online.maintenance(self.db,230))
        self.assertIsNotNone(engine.seated(self.room(),2))

    def test_owner_is_reassigned_and_last_departure_closes_room(self):
        self.fresh(220,except_uid=1)
        online.maintenance(self.db,220)
        self.assertEqual(self.room()['owner_id'],2)
        online.maintenance(self.db,340)
        self.assertEqual(self.room()['status'],'closed');self.assertEqual(self.total(340),12000)

    def test_offline_non_actor_folds_preserving_other_turn_deadline(self):
        self.call('join',3,100);self.call('start',1,210)
        before=self.room();target=next(p['user_id'] for p in before['hand']['players'] if p['user_id']!=before['hand']['actor'])
        self.fresh(220,except_uid=target);self.stale(target)
        online.maintenance(self.db,220)
        room=self.room();player=next(p for p in room['hand']['players'] if p['user_id']==target)
        self.assertTrue(player['folded']);self.assertTrue(engine.seated(room,target)['leaving'])
        self.assertEqual(room['hand']['actor'],before['hand']['actor']);self.assertEqual(room['hand']['deadline'],before['hand']['deadline'])
        self.assertEqual(self.total(220),12000)

    def test_offline_allin_keeps_eligibility_and_refunds_after_showdown(self):
        self.call('join',3,100);self.call('join',4,100);self.call('start',1,210)
        room=self.room();target=room['hand']['actor']
        self.call('action',target,151,hand_id=room['hand']['id'],action='allin')
        for clock in (235,259):
            room=self.room();self.call('action',room['hand']['actor'],clock,hand_id=room['hand']['id'],action='call')
        self.fresh(271,except_uid=target)
        online.maintenance(self.db,271)
        room=self.room();player=next(p for p in room['hand']['players'] if p['user_id']==target)
        self.assertFalse(player['folded']);self.assertTrue(engine.seated(room,target)['leaving'])
        self.assertEqual(room['status'],'playing')
        self.call('action',room['hand']['actor'],272,hand_id=room['hand']['id'],action='call')
        room=self.room();self.assertEqual(room['status'],'waiting');self.assertIsNone(engine.seated(room,target))
        final=next(r for r in room['hand']['results'] if r['user_id']==target)
        self.assertEqual(wallet.view(self.db,target,272)['balance'],2000+1000+final['profit'])
        self.assertEqual(self.total(272),12000)

    def test_push_snapshots_do_not_fabricate_client_activity(self):
        online.room_view(self.db,self.rid,2,219,touch_presence=False)
        online.lobby(self.db,self.users[2],219,touch_presence=False)
        self.assertEqual(self.db.execute('SELECT last_seen FROM poker_presence WHERE user_id=2').fetchone()[0],100)
        self.fresh(220,except_uid=2);online.maintenance(self.db,220)
        self.assertIsNone(engine.seated(self.room(),2))

    def test_heartbeat_validates_room_and_refreshes_only_client(self):
        for rid in (True,-1,0,'1',999):
            with self.assertRaises(engine.RuleError):online.heartbeat(self.db,2,rid,210)
        online.heartbeat(self.db,2,None,210)
        self.assertEqual(self.db.execute('SELECT last_seen FROM poker_presence WHERE user_id=2').fetchone()[0],210)
        self.assertEqual(self.db.execute('SELECT last_seen FROM poker_presence WHERE user_id=1').fetchone()[0],100)

    def test_visible_table_heartbeat_restores_only_own_seat_once(self):
        room=self.room()
        for seat in room['seats']:seat.update(away=True,away_reason='timeout')
        online.save(self.db,room,110);revision=self.room()['revision'];total=self.total(110)
        # A background stream snapshot or a visit to the lobby cannot resume a seat.
        online.room_view(self.db,self.rid,2,111,touch_presence=False)
        self.assertFalse(online.heartbeat(self.db,2,None,112)['resumed'])
        self.assertTrue(engine.seated(self.room(),2)['away'])
        response=online.heartbeat(self.db,2,self.rid,113)
        self.assertTrue(response['resumed']);self.assertEqual(response['offline_grace_seconds'],120)
        room=self.room();self.assertFalse(engine.seated(room,2)['away'])
        self.assertNotIn('away_reason',engine.seated(room,2))
        self.assertTrue(engine.seated(room,1)['away']);self.assertEqual(room['revision'],revision+1)
        self.assertFalse(online.heartbeat(self.db,2,self.rid,114)['resumed'])
        self.assertEqual(self.room()['revision'],revision+1);self.assertEqual(self.total(114),total)

    def test_resume_does_not_unfold_a_hand_or_reset_another_players_deadline(self):
        self.call('join',3,100);self.call('start',1,110)
        room=self.room();uid=room['hand']['actor'];deadline=room['hand']['deadline']
        online.maintenance(self.db,deadline)
        room=self.room();self.assertTrue(engine.seated(room,uid)['away'])
        player=next(p for p in room['hand']['players'] if p['user_id']==uid)
        self.assertTrue(player['folded']);hand=json.loads(json.dumps(room['hand']))
        self.assertTrue(online.heartbeat(self.db,uid,self.rid,deadline+1)['resumed'])
        self.assertEqual(self.room()['hand'],hand)
        self.assertFalse(engine.seated(self.room(),uid)['away'])
        self.assertEqual(self.total(deadline+1),12000)

    def test_return_does_not_cancel_explicit_departure_or_revive_departed_seat(self):
        self.call('join',3,100);self.call('start',1,110)
        room=self.room();uid=room['hand']['actor']
        self.call('leave',uid,111)
        room=self.room();seat=engine.seated(room,uid);seat['away']=True
        online.save(self.db,room,112)
        self.assertFalse(online.heartbeat(self.db,uid,self.rid,113)['resumed'])
        self.assertTrue(engine.seated(self.room(),uid)['leaving'])
        # A spectator cannot create a seat or debit their wallet by sending presence.
        self.assertFalse(online.heartbeat(self.db,4,self.rid,114)['resumed'])
        self.assertIsNone(engine.seated(self.room(),4));self.assertEqual(self.total(114),12000)

    def test_all_games_can_start_after_automatic_return(self):
        for kind in ('holdem','big2','blackjack','roulette','baccarat','slot','mines','tower','dice'):
            with self.subTest(game=kind):
                self.db.execute('SAVEPOINT game_return')
                try:
                    self.db.execute("UPDATE poker_rooms SET status='closed'")
                    rid=online.mutate(self.db,'/api/online/rooms',{'game_type':kind},self.users[1],110)['id']
                    path=f'/api/online/rooms/{rid}'
                    room=online.get_room(self.db,rid)
                    if room.get('capacity',6)>1:
                        online.mutate(self.db,path+'/join',{'revision':room['revision']},self.users[2],110)
                    if kind=='big2':
                        for uid in (3,4):online.mutate(self.db,path+'/join',{'revision':online.get_room(self.db,rid)['revision']},self.users[uid],110)
                    room=online.get_room(self.db,rid);engine.seated(room,1).update(away=True,away_reason='timeout')
                    online.save(self.db,room,111)
                    self.assertTrue(online.heartbeat(self.db,1,rid,112)['resumed'])
                    room=online.get_room(self.db,rid)
                    if kind=='blackjack':
                        online.mutate(self.db,path+'/start',{'revision':room['revision'],'stake':10,'expected_hand_number':1},self.users[2],113)
                        self.assertEqual(online.get_room(self.db,rid)['hand_no'],0)
                        room=online.get_room(self.db,rid)
                    data={'revision':room['revision'],**({'stake':10,'expected_hand_number':1} if kind=='blackjack' else {})}
                    if kind=='dice':data['bets']=[{'key':'big','amount':10}]
                    result=online.mutate(self.db,path+'/start',data,self.users[1],113)
                    self.assertFalse(result.get('conflict'));self.assertEqual(online.get_room(self.db,rid)['hand_no'],1)
                finally:
                    self.db.execute('ROLLBACK TO game_return');self.db.execute('RELEASE game_return')


class PresenceAPI(ServerTestCase):
    def test_client_heartbeat_stream_and_offline_departure(self):
        a,b=self.clients[:2]
        self.assertEqual(a.call('/api/register',{'username':'presence_a','nickname':'A','password':'password123'})[0],200)
        code=a.call('/api/state')[1]['invite_code']
        self.assertEqual(b.call('/api/register',{'username':'presence_b','nickname':'B','password':'password123','invite_code':code})[0],200)
        rid=a.call('/api/online/rooms',{'name':'Presence test'})[1]['id'];path=f'/api/online/rooms/{rid}'
        b.call(path+'/join',{'revision':a.call(path)[1]['revision']})
        self.assertEqual(Client(self.base).call('/api/online/presence',{})[0],401)
        self.assertEqual(a.call('/api/online/presence',{'room_id':True})[0],400)
        with closing(Stream(a,f'/api/online/events?presence=client&room={rid}')) as stream:
            state=stream.state();old=time.time()-40
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute('UPDATE poker_presence SET last_seen=? WHERE user_id=1',(old,));db.commit()
            self.assertEqual(b.call(path+'/return',{'revision':state['revision']})[0],200)
            stream.state(state['revision']+1)
            with closing(sqlite3.connect(self.db_path)) as db:
                self.assertEqual(db.execute('SELECT last_seen FROM poker_presence WHERE user_id=1').fetchone()[0],old)
            self.assertEqual(a.call('/api/online/presence',{'room_id':rid,'user_id':2})[0],200)
            with closing(sqlite3.connect(self.db_path)) as db:
                room=json.loads(db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0])
                next(s for s in room['seats'] if s['user_id']==1).update(away=True,away_reason='timeout')
                db.execute('UPDATE poker_rooms SET state=? WHERE id=?',(json.dumps(room),rid));db.commit()
            status,resumed=a.call('/api/online/presence',{'room_id':rid})
            self.assertEqual(status,200);self.assertTrue(resumed['resumed'])
            self.assertEqual(resumed['offline_grace_seconds'],120)
            pushed=stream.state(state['revision']+2)
            self.assertFalse(next(s for s in pushed['seats'] if s['user_id']==1)['away'])
            with closing(sqlite3.connect(self.db_path)) as db:
                self.assertGreater(db.execute('SELECT last_seen FROM poker_presence WHERE user_id=1').fetchone()[0],old+30)
                db.execute('UPDATE poker_presence SET last_seen=? WHERE user_id=2',(time.time()-121,));db.commit()
                room=json.loads(db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0])
                next(s for s in room['seats'] if s['user_id']==2)['joined_at']=time.time()-121
                db.execute('UPDATE poker_rooms SET state=? WHERE id=?',(json.dumps(room),rid));db.commit()
            state=a.call(path)[1]
            self.assertNotIn(2,[seat['user_id'] for seat in state['seats']])
            self.assertEqual(b.call('/api/online/lobby')[1]['wallet']['balance'],10000)
        self.assertEqual(a.call('/api/online/presence',{},origin='https://evil.invalid')[0],403)


if __name__=='__main__':unittest.main(verbosity=2)
