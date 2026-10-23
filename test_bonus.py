"""Independent payout, confidentiality, recovery and integration checks."""
import itertools
import json
import sqlite3
import unittest
from fractions import Fraction
from math import comb
from unittest.mock import patch, call
import bonus_engine as b
import poker_engine as p
import online
import rewards
import wallet
from test_app import ServerTestCase

def room(kind,stake=100,count=1):
    r=b.new_room(kind,1,kind,10000,stake)
    for uid in range(1,count+1):b.sit(r,uid,str(uid),100)
    return r

def points(r):
    return r['bank']+sum(s['stack'] for s in r['seats'])+(sum(p['contribution'] for p in r['hand']['players']) if r['status']=='playing' else 0)+sum(s['stack'] for s in r['departures'])

def shoe(cards):return list(reversed(cards+['Tc']*10))

class Slots(unittest.TestCase):
    def test_every_outcome_and_exact_rtp(self):
        total=0
        for reels in itertools.product(range(6),repeat=3):
            expected=[77,32,20,14,10,7][reels[0]] if len(set(reels))==1 else 4 if reels[0]==reels[1] else 0
            with self.subTest(reels=reels):
                r=room('slot');before=points(r)
                with patch.object(b.secrets,'randbelow',side_effect=reels) as draw:b.start_hand(r,101)
                self.assertEqual(draw.call_args_list,[call(6)]*3)
                self.assertEqual(r['hand']['slot_payout_version'],3)
                self.assertEqual(r['hand']['results'][0]['payout'],expected*100)
                self.assertEqual(points(r),before);total+=expected
        self.assertEqual(Fraction(total,216),Fraction(35,27))
        self.assertEqual(b.SLOT_RTP,Fraction(35,27))
    def test_no_house_overdraft(self):
        r=room('slot');r['bank']=7699
        with self.assertRaises(p.RuleError):b.start_hand(r,101)
        self.assertEqual(r['hand_no'],0)

    def test_exact_house_reserve_pays_peak_at_small_and_large_stakes(self):
        for stake in (1,100,1000):
            r=room('slot',stake);r['bank']=stake*77;before=points(r)
            with patch.object(b.secrets,'randbelow',side_effect=[0,0,0]):b.start_hand(r,101)
            self.assertEqual(r['hand']['results'][0]['payout'],stake*77)
            self.assertEqual(r['hand']['results'][0]['profit'],stake*76)
            self.assertEqual(r['bank'],stake)
            self.assertEqual(points(r),before)

    def test_legacy_outcomes_keep_original_payouts_and_old_hand_is_unchanged(self):
        for reels in itertools.product(range(6),repeat=3):
            expected=[75,30,18,12,8,5][reels[0]] if len(set(reels))==1 else 2 if reels[0]==reels[1] else 0
            self.assertEqual(b.slot_multiplier(reels,1),expected)
            self.assertEqual(b.slot_multiplier(reels,2),expected+3 if expected else 0)
            self.assertEqual(b.slot_multiplier(reels),expected+2 if expected else 0)
        r=room('slot')
        with patch.object(b.secrets,'randbelow',side_effect=[0,0,0]):b.start_hand(r,101)
        old=json.loads(json.dumps(r['hand']));old.pop('slot_payout_version')
        old['results'][0].update(payout=7500,profit=7400)
        r['hand']=old;saved=json.dumps(old,sort_keys=True)
        b.public_view(r,1)
        self.assertEqual(json.dumps(r['hand'],sort_keys=True),saved)
        with self.assertRaises(p.RuleError):b.slot_multiplier([0,0,0],99)

