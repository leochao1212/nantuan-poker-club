"""Game rules, private views and conserved virtual points for the new tables."""
from contextlib import closing
import json,random,sqlite3,time,unittest
from unittest.mock import patch
import arcade_engine as a,poker_engine as p,online,wallet
from test_app import ServerTestCase
from test_realtime import Stream


def room(kind,count=2,stake=10,stack=1000):
    r=a.new_room('Synthetic table',1,kind,stack,stake)
    for uid in range(1,count+1):a.sit(r,uid,f'P{uid}',100)
    return r


def shoe(draws):
    # Pop order is explicit; six decks retain enough cards for all split hands.
    return list(p.DECK)*6+list(reversed(draws))


def points(r):
    return r['bank']+sum(s['stack'] for s in r['seats'])+(sum(q['contribution'] for q in r['hand']['players']) if r['status']=='playing' else 0)


class BigTwo(unittest.TestCase):
    def test_combination_types_and_strength(self):
        self.assertGreater(a.big2_score(['2c']),a.big2_score(['As']))
        self.assertGreater(a.big2_score(['3s']),a.big2_score(['3h']))
        combos=[['3d','4c','5h','6s','7c'],['3d','5d','7d','9d','Jd'],['3d','3c','3h','4d','4s'],['3d','3c','3h','3s','4s'],['3d','4d','5d','6d','7d']]
        self.assertEqual(sorted(combos,key=a.big2_score),combos)
        for bad in ([],['3d','3d'],['3d','4d'],['3d','4d','5d'],['Ac','2d','3h','4s','5c'],[{}]):
            with self.assertRaises(p.RuleError):a.big2_score(bad)

    def test_complete_deal_first_card_and_card_privacy(self):
        r=room('big2',4);a.start_hand(r,101,deck=p.DECK)
        cards=[c for q in r['hand']['players'] for c in q['cards']]
        self.assertEqual(len(set(cards)),52)
        actor=r['hand']['actor'];v=a.public_view(r,actor)
        self.assertNotIn('deck',v['hand'])
        self.assertEqual(sum(len(q['cards']) for q in v['hand']['players']),13)
        self.assertEqual(sum(len(q['cards']) for q in a.public_view(r,-1)['hand']['players']),0)
        own=next(q for q in r['hand']['players'] if q['user_id']==actor)
        with self.assertRaises(p.RuleError):a.act(r,actor,'play',102,{'cards':[next(c for c in own['cards'] if c!=r['hand']['first_card'])]})
        a.act(r,actor,'play',102,{'cards':[r['hand']['first_card']]})
        for _ in range(3):a.act(r,r['hand']['actor'],'pass',103)
        self.assertEqual(r['hand']['actor'],actor);self.assertFalse(r['hand']['current_play'])

    def test_capacity_ownership_sizes_and_minimum_players(self):
        r=room('big2',4)
        with self.assertRaises(p.RuleError):a.sit(r,5,'Extra',100)
        a.start_hand(r,101)
        uid=r['hand']['actor'];a.act(r,uid,'play',102,{'cards':[r['hand']['first_card']]})
        q=a._player(r,r['hand']['actor'])
        with self.assertRaises(p.RuleError):a.act(r,q['user_id'],'play',102,{'cards':['invalid']})
        with self.assertRaises(p.RuleError):a.start_hand(room('big2',1),101)

    def test_automatic_round_terminates_conserves_and_can_restart(self):
        for count in (4,):
            r=room('big2',count,stack=10000);before=points(r);a.start_hand(r,101)
            for s in r['seats']:s['away']=True
            self.assertTrue(a.tick(r,102));self.assertEqual(r['status'],'waiting');self.assertEqual(points(r),before)
            self.assertEqual(sum(x['profit'] for x in r['hand']['results']),0)
            for s in r['seats']:s['away']=False
            a.start_hand(r,106);self.assertEqual(r['hand_no'],2)

    def test_leaving_keeps_ante_and_settles_one_winner(self):
        r=room('big2',4);a.start_hand(r,101)
        for uid in (1,3,4):a.leave(r,uid,102)
        self.assertEqual(r['status'],'waiting');self.assertIsNone(p.seated(r,1))
        self.assertEqual(r['departures'][0]['stack'],480)
        self.assertEqual(p.seated(r,2)['stack'],2560)


