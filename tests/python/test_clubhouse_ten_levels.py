"""Ten-tier progression preserves earned points and charges every upgrade once."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import math
import sqlite3
import unittest
import urllib.error
import urllib.request

import clubhouse as c
import wallet
from . import test_admin as fixtures
from .test_app import ROOT, ServerTestCase


class TenLevelRules(unittest.TestCase):
    def setUp(self):
        fixtures.AdminRules.setUp(self)
        self.clock=1800000000
        self.db.execute('UPDATE club_income SET last_at=?,stored_units=0',(self.clock,))
        wallet.transfer(self.db,2,2000000,'admin_adjustment','ten-tier-test-funds',self.clock)

    def upgrade(self,track,at=None,op='ten_level_upgrade_001'):
        at=self.clock if at is None else at
        view=c.income_view(self.db,2,at)
        level=next(u['level'] for u in view['upgrades'] if u['track']==track)
        return c.upgrade(self.db,{'id':2},dict(track=track,expected_level=level,revision=view['revision'],operation_id=op),at)

    def test_legacy_four_tier_values_and_costs_are_unchanged(self):
        self.assertEqual(c.RATES[:4],(60,90,120,180))
        self.assertEqual(c.HOURS[:4],(24,30,36,48))
        self.assertEqual(c.DECOR[:4],('私人包廂','暖燈小館','尊爵會館','曜金行宮'))
        self.assertEqual(c.SPEED_STEPS[:4],(2,3,4,5))
        for key,costs in [('production',(2000,5000,12000)),('storage',(1000,2500,5000)),('decor',(800,2000,5000))]:
            self.assertEqual(c.UPGRADES[key]['costs'][:3],costs)
        self.db.execute('UPDATE club_income SET production_level=3,storage_level=3,decor_level=3,stored_units=? WHERE user_id=2',(c.UNIT//2,))
        job=c.staff_mutate(self.db,{'id':2},'dispatch',dict(employee='concierge',mission='hosting',operation_id='ten_legacy_dispatch_01'),self.clock)['job_id']
        before=dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone())
        deadline=self.db.execute('SELECT finishes_at FROM staff_jobs WHERE id=?',(job,)).fetchone()[0]
        balance=wallet.view(self.db,2,self.clock)['balance']
        c.schema(self.db,self.clock+3600)
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),before)
        self.assertEqual(self.db.execute('SELECT finishes_at FROM staff_jobs WHERE id=?',(job,)).fetchone()[0],deadline)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],balance)
        view=c.income_view(self.db,2,self.clock+3600)
        self.assertEqual((view['rate'],view['cap_hours'],view['available']),(450,48,450))
        self.assertTrue(all(u['max_level']==9 and u['next'] is not None for u in view['upgrades']))

    def test_four_to_five_keeps_fraction_and_applies_only_future_rate(self):
        for track,rate,hours,cost in [('production',600,48,24000),('storage',450,60,9000),('decor',540,48,10000)]:
            with self.subTest(track=track):
                self.db.execute('UPDATE club_income SET production_level=3,storage_level=3,decor_level=3,last_at=?,stored_units=? WHERE user_id=2',(self.clock,c.UNIT//2))
                before=wallet.view(self.db,2,self.clock)['balance']
                self.upgrade(track,self.clock+1800,'ten_four_to_five_'+track)
                view=c.income_view(self.db,2,self.clock+1800)
                self.assertEqual(view['stored_units'],225*c.UNIT+c.UNIT//2)
                self.assertEqual((view['rate'],view['cap_hours']),(rate,hours))
                self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before-cost)
                self.assertEqual(c.income_view(self.db,2,self.clock+5400)['available'],225+rate)

    def test_tenth_decor_accelerates_only_remaining_work_with_ceiling(self):
        self.db.execute('UPDATE club_income SET decor_level=8 WHERE user_id=2')
        job=c.staff_mutate(self.db,{'id':2},'dispatch',dict(employee='concierge',mission='setup',operation_id='ten_job_dispatch_0001'),self.clock)['job_id']
        completed=self.db.execute('INSERT INTO staff_jobs(user_id,employee_key,mission_key,started_at,finishes_at,reward) VALUES(2,\'host\',\'hosting\',?,?,300)',(self.clock-3600,self.clock-1)).lastrowid
        done=dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(completed,)).fetchone())
        self.upgrade('decor',self.clock+100)
        current=self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(job,)).fetchone()
        self.assertAlmostEqual(current['finishes_at'],self.clock+100+math.ceil(620000*10/11)/1000,places=3)
        self.assertEqual(current['reward'],60)
        self.assertEqual(dict(self.db.execute('SELECT * FROM staff_jobs WHERE id=?',(completed,)).fetchone()),done)
        self.assertEqual(c.income_view(self.db,2,self.clock+100)['speed_multiplier'],5.5)

    def test_tenth_decor_receipt_failure_restores_money_income_and_task(self):
        self.db.execute('UPDATE club_income SET decor_level=8 WHERE user_id=2')
        c.staff_mutate(self.db,{'id':2},'dispatch',dict(employee='concierge',mission='setup',operation_id='ten_failed_dispatch_01'),self.clock)
        income=dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone())
        job=dict(self.db.execute('SELECT * FROM staff_jobs WHERE user_id=2').fetchone())
        balance=wallet.view(self.db,2,self.clock)['balance']
        self.db.execute("CREATE TEMP TRIGGER fail_tenth BEFORE INSERT ON income_upgrades BEGIN SELECT RAISE(ABORT,'test failure');END")
        with self.assertRaises(sqlite3.IntegrityError):self.upgrade('decor',self.clock+100)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],balance)
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),income)
        self.assertEqual(dict(self.db.execute('SELECT * FROM staff_jobs WHERE user_id=2').fetchone()),job)

    def test_max_income_cap_claim_and_retry_are_exact(self):
        self.db.execute('UPDATE club_income SET production_level=9,storage_level=9,decor_level=9 WHERE user_id=2')
        at=self.clock+1000*3600
        view=c.income_view(self.db,2,at)
        self.assertEqual((view['rate'],view['cap_hours'],view['cap'],view['available']),(3300,144,475200,475200))
        req=dict(operation_id='ten_max_income_claim_01')
        before=wallet.view(self.db,2,at)['balance']
        self.assertEqual(c.claim(self.db,{'id':2},req,at)['amount'],475200)
        self.assertTrue(c.claim(self.db,{'id':2},req,at+3600)['replayed'])
        self.assertEqual(wallet.view(self.db,2,at)['balance'],before+475200)
        self.assertEqual(c.income_view(self.db,2,at)['available'],0)


class TenLevelAPI(ServerTestCase):
    def test_all_twenty_seven_upgrades_concurrency_and_tenth_level_stop(self):
        client=self.clients[0]
        self.assertEqual(client.call('/api/register',dict(username='ten_level_test',nickname='Ten level test',password='SyntheticTenLevel123'))[0],200)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory=sqlite3.Row
            wallet.transfer(db,1,2000000,'admin_adjustment','ten-api-fixture-credit',1800000000);db.commit()
        replay=None
        for track in ['production','storage','decor']:
            for level in range(9):
                info=client.call('/api/online/lobby')[1]['wallet']['income']
                request=dict(track=track,expected_level=level,revision=info['revision'],operation_id=f'ten_api_{track}_{level:08d}',cost=0,speed_multiplier=1000,max_level=100)
                if track=='decor' and level==3:
                    with ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda _:client.call('/api/wallet/clubhouse-upgrade',request),range(8)))
                    self.assertTrue(all(status==200 for status,result in results),results)
                    self.assertEqual(sum(not result['replayed'] for status,result in results),1)
                    replay=request
                else:self.assertEqual(client.call('/api/wallet/clubhouse-upgrade',request)[0],200)
            info=client.call('/api/online/lobby')[1]['wallet']['income']
            status,_=client.call('/api/wallet/clubhouse-upgrade',dict(track=track,expected_level=9,revision=info['revision'],operation_id='ten_maxed_'+track+'_0001'))
            self.assertEqual(status,400)
        self.assertTrue(client.call('/api/wallet/clubhouse-upgrade',replay)[1]['replayed'])
        lobby=client.call('/api/online/lobby')[1]
        self.assertEqual(lobby['wallet']['balance'],814700)
        self.assertEqual((lobby['wallet']['income']['decor_level'],lobby['wallet']['income']['rate'],lobby['wallet']['income']['cap']),(9,3300,475200))
        self.assertEqual(client.call('/api/members/1')[1]['person']['clubhouse'],dict(level=9,name='楠團天宮'))
        self.assertEqual(client.call('/api/clubhouse/staff')[1]['speed_multiplier'],5.5)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM income_upgrades').fetchone()[0],27)
            self.assertEqual(db.execute("SELECT count(*),sum(amount) FROM wallet_ledger WHERE kind='club_upgrade'").fetchone(),(27,-1188300))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_all_twenty_images_have_valid_fingerprints_and_strict_urls(self):
        for tier in range(1,11):
            for suffix in ['', '-small']:
                name=f'assets/clubhouse/tier-{tier}{suffix}.webp'
                data=(ROOT/'static'/name).read_bytes();digest=hashlib.sha256(data).hexdigest()
                with urllib.request.urlopen(self.base+'/'+name+'?v='+digest[:12]) as response:
                    self.assertEqual(response.headers.get_content_type(),'image/webp')
                    self.assertIn('immutable',response.headers['Cache-Control'])
                    self.assertEqual(response.headers['ETag'],'"'+digest+'"')
                    self.assertEqual(response.read(),data)
        for name in ['tier-0.webp','tier-11.webp','tier-01.webp','tier-100.webp','tier-9-other.webp','tier-10.webp?v=wrong']:
            self.assertEqual(self.clients[0].call('/assets/clubhouse/'+name)[0],404,name)


if __name__=='__main__':unittest.main()
