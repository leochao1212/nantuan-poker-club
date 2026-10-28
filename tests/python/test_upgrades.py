"""Clubhouse level economy, exact accrual, migration and concurrent upgrade receipts."""
import json,sqlite3,time,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import clubhouse as c,wallet,member_accounts
from . import test_admin as fixtures
from .test_app import ServerTestCase

class UpgradeRules(unittest.TestCase):
    def setUp(self):
        fixtures.AdminRules.setUp(self);self.clock=int(time.time())
        self.db.execute('UPDATE club_income SET last_at=?',(self.clock,));self.db.execute('UPDATE wealth_accounts SET started_at=?',(self.clock,))
    def upgrade_payload(self,track,op='upgrade_rules_000001',uid=2):
        v=c.income_view(self.db,uid,self.clock);u=next(u for u in v['upgrades'] if u['track']==track)
        return dict(track=track,expected_level=u['level'],revision=v['revision'],operation_id=op)
    def upgrade(self,track,at=None,op='upgrade_rules_000001',uid=2):return c.upgrade(self.db,{'id':uid},self.upgrade_payload(track,op,uid),self.clock if at is None else at)
    def test_base_one_point_per_minute_and_upgrade_preserves_fraction(self):
        t=self.clock
        self.assertEqual(c.income_view(self.db,2,t+59.999)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+60)['available'],1)
        self.upgrade('production',t+30)
        v=c.income_view(self.db,2,t+30);self.assertEqual(v['rate'],90);self.assertEqual(v['stored_units'],c.UNIT//2)
        self.assertEqual(c.income_view(self.db,2,t+49.999)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+50)['available'],1)
        self.assertEqual(c.claim(self.db,{'id':2},{'operation_id':'upgrade_claim_000001'},t+50)['amount'],1)
        self.assertEqual(wallet.view(self.db,2,t+50)['total'],1001)
        w=c.public_profile(self.db,2,t+51)['wealth'];self.assertEqual(w['change'],-1999);self.assertEqual(w['game_profit'],0)
    def test_production_is_not_retroactive(self):
        t=self.clock;self.upgrade('production',t+10*3600)
        self.assertEqual(c.income_view(self.db,2,t+10*3600)['available'],600)
        self.assertEqual(c.income_view(self.db,2,t+11*3600)['available'],690)
    def test_full_storage_upgrade_does_not_backfill_capped_time(self):
        t=self.clock+10*86400;self.upgrade('storage',t)
        v=c.income_view(self.db,2,t);self.assertEqual((v['cap_hours'],v['cap'],v['available']),(30,1800,1440))
        self.assertEqual(c.income_view(self.db,2,t+3600)['available'],1500)
        self.assertEqual(c.income_view(self.db,2,t+30*3600)['available'],1800)
    def test_all_levels_costs_caps_and_permanent_decor(self):
        wallet.transfer(self.db,2,2000000,'admin_adjustment','upgrade-fixture-credit',self.clock)
        for track in ('production','storage','decor'):
            for level in range(9):
                v=c.income_view(self.db,2,self.clock);before=wallet.view(self.db,2,self.clock)['balance'];spec=c.UPGRADES[track]
                result=self.upgrade(track,op=f'upgrade_{track}_{level:08d}')
                self.assertEqual(result['cost'],spec['costs'][level]);self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before-spec['costs'][level])
            with self.assertRaises(Exception):self.upgrade(track,op='upgrade_maxed_00001')
        v=c.income_view(self.db,2,self.clock);self.assertEqual((v['rate'],v['cap_hours'],v['cap']),(3300,144,475200))
        self.assertTrue(all(u['level']==9 and u['max_level']==9 and u['next'] is None and u['cost'] is None for u in v['upgrades']))
        public=c.public_profile(self.db,2,self.clock);self.assertEqual(public['person']['clubhouse'],dict(level=9,name='楠團天宮'))
        self.db.commit();wallet.initialize(self.db,self.clock+1)
        self.assertEqual(c.income_view(self.db,2,self.clock+1)['decor_level'],9)
    def test_retries_conflicts_stale_revision_and_per_user_isolation(self):
        req=self.upgrade_payload('decor');first=c.upgrade(self.db,{'id':2},req,self.clock)
        self.assertTrue(c.upgrade(self.db,{'id':2},req,self.clock+86400)['replayed'])
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],2200)
        with self.assertRaises(member_accounts.AccountError):c.upgrade(self.db,{'id':2},{**req,'track':'storage'},self.clock)
        with self.assertRaises(member_accounts.AccountError):c.upgrade(self.db,{'id':2},{**req,'operation_id':'upgrade_stale_00001'},self.clock)
        c.upgrade(self.db,{'id':3},self.upgrade_payload('decor',uid=3),self.clock)
        self.assertEqual(wallet.view(self.db,3,self.clock)['balance'],2200)
    def test_insufficient_and_receipt_insert_failure_roll_back_everything(self):
        self.upgrade('production')
        before=dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone());balance=wallet.view(self.db,2,self.clock)['balance']
        with self.assertRaises(Exception):self.upgrade('production',self.clock+500,op='upgrade_insufficient_01')
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),before)
        self.db.execute("CREATE TEMP TRIGGER fail_receipt BEFORE INSERT ON income_upgrades BEGIN SELECT RAISE(ABORT,'injected failure');END")
        with self.assertRaises(sqlite3.IntegrityError):self.upgrade('decor',self.clock+500,op='upgrade_rollback_0001')
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],balance)
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),before)
        self.assertFalse(self.db.execute("SELECT 1 FROM wallet_ledger WHERE event_key='club-upgrade:upgrade_rollback_0001'").fetchone())
        self.assertFalse(self.db.execute("SELECT 1 FROM wealth_events WHERE event_key='club-upgrade:upgrade_rollback_0001'").fetchone())
    def test_invalid_target_and_blocked_accounts(self):
        req=self.upgrade_payload('production')
        for patch in ({'track':[]},{'track':'unknown'},{'revision':True},{'expected_level':True},{'operation_id':'bad'}):
            with self.assertRaises(Exception):c.upgrade(self.db,{'id':2},{**req,**patch},self.clock)
        self.db.execute("INSERT INTO account_states VALUES(2,'blocked',1,'test',?)",(self.clock,))
        with self.assertRaises(member_accounts.AccountError):c.upgrade(self.db,{'id':2},req,self.clock)
    def test_server_clock_backwards_cannot_reuse_already_accrued_time(self):
        t=self.clock;self.upgrade('production',t+3600)
        self.assertEqual(c.claim(self.db,{'id':2},{'operation_id':'clock_claim_0000001'},t+3000)['amount'],60)
        self.assertEqual(c.income_view(self.db,2,t+3600)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+3640)['available'],1)
    def test_legacy_migration_uses_old_rate_once_and_retains_partial_point(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;self.addCleanup(db.close)
        db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY);INSERT INTO users VALUES(1);INSERT INTO users VALUES(2);CREATE TABLE wallet_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);CREATE TABLE club_income(user_id INTEGER PRIMARY KEY,last_at REAL NOT NULL);")
        t=self.clock;db.execute('INSERT INTO club_income VALUES(1,?)',(t-3636,));db.execute('INSERT INTO club_income VALUES(2,?)',(t-10*86400,));db.commit()
        c.schema(db,t);db.commit()
        self.assertEqual(c.income_view(db,1,t)['available'],50)
        self.assertEqual(c.income_view(db,1,t)['stored_units'],int(50.5*c.UNIT))
        self.assertEqual(c.income_view(db,1,t+30)['available'],51)
        self.assertEqual(c.income_view(db,2,t)['available'],1200)
        self.assertEqual(c.income_view(db,2,t+3600)['available'],1260)
        c.schema(db,t+3600);db.commit()
        self.assertEqual(c.income_view(db,1,t+3600)['available'],110)