class Blackjack(unittest.TestCase):
    def test_soft_aces(self):
        self.assertEqual(a.blackjack_total(['As','Ah','9d']),21)
        self.assertEqual(a.blackjack_total(['As','Ah','9d','Kd']),21)
        self.assertEqual(a.blackjack_total(['As','6c']),17)

    def test_natural_three_to_two_and_dealer_private_card(self):
        r=room('blackjack',1);before=points(r)
        a.start_hand(r,101,shoe(['As','9d','Kh','8c']))
        self.assertEqual(r['status'],'waiting');self.assertEqual(p.seated(r,1)['stack'],1015);self.assertEqual(points(r),before)
        r=room('blackjack',1);a.start_hand(r,101,shoe(['9s','6d','7h','8c']))
        self.assertIsNone(a.public_view(r,1)['hand']['dealer'][1])
        self.assertNotIn('deck',a.public_view(r,-1)['hand'])

    def test_dealer_peeks_blackjack_before_double_or_split(self):
        r=room('blackjack',1);a.start_hand(r,101,shoe(['8s','As','8h','Kd']))
        self.assertEqual(r['status'],'waiting');self.assertEqual(p.seated(r,1)['stack'],990)
        self.assertIsNone(a.legal_actions(r,1))
        r=room('blackjack',1);a.start_hand(r,101,shoe(['As','Ah','Ks','Kd']))
        self.assertEqual(p.seated(r,1)['stack'],1000)

    def test_dealer_stands_on_soft_seventeen_and_pushes(self):
        r=room('blackjack',1);a.start_hand(r,101,shoe(['Ts','As','7h','6d','Kd']))
        a.act(r,1,'stand',102)
        self.assertEqual(len(r['hand']['dealer']),2);self.assertEqual(p.seated(r,1)['stack'],1000)

    def test_double_takes_one_card_and_stops(self):
        r=room('blackjack',1);before=points(r);a.start_hand(r,101,shoe(['5s','9d','6h','8c','Td']))
        a.act(r,1,'double',102)
        self.assertEqual(r['status'],'waiting');self.assertEqual(len(r['hand']['players'][0]['hands'][0]['cards']),3)
        self.assertEqual(p.seated(r,1)['stack'],1020);self.assertEqual(points(r),before)

    def test_split_aces_one_card_and_no_blackjack_bonus(self):
        r=room('blackjack',1);a.start_hand(r,101,shoe(['As','9d','Ah','8c','Td','Kc']))
        a.act(r,1,'split',102)
        self.assertEqual(r['status'],'waiting');self.assertEqual(p.seated(r,1)['stack'],1020)
        self.assertTrue(all(h['split_aces'] and len(h['cards'])==2 for h in r['hand']['players'][0]['hands']))

    def test_split_limit_insufficient_stack_and_timeout(self):
        r=room('blackjack',1,stack=10);a.start_hand(r,101,shoe(['8s','9d','8h','8c']))
        self.assertEqual(a.legal_actions(r,1)['actions'],['hit','stand'])
        a.tick(r,132);self.assertEqual(r['status'],'waiting');self.assertTrue(p.seated(r,1)['away'])
        r=room('blackjack',1);a.start_hand(r,101,shoe(['8s','9d','8h','8c']+['8d']*12))
        for _ in range(3):a.act(r,1,'split',102)
        self.assertEqual(len(r['hand']['players'][0]['hands']),4)
        self.assertNotIn('split',a.legal_actions(r,1)['actions'])

    def test_departure_and_random_rounds_conserve_bank_and_players(self):
        for seed in range(25):
            r=room('blackjack',6);before=points(r);a.start_hand(r,101)
            while r['status']=='playing':
                uid=r['hand']['actor'];h=a._player(r,uid)['hands'][r['hand']['active_index']]
                a.act(r,uid,'hit' if a.blackjack_total(h['cards'])<16 else 'stand',102)
            self.assertEqual(points(r),before)
        r=room('blackjack',1);a.start_hand(r,101,shoe(['9s','9d','7h','8c']))
        a.leave(r,1,102);self.assertEqual(r['status'],'closed');self.assertEqual(len(r['departures']),1)


