"""Expanded cosmetic catalog retains ownership, receipts and fixed costs."""
import unittest
import rewards,online,wallet
from . import test_admin as fixtures
from poker_engine import RuleError

class CosmeticCollection(unittest.TestCase):
    setUp=fixtures.AdminRules.setUp
    def test_new_cosmetics_require_ownership_and_charge_exactly_once(self):
        expected={'effect_orbit':('effect','orbit',900),'effect_inferno':('effect','inferno',1000),'effect_frost':('effect','frost',900),'effect_crown':('effect','crown',1200),'title_sovereign':('title','sovereign',60000),'title_legend':('title','legend',120000)}
        wallet.transfer(self.db,2,300000,'admin_adjustment','cosmetic_test_supply',self.clock)
        before=wallet.view(self.db,2,self.clock)['balance'];spent=0;user={'id':2}
        for index,(ident,(slot,style,cost)) in enumerate(expected.items()):
            self.assertEqual((rewards.ITEMS[ident]['slot'],rewards.ITEMS[ident]['style'],rewards.ITEMS[ident]['cost']),(slot,style,cost))
            with self.assertRaises(RuleError):rewards.mutate(self.db,'/api/club/equip',{'item_id':ident},user,self.clock)
            data={'item_id':ident,'expected_cost':cost,'operation_id':f'cosmetic_purchase_{index:08}'}
            online.mutate(self.db,'/api/club/buy',data,user,self.clock);online.mutate(self.db,'/api/club/buy',data,user,self.clock+1)
            spent+=cost;self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before-spent)
            online.mutate(self.db,'/api/club/equip',{'item_id':ident,'operation_id':f'cosmetic_equip_{index:08}'},user,self.clock)
            self.assertEqual(rewards.profile_map(self.db)[2][slot]['style'],style)
        self.assertEqual(self.db.execute('SELECT count(*) FROM cosmetic_items WHERE user_id=2').fetchone()[0],6)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=2 AND kind='cosmetic'").fetchone()[0],6)

    def test_existing_items_and_equipped_styles_survive_initialization(self):
        user={'id':2};rewards.mutate(self.db,'/api/club/buy',{'item_id':'effect_aurora'},user,self.clock)
        rewards.mutate(self.db,'/api/club/equip',{'item_id':'effect_aurora'},user,self.clock)
        before=wallet.view(self.db,2,self.clock)['balance'];online.initialize(self.db)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before)
        self.assertEqual(rewards.profile_map(self.db)[2]['effect']['id'],'effect_aurora')
        self.assertEqual(len(rewards.ITEMS),53)
        self.assertEqual(len({i['style'] for i in rewards.ITEMS.values() if i['slot']=='effect'}),6)

if __name__=='__main__':unittest.main()
