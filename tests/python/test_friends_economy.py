"""Friends economy invariants, preserving balances and bounded game supplements."""
import json
import hashlib
import sqlite3
import unittest
from unittest.mock import patch
import bank, clubhouse, economy, online, rewards, wallet
from poker_engine import RuleError
from .test_gate_protection import room as gate_room
import bonus_engine


class FriendsEconomy(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TEST');
          INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');""")
        online.initialize(self.db);self.t=1793318400
        self.db.execute('UPDATE club_income SET last_at=?',(self.t,))

    def borrow(self,amount=10000):
        return bank.mutate(self.db,{'id':1},'borrow',dict(amount=amount,operation_id='friends_borrow_123456',
            expected_revision=bank.settings(self.db)['revision'],accept_auto_repay=True),self.t)

    def test_new_members_supplies_limit_midnight_and_replay(self):
        self.assertEqual(wallet.view(self.db,1,self.t)['balance'],10000)
        self.assertEqual(wallet.claim(self.db,1,self.t)['amount'],2000)
        for i in range(4):
            self.assertTrue(wallet.claim_hourly(self.db,1,self.t+i*3600,'friends_hourly_'+str(i).zfill(8))['claimed'])
        self.assertFalse(wallet.claim_hourly(self.db,1,self.t+4*3600,'friends_hourly_00000004')['claimed'])
        self.assertFalse(wallet.claim_hourly(self.db,1,self.t+86400,'friends_hourly_00000000')['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,1,self.t+86400,'friends_hourly_00000005')['claimed'])
        self.assertEqual(wallet.view(self.db,1,self.t+86400)['hourly_remaining'],3)

    def test_migration_preserves_old_accrual_and_grants_once(self):
        d=self.db
        d.execute('DELETE FROM wallet_meta WHERE key=?',(economy.VERSION,))
        d.execute("UPDATE wallet_ledger SET amount=3000,balance_after=3000 WHERE kind='initial'")
        d.execute('UPDATE wallets SET balance=3000')
        d.execute('UPDATE club_income SET last_at=?,stored_units=1800000',(self.t,))
        economy.initialize(d,self.t+3600)
        self.assertEqual(clubhouse.income_view(d,1,self.t+3600)['available'],60)
        self.assertEqual(clubhouse.income_view(d,1,self.t+7200)['available'],180)
        self.assertEqual(wallet.view(d,1,self.t+3600)['balance'],10000)
        economy.initialize(d,self.t+7200)
        self.assertEqual(d.execute("SELECT count(*) FROM wallet_ledger WHERE kind='economy_gift' AND user_id=1").fetchone()[0],1)

    def test_loan_seven_days_immediate_interest_cap_and_consent(self):
        with self.assertRaises(RuleError):
            bank.mutate(self.db,{'id':1},'borrow',dict(amount=1000,operation_id='without_consent_1234',expected_revision=bank.settings(self.db)['revision']),self.t)
        self.borrow();l=bank.loan(self.db,1,self.t)
        self.assertEqual(l['due_at'],self.t+7*bank.DAY)
        self.assertEqual(l['grace_until'],self.t)
        self.assertEqual(bank.debt(bank.loan(self.db,1,self.t+bank.DAY)),10010)
        self.assertEqual(bank.debt(bank.loan(self.db,1,self.t+3*bank.DAY)),10030)
        self.assertEqual(bank.debt(bank.loan(self.db,1,self.t+7*bank.DAY)),10070)
        self.assertEqual(bank.debt(bank.loan(self.db,1,self.t+1000*bank.DAY)),10500)
        self.assertEqual(bank.lending_limit(self.db,1,self.t),14640)

    def test_reward_repayment_and_borrowed_savings_do_not_earn(self):
        self.borrow()
        bank.mutate(self.db,{'id':1},'deposit',dict(amount=10000,operation_id='deposit_borrowed_1234'),self.t)
        self.assertEqual(bank.summary(self.db,1,self.t+bank.DAY)['interest'],0)
        before=wallet.view(self.db,1,self.t)['balance']
        wallet.claim(self.db,1,self.t+bank.DAY)
        self.assertEqual(wallet.view(self.db,1,self.t+bank.DAY)['balance'],before+2000)
        self.assertEqual(bank.loan(self.db,1,self.t+bank.DAY)['principal'],10000)
        self.assertEqual(bank.summary(self.db,1,self.t+2*bank.DAY)['interest'],0)
        wallet.claim(self.db,1,self.t+bank.DAY)
        self.assertEqual(wallet.view(self.db,1,self.t+bank.DAY)['balance'],before+2000)
        due=self.t+7*bank.DAY
        wallet.transfer(self.db,1,4,'passive','before-due',due-1)
        self.assertEqual(bank.loan(self.db,1,due-1)['repay_remainder'],0)
        wallet.claim(self.db,1,due)
        self.assertEqual(bank.loan(self.db,1,due)['principal'],9670)
        self.assertEqual(wallet.view(self.db,1,due)['balance'],before+3604)
        self.assertEqual(bank.summary(self.db,1,due+bank.DAY)['interest'],1)
        wallet.claim(self.db,1,due)
        self.assertEqual(bank.loan(self.db,1,due)['principal'],9670)

    def test_old_loan_conversion_preserves_debt_and_only_once(self):
        d=self.db
        ident=d.execute('INSERT INTO bank_loans(user_id,original,principal,rate_bps,interest_units,generated_units,started_at,due_at,last_at) VALUES(1,300000,300000,150,0,0,?,?,?)',(self.t,self.t+bank.DAY*7,self.t)).lastrowid
        at=self.t+bank.DAY;before=bank.debt(bank.loan(d,1,at))
        data=dict(amount=0,loan_id=ident,expected_revision=bank.settings(d)['revision'],accept_auto_repay=True,operation_id='convert_old_loan_1234')
        bank.mutate(d,{'id':1},'convert',data,at)
        self.assertEqual(bank.debt(bank.loan(d,1,at)),before)
        self.assertEqual(bank.loan(d,1,at)['due_at'],at+7*bank.DAY)
        self.assertEqual(bank.debt(bank.loan(d,1,at+bank.DAY)),before+300)
        wallet.claim(d,1,at+bank.DAY)
        self.assertEqual(bank.loan(d,1,at+bank.DAY)['principal'],300000)
        self.assertTrue(bank.mutate(d,{'id':1},'convert',data,at+100)['replayed'])
        with self.assertRaises(RuleError):bank.mutate(d,{'id':1},'convert',{**data,'operation_id':'convert_twice_123456'},at)

    def test_legacy_bank_receipt_replays_without_new_loan_or_consent(self):
        data=dict(amount=1000,operation_id='legacy_borrow_123456',expected_revision=1)
        fingerprint=hashlib.sha256(json.dumps(['borrow',1000,1,False,None]).encode()).hexdigest()
        self.db.execute('INSERT INTO bank_operations VALUES(?,?,?,?)',(1,data['operation_id'],fingerprint,json.dumps(dict(ok=True,action='borrow',amount=1000))))
        self.assertTrue(bank.mutate(self.db,{'id':1},'borrow',data,self.t)['replayed'])
        self.assertIsNone(bank.loan(self.db,1,self.t))
        self.assertEqual(wallet.view(self.db,1,self.t)['balance'],10000)

    def test_small_rewards_carry_repayment_remainder_and_rollback(self):
        self.borrow();self.db.commit()
        due=self.t+7*bank.DAY
        for i in range(4):wallet.transfer(self.db,1,1,'passive','small:'+str(i),due)
        self.assertEqual(bank.debt(bank.loan(self.db,1,due)),10070)
        wallet.transfer(self.db,1,1,'passive','small:4',due)
        self.assertEqual(bank.debt(bank.loan(self.db,1,due)),10069)
        self.db.rollback()
        self.assertEqual(bank.loan(self.db,1,self.t)['principal'],10000)
        self.assertEqual(bank.loan(self.db,1,self.t)['repay_remainder'],0)
        self.assertEqual(wallet.view(self.db,1,self.t)['balance'],20000)

    def test_early_payoff_and_final_overdue_deduction_do_not_overcharge(self):
        self.borrow(100)
        due=self.t+7*bank.DAY
        wallet.claim(self.db,1,due)
        self.assertIsNone(bank.loan(self.db,1,due))
        self.assertEqual(wallet.view(self.db,1,due)['balance'],11999)
        wallet.claim(self.db,1,due+bank.DAY)
        self.assertEqual(wallet.view(self.db,1,due+bank.DAY)['balance'],13999)
        at=due+2*bank.DAY
        bank.mutate(self.db,{'id':1},'borrow',dict(amount=100,expected_revision=bank.settings(self.db)['revision'],accept_auto_repay=True,operation_id='second_borrow_123456'),at)
        loan=bank.loan(self.db,1,at)
        bank.mutate(self.db,{'id':1},'repay',dict(amount=100,pay_all=True,loan_id=loan['id'],operation_id='early_payoff_123456'),at+bank.DAY)
        before=wallet.view(self.db,1,at+7*bank.DAY)['balance']
        wallet.claim(self.db,1,at+7*bank.DAY)
        self.assertEqual(wallet.view(self.db,1,at+7*bank.DAY)['balance'],before+2000)

    def test_distinct_title_modes_and_shared_budget(self):
        for i,(game,mode,profit,expected) in enumerate([
            ('holdem','play',-1000,30),('slot','win',1000,30),
            ('roulette','loss',-1000,30),('roulette','loss',1000,0),
            ('slot','win',-1000,0),('inbetween','post',-1500,45)]):
            r=dict(game_type=game,hand=dict(stake=1000,third='5d',players=[dict(user_id=1,contribution=1000)],
                results=[dict(user_id=1,profit=profit,rank='撞柱')],economy=dict(day=wallet.day(self.t),
                players={'1':dict(used=0,title=dict(game=game,mode=mode,bps=300,per_hand=100))})))
            before=wallet.view(self.db,1,self.t)['balance']
            economy.settle(self.db,r,2000+i,self.t)
            self.assertEqual(wallet.view(self.db,1,self.t)['balance']-before,expected,(game,mode,profit))
        self.assertEqual(economy.remaining(self.db,1,wallet.day(self.t),'title'),1665)

    def test_partial_gate_refund_is_bounded_and_legacy_unchanged(self):
        for budget in (0,500,6000):
            r=gate_room(10000,cards=['5c','9c','5d','9d','2h'],version=4)
            r['hand']['economy']={'day':wallet.day(self.t),'players':{'1':dict(happy=budget,used=0,title={})}}
            r['hand'].pop('gate_quotes');r['hand']['gate_quotes']=bonus_engine.gate_quotes(r['hand'])
            before=r['seats'][0]['stack'];bonus_engine.act(r,1,'shoot',self.t,{'stake':1000})
            self.assertEqual(r['hand']['charged'],2000-min(2000,budget))
            self.assertEqual(r['seats'][0]['stack'],before-2000+min(2000,budget))
            self.assertEqual(r['hand']['economy']['players']['1']['used'],min(2000,budget))

    def test_blackjack_split_shares_allowance_and_settles_on_deal_day_once(self):
        from .test_arcade import room,shoe,points
        from .test_blackjack_benefits import settings
        import arcade_engine as arcade
        r=room('blackjack',1,stake=100);before=points(r)
        r['_next_economy']=dict(day=wallet.day(self.t),players={'1':dict(happy=150,used=0,title={})})
        arcade.start_hand(r,self.t,shoe(['8c','9c','8h','9h','Tc','7c','Ts']),settings=settings(10000,10000))
        arcade.act(r,1,'split',self.t+1);arcade.act(r,1,'stand',self.t+2);arcade.act(r,1,'hit',self.t+3)
        self.assertEqual([h['payout'] for h in r['hand']['players'][0]['hands']],[200,50])
        self.assertEqual(points(r),before)
        economy.settle(self.db,r,3000,self.t+86400)
        economy.settle(self.db,r,3000,self.t+86400)
        self.assertEqual(economy.remaining(self.db,1,wallet.day(self.t),'happy'),5850)
        self.assertEqual(economy.remaining(self.db,1,wallet.day(self.t+86400),'happy'),6000)

    def test_titles_snapshot_no_stacking_no_skip_and_daily_cap(self):
        d=self.db;ident='title_ms_slot_10000'
        d.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(1,ident,self.t))
        d.execute('INSERT INTO cosmetic_equipped VALUES(?,?,?)',(1,'title',ident))
        r=dict(game_type='slot',seats=[dict(user_id=1)])
        economy.prepare(d,r,self.t);r['hand']=dict(players=[dict(user_id=1,contribution=10000)],results=[dict(user_id=1,profit=10000,rank='won')])
        economy.attach(r);d.execute('DELETE FROM cosmetic_equipped')
        for i in range(20):economy.settle(d,r,100+i,self.t)
        self.assertEqual(d.execute("SELECT sum(amount) FROM wallet_ledger WHERE kind='title_game_bonus'").fetchone()[0],1800)
        economy.settle(d,r,100,self.t)
        self.assertEqual(economy.remaining(d,1,wallet.day(self.t),'title'),0)
        r['hand']['economy']['day']=wallet.day(self.t+86400);r['hand']['players'][0]['contribution']=0
        economy.settle(d,r,999,self.t+86400)
        self.assertEqual(economy.remaining(d,1,wallet.day(self.t+86400),'title'),1800)

    def test_upgraded_titles_award_each_game_with_the_displayed_rate(self):
        for i,(key,m) in enumerate(rewards.MILESTONES.items()):
            perk=rewards.ITEMS[m['title_id']]['game_perk'];game=m['game'];tier=m['tier']
            self.assertEqual(perk['bps'],(150,250,400)[tier-1])
            self.assertEqual(perk['per_hand'],(40,75,125)[tier-1])
            profit=-1000 if perk['mode']=='loss' else 1000
            r=dict(game_type=game,hand=dict(stake=1000,third='7c',selected=[0],
                players=[dict(user_id=2,contribution=1000)],results=[dict(user_id=2,profit=profit,rank='射中龍門')],
                economy=dict(day=wallet.day(self.t),players={'2':dict(used=0,title=perk)})))
            before=wallet.view(self.db,2,self.t)['balance']
            economy.settle(self.db,r,4000+i,self.t)
            self.assertEqual(wallet.view(self.db,2,self.t)['balance']-before,(15,25,40)[tier-1],key)
            economy.settle(self.db,r,4000+i,self.t)
            self.assertEqual(wallet.view(self.db,2,self.t)['balance']-before,(15,25,40)[tier-1],key)
        self.assertEqual(economy.remaining(self.db,2,wallet.day(self.t),'title'),920)

    def test_gate_title_rewards_wins_without_rewarding_refunds_or_losses(self):
        perk=rewards.ITEMS['title_ms_inbetween_10000']['game_perk']
        self.assertEqual(perk['mode'],'win')
        for i,(profit,expected) in enumerate([(0,0),(-1000,0),(1000,40)]):
            r=dict(game_type='inbetween',hand=dict(stake=1000,third='7c',
                players=[dict(user_id=1,contribution=0 if profit==0 else 1000)],
                results=[dict(user_id=1,profit=profit,rank='撞柱保護' if profit==0 else '射中龍門')],
                economy=dict(day=wallet.day(self.t),players={'1':dict(used=0,title=perk)})))
            before=wallet.view(self.db,1,self.t)['balance']
            economy.settle(self.db,r,5000+i,self.t)
            self.assertEqual(wallet.view(self.db,1,self.t)['balance']-before,expected)

    def test_shop_title_brackets_credit_displayed_percent_with_integer_rounding(self):
        for i,(ident,bps,expected) in enumerate([
                ('title_night',75,7),('title_patron',125,12),
                ('title_mogul',175,17),('title_treasury',250,25)]):
            perk=rewards.ITEMS[ident]['game_perk']
            self.assertEqual(perk['bps'],bps);self.assertEqual(perk['per_hand'],125)
            r=dict(game_type='slot',hand=dict(players=[dict(user_id=1,contribution=1000)],
                results=[dict(user_id=1,profit=2000,rank='won')],economy=dict(day=wallet.day(self.t),
                players={'1':dict(used=0,title=perk)})))
            before=wallet.view(self.db,1,self.t)['balance']
            economy.settle(self.db,r,6000+i,self.t)
            self.assertEqual(wallet.view(self.db,1,self.t)['balance']-before,expected)

    def test_mission_completion_and_staff_batch_retries(self):
        with patch.object(rewards,'progress',return_value=dict(play3=3,variety=2,win1=1)):
            for ident in (*rewards.MISSIONS,'complete','complete'):
                rewards.mutate(self.db,'/api/club/mission',dict(mission_id=ident),{'id':1},self.t)
        self.assertEqual(self.db.execute("SELECT sum(amount) FROM wallet_ledger WHERE kind='mission' AND user_id=1").fetchone()[0],1500)
        clubhouse.staff_mutate(self.db,{'id':1},'dispatch',dict(operation_id='staff_dispatch_12345',employee='concierge',mission='setup'),self.t)
        job=self.db.execute('SELECT id FROM staff_jobs').fetchone()[0]
        data=dict(operation_id='staff_redispatch_1234',job_id=job)
        clubhouse.staff_mutate(self.db,{'id':1},'redispatch',data,self.t+3600)
        self.assertTrue(clubhouse.staff_mutate(self.db,{'id':1},'redispatch',data,self.t+7200)['replayed'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM staff_jobs').fetchone()[0],2)
