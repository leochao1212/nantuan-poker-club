"""Taiwan mahjong legality, scoring, tile privacy and transaction invariants."""
import json,sqlite3,unittest,random
from collections import Counter
from copy import deepcopy
import mahjong_engine as m,poker_engine as p,online,wallet
import test_club

def tiles(types):
    used=Counter();out=[]
    for k in types:out.append(k*4+used[k]);used[k]+=1
    assert max(used.values(),default=0)<=4
    return out

def person(types,wind=0,melds=None,flowers=None):return dict(tiles=tiles(types),melds=melds or [],flowers=flowers or [],wind=wind)
STANDARD=[0,1,2,9,10,11,18,19,20,3,4,5,6,7,8,13,13]

def room():
    r=m.new_room('Mahjong',1,buy_in=3000)
    for uid in range(1,5):m.sit(r,uid,str(uid),0)
    m.start_hand(r,1)
    return r

def total(r):return sum(s['stack'] for s in r['seats'])+sum(s['stack'] for s in r['departures'])+(sum(p['contribution'] for p in r['hand']['players']) if r['status']=='playing' else 0)

class TaiwanScoring(unittest.TestCase):
    def test_five_melds_and_pair_only_not_thirteen_tile_shape(self):
        self.assertTrue(m.decompositions(tiles(STANDARD)))
        self.assertFalse(m.decompositions(tiles(STANDARD[:-3])))
        self.assertFalse(m.decompositions(tiles([*range(17)])))
        self.assertFalse(m.decompositions([0]*17))

    def test_closed_self_draw_is_three_not_one_plus_one_plus_three(self):
        q=person(STANDARD);result=m.score(q,q['tiles'][14],True)
        self.assertEqual(result,{'tai':3,'items':[{'name':'門清自摸','tai':3}]})

    def test_dragon_and_flush_patterns_do_not_double_count(self):
        q=person([31]*3+[32]*3+[33]*3+[0,1,2]+[9,10,11]+[18,18])
        result=m.score(q,q['tiles'][0],True);names=[i['name'] for i in result['items']]
        self.assertIn('大三元',names);self.assertNotIn('中',names);self.assertNotIn('發',names);self.assertNotIn('白',names)
        q=person([0]*3+[1]*3+[2]*3+[3]*3+[4]*3+[5]*2)
        result=m.score(q,q['tiles'][-1],True);names=[i['name'] for i in result['items']]
        self.assertIn('清一色',names);self.assertNotIn('混一色',names)

    def test_discard_completed_triplet_is_not_concealed(self):
        types=[0]*3+[3]*3+[9]*3+[12]*3+[18]*3+[33]*2
        q=person(types);winning=q['tiles'][0];self_draw=m.score(q,winning,True)
        q['tiles'].remove(winning);ron=m.score(q,winning)
        self.assertIn('五暗刻',[x['name'] for x in self_draw['items']]);self.assertIn('四暗刻',[x['name'] for x in ron['items']])
        self.assertNotIn('五暗刻',[x['name'] for x in ron['items']])

    def test_wind_flowers_and_special_timing_are_explicit(self):
        q=person([27]*3+[0,1,2,9,10,11,18,19,20,3,4,5,13,13],flowers=[136,140])
        result=m.score(q,q['tiles'][-1],True,round_wind=0,kong=True,last=True)
        names=[x['name'] for x in result['items']]
        self.assertIn('門風',names);self.assertIn('圈風',names);self.assertEqual(sum(x['tai'] for x in result['items'] if x['name'].startswith('正花')),2)
        self.assertIn('槓上開花',names);self.assertIn('海底撈月',names)
        heaven=m.score(q,q['tiles'][-1],True,heaven=True,kong=True)
        self.assertIn('天胡',[x['name'] for x in heaven['items']]);self.assertNotIn('門清自摸',[x['name'] for x in heaven['items']]);self.assertNotIn('槓上開花',[x['name'] for x in heaven['items']])

