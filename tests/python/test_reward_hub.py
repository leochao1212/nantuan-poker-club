"""Reward hub is atomic, retry-safe and preserves existing economy rules."""
import json
import unittest
from unittest.mock import patch
import bank, online, wallet
from .test_friends_economy import FriendsEconomy


class RewardHub(unittest.TestCase):
    def setUp(self):
        FriendsEconomy.setUp(self)
        self.user={'id':1}

    def claim(self,op='reward_hub_test_0001',clock=None):
        return online.mutate(self.db,'/api/club/claim-all',{'operation_id':op},self.user,self.t if clock is None else clock)

    def test_one_click_claims_dependencies_and_titles_without_equipping(self):
        for i in range(1,102):
            game='slot' if i<=100 else 'big2'
            state=json.dumps(dict(game_type=game,players=[dict(user_id=1,contribution=10)]))
            self.db.execute('INSERT INTO poker_hands VALUES(?,?,?,?,?)',(i,999,i,state,self.t))
            self.db.execute('INSERT INTO poker_results VALUES(?,?,?,?,?)',(i,1,20,10,'fixture'))
        before=wallet.view(self.db,1,self.t)['balance']
        result=self.claim()['receipt']
        self.assertEqual(result['gross'],4000)
        self.assertEqual(result['net'],4000)
        self.assertEqual(wallet.view(self.db,1,self.t)['balance'],before+4000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM mission_claims WHERE user_id=1').fetchone()[0],4)
        self.assertEqual([r['title_id'] for r in result['rows'] if 'title_id' in r],['title_ms_slot_100'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM cosmetic_equipped WHERE user_id=1').fetchone()[0],0)
        again=self.claim(clock=self.t+86400)
        self.assertTrue(again['replayed'])
        self.assertEqual(again['receipt'],result)
        self.assertEqual(wallet.view(self.db,1,self.t+86400)['balance'],before+4000)

    def test_new_click_during_cooldown_has_no_duplicate_credit(self):
        first=self.claim()['receipt'];second=self.claim('reward_hub_test_0002')['receipt']
        self.assertEqual(first['gross'],2500)
        self.assertEqual(second['rows'],[])
        self.assertEqual(second['net'],0)

    def test_failure_rolls_back_every_reward(self):
        self.db.commit()
        before=wallet.view(self.db,1,self.t)['balance']
        with patch('clubhouse.staff_mutate',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):self.claim()
        self.assertEqual(wallet.view(self.db,1,self.t)['balance'],before)
        self.assertFalse(wallet.view(self.db,1,self.t)['daily_claimed'])
        self.assertEqual(self.claim()['receipt']['gross'],2500)

    def test_receipt_reports_overdue_debt_and_actual_wallet_credit(self):
        FriendsEconomy.borrow(self)
        before=wallet.view(self.db,1,self.t)['balance']
        receipt=self.claim(clock=self.t+8*bank.DAY)['receipt']
        self.assertGreater(receipt['repaid'],0)
        self.assertEqual(receipt['net']+receipt['repaid'],receipt['gross'])
        self.assertEqual(wallet.view(self.db,1,self.t+8*bank.DAY)['balance'],before+receipt['net'])

    def test_operation_id_cannot_be_reused_for_a_different_action(self):
        self.claim()
        other=online.mutate(self.db,'/api/club/mission',dict(operation_id='reward_hub_test_0001',mission_id='play3'),self.user,self.t)
        self.assertTrue(other['conflict'])

    def test_completed_staff_and_passive_income_are_collected_together(self):
        import clubhouse
        clubhouse.staff_mutate(self.db,self.user,'dispatch',dict(operation_id='hub_dispatch_000001',employee='concierge',mission='setup'),self.t)
        result=self.claim(clock=self.t+3600)['receipt']
        amounts={r['name']:r['amount'] for r in result['rows']}
        self.assertEqual(amounts['會所收益'],120)
        self.assertGreater(amounts['員工派遣'],0)
        self.assertEqual(result['net'],sum(amounts.values()))
        self.assertEqual(self.db.execute('SELECT count(*) FROM staff_jobs WHERE user_id=1 AND claimed_at IS NULL').fetchone()[0],0)
