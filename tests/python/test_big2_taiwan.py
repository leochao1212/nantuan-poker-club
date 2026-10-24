"""Taiwan table specification: escrow, zero-sum scoring and authoritative turns."""
import copy,json,unittest
import arcade_engine as a,poker_engine as p,online
from .test_arcade import room,points
from . import test_arcade as fixtures

class TaiwanBigTwo(unittest.TestCase):
    def test_four_players_and_full_reserve_required_before_any_deal(self):
        for count in (1,2,3):
            r=room('big2',count);before=copy.deepcopy(r)
            with self.assertRaises(p.RuleError):a.start_hand(r,101)
            self.assertEqual(r,before)
        r=room('big2',4,stack=519);before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):a.start_hand(r,101)
        self.assertEqual(r,before)
        r=room('big2',4,stack=520);total=points(r);a.start_hand(r,101)
        self.assertTrue(all(q['contribution']==520 and q['stack']==0 for q in r['hand']['players']))
        self.assertEqual(points(r),total)

    def test_remaining_thresholds_and_deuce_multipliers_exactly_once(self):
        for enabled in (False,True):
            for count in (1,7,8,12,13):
                for twos in range(min(count,4)+1):
                    r=room('big2',4,stack=10000);r['big2_rules']['twos_double']=enabled
                    total=points(r);a.start_hand(r,101);h=r['hand']
                    h['players'][0]['cards']=[]
                    cards=[c for c in p.DECK if c[0]!='2'][:count-twos]+['2'+s for s in a.SUITS[:twos]]
                    for q in h['players'][1:]:q['cards']=cards[:]
                    expected=count*10*(4 if count==13 else 2 if count>=8 else 1)*(2**twos if enabled else 1)
                    a._finish_big2(r,1,102)
                    self.assertEqual([q['profit'] for q in h['results']],[expected*3,-expected,-expected,-expected])
                    self.assertTrue(all(q['stack']>=0 for q in h['players']));self.assertEqual(points(r),total);self.assertEqual(r['bank'],0)

    def test_maximum_optional_loss_is_covered_by_escrow(self):
        r=room('big2',4,stake=1,stack=832);r['big2_rules']['twos_double']=True;a.start_hand(r,101)
        h=r['hand'];h['players'][0]['cards']=[]
        h['players'][1]['cards']=['2'+s for s in a.SUITS]+[c for c in p.DECK if c[0]!='2'][:9]
        a._finish_big2(r,1,102)
        self.assertEqual(h['results'][1]['profit'],-832);self.assertEqual(h['players'][1]['stack'],0)

    def test_flush_suit_precedes_rank_but_pair_rank_precedes_suit(self):
        self.assertGreater(a.big2_score('3s 5s 7s 9s Js'.split()),a.big2_score('2h Ah Kh Qh 8h'.split()))
        self.assertGreater(a.big2_score(['4c','4d']),a.big2_score(['3h','3s']))
        self.assertGreater(a.big2_score(['4s','4c']),a.big2_score(['4h','4d']))
        self.assertGreater(a.big2_score('3s 5s 7s 9s Qs'.split()),a.big2_score('3s 5s 7s 9s Js'.split()))

    def test_every_hand_requires_club_three_even_when_previous_winner_stays(self):
        r=room('big2',4,stack=10000)
        for number in range(4):
            clock=101+number*10
            # Rotate the full deck so all four seats hold club three in turn.
            deck=list(p.DECK[number:])+list(p.DECK[:number])
            a.start_hand(r,clock,deck=deck);h=r['hand']
            starter=next(q for q in h['players'] if '3c' in q['cards'])
            self.assertEqual(h['first_card'],'3c');self.assertEqual(h['actor'],starter['user_id'])
            self.assertEqual(a.legal_actions(r,starter['user_id'])['first_card'],'3c')
            if number:self.assertNotEqual(h['actor'],r['big2_last_winner'])
            other=next(c for c in starter['cards'] if c!='3c');before=copy.deepcopy(r)
            with self.assertRaises(p.RuleError):a.act(r,starter['user_id'],'play',clock+1,{'cards':[other]})
            self.assertEqual(r,before)
            a.act(r,starter['user_id'],'play',clock+1,{'cards':['3c']})
            self.assertEqual(h['current_play'],['3c'])
            self.assertEqual(h['actor'],a._big2_order(r,h['players'],starter['seat'])[0]['user_id'])
            self.assertIsNone(a.legal_actions(r,h['actor'])['first_card'])
            winner=starter['user_id'];starter['cards']=[];a._finish_big2(r,winner,clock+2)

    def test_replacement_player_can_start_with_club_three_after_winner_leaves(self):
        r=room('big2',4,stack=10000);a.start_hand(r,101,deck=p.DECK)
        winner=r['hand']['actor'];a._player(r,winner)['cards']=[];a._finish_big2(r,winner,102)
        a.leave(r,winner,103);a.sit(r,5,'Replacement',103,buy_in=10000)
        a.start_hand(r,106,deck=p.DECK)
        self.assertEqual(r['hand']['first_card'],'3c')
        self.assertIn('3c',a._player(r,r['hand']['actor'])['cards'])

    def test_top_card_is_enforced_and_timeout_lead_obeys_it(self):
        r=room('big2',4);a.start_hand(r,101);h=r['hand']
        for q in h['players']:q['cards']=['4'+a.SUITS[q['seat']],'K'+a.SUITS[q['seat']]]
        h['players'][3]['cards']=['3s'];h.update(actor=1,first_play=False,current_play=[],passes=[])
        self.assertEqual(a.legal_actions(r,1)['required_single'],'Kc')
        before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):a.act(r,1,'play',102,{'cards':['4c']})
        self.assertEqual(r,before)
        h['deadline']=103;a.tick(r,103);self.assertEqual(h['current_play'],['Kc']);self.assertEqual(h['actor'],4)
        self.assertTrue(p.seated(r,1)['away'])

    def test_triple_option_and_five_cards_cannot_bomb_single(self):
        r=room('big2',4);r['big2_rules']['triples']=False;a.start_hand(r,101);h=r['hand']
        h.update(actor=1,first_play=False,current_play=[]);h['players'][0]['cards']='4c 4d 4h Ks'.split()
        with self.assertRaises(p.RuleError):a.act(r,1,'play',102,{'cards':'4c 4d 4h'.split()})
        h['big2_rules']['triples']=True;a.act(r,1,'play',102,{'cards':'4c 4d 4h'.split()})
        h.update(actor=1,current_play=['3c']);h['players'][0]['cards']='5c 5d 5h 5s 6c'.split()
        with self.assertRaises(p.RuleError):a.act(r,1,'play',102,{'cards':h['players'][0]['cards'][:]})

    def test_early_departure_pays_remaining_cards_and_refunds_only_after_settlement(self):
        r=room('big2',4);total=points(r);a.start_hand(r,101)
        a.leave(r,1,102);self.assertTrue(p.seated(r,1)['leaving']);self.assertEqual(r['departures'],[])
        for uid in (2,3):a.leave(r,uid,102)
        self.assertEqual(r['status'],'waiting');self.assertEqual(r['hand']['results'][0]['charged'],520)
        self.assertEqual(sum(s['stack'] for s in r['seats'])+sum(s['stack'] for s in r['departures']),total)