class MahjongFlow(unittest.TestCase):
    def test_start_validation_four_players_and_full_physical_deck(self):
        r=m.new_room('M',1)
        for uid in (1,2,3):m.sit(r,uid,str(uid),0)
        before=deepcopy(r)
        with self.assertRaises(p.RuleError):m.start_hand(r,1)
        self.assertEqual(r,before);m.sit(r,4,'4',0)
        with self.assertRaises(p.RuleError):m.sit(r,5,'5',0)
        before=deepcopy(r)
        for deck in (list(range(143)),[0]*144,[True]+list(range(1,144))):
            with self.assertRaises(p.RuleError):m.start_hand(r,1,deck=deck)
            self.assertEqual(r,before)
        r['seats'][0]['stack']=1379;before=deepcopy(r)
        with self.assertRaises(p.RuleError):m.start_hand(r,1)
        self.assertEqual(r,before)

    def test_deal_flowers_privacy_and_illegal_discard(self):
        r=room();h=r['hand'];self.assertEqual(sorted(len(q['tiles']) for q in h['players']),[16,16,16,17])
        all_tiles=h['wall']+[t for q in h['players'] for t in q['tiles']+q['flowers']]
        self.assertEqual(sorted(all_tiles),m.DECK);self.assertEqual(total(r),12000)
        v=m.public_view(r,2);self.assertNotIn('wall',v['hand']);self.assertEqual(v['hand']['players'][0]['tiles'],[]);self.assertIsNone(v['hand']['drawn_tile']);self.assertNotIn('session_id',v['seats'][0])
        before=deepcopy(r)
        for uid,t in [(2,h['players'][1]['tiles'][0]),(1,True),(1,-1)]:
            with self.assertRaises(p.RuleError):m.act(r,uid,'discard',2,{'tile':t})
            self.assertEqual(r,before)

    def test_chow_is_only_next_player_and_pong_beats_chow(self):
        r=room();h=r['hand'];h['players'][0]['tiles']=[8]
        h['players'][1]['tiles']=[0,4];h['players'][2]['tiles']=[9,10];h['players'][3]['tiles']=[1,5]
        h.update(actor=1,drawn_tile=8);m.act(r,1,'discard',2,{'tile':8})
        self.assertIn('chi',m.legal_actions(r,2)['actions']);self.assertIn('pong',m.legal_actions(r,3)['actions']);self.assertIsNone(m.legal_actions(r,4))
        turn=h['turn_id'];m.act(r,2,'chi',3,{'tiles':[0,4]});self.assertEqual(h['turn_id'],turn)
        m.act(r,3,'pong',3);self.assertEqual(h['actor'],3);self.assertEqual(h['players'][2]['melds'][0]['kind'],'pong');self.assertTrue(h['players'][0]['river'][-1]['claimed'])
        self.assertNotIn('hu',m.legal_actions(r,3)['actions'])

    def test_all_simultaneous_hu_claims_use_seat_priority_not_request_order(self):
        r=room();h=r['hand'];winning=tiles(STANDARD)[-1]
        for q in h['players'][1:]:q['tiles']=tiles(STANDARD)[:-1]
        h['players'][0]['river']=[{'tile':winning,'claimed':False}];m._open_claim(r,winning,1,2)
        for uid in (4,3,2):m.act(r,uid,'hu',3)
        self.assertEqual(h['winner'],2);self.assertEqual(sum(x['profit'] for x in h['results']),0);self.assertEqual(total(r),12000)

    def test_passed_hu_until_own_draw_and_added_kong_rob(self):
        r=room();h=r['hand'];q=h['players'][1];q['tiles']=tiles(STANDARD)[:-1];tile=tiles(STANDARD)[-1]
        q['passed_hu']=True;self.assertNotIn('hu',m._claim_options(h,q,tile,1))
        q['passed_hu']=False;h['players'][0]['tiles']=[tile];h['players'][0]['melds']=[{'kind':'pong','tiles':[52,53,54],'concealed':False,'from':3}]
        h.update(actor=1,drawn_tile=tile);m.act(r,1,'added_kong',2,{'tile':tile})
        self.assertTrue(h['last_discard']['rob']);self.assertEqual(m.legal_actions(r,2)['actions'],['hu','pass'])
        m.act(r,2,'hu',3);self.assertEqual(h['winner'],2);self.assertIn('搶槓',[x['name'] for x in h['score']['items']])

    def test_dealer_tai_is_added_only_to_the_dealer_payment(self):
        r=room();h=r['hand'];q=h['players'][1];q['tiles']=tiles(STANDARD);q['flowers']=[];h.update(actor=2,drawn_tile=q['tiles'][14],discard_count=8,draw_source='normal');q['draws']=2
        m.act(r,2,'hu',2)
        pays={x['from']:x for x in h['payments']};self.assertEqual(pays[1]['amount'],180);self.assertEqual(pays[3]['amount'],160);self.assertEqual(pays[4]['amount'],160)
        self.assertEqual(h['results'][1]['profit'],500);self.assertEqual(r['mahjong_dealer'],2);self.assertEqual(total(r),12000)
        # A kong before the dealer's first discard breaks an opening heavenly win.
        r=room();h=r['hand'];q=h['players'][0];q['tiles']=tiles(STANDARD);q['flowers']=[]
        h.update(drawn_tile=q['tiles'][14],draw_source='kong',calls=1,discard_count=0)
        m.act(r,1,'hu',2);names=[x['name'] for x in h['score']['items']]
        self.assertNotIn('天胡',names);self.assertIn('槓上開花',names)

    def test_passing_pong_lasts_until_own_draw_and_concealed_kong_stays_private(self):
        r=room();h=r['hand'];q=h['players'][1];q['tiles']=[0,1];q['passed_pong']=[0]
        self.assertNotIn('pong',m._claim_options(h,q,2,1));q['passed_pong']=[];self.assertIn('pong',m._claim_options(h,q,2,1))
        # Timeout is a pass too; it cannot bypass the same-tile pong restriction.
        q['tiles']=[52,53];h['players'][2]['tiles']=tiles(STANDARD)[:-1];h['players'][3]['tiles']=[8,9,10]
        h['players'][0]['river']=[{'tile':55,'claimed':False}];m._open_claim(r,55,1,2)
        r['seats'][1]['away']=True;m.tick(r,3)
        self.assertIn(13,q['passed_pong']);self.assertNotIn('pong',m._claim_options(h,q,54,1))
        m._draw(r,2,4);self.assertEqual(q['passed_pong'],[])
        r=room();h=r['hand'];q=h['players'][0];q['tiles']=tiles([0]*4+[1,2,3,9,10,11,18,19,20,13,13,5,6]);h['drawn_tile']=q['tiles'][0]
        m.act(r,1,'concealed_kong',2,{'tiles':q['tiles'][:4]})
        self.assertEqual(len(q['tiles']),14);self.assertEqual(q['melds'][0]['kind'],'kong');self.assertTrue(q['melds'][0]['concealed'])
        self.assertEqual(m.public_view(r,2)['hand']['players'][0]['melds'][0]['tiles'],[None]*4)
        self.assertEqual(len(m.public_view(r,1)['hand']['players'][0]['melds'][0]['tiles']),4);self.assertEqual(total(r),12000)

    def test_flower_wins_settle_without_a_standard_shape(self):
        for eight in (True,False):
            r=room();h=r['hand'];h['players'][0]['flowers']=list(range(136,144 if eight else 143))
            if not eight:h['players'][1]['flowers']=[143]
            for q in h['players'][2:]:q['flowers']=[]
            if eight:h['players'][1]['flowers']=[]
            self.assertTrue(m._flower_win(r,2));self.assertEqual(h['winner'],1)
            self.assertEqual(h['score']['items'],[{'name':'八仙過海' if eight else '七搶一','tai':8}])
            self.assertEqual(len(h['payments']),3 if eight else 1);self.assertEqual(total(r),12000)

    def test_high_priority_claim_does_not_wait_for_unneeded_lower_priority(self):
        r=room();h=r['hand'];winning=tiles(STANDARD)[-1];h['players'][1]['tiles']=tiles(STANDARD)[:-1]
        h['players'][2]['tiles']=[52,54];h['players'][3]['tiles']=[0]
        h['players'][0]['river']=[{'tile':winning,'claimed':False}];m._open_claim(r,winning,1,2)
        self.assertIn('pong',m.legal_actions(r,3)['actions']);m.act(r,2,'hu',3)
        self.assertEqual(r['status'],'waiting');self.assertEqual(h['winner'],2)

    def test_cap_and_draw_refund_leaving_and_restart(self):
        r=room();h=r['hand'];q=h['players'][0];q['tiles']=tiles(STANDARD);h.update(drawn_tile=q['tiles'][14],streak=100,discard_count=8)
        m.act(r,1,'hu',2);self.assertTrue(all(x['tai']==64 and x['amount']==1380 for x in h['payments']));self.assertEqual(total(r),12000)
        r=room();h=r['hand'];h['wall']=h['wall'][:16];uid=h['actor'];m.leave(r,uid,2)
        while r['status']=='playing':m.tick(r,1000)
        self.assertEqual(total(r),12000);self.assertEqual(r['departures'][0]['stack'],3000)

    def test_many_full_random_games_conserve_144_tiles_and_chips(self):
        rng=random.Random(480)
        for game in range(40):
            r=room()
            for step in range(600):
                if r['status']!='playing':break
                h=r['hand'];physical=h['wall'][:]
                for q in h['players']:physical+=q['tiles']+q['flowers']+[d['tile'] for d in q['river'] if not d['claimed']]+[t for meld in q['melds'] for t in meld['tiles']]
                self.assertEqual(sorted(physical),m.DECK);self.assertEqual(total(r),12000)
                if h['phase']=='claim':
                    ids=[int(x) for x in h['pending']];rng.shuffle(ids)
                    for uid in ids:
                        legal=m.legal_actions(r,uid)
                        if not legal:continue
                        action='hu' if 'hu' in legal['actions'] else rng.choice(legal['actions']);data={'tiles':legal['chi'][0]} if action=='chi' else {}
                        m.act(r,uid,action,2+step,data)
                else:
                    uid=h['actor'];legal=m.legal_actions(r,uid)
                    if 'hu' in legal['actions']:m.act(r,uid,'hu',2+step)
                    elif legal.get('concealed_kong'):m.act(r,uid,'concealed_kong',2+step,{'tiles':legal['concealed_kong'][0]})
                    elif legal.get('added_kong'):m.act(r,uid,'added_kong',2+step,{'tile':legal['added_kong'][0]})
                    else:m.act(r,uid,'discard',2+step,{'tile':rng.choice(legal['discard_tiles'])})
            self.assertEqual(r['status'],'waiting');self.assertEqual(total(r),12000)

