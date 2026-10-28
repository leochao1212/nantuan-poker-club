"""Decor speed bonuses: exact accrual, live task work, migration and receipts."""
import sqlite3,time,unittest
from concurrent.futures import ThreadPoolExecutor
import clubhouse as c,wallet
from .test_admin import AdminRules
from .test_app import ServerTestCase

class SpeedRules(unittest.TestCase):
    def setUp(self):
        AdminRules.setUp(self);self.clock=int(time.time())
        self.db.execute('UPDATE club_income SET last_at=?,stored_units=0',(self.clock,))
        wallet.transfer(self.db,2,100000,'admin_adjustment','speed-fixture-credit',self.clock)
    def upgrade(self,clock=None,op='speed_upgrade_000001'):
        at=self.clock if clock is None else clock;v=c.income_view(self.db,2,at)
        return c.upgrade(self.db,{'id':2},dict(track='decor',expected_level=v['decor_level'],revision=v['revision'],operation_id=op),at)
    def dispatch(self,clock=None,op='speed_dispatch_00001',mission='setup'):
        return c.staff_mutate(self.db,{'id':2},'dispatch',dict(employee='concierge',mission=mission,operation_id=op),self.clock if clock is None else clock)
    def test_additive_speed_and_stacked_production_rates(self):
        for level,step in enumerate(c.SPEED_STEPS):
            for production,base in enumerate(c.RATES):
                self.db.execute('UPDATE club_income SET decor_level=?,production_level=? WHERE user_id=2',(level,production))
                v=c.income_view(self.db,2,self.clock)
                self.assertEqual(v['speed_multiplier'],step/2);self.assertEqual(v['rate'],base*step//2)
                self.assertEqual(v['cap'],v['rate']*24)
                u=next(u for u in v['upgrades'] if u['track']=='production');self.assertEqual(u['current'],v['rate'])
    def test_decor_preserves_fraction_and_does_not_backdate_speed(self):
        t=self.clock;self.upgrade(t+30)
        v=c.income_view(self.db,2,t+30);self.assertEqual(v['stored_units'],c.UNIT//2);self.assertEqual(v['rate'],90)
        self.assertEqual(c.income_view(self.db,2,t+49.999)['available'],0)
        self.assertEqual(c.income_view(self.db,2,t+50)['available'],1)
        self.assertEqual(c.income_view(self.db,2,t+3630)['available'],90)
    def test_running_jobs_only_accelerate_remaining_time(self):
        t=self.clock;job=self.dispatch()['job_id'];self.upgrade(t+1200)
        row=self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone()
        self.assertEqual(row['finishes_at'],t+2800);self.assertEqual(row['reward'],60)
        self.assertFalse(c.staff_view(self.db,2,t+2799.999)['employees'][0]['job']['ready'])
        self.assertTrue(c.staff_view(self.db,2,t+2800)['employees'][0]['job']['ready'])
        self.upgrade(t+1600,op='speed_upgrade_000002')
        self.assertEqual(self.db.execute('SELECT finishes_at FROM staff_jobs WHERE id=?',(job,)).fetchone()[0],t+2500)
    def test_new_jobs_use_bonus_but_keep_rewards_server_authoritative(self):
        for level,step in enumerate(c.SPEED_STEPS):
            self.db.execute('UPDATE club_income SET decor_level=? WHERE user_id=2',(level,))
            for key,spec in c.MISSIONS.items():
                job=self.dispatch(op=f'speed_dispatch_{level}_{key}',mission=key)['job_id']
                row=self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone()
                # Higher tiers include repeating fractions (3.5x and 5.5x).
                # Subtracting epoch timestamps loses sub-microsecond precision.
                self.assertAlmostEqual(row['finishes_at']-row['started_at'],spec['seconds']*2/step,delta=0.000001)
                self.assertEqual(row['reward'],spec['reward']);self.db.execute('DELETE FROM staff_jobs WHERE id=?',(job,))
    def test_completed_jobs_remain_ready_through_upgrade(self):
        job=self.dispatch()['job_id'];before=dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone())
        self.upgrade(self.clock+3601);self.assertEqual(dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone()),before)
    def test_existing_accounts_migrate_once_without_retroactive_income(self):
        t=self.clock;self.db.execute("DELETE FROM wallet_meta WHERE key='clubhouse_speed_v1'")
        self.db.execute('UPDATE club_income SET decor_level=2,last_at=? WHERE user_id=2',(t-36000,))
        job=self.dispatch()['job_id'];self.db.execute('UPDATE staff_jobs SET finishes_at=? WHERE id=?',(t+3600,job));self.db.commit()
        c.schema(self.db,t);self.db.commit();v=c.income_view(self.db,2,t)
        self.assertEqual(v['available'],600);self.assertEqual(v['rate'],120)
        self.assertEqual(c.income_view(self.db,2,t+3600)['available'],720)
        self.assertEqual(self.db.execute('SELECT finishes_at FROM staff_jobs WHERE id=?',(job,)).fetchone()[0],t+1800)
        before=dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone());c.schema(self.db,t+1800)
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),before)
    def test_migration_preserves_old_storage_ceiling_without_backfill(self):
        t=self.clock;self.db.execute("DELETE FROM wallet_meta WHERE key='clubhouse_speed_v1'")
        self.db.execute('UPDATE club_income SET decor_level=3,last_at=? WHERE user_id=2',(t-864000,));self.db.commit();c.schema(self.db,t)
        v=c.income_view(self.db,2,t);self.assertEqual(v['available'],1440);self.assertEqual(v['cap'],3600)
        self.assertEqual(c.income_view(self.db,2,t+3600)['available'],1590)
    def test_failed_receipt_rolls_back_deadline_rate_and_charge(self):
        job=self.dispatch()['job_id'];before=dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone());balance=wallet.view(self.db,2,self.clock)['balance']
        self.db.execute("CREATE TEMP TRIGGER fail_speed BEFORE INSERT ON income_upgrades BEGIN SELECT RAISE(ABORT,'test failure');END")
        with self.assertRaises(sqlite3.IntegrityError):self.upgrade(self.clock+100)
        self.assertEqual(dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone()),before)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],balance);self.assertEqual(c.income_view(self.db,2,self.clock)['rate'],60)

class SpeedAPI(ServerTestCase):
    def test_concurrent_decor_receipt_accelerates_only_once(self):
        client=self.clients[0];client.call('/api/register',dict(username='speed_api_one',nickname='Speed',password='PreviewOnly123'))
        _,dispatched=client.call('/api/clubhouse/dispatch',dict(employee='concierge',mission='setup',operation_id='speed_api_dispatch_001',seconds=0,reward=9999))
        _,lobby=client.call('/api/online/lobby');i=lobby['wallet']['income']
        request=dict(track='decor',expected_level=0,revision=i['revision'],operation_id='speed_api_upgrade_001',speed_multiplier=1000)
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda _:client.call('/api/wallet/clubhouse-upgrade',request),range(8)))
        self.assertTrue(all(code==200 for code,_ in results));self.assertEqual(sum(not value['replayed'] for _,value in results),1)
        _,lobby=client.call('/api/online/lobby');self.assertEqual(lobby['wallet']['balance'],2200);self.assertEqual(lobby['wallet']['income']['rate'],90)
        _,staff=client.call('/api/clubhouse/staff');self.assertEqual(staff['speed_multiplier'],1.5);self.assertEqual(staff['missions'][0]['seconds'],2400)
        job=staff['employees'][0]['job'];self.assertEqual(job['reward'],60);self.assertAlmostEqual(job['finishes_at']-job['started_at'],2400,delta=2)

if __name__=='__main__':unittest.main()
