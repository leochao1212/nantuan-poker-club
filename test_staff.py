"""Staff task clocks, fixed rewards, ownership, atomic money and replay isolation."""
import sqlite3,time,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import clubhouse as c,wallet,member_accounts
import test_admin as fixtures
from test_app import ServerTestCase

class StaffRules(unittest.TestCase):
    def setUp(self):
        fixtures.AdminRules.setUp(self);self.clock=int(time.time())
    def action(self,action,uid=2,at=None,**payload):
        return c.staff_mutate(self.db,{'id':uid},action,{'operation_id':f'staff_{action}_0000001',**payload},self.clock if at is None else at)
    def test_free_employee_and_read_only_view(self):
        before=self.db.total_changes;view=c.staff_view(self.db,2,self.clock)
        self.assertEqual(self.db.total_changes,before);self.assertEqual([p['key'] for p in view['employees'] if p['owned']],['concierge'])
        self.assertEqual([(m['seconds'],m['reward']) for m in view['missions']],[(3600,60),(14400,300),(28800,650)])
        self.db.commit();self.db.execute('PRAGMA query_only=ON');c.staff_view(self.db,2,self.clock)
    def test_dispatch_offline_boundary_claim_and_game_profit_separation(self):
        job=self.action('dispatch',employee='concierge',mission='setup',reward=999999,seconds=0)['job_id']
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000)
        with self.assertRaises(Exception):self.action('collect',job_id=job,at=self.clock+3599.999)
        self.db.commit();wallet.initialize(self.db,self.clock+3600)
        self.assertTrue(c.staff_view(self.db,2,self.clock+3600)['employees'][0]['job']['ready'])
        result=self.action('collect',job_id=job,at=self.clock+3600);self.assertEqual(result['amount'],60)
        self.assertEqual(wallet.view(self.db,2,self.clock+3600)['balance'],3060)
        self.assertTrue(self.action('collect',job_id=job,at=self.clock+4000)['replayed'])
        self.assertFalse(self.action('collect',job_id=job,at=self.clock+4000,operation_id='staff_collect_new_0001')['collected'])
        wealth=c.public_profile(self.db,2,self.clock+4000)['wealth'];self.assertEqual(wealth['game_profit'],0);self.assertEqual(wealth['net_flow'],60)
    def test_hire_and_parallel_tasks_are_limited_per_employee(self):
        self.action('hire',employee='host');self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],1500)
        self.assertTrue(self.action('hire',employee='host')['replayed'])
        self.assertFalse(self.action('hire',employee='host',operation_id='staff_hire_repeat_001')['hired'])
        with self.assertRaises(Exception):self.action('hire',employee='steward',operation_id='staff_hire_poor_0001')
        wallet.transfer(self.db,2,5000,'admin_adjustment','staff-fixture-credit',self.clock)
        self.action('hire',employee='steward',operation_id='staff_hire_steward_01')
        for index,employee in enumerate(('concierge','host','steward')):
            self.action('dispatch',employee=employee,mission=['setup','hosting','nightshift'][index],operation_id=f'staff_parallel_{index:08d}')
        self.assertEqual(self.db.execute('SELECT count(*) FROM staff_jobs WHERE user_id=2 AND claimed_at IS NULL').fetchone()[0],3)
        with self.assertRaises(member_accounts.AccountError):self.action('dispatch',employee='concierge',mission='hosting')
        with self.assertRaises(member_accounts.AccountError):self.action('dispatch',employee='concierge',mission='hosting',at=self.clock+86400)
    def test_cross_account_task_and_non_owned_employee_are_rejected(self):
        job=self.action('dispatch',employee='concierge',mission='nightshift')['job_id']
        with self.assertRaises(member_accounts.AccountError):self.action('collect',uid=3,job_id=job,at=self.clock+86400)
        with self.assertRaises(Exception):self.action('dispatch',employee='host',mission='setup',operation_id='staff_locked_0000001')
        self.assertIsNone(c.staff_view(self.db,3,self.clock)['employees'][0]['job'])
        self.assertEqual(wallet.view(self.db,3,self.clock)['balance'],3000)
    def test_fingerprint_conflict_and_validation(self):
        self.action('dispatch',employee='concierge',mission='setup')
        with self.assertRaises(member_accounts.AccountError):self.action('dispatch',employee='concierge',mission='hosting')
        for patch in ({'employee':[]},{'mission':[]},{'mission':'oops'},{'operation_id':'bad'}):
            with self.assertRaises(Exception):self.action('dispatch',**{'employee':'host','mission':'setup',**patch})
        for job_id in (True,0,-1,2**63,'1'):
            with self.assertRaises(Exception):self.action('collect',job_id=job_id)
    def test_partial_failures_roll_back_hire_dispatch_collect_and_wealth(self):
        job=self.action('dispatch',employee='concierge',mission='setup')['job_id'];self.db.commit()
        self.db.execute("CREATE TEMP TRIGGER staff_fail BEFORE INSERT ON staff_operations BEGIN SELECT RAISE(ABORT,'test receipt failure');END")
        with self.assertRaises(sqlite3.IntegrityError):self.action('hire',employee='host')
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000);self.assertEqual(self.db.execute('SELECT count(*) FROM staff_roster').fetchone()[0],0)
        with self.assertRaises(sqlite3.IntegrityError):self.action('collect',job_id=job,at=self.clock+3600)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000);self.assertIsNone(self.db.execute('SELECT claimed_at FROM staff_jobs WHERE id=?',(job,)).fetchone()[0])
        self.assertFalse(self.db.execute("SELECT 1 FROM wallet_ledger WHERE kind IN ('staff_hire','staff_mission')").fetchone())
        self.assertFalse(self.db.execute("SELECT 1 FROM wealth_events WHERE kind IN ('staff_hire','staff_mission')").fetchone())
    def test_blocked_account_and_pending_wallet(self):
        self.db.execute("INSERT INTO account_states VALUES(2,'blocked',1,'test',?)",(self.clock,))
        with self.assertRaises(member_accounts.AccountError):self.action('dispatch',employee='concierge',mission='setup')
        self.db.execute("UPDATE wallet_meta SET value='pending' WHERE key='state'")
        with self.assertRaises(Exception):self.action('dispatch',uid=3,employee='concierge',mission='setup')

