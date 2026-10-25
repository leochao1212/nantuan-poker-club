"""Public post protection preserves the ordered shoe and original gross payouts."""
from copy import deepcopy
from fractions import Fraction
from itertools import permutations
import json,unittest
from unittest.mock import patch
import bonus_engine as b,game_settings as g,online,poker_engine as poker
from .test_gate_blackjack import deck_order,points
from . import test_club,test_game_settings


def room(rate=5000,cards=None,stack=10000):
    r=b.new_room('Protection fixture',1,'inbetween',buy_in=stack,stake=100)
    b.sit(r,1,'Player',0)
    snapshot=g.default('inbetween');snapshot['params']['post_protection_bps']=rate
    b.start_hand(r,1,deck=deck_order(cards or ['5c','9c','5d','9d','7h']),settings=snapshot)
    return r


class GateProtection(unittest.TestCase):
    def test_preserves_payout_and_exactly_scales_collision_chance(self):
        for left,right in [('5c','9c'),('7c','7d'),('Ac','Ad'),('Kc','Kd')]:
            classic=room(0,[left,right,'2s'])['hand']['gate_quotes']
            for rate in [0,1,2500,5000,9999,10000]:
                h=room(rate,[left,right,'2s'])['hand']
                for direction,q in h['gate_quotes'].items():
                    old=classic[direction];N=q['total_cards'];m=q['post_cards'];w=q['winning_cards']
                    win=Fraction(w,N)+Fraction(rate*m*w,10000*N*(N-m))
                    post=Fraction(m*(10000-rate),10000*N)
                    self.assertEqual(Fraction(q['return_numerator'],q['return_denominator']),Fraction(old['return_numerator'],old['return_denominator']))
                    self.assertEqual(Fraction(q['win_numerator'],q['win_denominator']),win)
                    self.assertEqual(Fraction(q['post_numerator'],q['post_denominator']),post)
                    self.assertEqual(Fraction(q['charge_numerator'],q['charge_denominator']),1+(q['loss_multiplier']-1)*post)
                    if rate==5000:self.assertEqual(post,Fraction(m,2*N))
                    if rate:self.assertGreater(q['rtp_percent'],old['rtp_percent'])

    def test_independent_permutation_enumeration_matches_quotes_and_point_conservation(self):
        # Every ordered four-card shoe and both equal-probability protection tickets.
        for rate in (0,5000,10000):
            win_count=post_count=paid=returned=0
            for order in permutations(['5d','9d','7h','2h']):
                for ticket in (0,5000):
                    r=room(rate);h=r['hand'];h['deck']=list(order);h.pop('gate_quotes');h['gate_quotes']=b.gate_quotes(h)
                    q=h['gate_quotes']['between'];original=points(r);before=list(h['deck']);frozen=deepcopy(q)
                    with patch.object(b.secrets,'randbelow',return_value=ticket):b.act(r,1,'shoot',2,{'stake':100})
                    self.assertEqual(points(r),original);self.assertEqual(h['gate_quotes']['between'],frozen)
                    consumed=h['protected_discards']+[h['third']]
                    self.assertEqual(consumed,list(reversed(before[-len(consumed):])))
                    self.assertEqual(h['deck'],before[:-len(consumed)])
                    self.assertEqual(h['remaining_cards'],len(h['deck']))
                    self.assertTrue(all(b.gate_rank(c) in (5,9) for c in h['protected_discards']))
                    win_count+=h['results'][0]['payout']>0;post_count+=b.gate_rank(h['third']) in (5,9)
                    paid+=h['charged'];returned+=h['results'][0]['payout']
            self.assertEqual(Fraction(win_count,48),Fraction(q['win_numerator'],q['win_denominator']))
            self.assertEqual(Fraction(post_count,48),Fraction(q['post_numerator'],q['post_denominator']))
            self.assertAlmostEqual(100*returned/paid,q['rtp_percent'],places=9)  # stake gives exact integer payout in this fixture

    def test_boundary_roll_and_consecutive_posts_follow_original_order(self):
        for ticket,protected in [(4999,True),(5000,False)]:
            r=room();h=r['hand'];before=deepcopy(h['deck']);quotes=deepcopy(h['gate_quotes'])
            with patch.object(b.secrets,'randbelow',return_value=ticket) as draw:b.act(r,1,'shoot',2,{'stake':100})
            draw.assert_called_once_with(10000)
            self.assertEqual(h['post_protection_triggered'],protected)
            self.assertEqual(h['protected_discards'],['5d','9d'] if protected else [])
            self.assertEqual(h['third'],'7h' if protected else '5d')
            self.assertEqual(h['charged'],100 if protected else 200)
            self.assertEqual(h['deck'],before[:-3] if protected else before[:-1])
            public=b.public_view(r,1)['hand'];self.assertNotIn('deck',public);self.assertEqual(public['gate_quotes'],quotes)
            self.assertEqual(public['protected_discards'],h['protected_discards'])
            tail=h['deck'][:];sid=h['shoe_id'];restored=json.loads(json.dumps(r));b.start_hand(restored,3)
            self.assertEqual(restored['hand']['shoe_id'],sid)
            self.assertEqual(restored['hand']['pillars'],sorted(tail[-2:],key=b.gate_rank))
            self.assertEqual(restored['hand']['deck'],tail[:-2])

    def test_no_unnecessary_rng_and_maximum_protection_needs_only_one_stake(self):
        for rate,cards in [(0,None),(10000,None),(5000,['5c','9c','2h'])]:
            r=room(rate,cards,stack=100);h=r['hand']
            if rate<10000:r['hand']['players'][0].update(stack=200,starting_stack=200);r['seats'][0]['stack']=200
            self.assertEqual(b.legal_actions(r,1)['max_stake'],100)
            with patch.object(b.secrets,'randbelow',side_effect=AssertionError('Unexpected RNG')):b.act(r,1,'shoot',2,{'stake':100})
            if rate==10000:self.assertEqual(h['charged'],100);self.assertTrue(h['post_protection_triggered'])

    def test_cut_boundary_reshuffles_only_next_hand_and_missing_snapshot_is_disabled(self):
        r=room(10000);h=r['hand']
        nonposts=[c for c in h['deck'] if b.gate_rank(c) not in (5,9)]
        posts=[c for c in h['deck'] if b.gate_rank(c) in (5,9)]
        h['deck']=nonposts[:8]+posts;h.pop('gate_quotes');h['gate_quotes']=b.gate_quotes(h)
        sid=h['shoe_id'];b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(len(h['protected_discards']),6);self.assertEqual(len(h['deck']),7)
        self.assertEqual(h['shoe_id'],sid);b.start_hand(r,3)
        self.assertNotEqual(r['hand']['shoe_id'],sid);self.assertTrue(r['hand']['shoe_reshuffled'])
        self.assertEqual(len(r['hand']['deck']),50)
        for missing in ('params','game_settings'):
            r=room();h=r['hand'];h.pop('gate_quotes')
            if missing=='params':h['game_settings'].pop('params')
            else:h.pop('game_settings')
            self.assertEqual(b.gate_quotes(h)['between']['post_protection_bps'],0)

    def test_validation_skip_and_legacy_hands_do_not_draw_protection(self):
        r=room();r['bank']=0;before=deepcopy(r)
        with patch.object(b.secrets,'randbelow',side_effect=AssertionError('Invalid request drew RNG')):
            with self.assertRaises(poker.RuleError):b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(r,before)
        for version in (1,2):
            r=room();h=r['hand'];h['gate_rules_version']=version;h.pop('gate_quotes');h['gate_quotes']=b.gate_quotes(h)
            with patch.object(b.secrets,'randbelow',side_effect=AssertionError('Legacy drew RNG')):b.act(r,1,'shoot',2,{'stake':100})
            self.assertEqual(h['third'],'5d');self.assertEqual(h['charged'],100 if version==1 else 200)
        r=room();before=list(r['hand']['deck'])
        with patch.object(b.secrets,'randbelow',side_effect=AssertionError('Skip drew RNG')):b.act(r,1,'skip',2)
        self.assertEqual(r['hand']['deck'],before);self.assertEqual(r['hand']['players'][0]['contribution'],0)