class TaiwanStorage(unittest.TestCase):
    setUp=fixtures.ArcadeStorage.setUp
    call=fixtures.ArcadeStorage.call

    def test_options_history_replay_and_wallet_departure(self):
        user=self.users[1]
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'big2','stake':1,'big2_rules':{'triples':False,'twos_double':True}},user,100)['id']
        for uid in (2,3,4):self.call(rid,uid,'join',100)
        self.call(rid,1,'start',101);r=online.get_room(self.db,rid)
        self.assertEqual(r['hand']['reserve'],832)
        for s in r['seats']:s['away']=True
        a.tick(r,102);online.save(self.db,r,102)
        rows=self.db.execute('SELECT profit,payout FROM poker_results').fetchall()
        self.assertEqual(len(rows),4);self.assertEqual(sum(q['profit'] for q in rows),0)
        before=self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0]+sum(s['stack'] for s in r['seats'])
        for uid in (1,2,3,4):self.call(rid,uid,'leave',103,operation_id=f'taiwan_leave_{uid:08}')
        self.assertEqual(self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0],before)
        self.call(rid,4,'leave',104,operation_id='taiwan_leave_00000004')
        self.assertEqual(self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0],before)
        for bad in ({'triples':0},{'twos_double':'yes'},[]):
            with self.assertRaises(p.RuleError):a.big2_options(bad)

    def test_upgrade_keeps_active_legacy_hand_and_stored_history_unchanged(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'big2'},self.users[1],100)['id']
        for uid in (2,3,4):self.call(rid,uid,'join',100)
        self.call(rid,1,'start',101);r=online.get_room(self.db,rid)
        r.pop('big2_rules');r['hand'].pop('big2_rules');r['hand'].pop('reserve')
        for q in r['hand']['players']:
            q['stack']+=q['contribution']-10;q['contribution']=10;q['street_bet']=10
        p.sync_stacks(r);online.save(self.db,r,101);hand=copy.deepcopy(r['hand'])
        online.upgrade_big2_rules(self.db);online.upgrade_big2_rules(self.db)
        migrated=online.get_room(self.db,rid);self.assertEqual(migrated['hand'],hand)
        a._finish_big2(migrated,1,102);self.assertEqual(migrated['hand']['results'][0]['profit'],30)
        a.start_hand(migrated,106);self.assertEqual(migrated['hand']['big2_rules']['version'],2)

if __name__=='__main__':unittest.main()