class Roulette(unittest.TestCase):
    def test_zero_color_and_all_outside_bets(self):
        for kind in ('red','black','odd','even','low','high','dozen1','dozen2','dozen3','column1','column2','column3'):
            self.assertFalse(a.roulette_wins({'kind':kind},0))
        for number in range(1,37):
            self.assertNotEqual(a.roulette_wins({'kind':'red'},number),a.roulette_wins({'kind':'black'},number))
            self.assertEqual(sum(a.roulette_wins({'kind':f'dozen{i}'},number) for i in range(1,4)),1)
            self.assertEqual(sum(a.roulette_wins({'kind':f'column{i}'},number) for i in range(1,4)),1)

    def test_straight_up_red_and_multiple_bets_payout(self):
        r=room('roulette',2);before=points(r);a.start_hand(r,101)
        a.act(r,1,'bet',102,{'bets':[{'kind':'number','number':1,'amount':10},{'kind':'red','amount':10}]})
        self.assertEqual(p.seated(r,1)['stack'],980)
        with patch.object(a.secrets,'randbelow',return_value=1):a.act(r,2,'skip',102)
        self.assertEqual(p.seated(r,1)['stack'],1360);self.assertEqual(points(r),before)
        self.assertEqual(r['hand']['number'],1)

    def test_invalid_bets_do_not_spend_points(self):
        r=room('roulette',1);a.start_hand(r,101)
        for bets in ([],[{'kind':'number','number':37,'amount':10}],[{'kind':'red','amount':True}],[{'kind':'red','amount':0}],[{'kind':'red','amount':5.5}],[{'kind':'red','amount':1010}],[{'kind':'red','amount':10}]*2):
            with self.assertRaises(p.RuleError):a.act(r,1,'bet',102,{'bets':bets})
            self.assertEqual(a._player(r,1)['stack'],1000)
        self.assertIn(1,r['hand']['pending'])

    def test_timeout_is_no_bet_and_submitted_bet_survives_leaving(self):
        r=room('roulette',2);before=points(r);a.start_hand(r,101)
        a.act(r,1,'bet',102,{'bets':[{'kind':'number','number':0,'amount':10}]});a.leave(r,1,103)
        self.assertTrue(p.seated(r,1)['leaving'])
        with patch.object(a.secrets,'randbelow',return_value=0):a.tick(r,132)
        self.assertEqual(r['departures'][0]['stack'],1350)
        self.assertEqual(r['bank']+sum(s['stack'] for s in r['seats'])+r['departures'][0]['stack'],before)
        self.assertEqual(p.seated(r,2)['stack'],1000)

    def test_bank_reserve_and_odd_blackjack_stake_are_rejected(self):
        r=room('roulette',6);r['bank']=1
        with self.assertRaises(p.RuleError):a.start_hand(r,101)
        self.assertEqual(r['status'],'waiting')
        with self.assertRaises(p.RuleError):room('blackjack',1,stake=3)


class ArcadeStorage(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES("invite_code","TESTONLY");')
        self.db.executemany('INSERT INTO users VALUES(?,?,?,?)',[(i,f'u{i}',f'P{i}','2026-10-20') for i in range(1,5)])
        online.initialize(self.db);self.users={i:{'id':i,'nickname':f'P{i}','username':f'u{i}'} for i in range(1,5)}

    def call(self,rid,uid,verb,clock=102,**data):
        r=online.get_room(self.db,rid)
        return online.mutate(self.db,f'/api/online/rooms/{rid}/{verb}',{'revision':r['revision'],**data},self.users[uid],clock)

    def test_three_kinds_use_existing_wallet_receipts_and_history(self):
        for kind in a.CATALOG:
            before=wallet.view(self.db,1,100)['total']
            rid=online.mutate(self.db,'/api/online/rooms',{'name':kind,'game_type':kind,'operation_id':f'create_{kind}_000001'},self.users[1],100)['id']
            self.assertEqual(wallet.view(self.db,1,100)['total'],before)
            self.assertEqual(online.current_room(self.db,1),rid)
            if kind=='big2':
                for uid in (2,3,4):self.call(rid,uid,'join',101)
            self.call(rid,1,'start',102,**({'stake':10,'expected_hand_number':1} if kind=='blackjack' else {}))
            r=online.get_room(self.db,rid)
            if r['status']=='playing':
                for s in r['seats']:s['away']=True
                a.tick(r,140);online.save(self.db,r,140)
            view=online.room_view(self.db,rid,1,141)
            self.assertTrue(view['history']);self.assertEqual(view['game_type'],kind)
            for s in list(view['seats']):self.call(rid,s['user_id'],'leave',142,operation_id=f'leave_{kind}_{s["user_id"]}_0001')
            self.assertIsNone(online.current_room(self.db,1))
            self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands WHERE room_id=?',(rid,)).fetchone()[0],1)

    def test_roulette_parallel_turn_receipts_and_cross_game_seat_limit(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'name':'Roulette','game_type':'roulette'},self.users[1],100)['id']
        self.call(rid,2,'join',101);self.call(rid,1,'start',102)
        r=online.get_room(self.db,rid)
        payload={'action':'bet','bets':[{'kind':'red','amount':10}],'hand_id':r['hand']['id'],'turn_id':r['hand']['turn_id'],'operation_id':'roulette_bet_once_0001'}
        self.call(rid,1,'action',103,**payload);self.call(rid,1,'action',104,**payload)
        self.assertEqual(p.seated(online.get_room(self.db,rid),1)['stack'],990)
        result=self.call(rid,2,'action',105,action='skip',hand_id=r['hand']['id'],turn_id=r['hand']['turn_id'])
        self.assertFalse(result.get('conflict'))
        with self.assertRaises(p.RuleError):online.mutate(self.db,'/api/online/rooms',{'name':'Holdem'},self.users[1],106)