class Risk(unittest.TestCase):
    def test_returns_match_independent_probability(self):
        for kind,limit in [('mines',5),('tower',6)]:
            for stake in [1,2,10,100,1000]:
                for k in range(1,limit+1):
                    probability=Fraction(comb(20,k),comb(25,k)) if kind=='mines' else Fraction(3,4)**k
                    gross=Fraction(stake*97,100)/probability
                    self.assertEqual(b.risk_return(kind,stake,k),gross.numerator//gross.denominator)
                    self.assertLessEqual(Fraction(b.risk_return(kind,stake,k),stake)*probability,Fraction(97,100))
    def test_mines_hidden_repeat_selection_and_cashout(self):
        r=room('mines');before=points(r);b.start_hand(r,101)
        r['hand']['hazards']=[20,21,22,23,24]
        self.assertNotIn('hazards',b.public_view(r,1)['hand']);self.assertNotIn('hazards',b.public_view(r,2)['hand'])
        for step in range(3):b.act(r,1,'pick',102+step,{'cell':step})
        with self.assertRaises(p.RuleError):b.act(r,1,'pick',105,{'cell':0})
        with self.assertRaises(p.RuleError):b.act(r,2,'cashout',105)
        b.act(r,1,'cashout',106)
        self.assertEqual(r['hand']['results'][0]['payout'],b.risk_return('mines',100,3));self.assertEqual(points(r),before)
        self.assertIn('hazards',b.public_view(r,1)['hand'])
    def test_loss_and_auto_collect_at_limit(self):
        for kind,limit in [('mines',5),('tower',6)]:
            for lose in [True,False]:
                r=room(kind);before=points(r);b.start_hand(r,101)
                r['hand']['hazards']=[20,21,22,23,24] if kind=='mines' else [2]*6
                if lose:b.act(r,1,'pick',102,{'cell':20 if kind=='mines' else 2})
                else:
                    for i in range(limit):b.act(r,1,'pick',102+i,{'cell':i if kind=='mines' else 0})
                self.assertEqual(r['status'],'waiting');self.assertEqual(r['hand']['results'][0]['payout'],0 if lose else b.risk_return(kind,100,limit));self.assertEqual(points(r),before)
    def test_timeout_leave_and_restart(self):
        for kind in ['mines','tower']:
            for action in ['timeout','leave']:
                for played in [False,True]:
                    r=room(kind);before=points(r);b.start_hand(r,101)
                    r['hand']['hazards']=[20,21,22,23,24] if kind=='mines' else [2]*6
                    if played:b.act(r,1,'pick',102,{'cell':0})
                    r=json.loads(json.dumps(r))
                    if action=='timeout':self.assertTrue(b.tick(r,133));self.assertFalse(b.tick(r,134))
                    else:b.leave(r,1,103)
                    self.assertEqual(points(r),before);self.assertEqual(r['hand']['results'][0]['payout'],b.risk_return(kind,100,1 if played else 0))
    def test_invalid_cells_and_stakes(self):
        for kind in ['mines','tower']:
            r=room(kind);b.start_hand(r,101)
            for cell in [-1,True,'1',None,25]:
                with self.assertRaises(p.RuleError):b.act(r,1,'pick',102,{'cell':cell})
            with self.assertRaises(p.RuleError):b.act(r,1,'cashout',102)
        with self.assertRaises(p.RuleError):room('baccarat',10)

class Baccarat(unittest.TestCase):
    def test_full_banker_third_card_matrix(self):
        allowed={0:set(range(10)),1:set(range(10)),2:set(range(10)),3:set(range(10))-{8},4:set(range(2,8)),5:set(range(4,8)),6:{6,7},7:set()}
        for total in range(8):
            for third in range(10):self.assertEqual(b.banker_draws(total,third),third in allowed[total])
            self.assertEqual(b.banker_draws(total,None),total<6)
    def test_naturals_draws_and_all_payout_sides(self):
        cases=[(['4c','4h','5c','4d'],'player',2,2),(['4c','4h','4d','5c'],'banker',2,2),(['4c','4h','4d','4s'],'tie',2,2),(['Ac','Ac','2c','2d','5c','4c'],'player',3,3),(['3c','Ac','3d','2d','5c'],'banker',2,3)]
        for cards,winner,alen,blen in cases:
            r=room('baccarat',100,3);before=points(r);b.start_hand(r,101,shoe(cards))
            self.assertNotIn('deck',b.public_view(r,1)['hand'])
            for uid,side in enumerate(['player','banker','tie'],1):
                b.act(r,uid,'bet',102,{'side':side})
                if uid<3:self.assertTrue(all('side' not in q for q in b.public_view(r,3)['hand']['players']))
            h=r['hand'];self.assertEqual((h['winner'],len(h['player_cards']),len(h['banker_cards'])),(winner,alen,blen))
            expected={'player':[200,0,0],'banker':[0,195,0],'tie':[100,100,900]}[winner]
            self.assertEqual([p['payout'] for p in h['results']],expected);self.assertEqual(points(r),before)
    def test_random_conservation_and_six_player_limit(self):
        for _ in range(100):
            r=room('baccarat',20,6);before=points(r)
            with self.assertRaises(p.RuleError):b.sit(r,7,'7',100)
            b.start_hand(r,101)
            for uid in range(1,7):b.act(r,uid,'bet',102,{'side':['player','banker','tie'][uid%3]})
            self.assertEqual(points(r),before);self.assertLessEqual(len(r['hand']['player_cards']),3)
    def test_timeout_does_not_cancel_accepted_bets(self):
        r=room('baccarat',100,2);before=points(r);b.start_hand(r,101,shoe(['4c','4h','5c','4d']))
        b.act(r,1,'bet',102,{'side':'player'});b.leave(r,1,103);self.assertEqual(r['status'],'playing')
        b.tick(r,132);self.assertEqual(r['hand']['results'][0]['payout'],200);self.assertEqual(points(r),before)

class Storage(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES("invite_code","TESTONLY");INSERT INTO users VALUES(1,"a","A","2026");INSERT INTO users VALUES(2,"b","B","2026");')
        online.initialize(self.db);self.user=dict(id=1,username='a',nickname='A')
    def call(self,rid,verb,clock,**data):
        r=online.get_room(self.db,rid)
        return online.mutate(self.db,f'/api/online/rooms/{rid}/{verb}',dict(revision=r['revision'],**data),self.user,clock)
    def test_slot_new_peak_payout_persists_once_when_start_is_retried(self):
        rid=online.mutate(self.db,'/api/online/rooms',dict(name='slot',game_type='slot',stake=100,buy_in=1000),self.user,100)['id']
        operation='slotplus-start-retry-00001'
        with patch.object(b.secrets,'randbelow',side_effect=[0,0,0]) as draw:
            self.call(rid,'start',101,operation_id=operation)
            replay=self.call(rid,'start',102,operation_id=operation)
        self.assertTrue(replay['replayed'])
        self.assertEqual(draw.call_count,3)
        r=online.get_room(self.db,rid)
        self.assertEqual(r['hand_no'],1)
        self.assertEqual(r['seats'][0]['stack'],8600)
        self.assertEqual(wallet.view(self.db,1,102)['total'],10600)
        record=json.loads(self.db.execute('SELECT public_state FROM poker_hands WHERE room_id=?',(rid,)).fetchone()[0])
        self.assertEqual(record['slot_payout_version'],3)
        self.assertEqual(record['results'][0]['payout'],7700)
        self.assertEqual(tuple(self.db.execute('SELECT profit,payout FROM poker_results').fetchone()),(7600,7700))
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands').fetchone()[0],1)
    def test_all_modes_persist_receipts_and_refund_once(self):
        for kind in b.CATALOG:
            rid=online.mutate(self.db,'/api/online/rooms',dict(name=kind,game_type=kind,stake=20),self.user,100)['id']
            self.call(rid,'start',101,operation_id='start_'+kind+'_00001',**({'bets':[{'key':'big','amount':20}]} if kind=='dice' else {}))
            h=online.get_room(self.db,rid)['hand']
            if kind not in ('slot','dice'):
                data=dict(action='bet',side='banker') if kind=='baccarat' else (dict(action='shoot',stake=20) if h.get('winning_cards') else dict(action='skip')) if kind=='inbetween' else dict(action='pick',cell=0)
                payload=dict(operation_id='act_'+kind+'_000001',hand_id=h['id'],turn_id=h['turn_id'],**data)
                self.call(rid,'action',102,**payload);self.call(rid,'action',102,**payload)
                r=online.get_room(self.db,rid);b.tick(r,200);online.save(self.db,r,200)
            self.assertEqual(len(online.room_view(self.db,rid,1,201)['history']),1)
            self.call(rid,'leave',202,operation_id='leave_'+kind+'_000001');balance=wallet.view(self.db,1,202)['balance']
            self.call(rid,'leave',203,operation_id='leave_'+kind+'_000001');self.assertEqual(wallet.view(self.db,1,203)['balance'],balance)
            self.assertIsNone(online.current_room(self.db,1))
    def test_shop_balance_equip_and_replay(self):
        request=dict(item_id='frame_brass',operation_id='purchase_frame_000001')
        online.mutate(self.db,'/api/club/buy',request,self.user,100);online.mutate(self.db,'/api/club/buy',request,self.user,101)
        self.assertEqual(wallet.view(self.db,1,101)['balance'],2700)
        online.mutate(self.db,'/api/club/buy',dict(item_id='frame_brass',operation_id='purchase_frame_000002'),self.user,102)
        self.assertEqual(wallet.view(self.db,1,102)['balance'],2700)
        online.mutate(self.db,'/api/club/equip',dict(item_id='frame_brass',operation_id='equip_frame_0000001'),self.user,103)
        self.assertEqual(rewards.profile_map(self.db)[1]['frame']['style'],'brass')
        with self.assertRaises(p.RuleError):rewards.mutate(self.db,'/api/club/equip',dict(item_id='title_ace'),self.user,103)
        before=wallet.view(self.db,2,100)['balance'];self.assertEqual(before,3000)
    def test_daily_claims_separate_from_profit_and_day_boundary(self):
        def record(number,kind,profit,clock,selected=None,contribution=10):
            h=dict(game_type=kind,players=[dict(user_id=1,contribution=contribution)],selected=selected,board=[],results=[],pots=[])
            cur=self.db.execute('INSERT INTO poker_rooms(name,owner_id,status,revision,state,created_at,updated_at) VALUES(?,1,"closed",1,"{}",?,?)',(str(number),clock,clock))
            hid=self.db.execute('INSERT INTO poker_hands(room_id,hand_number,public_state,finished_at) VALUES(?,?,?,?)',(cur.lastrowid,number,json.dumps(h),clock)).lastrowid
            self.db.execute('INSERT INTO poker_results VALUES(?,1,?,0,"")',(hid,profit))
        clock=1760000000
        record(1,'slot',10,clock);record(2,'baccarat',0,clock);record(3,'mines',-10,clock,[0]);record(4,'tower',0,clock,[]);record(5,'baccarat',0,clock,contribution=0)
        self.assertEqual(rewards.progress(self.db,1,clock),dict(play3=3,variety=3,win1=1))
        for ident in rewards.MISSIONS:
            data=dict(mission_id=ident,operation_id='mission_claim_'+ident+'_001')
            online.mutate(self.db,'/api/club/mission',data,self.user,clock);online.mutate(self.db,'/api/club/mission',data,self.user,clock+1)
        self.assertEqual(wallet.view(self.db,1,clock)['balance'],3350)
        self.assertEqual(self.db.execute('SELECT sum(profit) FROM poker_results').fetchone()[0],0)
        self.assertEqual(rewards.progress(self.db,1,clock+86400)['play3'],0)
        self.assertEqual(len(rewards.view(self.db,1,clock)['items']),14)

class API(ServerTestCase):
    def test_bonus_games_shop_auth_and_history(self):
        c=self.clients[0]
        self.assertEqual(c.call('/api/club/buy',dict(item_id='frame_brass',operation_id='purchase_frame_000001'))[0],401)
        self.assertEqual(c.call('/api/register',dict(username='newgames',nickname='測試',password='password123'))[0],200)
        for asset in ['/bonus.js','/club.js']:self.assertEqual(c.call(asset)[0],200)
        for kind in b.CATALOG:
            status,res=c.call('/api/online/rooms',dict(name=kind,game_type=kind,stake=20,operation_id='create_'+kind+'_00001'));self.assertEqual(status,200,res)
            rid=res['id'];base=f'/api/online/rooms/{rid}';r=c.call(base)[1]
            status,res=c.call(base+'/start',dict(revision=r['revision'],operation_id='start_'+kind+'_00001',**({'bets':[{'key':'big','amount':20}]} if kind=='dice' else {})));self.assertEqual(status,200,res)
            r=c.call(base)[1];self.assertNotIn('deck',r['hand'])
            if kind in ('mines','tower'):self.assertNotIn('hazards',r['hand'])
            status,res=c.call(base+'/leave',dict(revision=r['revision'],operation_id='leave_'+kind+'_00001'));self.assertEqual(status,200,res)
            self.assertEqual(len(c.call(base)[1]['history']),1)
        status,res=c.call('/api/club/buy',dict(item_id='title_night',operation_id='buy_title_night_0001'));self.assertEqual(status,200,res)
        self.assertTrue(next(i for i in res['club']['items'] if i['id']=='title_night')['owned'])
        self.assertEqual(c.call('/api/club/equip',dict(item_id='title_night',operation_id='equip_title_night_001'))[0],200)
        self.assertEqual(c.call('/api/online/lobby')[1]['users'][0]['cosmetics']['title']['name'],'深夜常客')

if __name__=='__main__':unittest.main()
