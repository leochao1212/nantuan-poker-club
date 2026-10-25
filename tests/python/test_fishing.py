"""Fishing: exact odds, private casts, immutable receipts and atomic points."""
from fractions import Fraction
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json,sqlite3,time,unittest
import fishing as f,online,wallet,game_settings,member_accounts
from .test_app import ServerTestCase,Client

class FishingRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TEST');INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');")
        online.initialize(self.db);f.initialize(self.db);self.serial=0;self.t=1792944000.
    def call(self,action,uid=1,clock=None,**fields):
        self.serial+=1;cfg=game_settings.current(self.db,'fishing')
        data=dict(operation_id='fishing_test_'+str(self.serial).zfill(8),**fields)
        if action in ('cast','shot'):data.setdefault('expected_revision',cfg['revision'])
        if action=='shot':data.setdefault('expected_limit_revision',cfg['bet_limit_revision'])
        return f.mutate(self.db,{'id':uid},action,data,self.t+self.serial if clock is None else clock)
    def test_private_persistent_cast_ready_ownership_sale_and_idempotency(self):
        cast=self.call('cast',clock=self.t);ident=cast['result']['cast_id']
        state=cast['state'];self.assertEqual(state['free_casts'],19);self.assertEqual(set(state['pending']),{'id','ready_at'})
        self.assertNotIn('species',cast['result']);self.assertEqual(state['wallet']['balance'],3000)
        with self.assertRaises(f.RuleError):self.call('cast',clock=self.t+1)
        with self.assertRaises(f.RuleError):self.call('reel',cast_id=ident,clock=self.t+1)
        with self.assertRaises(f.RuleError):self.call('reel',uid=2,cast_id=ident,clock=self.t+10)
        f.initialize(self.db)
        reel=self.call('reel',cast_id=ident,clock=self.t+10)
        self.assertEqual(reel['state']['bag_count'],1);self.assertEqual(reel['state']['discovered'],1)
        op=reel['result']['operation_id'];again=f.mutate(self.db,{'id':1},'reel',dict(operation_id=op,cast_id=ident),self.t+20)
        self.assertTrue(again['replayed']);self.assertEqual(again['state']['bag_count'],1)
        value=reel['result']['value'];sale=self.call('sell');self.assertEqual(sale['result']['amount'],value)
        self.assertEqual(sale['state']['bag_count'],0);self.assertEqual(sale['state']['discovered'],1)
        self.assertEqual(sale['state']['wallet']['balance'],3000+value)
        with self.assertRaises(f.RuleError):self.call('sell')
    def test_quota_taipei_midnight_and_setting_revision(self):
        cfg=game_settings.current(self.db,'fishing');cfg['params']['daily_casts']=1
        self.db.execute("UPDATE game_settings SET params=?,revision=2 WHERE game_type='fishing'",(game_settings.encode(cfg['params']),))
        with self.assertRaises(f.RuleError):self.call('cast',expected_revision=1)
        cast=self.call('cast',clock=self.t)
        self.call('reel',cast_id=cast['result']['cast_id'],clock=self.t+10)
        with self.assertRaises(f.RuleError):self.call('cast',clock=self.t+20)
        next_day=self.t+86400;self.assertEqual(f.view(self.db,1,next_day)['free_casts'],1)
        self.call('cast',clock=next_day)
    def test_exact_uniform_shot_odds_boundaries_and_no_sellable_arcade_fish(self):
        self.assertEqual(sum(x['weight'] for x in f.FISH),100)
        for fish in f.FISH:
            denominator=10000*fish['multiplier']
            self.assertEqual(Fraction(9500,denominator)*fish['multiplier'],Fraction(95,100))
            for ticket,caught in [(0,True),(9499,True),(9500,False),(denominator-1,False)]:
                with patch.object(f.secrets,'randbelow',return_value=ticket):
                    result=self.call('shot',species=fish['id'],stake=5)
                self.assertEqual(result['result']['caught'],caught)
                self.assertEqual(result['result']['gross'],5*fish['multiplier'] if caught else 0)
        state=f.view(self.db,1,self.t+100);self.assertEqual(state['bag_count'],0);self.assertEqual(state['discovered'],8)
        self.assertEqual(state['shots'],32)
        totals=self.db.execute('SELECT sum(game_delta),sum(flow_delta) FROM wealth_events WHERE kind LIKE ?',('fishing_%',)).fetchone()
        self.assertEqual(totals[0],state['returned']-state['spent']);self.assertEqual(totals[1],0)
    def test_duplicate_conflict_insufficient_cooldown_and_unknown_fields(self):
        data=dict(operation_id='same_shot_operation_001',species='goldfish',stake=10,expected_revision=1,expected_limit_revision=1)
        with patch.object(f.secrets,'randbelow',return_value=99999):first=f.mutate(self.db,{'id':1},'shot',data,self.t)
        self.assertTrue(f.mutate(self.db,{'id':1},'shot',data,self.t)['replayed'])
        self.assertEqual(f.view(self.db,1,self.t)['shots'],1)
        with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'shot',{**data,'stake':11},self.t+1)
        for changes in ({'stake':True},{'stake':0},{'stake':101},{'species':'fake'},{'expected_revision':0},{'expected_limit_revision':0},{'gross':9999}):
            with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'shot',{**data,**changes,'operation_id':'invalid_shot_'+str(self.serial).zfill(8)},self.t+2)
        with self.assertRaises(f.RuleError):self.call('shot',species='goldfish',stake=1,clock=self.t+.1)
        self.db.execute('UPDATE wallets SET balance=0 WHERE user_id=1')
        with self.assertRaises(f.RuleError):self.call('shot',species='sardine',stake=1,clock=self.t+2)
        self.assertEqual(f.view(self.db,1,self.t+2)['shots'],1)
    def test_credit_failure_rolls_back_debit_collection_stats_and_receipt(self):
        original=wallet.transfer
        def fail(db,uid,amount,*args,**kwargs):
            if amount>0:raise RuntimeError('failed credit')
            return original(db,uid,amount,*args,**kwargs)
        with patch.object(f.secrets,'randbelow',return_value=0),patch.object(wallet,'transfer',side_effect=fail):
            with self.assertRaises(RuntimeError):self.call('shot',species='sardine',stake=100)
        state=f.view(self.db,1,self.t+100)
        self.assertEqual(state['wallet']['balance'],3000);self.assertEqual(state['shots'],0);self.assertEqual(state['discovered'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_operations').fetchone()[0],0)
    def test_disabled_account_cannot_fish(self):
        self.db.execute("INSERT INTO account_states(user_id,status,revision,reason,changed_at) VALUES(1,'blocked',1,'test',0)")
        with self.assertRaises(member_accounts.AccountError):self.call('cast')

class FishingAPI(ServerTestCase):
    def test_auth_receipts_twenty_players_and_no_double_sale(self):
        a=self.clients[0];self.assertEqual(a.call('/api/fishing')[0],401)
        self.assertEqual(a.call('/api/fishing/shot',{})[0],401)
        self.assertEqual(a.call('/api/register',dict(username='angler_0',nickname='Fishing',password='SyntheticFishing123'))[0],200)
        invite=a.call('/api/state')[1]['invite_code'];people=[a]
        for i in range(1,20):
            c=Client(self.base);self.assertEqual(c.call('/api/register',dict(username='angler_'+str(i),nickname='Fishing'+str(i),password='SyntheticFishing123',invite_code=invite))[0],200);people.append(c)
        data=dict(operation_id='http_shot_receipt_0001',species='sardine',stake=5,expected_revision=1,expected_limit_revision=1)
        self.assertEqual(a.call('/api/fishing/shot',data,origin='https://foreign.invalid')[0],403)
        starts=time.perf_counter()
        with ThreadPoolExecutor(20) as pool:responses=list(pool.map(lambda c:c.call('/api/fishing/shot',data),people))
        elapsed=time.perf_counter()-starts
        self.assertTrue(all(status==200 for status,_ in responses));self.assertTrue(all(not r['replayed'] for _,r in responses))
        with ThreadPoolExecutor(8) as pool:replays=list(pool.map(lambda _:a.call('/api/fishing/shot',data),range(8)))
        self.assertTrue(all(s==200 and r['replayed'] for s,r in replays));self.assertEqual(a.call('/api/fishing')[1]['shots'],1)
        self.assertEqual(len(a.call('/api/fishing')[1]['recent']),1)
        cast=a.call('/api/fishing/cast',dict(operation_id='http_fishing_cast_0001',expected_revision=1))[1]
        self.assertNotIn('species',cast['result']);ident=cast['result']['cast_id']
        self.assertEqual(people[1].call('/api/fishing/reel',dict(operation_id='stolen_fishing_cast_001',cast_id=ident))[0],400)
        with closing(sqlite3.connect(self.db_path)) as db:db.execute('UPDATE fishing_casts SET ready_at=0 WHERE id=?',(ident,));db.commit()
        self.assertEqual(a.call('/api/fishing/reel',dict(operation_id='http_fishing_reel_0001',cast_id=ident))[0],200)
        with ThreadPoolExecutor(2) as pool:sales=list(pool.map(lambda i:a.call('/api/fishing/sell',dict(operation_id='http_fishing_sale_'+str(i).zfill(6))),range(2)))
        self.assertEqual(sorted(s for s,_ in sales),[200,400]);self.assertEqual(a.call('/api/fishing')[1]['bag_count'],0)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT sum(shots) FROM fishing_stats').fetchone()[0],20)
        print(f'Fishing20players concurrent HTTP elapsed: {elapsed:.3f}s')
