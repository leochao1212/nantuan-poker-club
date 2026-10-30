"""Bank conservation, rate snapshots, atomic retries and private HTTP receipts."""
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import bank,online,wallet,clubhouse,member_accounts,club_admin
from poker_engine import RuleError
from .test_app import ServerTestCase,Client


class BankRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTONLY');
          INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');''')
        online.initialize(self.db)
        from . import scenario_budget
        scenario_budget(self.db)
        self.user={'id':1};self.serial=0
        self.db.execute('INSERT INTO club_admins VALUES(2,0,0)')

    def act(self,action,amount=0,clock=100,**extra):
        self.serial+=1
        if action=='borrow':extra.setdefault('accept_auto_repay',True)
        if action=='repay':extra.setdefault('loan_id',(bank.loan(self.db,1,clock) or {}).get('id'))
        return bank.mutate(self.db,self.user,action,dict(amount=amount,operation_id='bank_test_'+str(self.serial).zfill(16),**extra),clock)

    def policy(self,clock=100,**change):
        self.serial+=1;p=bank.settings(self.db)
        return bank.configure(self.db,{'id':2},dict(p,**{})|change|dict(operation_id='policy_'+str(self.serial).zfill(16),note='測試設定'),clock)

    def test_savings_conservation_fraction_and_simple_interest(self):
        self.act('deposit',1000)
        self.assertEqual(wallet.view(self.db,1,100)['total'],3000)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],2000)
        self.assertEqual(bank.view(self.db,1,100+bank.DAY)['interest'],5)
        self.assertEqual(bank.view(self.db,1,100+2*bank.DAY)['interest'],10,'unclaimed interest does not compound')
        self.act('collect',clock=100+bank.DAY//2)
        self.assertEqual(bank.view(self.db,1,100+bank.DAY)['interest'],3,'fractional points survive claiming')
        self.act('collect',clock=100+bank.DAY)
        self.act('withdraw',1000,clock=100+bank.DAY)
        self.assertEqual(wallet.view(self.db,1,100+bank.DAY)['balance'],3005)
        events=self.db.execute("SELECT kind,amount FROM wealth_events WHERE kind LIKE 'bank_%'").fetchall()
        self.assertEqual([(r[0],r[1]) for r in events],[('bank_interest',2),('bank_interest',3)])

    def test_idempotency_and_conflict(self):
        data=dict(amount=1000,operation_id='duplicate_operation_12345')
        first=bank.mutate(self.db,self.user,'deposit',data,100)
        again=bank.mutate(self.db,self.user,'deposit',data,200)
        self.assertTrue(again['replayed']);self.assertEqual(first['record_id'],again['record_id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM bank_ledger').fetchone()[0],1)
        for action,amount in [('withdraw',1000),('deposit',999)]:
            with self.assertRaises(member_accounts.AccountError):bank.mutate(self.db,self.user,action,{**data,'amount':amount},200)

    def test_loan_is_not_wealth_and_repay_is_interest_first(self):
        self.act('borrow',3000,expected_revision=2)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],6000)
        self.assertEqual(wallet.view(self.db,1,100)['total'],3000)
        self.assertEqual(bank.view(self.db,1,100+4*bank.DAY)['loan']['total_due'],3012)
        self.act('repay',1000,clock=100+4*bank.DAY)
        l=bank.view(self.db,1,100+4*bank.DAY)['loan'];self.assertEqual(l['principal'],2012);self.assertEqual(l['interest'],0)
        self.assertEqual(wallet.view(self.db,1,100+4*bank.DAY)['total'],2988)
        self.act('repay',2012,clock=100+4*bank.DAY)
        self.assertIsNone(bank.view(self.db,1,100+bank.DAY)['loan'])
        self.assertEqual(wallet.view(self.db,1,100+4*bank.DAY)['total'],2988)
        self.act('borrow',100,clock=100+bank.DAY,expected_revision=2)

    def test_overdue_and_interest_cap_no_auto_debit(self):
        self.act('borrow',1000,expected_revision=2)
        before=wallet.view(self.db,1,100)['balance']
        l=bank.view(self.db,1,100+bank.DAY*10000)['loan']
        self.assertEqual(l['total_due'],1050);self.assertTrue(l['overdue'])
        self.assertEqual(wallet.view(self.db,1,100+bank.DAY*10000)['balance'],before)
        with self.assertRaises(RuleError):self.act('borrow',1000,clock=100+bank.DAY*10000,expected_revision=2)

    def test_full_payoff_uses_arrival_interest_and_same_receipt(self):
        self.act('borrow',1000,expected_revision=2)
        request=dict(amount=1000,pay_all=True,loan_id=bank.loan(self.db,1,100)['id'],operation_id='bank_full_payoff_123456')
        r=bank.mutate(self.db,self.user,'repay',request,100+3*bank.DAY+1)
        self.assertEqual(r['amount'],1004);self.assertIsNone(bank.loan(self.db,1,100+3*bank.DAY+1))
        self.assertEqual(bank.mutate(self.db,self.user,'repay',request,1000)['amount'],1004)
        with self.assertRaises(member_accounts.AccountError):bank.mutate(self.db,self.user,'repay',{**request,'pay_all':False},1000)

    def test_rounded_interest_also_consumes_total_interest_cap(self):
        self.act('borrow',1,expected_revision=2)
        self.act('repay',1,clock=100+3*bank.DAY+1)
        self.assertEqual(bank.view(self.db,1,100+bank.DAY*10000)['loan']['total_due'],1)
        self.act('repay',1,clock=100+bank.DAY*10000)
        self.assertIsNone(bank.loan(self.db,1,100+bank.DAY*10000))

    def test_delayed_repayment_cannot_pay_a_different_loan(self):
        self.act('borrow',100,expected_revision=2)
        first=bank.loan(self.db,1,100)['id']
        self.act('repay',100)
        self.act('borrow',3000,expected_revision=2)
        before=wallet.view(self.db,1,100)['balance']
        with self.assertRaises(member_accounts.AccountError):self.act('repay',100,pay_all=True,loan_id=first)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],before)
        self.assertEqual(bank.loan(self.db,1,100)['principal'],3000)

    def test_rate_change_settles_old_savings_and_preserves_loan(self):
        self.act('deposit',1000);self.act('borrow',1000,expected_revision=2)
        self.policy(clock=100+bank.DAY,deposit_bps=100,loan_bps=200)
        self.assertEqual(bank.view(self.db,1,100+2*bank.DAY)['interest'],0)
        self.assertEqual(bank.view(self.db,1,100+2*bank.DAY)['loan']['interest'],2)
        self.assertEqual(bank.view(self.db,1,100+2*bank.DAY)['loan']['rate_bps'],10)
        with self.assertRaises(member_accounts.AccountError):self.act('borrow',100,expected_revision=2)

    def test_validation_and_no_funds(self):
        for value in [True,0,-1,1.5,'100',1_000_001]:
            with self.subTest(value=value),self.assertRaises(RuleError):self.act('deposit',value)
        with self.assertRaises(RuleError):self.act('deposit',3001)
        with self.assertRaises(RuleError):self.act('withdraw',1)
        with self.assertRaises(RuleError):self.act('collect')
        with self.assertRaises(RuleError):self.act('repay',1)
        with self.assertRaises(RuleError):self.act('borrow',14641,expected_revision=2)
        with self.assertRaises(RuleError):self.policy(deposit_bps=501,loan_bps=100)
        self.policy(loan_limit=0)
        with self.assertRaises(RuleError):self.act('borrow',1,expected_revision=3)

    def test_atomic_rollback_and_insufficient_repayment(self):
        with patch('bank.save_account',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):self.act('deposit',1000)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],3000)
        self.assertEqual(bank.view(self.db,1,100)['history'],[])
        self.act('borrow',3000,expected_revision=2)
        wallet.transfer(self.db,1,-6000,'test','spend',100)
        before=dict(bank.loan(self.db,1,100+bank.DAY))
        with self.assertRaises(RuleError):self.act('repay',100,clock=100+bank.DAY)
        self.assertEqual(bank.loan(self.db,1,100+bank.DAY),before)

    def test_private_history_readonly_and_clock_rollback(self):
        self.act('deposit',1000)
        self.assertEqual(bank.view(self.db,2,100)['history'],[])
        self.assertEqual(bank.view(self.db,1,99)['interest'],0)
        self.db.commit();self.db.execute('PRAGMA query_only=ON')
        self.assertEqual(bank.view(self.db,1,100+bank.DAY)['interest'],5)
        self.assertEqual(bank.assets(self.db,100),{1:1000})
        with self.assertRaises(club_admin.AdminError):bank.admin_view(self.db,self.user)

    def test_history_cursor_stays_private_and_bounded(self):
        for _ in range(35):self.act('deposit',1)
        first=bank.view(self.db,1,100);self.assertEqual(len(first['history']),30)
        second=bank.view(self.db,1,100,first['next_before']);self.assertEqual(len(second['history']),5)
        self.assertTrue(set(r['id'] for r in first['history']).isdisjoint(r['id'] for r in second['history']))
        self.assertEqual(bank.view(self.db,2,100,first['next_before'])['history'],[])

    def test_settings_audit_failure_rolls_back_old_interest_and_rate(self):
        self.act('deposit',1000)
        self.db.execute("CREATE TRIGGER bank_audit_failure BEFORE INSERT ON bank_settings_history BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.policy(clock=100+bank.DAY,deposit_bps=100,loan_bps=200)
        self.assertEqual(bank.settings(self.db)['revision'],2)
        self.assertEqual(bank.view(self.db,1,100+2*bank.DAY)['interest'],10)


class BankHTTP(ServerTestCase):
    def test_private_concurrent_receipts_and_assets(self):
        c=Client(self.base)
        self.assertEqual(c.call('/api/bank')[0],401)
        self.assertEqual(c.call('/api/register',dict(username='bank_http',nickname='銀行測試',password='SyntheticBank123'))[0],200)
        self.assertEqual(c.call('/api/admin/bank-settings')[0],403)
        data=dict(amount=1000,operation_id='http_bank_operation_123456')
        with ThreadPoolExecutor(8) as pool:responses=list(pool.map(lambda _:c.call('/api/bank/deposit',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in responses),responses)
        self.assertEqual(sum(not r[1]['replayed'] for r in responses),1)
        result=c.call('/api/bank')[1]
        self.assertEqual(result['bank']['savings'],1000);self.assertEqual(result['wallet']['balance'],9000)
        self.assertEqual(result['wallet']['total'],10000)
        self.assertEqual(len(result['bank']['history']),1)
        self.assertEqual(c.call('/api/online/lobby')[1]['users'][0]['total_chips'],10000)
        with ThreadPoolExecutor(2) as pool:
            withdrawals=list(pool.map(lambda i:c.call('/api/bank/withdraw',dict(amount=700,operation_id='bank_withdraw_race_'+str(i).zfill(8))),range(2)))
        self.assertEqual(sorted(r[0] for r in withdrawals),[200,400])
        self.assertEqual(c.call('/api/bank')[1]['bank']['savings'],300)
        payload=dict(amount=3000,expected_revision=2,accept_auto_repay=True,operation_id='http_bank_borrow_12345678')
        with ThreadPoolExecutor(4) as pool:loans=list(pool.map(lambda _:c.call('/api/bank/borrow',payload),range(4)))
        self.assertTrue(all(r[0]==200 for r in loans));self.assertEqual(sum(not r[1]['replayed'] for r in loans),1)
        self.assertEqual(c.call('/api/bank')[1]['wallet']['balance'],12700)
