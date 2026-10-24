"""Independent enumeration of every Sic Bo result, tower odds and atomic replay."""
import copy
import itertools
import json
import unittest
from fractions import Fraction
from unittest.mock import patch
import bonus_engine as b
import poker_engine as p
import online
from . import test_bonus as fixtures


class SicBo(unittest.TestCase):
    def test_every_roll_every_supported_bet(self):
        totals={4:50,5:18,6:14,7:12,8:8,9:6,10:6,11:6,12:6,13:8,14:12,15:14,16:18,17:50}
        accumulated={k:0 for k in ('small','big','odd','even','number:1','any_triple','triple:1')}
        for dice in itertools.product(range(1,7),repeat=3):
            triple=dice[0]==dice[1]==dice[2];total=sum(dice)
            expected={
                'small':2*int(4<=total<=10 and not triple),
                'big':2*int(11<=total<=17 and not triple),
                'odd':2*int(total%2==1 and not triple),
                'even':2*int(total%2==0 and not triple),
                'any_triple':25*int(triple),
            }
            for face in range(1,7):
                count=sum(v==face for v in dice)
                expected[f'number:{face}']=count+1 if count else 0
                expected[f'triple:{face}']=151*int(dice==(face,face,face))
            for value,net in totals.items():expected[f'total:{value}']=(net+1)*int(total==value)
            for key,multiplier in expected.items():
                self.assertEqual(b.dice_multiplier(list(dice),key),multiplier,(dice,key))
                if key in accumulated:accumulated[key]+=multiplier
            r=fixtures.room('dice');before=fixtures.points(r)
            bets=[{'key':k,'amount':1} for k in expected]
            with patch.object(b.secrets,'randbelow',side_effect=[v-1 for v in dice]) as random:
                b.start_hand(r,101,options={'bets':bets})
            self.assertEqual([c.args for c in random.call_args_list],[(6,)]*3)
            self.assertEqual(r['hand']['dice'],list(dice));self.assertEqual(r['hand']['results'][0]['payout'],sum(expected.values()))
            self.assertEqual(fixtures.points(r),before)
            self.assertEqual(r['status'],'waiting');self.assertEqual(r['next_hand_at'],101)
        self.assertEqual(accumulated,dict(small=210,big=210,odd=210,even=210,**{'number:1':199,'any_triple':150,'triple:1':151}))

    def test_validation_reserve_and_immediate_replay(self):
        for raw in (None,[],{},[{'key':'bad','amount':10}],[{'key':'total:3','amount':1}],[{'key':'small','amount':True}],[{'key':'big','amount':1001}],[{'key':'big','amount':600},{'key':'small','amount':401}]):
            r=fixtures.room('dice');before=copy.deepcopy(r)
            with self.assertRaises(p.RuleError):b.start_hand(r,101,options={'bets':raw})
            self.assertEqual(r,before)
        r=fixtures.room('dice');r['bank']=15099;before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):b.start_hand(r,101,options={'bets':[{'key':'triple:6','amount':100}]})
        self.assertEqual(r,before)
        r=fixtures.room('dice');r['seats'][0]['stack']=1
        with self.assertRaises(p.RuleError):b.start_hand(r,101,options={'bets':[{'key':'big','amount':2}]})
        r=fixtures.room('dice')
        for _ in range(3):b.start_hand(r,101,options={'bets':[{'key':'big','amount':1}]})
        self.assertEqual(r['hand_no'],3)
        self.assertEqual(b.dice_bets([{'key':'big','amount':1},{'key':'big','amount':2}]),[{'key':'big','amount':3}])

    def test_single_player_replay_does_not_change_baccarat_group_pacing(self):
        r=fixtures.room('baccarat');b.start_hand(r,101);b.act(r,1,'bet',102,{'side':'banker'})
        with self.assertRaises(p.RuleError):b.start_hand(r,102)
        b.start_hand(r,105)
        self.assertEqual(r['hand_no'],2)