class MahjongReceipts(unittest.TestCase):
    def setUp(self):
        test_club.WalletRules.setUp(self);self.db.execute("INSERT INTO users VALUES(4,'u4','P4')");self.users.append({'id':4,'username':'u4','nickname':'P4'})

    def call(self,path,data,uid=1,at=1):return online.mutate(self.db,path,data,self.users[uid-1],self.clock+at)

    def test_create_join_start_discard_retry_and_wallet_supply(self):
        made=self.call('/api/online/rooms',{'game_type':'mahjong','buy_in':2000,'operation_id':'mahjong_create_00001'});path=f'/api/online/rooms/{made["id"]}'
        for uid in (2,3,4):self.call(path+'/join',{'buy_in':2000,'operation_id':f'mahjong_join_0000{uid}'},uid)
        self.call(path+'/start',{'operation_id':'mahjong_start_000001'})
        r=online.get_room(self.db,made['id']);self.assertEqual([q['contribution'] for q in r['hand']['players']],[1380]*4)
        data={'action':'discard','tile':r['hand']['players'][0]['tiles'][0],'hand_id':r['hand']['id'],'turn_id':r['hand']['turn_id'],'operation_id':'mahjong_discard_0001'}
        self.call(path+'/action',data,at=2);self.assertTrue(self.call(path+'/action',data,at=3)['replayed'])
        self.assertTrue(self.call(path+'/action',{**data,'tile':143},at=3)['conflict'])
        r=online.get_room(self.db,made['id']);self.assertEqual(r['hand']['discard_count'],1);self.assertEqual(total(r),8000)
        v=online.room_view(self.db,made['id'],2,self.clock+3);self.assertEqual(v['hand']['players'][0]['tiles'],[])
        for uid in (1,2,3,4):self.call(path+'/leave',{'operation_id':f'mahjong_leave_0000{uid}'},uid,at=4)
        for i in range(300):
            online.maintenance(self.db,self.clock+5+i)
            if online.get_room(self.db,made['id'])['status']=='closed':break
        self.assertEqual(online.get_room(self.db,made['id'])['status'],'closed')
        self.assertEqual(sum(wallet.view(self.db,uid,self.clock+400)['balance'] for uid in (1,2,3,4)),12000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_operations WHERE operation_id=?',(data['operation_id'],)).fetchone()[0],1)

    def test_replay_is_unavailable_midgame_and_never_reveals_prior_opponent_hands(self):
        import club_features
        made=self.call('/api/online/rooms',{'game_type':'mahjong','buy_in':2000});rid=made['id'];path=f'/api/online/rooms/{rid}'
        for uid in (2,3,4):self.call(path+'/join',{'buy_in':2000,'operation_id':f'mj_replay_join_000{uid}'},uid)
        self.call(path+'/start',{'operation_id':'mj_replay_start_0001'});r=online.get_room(self.db,rid)
        with self.assertRaises(p.RuleError):club_features.replay(self.db,r,1,2)
        q=r['hand']['players'][0];q['tiles']=tiles(STANDARD);r['hand']['drawn_tile']=q['tiles'][14]
        m.act(r,1,'hu',self.clock+2);online.save(self.db,r,self.clock+2)
        replay=club_features.replay(self.db,r,1,2)
        first=replay['frames'][0]['state'];self.assertEqual(first['players'][0]['tiles'],[]);self.assertEqual(len(first['players'][1]['tiles']),16)
        self.assertNotIn('wall',first);self.assertNotIn('pending',first)
        self.assertEqual(len(replay['frames'][-1]['state']['players'][0]['tiles']),17)


if __name__=='__main__':unittest.main()
