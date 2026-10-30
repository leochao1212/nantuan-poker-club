"""Milestone eligibility, exclusive ownership and single-title supply bonuses."""
import json,unittest
import rewards,result_stats,clubhouse as c,wallet,online
from member_accounts import AccountError
from poker_engine import RuleError
from .test_admin import AdminRules

class Milestones(unittest.TestCase):
    def setUp(self):
        AdminRules.setUp(self);self.clock=int(self.clock);self.seq=0;self.user={'id':2}
        self.db.execute('UPDATE club_income SET stored_units=0,last_at=?',(self.clock,))
    def hand(self,game='slot',uid=2,contribution=10,selected=None):
        self.seq+=1;state=dict(game_type=game,players=[dict(user_id=uid,contribution=contribution)],selected=selected)
        self.db.execute('INSERT INTO poker_hands(id,room_id,hand_number,public_state,finished_at) VALUES(?,?,?,?,?)',(self.seq,999,self.seq,json.dumps(state),self.clock))
        self.db.execute('INSERT INTO poker_results VALUES(?,?,?,?,?)',(self.seq,uid,0,contribution,'fixture'))
    def own(self,item):self.db.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(2,item,self.clock))
    def equip(self,item,clock=None,remove=False):
        return rewards.mutate(self.db,'/api/club/equip',dict(item_id=item,remove=remove),self.user,self.clock if clock is None else clock)
    def test_all_eleven_games_have_three_valid_settlement_milestones(self):
        for game in rewards.GAMES:self.hand(game,selected=[0])
        self.hand('slot',uid=3);self.hand('tower',selected=[]);self.hand('mines',selected=[]);self.hand('inbetween',contribution=0)
        self.assertEqual(result_stats.game_counts(self.db,2),{g:1 for g in rewards.GAMES})
        v=rewards.view(self.db,2,self.clock);self.assertEqual(len(v['milestones']),11);self.assertEqual(sum(len(g['tiers']) for g in v['milestones']),33)
        self.assertEqual(len(v['items']),20);self.assertEqual(v['total_items'],53)
    def test_corrections_deletes_rollback_and_migration_keep_progress_authoritative(self):
        self.hand();self.db.commit();self.hand();self.assertEqual(result_stats.game_counts(self.db,2)['slot'],2);self.db.rollback()
        self.assertEqual(result_stats.game_counts(self.db,2)['slot'],1)
        self.db.execute('UPDATE poker_results SET user_id=3 WHERE hand_id=1');self.assertEqual(result_stats.game_counts(self.db,2),{})
        self.db.execute('DELETE FROM poker_results');self.assertEqual(result_stats.game_counts(self.db,3),{})
        self.hand('dice');self.db.execute('DELETE FROM result_projection_state WHERE version=2');self.db.commit();result_stats.initialize(self.db);result_stats.initialize(self.db)
        self.assertEqual(result_stats.game_counts(self.db,2),{'dice':1})
    def test_cannot_buy_or_prematurely_claim_an_earned_title(self):
        with self.assertRaises(RuleError):rewards.mutate(self.db,'/api/club/buy',dict(item_id='title_ms_slot_100'),self.user,self.clock)
        with self.assertRaises(RuleError):rewards.mutate(self.db,'/api/club/milestone',dict(milestone_id='slot_100'),self.user,self.clock)
        with self.assertRaises(RuleError):self.equip('title_ms_slot_100')
    def test_claim_receipt_retries_unlock_once_without_minting_points(self):
        for _ in range(100):self.hand()
        before=wallet.view(self.db,2,self.clock)['balance'];data=dict(milestone_id='slot_100',operation_id='milestone_claim_000001')
        first=online.mutate(self.db,'/api/club/milestone',data,self.user,self.clock);again=online.mutate(self.db,'/api/club/milestone',data,self.user,self.clock+1)
        self.assertTrue(first['ok']);self.assertTrue(again['replayed']);self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before)
        rewards.mutate(self.db,'/api/club/milestone',dict(milestone_id='slot_100'),self.user,self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM cosmetic_items WHERE user_id=2').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM milestone_claims').fetchone()[0],1)
    def test_prices_are_confirmed_and_wallet_deducted_once(self):
        wallet.transfer(self.db,2,200000,'admin_adjustment','title_test_supply',self.clock)
        before=wallet.view(self.db,2,self.clock)['balance']
        for quote in [None,700,False,60000.0]:
            with self.assertRaises(AccountError):rewards.mutate(self.db,'/api/club/buy',dict(item_id='title_sovereign',expected_cost=quote),self.user,self.clock)
            self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before)
        data=dict(item_id='title_sovereign',expected_cost=60000,operation_id='title_purchase_000001')
        online.mutate(self.db,'/api/club/buy',data,self.user,self.clock);online.mutate(self.db,'/api/club/buy',data,self.user,self.clock+1)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before-60000)
    def test_bonus_is_only_single_equipped_title_and_integer_supplies(self):
        self.own('title_treasury');self.own('title_ace')
        self.assertEqual(wallet.supply_amounts(self.db,2)['daily_amount'],2000)
        self.equip('title_treasury')
        v=wallet.view(self.db,2,self.clock)
        self.assertEqual((v['daily_amount'],v['hourly_amount']),(2040,550))
        self.assertEqual(c.income_view(self.db,2,self.clock+3600)['available'],120)
        self.assertEqual(c.income_view(self.db,2,self.clock)['cap_hours'],24)
        self.equip('title_ace')
        self.assertEqual(wallet.supply_amounts(self.db,2)['daily_amount'],2005)
        self.assertEqual(wallet.supply_amounts(self.db,2)['hourly_amount'],500)
        self.equip('title_ace',remove=True)
        self.assertEqual(wallet.supply_amounts(self.db,2)['daily_amount'],2000)
    def test_change_title_never_reopens_daily_or_hourly_or_reprices_claim(self):
        wallet.claim(self.db,2,self.clock)
        wallet.claim_hourly(self.db,2,self.clock,'supply_original_0001')
        self.own('title_treasury');self.equip('title_treasury')
        self.assertFalse(wallet.claim(self.db,2,self.clock+1)['claimed'])
        self.assertFalse(wallet.claim_hourly(self.db,2,self.clock+1,'supply_changed_0001')['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,2,self.clock+7200,'supply_original_0001')['replayed'])
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],5500)
        self.assertEqual(wallet.claim_hourly(self.db,2,self.clock+7200,'supply_new_0000001')['amount'],550)
        self.assertEqual(wallet.claim(self.db,2,self.clock+86400)['amount'],2040)
        self.assertEqual([r[0] for r in self.db.execute("SELECT amount FROM wallet_ledger WHERE user_id=2 AND kind IN ('daily','hourly') ORDER BY id")],[2000,500,550,2040])
    def test_all_catalog_supply_bonus_amounts_are_capped_and_integral(self):
        for ident,item in rewards.ITEMS.items():
            if item['slot']!='title':continue
            self.own(ident);self.equip(ident)
            v=wallet.supply_amounts(self.db,2)
            self.assertIs(type(v['daily_amount']),int);self.assertIs(type(v['hourly_amount']),int)
            self.assertLessEqual(v['daily_amount'],2040);self.assertLessEqual(v['hourly_amount'],550)
            self.assertIn('補給',v['title_bonus']['label'])
    def test_retired_title_income_migration_preserves_accrual_once(self):
        self.own('title_ace');self.equip('title_ace')
        self.db.execute("DELETE FROM wallet_meta WHERE key IN ('title_supply_perks_v2','friends-economy-v1')");self.db.commit()
        later=self.clock+3600;c.schema(self.db,later)
        row=self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()
        self.assertEqual(row['stored_units'],3600000*60*10025//10000)
        self.assertEqual(c.income_view(self.db,2,later+3600)['available'],120)
        old=dict(row);c.schema(self.db,later+3600)
        self.assertEqual(dict(self.db.execute('SELECT * FROM club_income WHERE user_id=2').fetchone()),old)
        self.assertEqual(wallet.view(self.db,2,later)['balance'],3000)
    def test_retired_capacity_income_stays_claimable_above_new_cap(self):
        self.own('title_treasury');self.equip('title_treasury')
        self.db.execute("DELETE FROM wallet_meta WHERE key IN ('title_supply_perks_v2','friends-economy-v1')");self.db.commit()
        later=self.clock+30*3600;c.schema(self.db,later)
        v=c.income_view(self.db,2,later+3600)
        self.assertEqual(v['cap'],1440);self.assertEqual(v['available'],1615)
        self.equip('title_treasury',later+3600,remove=True)
        self.assertEqual(c.income_view(self.db,2,later+7200)['available'],1615)
        result=c.claim(self.db,self.user,dict(operation_id='title_income_claim_0001'),later+7200)
        self.assertEqual(result['amount'],1615)
        self.assertTrue(c.claim(self.db,self.user,dict(operation_id='title_income_claim_0001'),later+7201)['replayed'])
    def test_pre_title_install_does_not_receive_retroactive_club_bonus(self):
        self.own('title_ace');self.equip('title_ace')
        self.db.execute("DELETE FROM wallet_meta WHERE key IN ('title_perks_v1','title_supply_perks_v2','friends-economy-v1')");self.db.commit()
        c.schema(self.db,self.clock+3600)
        self.assertEqual(c.income_view(self.db,2,self.clock+3600)['available'],60)
        self.assertEqual(c.income_view(self.db,2,self.clock+7200)['available'],120)
    def test_stale_remove_does_not_unequip_a_newer_title(self):
        self.own('title_treasury');self.own('title_ace');self.equip('title_treasury');self.equip('title_ace')
        self.equip('title_treasury',remove=True)
        self.assertEqual(rewards.equipped_bonus(self.db,2)['title_id'],'title_ace')

    def test_no_history_scan_on_progress_read(self):
        self.hand();queries=[];self.db.set_trace_callback(queries.append);result_stats.game_counts(self.db,2)
        self.assertFalse(any('json_' in q.lower() or 'poker_hands' in q.lower() or 'poker_results' in q.lower() for q in queries))

if __name__=='__main__':unittest.main()