class StaffAPI(ServerTestCase):
    def test_concurrent_dispatch_and_collection_once_and_private_reads(self):
        a,b=self.clients[:2];self.assertEqual(a.call('/api/clubhouse/staff')[0],401)
        self.assertEqual(a.call('/api/clubhouse/dispatch',{})[0],401)
        a.call('/api/register',{'username':'staff_one','nickname':'One','password':'PreviewOnly123'});code=a.call('/api/state')[1]['invite_code']
        b.call('/api/register',{'username':'staff_two','nickname':'Two','password':'PreviewOnly123','invite_code':code})
        payload=dict(employee='concierge',mission='setup',operation_id='staff_api_dispatch_01',user_id=2,reward=999999,seconds=0)
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda _:a.call('/api/clubhouse/dispatch',payload),range(8)))
        self.assertTrue(all(status==200 for status,r in results));self.assertEqual(sum(not r['replayed'] for status,r in results),1)
        job=results[0][1]['job_id'];self.assertIsNone(b.call('/api/clubhouse/staff')[1]['employees'][0]['job'])
        self.assertEqual(b.call('/api/clubhouse/collect',dict(job_id=job,operation_id='staff_api_other_0001'))[0],404)
        self.assertEqual(a.call('/api/clubhouse/collect',dict(job_id=job,operation_id='staff_api_early_0001'))[0],400)
        with closing(sqlite3.connect(self.db_path)) as db:db.execute('UPDATE staff_jobs SET finishes_at=? WHERE id=?',(time.time()-1,job));db.commit()
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda i:a.call('/api/clubhouse/collect',dict(job_id=job,operation_id=f'staff_api_collect_{i:08d}')),range(8)))
        self.assertTrue(all(status==200 for status,r in results));self.assertEqual(sum(r['collected'] for status,r in results),1)
        self.assertEqual(a.call('/api/online/lobby')[1]['wallet']['balance'],3060)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM staff_jobs').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='staff_mission'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM wealth_events WHERE kind='staff_mission'").fetchone()[0],1)
        self.assertEqual(a.call('/api/clubhouse/dispatch',dict(employee=[],mission='setup',operation_id='staff_api_bad_00001'))[0],400)

if __name__=='__main__':unittest.main()
