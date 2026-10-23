"""Offline income, atomic claims, public history and cash-flow/game separation."""
import json,sqlite3,time,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import clubhouse as c, wallet, online, transfers, member_accounts
import test_admin as fixtures
from test_app import ServerTestCase

class IncomeRules(unittest.TestCase):
    def setUp(self):
        fixtures.AdminRules.setUp(self)
        self.db.execute('UPDATE club_income SET last_at=?',(self.clock,))
        self.db.execute('UPDATE wealth_accounts SET started_at=?',(self.clock,))
    def claim(self,at,op='income_claim_00000001',uid=2):return c.claim(self.db,{'id':uid},{'operation_id':op},at)
    def test_rate_fractional_points_and_no_clock_backwards_income(self):
        t=self.clock
        self.assertEqual(c.income_view(self.db,2,t-100)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+59.999)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+3600)['available'],60)
        self.assertEqual(self.claim(t+100)['amount'],1)
        self.assertEqual(c.income_view(self.db,2,t+119.999)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+120)['available'],1)
        self.assertEqual(self.claim(t+3600,'income_claim_00000002')['amount'],59)
        self.assertEqual(wallet.view(self.db,2,t+3600)['total'],3060)
        self.assertEqual(c.income_view(self.db,1,t+3600)['available'],60)
    def test_offline_cap_discards_excess_and_restart_does_not_reset(self):
        t=self.clock+10*86400
        self.assertEqual(c.income_view(self.db,2,t)['available'],1440)
        self.assertEqual(self.claim(t)['amount'],1440)
        self.db.commit();wallet.initialize(self.db,t+1)
        self.assertEqual(c.income_view(self.db,2,t+1)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+60)['available'],1)
        self.assertTrue(self.claim(t+86400)['replayed'])
        self.assertEqual(wallet.view(self.db,2,t+86400)['total'],4440)
    def test_zero_receipt_stays_zero_and_retries_are_isolated_by_account(self):
        self.assertEqual(self.claim(self.clock)['amount'],0)
        self.assertTrue(self.claim(self.clock+3600)['replayed'])
        self.assertEqual(wallet.view(self.db,2,self.clock+3600)['total'],3000)
        self.assertEqual(self.claim(self.clock+3600,uid=3)['amount'],60)
        self.assertEqual(self.claim(self.clock+3600,'income_claim_00000002')['amount'],60)
    def test_atomic_rollback_validation_and_disabled_account(self):
        self.db.commit()
        self.claim(self.clock+3600);self.db.rollback()
        self.assertEqual(self.claim(self.clock+3600)['amount'],60)
        for bad in ('',True,5,'x'*81):
            with self.assertRaises(Exception):c.claim(self.db,{'id':2},{'operation_id':bad},self.clock+3600)
        self.db.execute("INSERT INTO account_states VALUES(3,'blocked',1,'test',?)",(self.clock,))
        with self.assertRaises(member_accounts.AccountError):self.claim(self.clock+3600,uid=3)
        self.db.execute("UPDATE wallet_meta SET value='pending' WHERE key='state'")
        with self.assertRaises(Exception):self.claim(self.clock+3600,'income_claim_00000002')
    def test_supply_transfer_and_game_changes_do_not_mix(self):
        t=self.clock
        wallet.claim(self.db,2,t+1);wallet.claim_hourly(self.db,2,t+2,'wealth_hourly_000001')
        self.claim(t+3600)
        transfers.initialize(self.db)
        transfers.send(self.db,{'id':2},{'recipient_id':3,'recipient_username':'user_3','amount':100,'note':'private-note-never-public','operation_id':'wealth_transfer_0001'},t+3601)
        r=c.public_profile(self.db,2,t+3602)
        self.assertEqual(r['wealth']['change'],1160);self.assertAlmostEqual(r['wealth']['percent'],38.67)
        self.assertEqual(r['wealth']['game_profit'],0);self.assertEqual(r['wealth']['net_flow'],1160)
        self.assertEqual(c.public_profile(self.db,3,t+3602)['wealth']['change'],100)
        raw=json.dumps(r)
        for secret in ('event_key','password_hash','salt','last_at','operation_id','private-note','balance_after','recipient_id'):self.assertNotIn(secret,raw)
    def test_table_funding_does_not_change_wealth_and_settlement_records_once(self):
        t=self.clock
        users=[{'id':i,'nickname':f'Player{i}'} for i in (2,3)]
        rid=online.mutate(self.db,'/api/online/rooms',{},users[0],t+1)['id'];path=f'/api/online/rooms/{rid}'
        online.mutate(self.db,path+'/join',{'revision':online.get_room(self.db,rid)['revision']},users[1],t+2)
        for uid in (2,3):self.assertEqual(c.public_profile(self.db,uid,t+3)['wealth']['change'],0)
        online.mutate(self.db,path+'/start',{'revision':online.get_room(self.db,rid)['revision']},users[0],t+4)
        room=online.get_room(self.db,rid);actor=room['hand']['actor']
        online.mutate(self.db,path+'/action',{'action':'fold','revision':room['revision'],'hand_id':room['hand']['id']}, {'id':actor,'nickname':f'Player{actor}'},t+5)
        for uid in (2,3):
            w=c.public_profile(self.db,uid,t+6)['wealth']
            self.assertEqual(w['change'],w['game_profit']);self.assertEqual(w['net_flow'],0)
        self.assertNotEqual(c.public_profile(self.db,2,t+6)['wealth']['game_profit'],0)
        count=self.db.execute('SELECT count(*) FROM wealth_events').fetchone()[0]
        online.save(self.db,online.get_room(self.db,rid),t+7)
        self.assertEqual(self.db.execute('SELECT count(*) FROM wealth_events').fetchone()[0],count)
        for u in users:online.mutate(self.db,path+'/leave',{'revision':online.get_room(self.db,rid)['revision']},u,t+8)
        for uid in (2,3):
            w=c.public_profile(self.db,uid,t+9)['wealth'];self.assertEqual(w['total'],w['points'][-1]['total']);self.assertEqual(w['change'],w['game_profit'])
    def test_period_baseline_zero_percent_bounds_and_new_accounts(self):
        t=self.clock
        wallet.transfer(self.db,2,-3000,'admin_adjustment','zero-start',t+1)
        wallet.transfer(self.db,2,100,'daily','later-funds',t+8*86400)
        w=c.public_profile(self.db,2,t+8*86400+100,'1d')['wealth']
        self.assertEqual(w['opening'],0);self.assertIsNone(w['percent']);self.assertEqual(w['change'],100)
        for period in ('1d','7d','30d'):
            w=c.public_profile(self.db,2,t+31*86400,period)['wealth'];self.assertLessEqual(len(w['points']),34)
        with self.assertRaises(Exception):c.public_profile(self.db,2,t,'evil')
        self.db.execute("INSERT INTO users VALUES(4,'newbie','New','2026-10-21')")
        wallet.create(self.db,4,t+100)
        self.assertEqual(c.income_view(self.db,4,t+100)['available'],0)
        self.assertEqual(c.public_profile(self.db,4,t+101)['wealth']['opening'],3000)
    def test_migration_preserves_current_total_and_read_models_are_read_only(self):
        rid=online.mutate(self.db,'/api/online/rooms',{}, {'id':2,'nickname':'Player2'},self.clock)['id']
        self.db.execute('DELETE FROM club_income');self.db.execute('DELETE FROM wealth_accounts');self.db.commit()
        wallet.initialize(self.db,self.clock+10);self.db.commit()
        self.assertEqual(c.public_profile(self.db,2,self.clock+11)['wealth']['opening'],3000)
        self.assertEqual(wallet.view(self.db,2,self.clock+11)['balance'],2000)
        self.db.execute('PRAGMA query_only=ON');self.db.execute('BEGIN')
        c.public_profile(self.db,2,self.clock+11);c.income_view(self.db,2,self.clock+11)
        self.db.rollback();self.db.execute('PRAGMA query_only=OFF')
        self.db.execute("INSERT INTO account_states VALUES(2,'deleted',1,'test',?)",(self.clock,))
        with self.assertRaises(member_accounts.AccountError):c.public_profile(self.db,2,self.clock+12)