class TowerDifficulty(unittest.TestCase):
    def test_progressive_all_layouts_have_the_declared_probability(self):
        choices=[list(itertools.combinations(range(4),n)) for n in (1,1,1,2,2,2)]
        total=winners=0
        for layout in itertools.product(*choices):
            total+=1;winners+=all(0 not in bombs for bombs in layout)
        self.assertEqual(Fraction(winners,total),Fraction(27,512))
        self.assertLessEqual(Fraction(winners*1839,total*100),Fraction(97,100))

    def test_progressive_exact_payouts_and_saved_hand(self):
        r=fixtures.room('tower');before=fixtures.points(r)
        b.start_hand(r,101,options={'tower_mode':'progressive'})
        h=r['hand'];self.assertEqual(h['bomb_counts'],[1,1,1,2,2,2])
        for row,bombs in enumerate(h['hazards']):
            self.assertEqual(len(bombs),1 if row<3 else 2);self.assertEqual(len(set(bombs)),len(bombs));self.assertTrue(all(0<=x<4 for x in bombs))
        self.assertNotIn('hazards',b.public_view(r,1)['hand']);self.assertNotIn('hazards',b.public_view(r,2)['hand'])
        self.assertEqual(b.public_view(r,1)['hand']['returns'],[129,172,229,459,919,1839])
        for k in range(1,7):
            probability=Fraction(3,4)**min(k,3)*Fraction(1,2)**max(k-3,0)
            expected=Fraction(9700,100)/probability
            self.assertEqual(b.risk_return('tower',100,k,mode='progressive'),expected.numerator//expected.denominator)
        h['hazards']=[[0]]*3+[[0,1]]*3
        for step in range(6):
            r=json.loads(json.dumps(r))
            b.act(r,1,'pick',102+step,{'cell':3,'tower_mode':'fixed'})
        self.assertEqual(r['hand']['tower_mode'],'progressive');self.assertEqual(r['hand']['results'][0]['payout'],1839)
        self.assertEqual(fixtures.points(r),before)
        b.start_hand(r,109);self.assertEqual(r['hand']['tower_mode'],'progressive')
        b.finish_risk(r,110);b.start_hand(r,110,options={'tower_mode':'fixed','stake':50})
        self.assertEqual(r['hand']['bomb_counts'],[1]*6);self.assertEqual(r['stake'],50)

    def test_either_bomb_loses_and_invalid_mode_cannot_debit(self):
        for bomb in (0,1):
            r=fixtures.room('tower');before=fixtures.points(r);b.start_hand(r,101,options={'tower_mode':'progressive'})
            r['hand']['hazards']=[[0]]*3+[[0,1]]*3
            for step in range(3):b.act(r,1,'pick',102+step,{'cell':3})
            b.act(r,1,'pick',105,{'cell':bomb})
            self.assertEqual(r['hand']['results'][0]['payout'],0);self.assertEqual(fixtures.points(r),before)
        for value in ('hard',None,{},True):
            r=fixtures.room('tower');before=copy.deepcopy(r)
            with self.assertRaises(p.RuleError):b.start_hand(r,101,options={'tower_mode':value})
            self.assertEqual(r,before)
        r=fixtures.room('tower');r['bank']=1838
        with self.assertRaises(p.RuleError):b.start_hand(r,101,options={'tower_mode':'progressive'})
        self.assertEqual(r['hand_no'],0)


class AtomicStarts(unittest.TestCase):
    setUp=fixtures.Storage.setUp
    call=fixtures.Storage.call

    def test_dice_receipt_and_tower_options_persist(self):
        for kind in ('dice','tower'):
            rid=online.mutate(self.db,'/api/online/rooms',dict(name=kind,game_type=kind),self.user,100)['id']
            options=dict(operation_id='atomic_'+kind+'_0001',stake=50,**({'bets':[{'key':'big','amount':50}]} if kind=='dice' else {'tower_mode':'progressive'}))
            self.call(rid,'start',101,**options);self.call(rid,'start',102,**options)
            r=online.get_room(self.db,rid);self.assertEqual(r['hand_no'],1);self.assertEqual(r['stake'],50)
            if kind=='dice':self.assertEqual(len(online.room_view(self.db,rid,1,102)['history']),1)
            else:self.assertEqual(r['hand']['tower_mode'],'progressive')
            self.call(rid,'leave',103,operation_id='atomic_leave_'+kind)

    def test_roulette_combined_start_is_atomic_and_replay_safe(self):
        rid=online.mutate(self.db,'/api/online/rooms',dict(name='wheel',game_type='roulette'),self.user,100)['id']
        before=online.get_room(self.db,rid)
        with self.assertRaises(p.RuleError):self.call(rid,'start',101,bets=[{'kind':'bad','amount':10}],operation_id='invalid_combo_00001')
        self.assertEqual(online.get_room(self.db,rid),before)
        data=dict(bets=[{'kind':'red','amount':20}],operation_id='valid_combo_000001')
        self.call(rid,'start',101,**data);self.call(rid,'start',102,**data)
        r=online.get_room(self.db,rid);self.assertEqual(r['hand_no'],1);self.assertEqual(r['status'],'waiting')
        self.assertEqual(r['hand']['players'][0]['contribution'],20)
        self.call(rid,'start',101,bets=[{'kind':'black','amount':10}],operation_id='immediate_combo_001')
        self.assertEqual(online.get_room(self.db,rid)['hand_no'],2)

    def test_invalid_mode_does_not_create_room_or_transfer_wallet(self):
        with self.assertRaises(p.RuleError):online.mutate(self.db,'/api/online/rooms',dict(name='bad',game_type='tower',tower_mode='unknown'),self.user,100)
        self.assertIsNone(online.current_room(self.db,1))

    def test_two_roulette_players_can_submit_start_from_same_waiting_snapshot(self):
        rid=online.mutate(self.db,'/api/online/rooms',dict(name='race',game_type='roulette'),self.user,100)['id']
        path=f'/api/online/rooms/{rid}'
        other=dict(id=2,username='b',nickname='B')
        online.mutate(self.db,path+'/join',dict(revision=online.get_room(self.db,rid)['revision']),other,100)
        revision=online.get_room(self.db,rid)['revision']
        online.mutate(self.db,path+'/start',dict(revision=revision,bets=[{'kind':'red','amount':10}],operation_id='first_combined_start'),self.user,101)
        self.assertEqual(online.get_room(self.db,rid)['status'],'playing')
        online.mutate(self.db,path+'/start',dict(revision=revision,bets=[{'kind':'black','amount':20}],operation_id='second_combined_start'),other,102)
        r=online.get_room(self.db,rid)
        self.assertEqual(r['status'],'waiting');self.assertEqual(r['hand_no'],1)
        self.assertEqual([p['contribution'] for p in r['hand']['players']],[10,20])

if __name__=='__main__':unittest.main()