class ProtectionSettings(unittest.TestCase):
    setUp=test_game_settings.SettingsRules.setUp
    update=test_game_settings.SettingsRules.update

    def test_idempotent_migration_preserves_custom_payouts_and_other_games(self):
        original={row['game_type']:tuple(row) for row in self.db.execute('SELECT * FROM game_settings') if row['game_type']!='inbetween'}
        self.db.execute("UPDATE game_settings SET revision=7,params=?,updated_by=1,updated_at=123 WHERE game_type='inbetween'",(g.encode({'target_bps':12000}),))
        g.initialize(self.db);saved=g.current(self.db,'inbetween');g.initialize(self.db)
        self.assertEqual(g.current(self.db,'inbetween'),saved);self.assertEqual(saved['revision'],8)
        self.assertEqual(saved['params'],{'target_bps':12000,'post_protection_bps':5000})
        self.assertEqual({row['game_type']:tuple(row) for row in self.db.execute('SELECT * FROM game_settings') if row['game_type']!='inbetween'},original)

    def test_admin_validation_audit_retry_and_frozen_hand(self):
        user={'id':2,'nickname':'P2','username':'person_2'};rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'inbetween'},user,self.t)['id'];path=f'/api/online/rooms/{rid}'
        online.mutate(self.db,path+'/start',{'operation_id':'protection_start_00001'},user,self.t+1);hand=deepcopy(online.get_room(self.db,rid)['hand'])
        for bad in (-1,10001,True,0.5,'50'):
            with self.assertRaises(poker.RuleError):self.update('inbetween',{'post_protection_bps':bad})
        for rate in (0,10000,5000):self.update('inbetween',{'post_protection_bps':rate})
        view=g.admin_view(self.db,{'id':1});entry=next(x for x in view['games'] if x['game_type']=='inbetween')
        self.assertEqual(next(f for f in entry['fields'] if f['key']=='post_protection_bps')['max'],10000)
        self.assertEqual(entry['metrics']['post_protection_percent'],50)
        self.assertEqual(online.get_room(self.db,rid)['hand'],hand)
        online.mutate(self.db,path+'/action',{'action':'skip','hand_id':hand['id'],'turn_id':hand['turn_id'],'operation_id':'protection_skip_000001'},user,self.t+2)
        self.update('inbetween',{'post_protection_bps':0});online.mutate(self.db,path+'/start',{'operation_id':'protection_start_00002'},user,self.t+3)
        self.assertEqual(online.get_room(self.db,rid)['hand']['game_settings']['params']['post_protection_bps'],0)
        self.assertEqual(len(view['history']),3)