class IncomeAPI(ServerTestCase):
    def test_concurrent_claims_authentication_public_profile_privacy_and_balance(self):
        a,b=self.clients[:2]
        self.assertEqual(a.call('/api/members/1')[0],401)
        self.assertEqual(a.call('/api/wallet/passive',{'operation_id':'passive_api_00000001'})[0],401)
        self.assertEqual(a.call('/api/register',{'username':'income_one','nickname':'Income One','password':'PreviewOnly123'})[0],200)
        invite=a.call('/api/state')[1]['invite_code']
        self.assertEqual(b.call('/api/register',{'username':'income_two','nickname':'Income Two','password':'PreviewOnly123','invite_code':invite})[0],200)
        with closing(sqlite3.connect(self.db_path)) as d:d.execute('UPDATE club_income SET last_at=last_at-3601');d.commit()
        payload={'operation_id':'passive_api_00000001','user_id':2,'amount':99999999,'clock':time.time()+999999}
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda _:a.call('/api/wallet/passive',payload),range(8)))
        self.assertTrue(all(s==200 for s,r in results));self.assertEqual(sum(not r['replayed'] for s,r in results),1)
        v=a.call('/api/online/lobby')[1];self.assertEqual(v['wallet']['balance'],3060)
        self.assertEqual(v['users'][0]['profit'],0)
        public=b.call('/api/members/1')[1];self.assertEqual(public['wealth']['change'],60);self.assertEqual(public['wealth']['game_profit'],0)
        self.assertEqual(public['wealth']['percent'],2.0)
        self.assertEqual(b.call('/api/members/2')[1]['wealth']['total'],3000)
        self.assertEqual(a.call('/api/members/99999')[0],404)
        self.assertEqual(a.call('/api/members/1?period=bad')[0],400)
        with closing(sqlite3.connect(self.db_path)) as d:
            self.assertEqual(d.execute("SELECT count(*) FROM wallet_ledger WHERE kind='passive'").fetchone()[0],1)
            self.assertEqual(d.execute("SELECT count(*) FROM wealth_events WHERE kind='passive'").fetchone()[0],1)
        self.assertEqual(a.call('/api/wallet/passive',{})[0],400)
        self.assertEqual(a.call('/api/wallet/passive',{'operation_id':'passive_new_00000001'},origin='https://evil.invalid')[0],403)
        raw=json.dumps(public)
        for secret in ('password','salt','cookie','invite_code','income_claims','admin_account_events','private-note'):self.assertNotIn(secret,raw)

if __name__=='__main__':unittest.main()
