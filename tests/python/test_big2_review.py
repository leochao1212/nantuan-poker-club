"""Explicit house rules, turn identity, consecutive passes and fixed-ante payouts."""
import copy,unittest
import arcade_engine as a,poker_engine as p,online
from .test_arcade import room,points
from . import test_bonus as fixtures

class BigTwoReview(unittest.TestCase):
    def test_straight_boundaries_and_five_card_comparison(self):
        a.big2_score(['Tc','Jd','Qh','Ks','Ac'])
        for cards in (['Ac','2d','3h','4s','5c'],['2c','3d','4h','5s','6c'],['Jc','Qd','Kh','As','2c']):
            with self.assertRaises(p.RuleError):a.big2_score(cards)
        self.assertGreater(a.big2_score(['3s','3h','3d','2c','2h']),a.big2_score(['2s','Ks','Ts','7s','4s']))
        self.assertGreater(a.big2_score(['4c','4d','4h','4s','3d']),a.big2_score(['2s','2c','2d','Ah','As']))
        self.assertGreater(a.big2_score(['9c','Tc','Jc','Qc','Kc']),a.big2_score(['2c','2d','2h','2s','Ac']))
    def test_new_higher_play_resets_passes_and_last_player_leads(self):
        r=room('big2',4);a.start_hand(r,101)
        h=r['hand'];players=h['players'];uids=[q['user_id'] for q in players]
        # Synthetic mid-hand state isolates pass sequencing from the shuffle.
        for q in players:q.update(cards=['3'+a.SUITS[q['seat']],'K'+a.SUITS[q['seat']]])
        h.update(first_play=False,current_play=[],passes=[],actor=uids[0]);a.act(r,uids[0],'play',102,{'cards':['3c']})
        a.act(r,uids[3],'pass',103);a.act(r,uids[2],'play',104,{'cards':['3h']})
        self.assertEqual(h['passes'],[])
        for uid in (uids[1],uids[0],uids[3]):a.act(r,uid,'pass',105)
        self.assertEqual(h['actor'],uids[2]);self.assertEqual(h['current_play'],[])
        with self.assertRaises(p.RuleError):a.act(r,uids[2],'pass',106)
class QueuedBigTwo(unittest.TestCase):
    setUp=fixtures.Storage.setUp
    def test_action_received_before_deadline_survives_processing_delay_and_replays_once(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'big2'},self.user,100)['id'];path=f'/api/online/rooms/{rid}'
        other={'id':2,'username':'b','nickname':'B'}
        users={1:self.user,2:other}
        for uid in (3,4):
            self.db.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,f'player{uid}',f'P{uid}','2026-10-20'));users[uid]={'id':uid,'username':f'player{uid}','nickname':f'P{uid}'}
        for uid in (2,3,4):online.mutate(self.db,path+'/join',{'revision':online.get_room(self.db,rid)['revision']},users[uid],100)
        online.mutate(self.db,path+'/start',{'revision':online.get_room(self.db,rid)['revision']},self.user,101)
        r=online.get_room(self.db,rid);h=r['hand'];actor=users[h['actor']]
        data={'revision':r['revision'],'hand_id':h['id'],'turn_id':h['turn_id'],'operation_id':'delayed_big_two_play_001','action':'play','cards':[h['first_card']]}
        result=online.mutate(self.db,path+'/action',data,actor,120,received_at=115)
        self.assertFalse(result.get('conflict'));after=copy.deepcopy(online.get_room(self.db,rid))
        self.assertTrue(online.mutate(self.db,path+'/action',data,actor,121)['replayed']);self.assertEqual(online.get_room(self.db,rid),after)
        stale={**data,'operation_id':'stale_big_two_play_0002'}
        self.assertEqual(online.mutate(self.db,path+'/action',stale,actor,121)['reason'],'stale_turn')

if __name__=='__main__':unittest.main()