class ArcadeAPI(ServerTestCase):
    def test_shared_room_push_chat_and_server_only_outcome(self):
        first,second=self.clients[:2]
        self.assertEqual(first.call('/arcade.js')[0],200)
        self.assertEqual(first.call('/arcade-motion.js')[0],200)
        self.assertEqual(first.call('/arcade.css')[0],200)
        first.call('/api/register',{'username':'arcade_a','nickname':'A','password':'password123'})
        invite=first.call('/api/state')[1]['invite_code']
        second.call('/api/register',{'username':'arcade_b','nickname':'B','password':'password123','invite_code':invite})
        for i,client in enumerate(self.clients[2:4],2):
            self.assertEqual(client.call('/api/register',{'username':f'arcade_{i}','nickname':str(i),'password':'password123','invite_code':invite})[0],200)
        for kind in ('roulette','blackjack','big2'):
            status,result=first.call('/api/online/rooms',{'name':kind,'game_type':kind,'stake':10,'operation_id':f'api_create_{kind}_001'})
            self.assertEqual(status,200,result);rid=result['id'];path=f'/api/online/rooms/{rid}'
            state=first.call(path)[1]
            self.assertEqual(state['game_type'],kind)
            self.assertEqual(second.call(f'/api/social/rooms/{rid}/chat',{'nonce':f'spectator_{kind}_0001','message':'觀戰聊天'})[0],200)
            second.call(path+'/join',{'revision':state['revision']})
            if kind=='big2':
                for client in self.clients[2:4]:client.call(path+'/join',{'revision':first.call(path)[1]['revision']})
            if kind=='blackjack':
                self.assertEqual(second.call(path+'/start',{'revision':first.call(path)[1]['revision'],'stake':10,'expected_hand_number':1})[0],200)
                self.assertEqual(first.call(path)[1]['hand_no'],0)
            with closing(Stream(first,f'/api/online/events?presence=client&room={rid}')) as stream:
                stream.state();state=first.call(path)[1]
                self.assertEqual(first.call(path+'/start',{'revision':state['revision'],**({'stake':10,'expected_hand_number':1} if kind=='blackjack' else {})})[0],200)
                state=stream.state(state['revision']+1)
                # Public shoe counts/settings are safe; the private card order
                # must never appear as a deck field anywhere in a response.
                def check_private(value):
                    if isinstance(value,dict):
                        self.assertNotIn('deck',value)
                        for child in value.values():check_private(child)
                    elif isinstance(value,list):
                        for child in value:check_private(child)
                check_private(state)
            # Complete only this synthetic round using the same timeout engine.
            with closing(sqlite3.connect(self.db_path)) as db:
                db.row_factory=sqlite3.Row;r=online.get_room(db,rid)
                for seat in r['seats']:seat['away']=True
                a.tick(r,time.time()+31);online.save(db,r,time.time());db.commit()
            self.assertEqual(first.call(path)[1]['status'],'waiting')
            for client in (self.clients[:4] if kind=='big2' else (first,second)):
                state=client.call(path)[1];self.assertEqual(client.call(path+'/leave',{'revision':state['revision']})[0],200)
        self.assertEqual(first.call('/api/online/lobby')[1]['total_hands'],3)


if __name__=='__main__':unittest.main(verbosity=2)