class ProtectionReceipts(unittest.TestCase):
    setUp=test_club.WalletRules.setUp

    def test_protected_shot_persists_draw_and_debits_once_after_retries(self):
        user=self.users[0];rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'inbetween'},user,self.clock)['id'];path=f'/api/online/rooms/{rid}'
        online.mutate(self.db,path+'/start',{'operation_id':'protection_start_00003'},user,self.clock+1)
        r=online.get_room(self.db,rid);h=r['hand'];shoe=deck_order(['5c','9c','5d','9d','2h']);shoe.pop();shoe.pop()
        h['pillars']=['5c','9c'];h['deck']=shoe;h.pop('gate_quotes');h['gate_quotes']=b.gate_quotes(h);online.save(self.db,r,self.clock+1)
        data={'action':'shoot','stake':100,'hand_id':h['id'],'turn_id':h['turn_id'],'operation_id':'protected_shot_receipt_01'}
        with patch.object(b.secrets,'randbelow',return_value=0) as draw:
            online.mutate(self.db,path+'/action',data,user,self.clock+2)
            saved=deepcopy(online.get_room(self.db,rid));self.assertTrue(online.mutate(self.db,path+'/action',data,user,self.clock+3)['replayed'])
            self.assertTrue(online.mutate(self.db,path+'/action',{**data,'operation_id':'protected_shot_receipt_02'},user,self.clock+3)['conflict'])
            draw.assert_called_once_with(10000)
        self.assertEqual(online.get_room(self.db,rid),saved)
        self.assertEqual(saved['hand']['protected_discards'],['5d','9d']);self.assertEqual(saved['hand']['third'],'2h')
        self.assertEqual(saved['seats'][0]['stack'],900)
        self.assertEqual(self.db.execute('SELECT hands,profit FROM player_result_totals WHERE user_id=?',(user['id'],)).fetchone()[:],(1,-100))
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_operations WHERE operation_id=?',(data['operation_id'],)).fetchone()[0],1)