class UpgradeAPI(ServerTestCase):
    def test_concurrent_upgrade_receipts_and_stale_tabs(self):
        a,b=self.clients[:2]
        self.assertEqual(a.call('/api/wallet/clubhouse-upgrade',{})[0],401)
        a.call('/api/register',{'username':'upgrade_one','nickname':'One','password':'PreviewOnly123'})
        code=a.call('/api/state')[1]['invite_code'];b.call('/api/register',{'username':'upgrade_two','nickname':'Two','password':'PreviewOnly123','invite_code':code})
        info=a.call('/api/online/lobby')[1]['wallet']['income'];self.assertEqual(info['rate'],60)
        payload=dict(track='production',expected_level=0,revision=info['revision'],operation_id='upgrade_api_0000001',user_id=2,cost=0,rate=999999)
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda _:a.call('/api/wallet/clubhouse-upgrade',payload),range(8)))
        self.assertTrue(all(status==200 for status,r in results));self.assertEqual(sum(not r['replayed'] for status,r in results),1)
        self.assertEqual(a.call('/api/online/lobby')[1]['wallet']['balance'],1000)
        self.assertEqual(b.call('/api/online/lobby')[1]['wallet']['balance'],3000)
        info=b.call('/api/online/lobby')[1]['wallet']['income']
        with ThreadPoolExecutor(6) as pool:results=list(pool.map(lambda i:b.call('/api/wallet/clubhouse-upgrade',dict(track='storage',expected_level=0,revision=info['revision'],operation_id=f'upgrade_unique_{i:08d}')),range(6)))
        self.assertEqual(sum(status==200 for status,r in results),1);self.assertEqual(sum(status==409 for status,r in results),5)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='club_upgrade'").fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM income_upgrades').fetchone()[0],2)
        self.assertEqual(a.call('/api/wallet/clubhouse-upgrade',{**payload,'track':[]})[0],400)
        self.assertEqual(a.call('/api/wallet/clubhouse-upgrade',payload,origin='https://evil.invalid')[0],403)

if __name__=='__main__':unittest.main()
