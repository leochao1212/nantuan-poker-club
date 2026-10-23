"""Replay disclosure boundaries, private invitations and transactional ready checks."""
import copy
import json
import unittest
from unittest.mock import patch
import online,club_features as f,bonus_engine,arcade_engine,wallet,social
from poker_engine import RuleError
import test_club as fixtures
from test_app import ServerTestCase


class FeatureRules(unittest.TestCase):
    def setUp(self):
        fixtures.WalletRules.setUp(self)

    def create(self,private=False,ready=False,kind='holdem'):
        return online.mutate(self.db,'/api/online/rooms',{'name':'Feature table','private':private,'ready_required':ready,'game_type':kind,'buy_in':1000,'stake':10},self.users[0],self.clock)['id']

    def command(self,rid,uid,verb,**data):
        return online.mutate(self.db,f'/api/online/rooms/{rid}/{verb}',{'operation_id':f'feature_operation_{self.sequence:08d}',**data},self.users[uid-1],self.clock)

    def join(self,rid,uid):
        self.sequence+=1;return self.command(rid,uid,'join')

    def operation(self,rid,uid,verb,**data):
        self.sequence+=1;return self.command(rid,uid,verb,**data)

    sequence=0

    def test_private_table_hidden_admission_and_chat_boundaries(self):
        rid=self.create(True,True);room=online.get_room(self.db,rid)
        self.assertEqual(online.lobby(self.db,self.users[1],self.clock)['rooms'],[])
        for operation in (lambda:online.room_view(self.db,rid,2,self.clock),lambda:self.join(rid,2),lambda:online.heartbeat(self.db,2,rid,self.clock),lambda:social.mutate(self.db,f'/api/social/rooms/{rid}/chat',{'message':'hi','nonce':'private_message_test_01'},self.users[1],self.clock)):
            with self.assertRaisesRegex(RuleError,'私人包廂'):operation()
        with self.assertRaises(RuleError):self.operation(rid,2,'invite',code='wrong')
        self.operation(rid,2,'invite',code=room['party']['code']);self.join(rid,2)
        view=online.room_view(self.db,rid,2,self.clock)
        self.assertTrue(view['party']['private']);self.assertNotIn('members',view['party'])
        self.assertNotIn('session_id',json.dumps(view));self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],2000)
        self.assertEqual(len(online.lobby(self.db,self.users[1],self.clock)['rooms']),1)

    def test_invitation_retry_is_atomic_and_does_not_transfer_chips(self):
        rid=self.create(True);code=online.get_room(self.db,rid)['party']['code'];path=f'/api/online/rooms/{rid}/invite';data={'operation_id':'invite_idempotent_test_01','code':code}
        before=wallet.view(self.db,2,self.clock)['balance'];online.mutate(self.db,path,data,self.users[1],self.clock)
        self.assertTrue(online.mutate(self.db,path,data,self.users[1],self.clock)['replayed'])
        self.assertEqual(online.get_room(self.db,rid)['party']['members'],[1,2]);self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],before)
        self.assertTrue(online.mutate(self.db,path,{**data,'code':'different'},self.users[1],self.clock)['conflict'])

    def test_public_creation_ignores_old_ready_setting(self):
        rid=self.create(ready=True);self.join(rid,2)
        self.assertIsNone(online.room_view(self.db,rid,1,self.clock)['party'])
        self.operation(rid,2,'start')
        self.assertEqual(online.get_room(self.db,rid)['status'],'playing')

    def test_private_table_starts_and_restarts_without_ready(self):
        rid=self.create(True,True);code=online.get_room(self.db,rid)['party']['code']
        self.operation(rid,2,'invite',code=code);self.join(rid,2)
        self.assertFalse(online.room_view(self.db,rid,1,self.clock)['party']['required'])
        self.operation(rid,2,'start');room=online.get_room(self.db,rid)
        self.operation(rid,room['hand']['actor'],'action',action='fold',hand_id=room['hand']['id'],turn_id=online.rules(room).turn_id(room['hand']))
        self.clock+=10
        self.operation(rid,1,'start');self.assertEqual(online.get_room(self.db,rid)['hand_no'],2)

    def test_existing_legacy_ready_room_has_no_gate_but_minimum_remains(self):
        rid=self.create(True);room=online.get_room(self.db,rid);room['party']['required']=True;online.save(self.db,room,self.clock)
        with self.assertRaises(RuleError):self.operation(rid,1,'start')
        self.operation(rid,2,'invite',code=room['party']['code']);self.join(rid,2)
        view=online.room_view(self.db,rid,1,self.clock)['party'];self.assertFalse(view['required']);self.assertTrue(view['can_start'])
        with self.assertRaisesRegex(RuleError,'已取消'):self.operation(rid,1,'ready',ready=True)
        self.operation(rid,2,'start');self.assertEqual(online.get_room(self.db,rid)['status'],'playing')

    def test_legacy_table_keeps_existing_start_behavior(self):
        rid=self.create();self.join(rid,2);self.operation(rid,2,'start')
        self.assertIsNone(online.room_view(self.db,rid,1,self.clock)['party'])

    def test_replay_own_hole_only_and_uncontested_opponent_stays_hidden(self):
        rid=self.create();self.join(rid,2);self.operation(rid,1,'start');r=online.get_room(self.db,rid)
        holes={p['user_id']:p['hole'] for p in r['hand']['players']};actor=r['hand']['actor']
        with self.assertRaisesRegex(RuleError,'已結束'):f.replay(self.db,r,1,1)
        self.operation(rid,actor,'action',action='fold',hand_id=r['hand']['id'],turn_id=online.rules(r).turn_id(r['hand']))
        r=online.get_room(self.db,rid)
        for uid in (1,2,3):
            replay=f.replay(self.db,r,1,uid);self.assertEqual(len(replay['frames']),2)
            for frame in replay['frames']:
                for p in frame['state']['players']:self.assertEqual(p['hole'],holes[uid] if p['user_id']==uid else [])
            self.assertNotIn('deck',json.dumps(replay));self.assertNotIn('private_state',json.dumps(replay));self.assertNotIn('session_id',json.dumps(replay))
        count=self.db.execute('SELECT count(*) FROM replay_steps').fetchone()[0];online.save(self.db,r,self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM replay_steps').fetchone()[0],count)

    def test_legacy_replay_is_explicit_without_inventing_steps(self):
        rid=self.create();self.join(rid,2);self.operation(rid,1,'start');r=online.get_room(self.db,rid)
        self.operation(rid,r['hand']['actor'],'action',action='fold',hand_id=r['hand']['id'],turn_id=online.rules(r).turn_id(r['hand']))
        self.db.execute('DELETE FROM replay_steps');value=f.replay(self.db,online.get_room(self.db,rid),1,1)
        self.assertTrue(value['legacy']);self.assertEqual(value['frames'],[]);self.assertTrue(value['result']['results'])
        self.operation(rid,1,'rebuy',amount=10)
        self.assertTrue(f.replay(self.db,online.get_room(self.db,rid),1,1)['legacy'])

    def test_big_two_replay_never_reveals_other_remaining_hands(self):
        self.db.execute('INSERT INTO users VALUES(?,?,?)',(4,'u4','P4'));wallet.create(self.db,4,self.clock)
        self.users.append({'id':4,'username':'u4','nickname':'P4'})
        rid=self.create(kind='big2')
        for uid in (2,3,4):self.join(rid,uid)
        self.operation(rid,1,'start');r=online.get_room(self.db,rid)
        self.operation(rid,r['hand']['actor'],'action',action='play',cards=[r['hand']['first_card']],hand_id=r['hand']['id'],turn_id=online.rules(r).turn_id(r['hand']))
        for uid in (2,3,4):self.operation(rid,uid,'leave')
        r=online.get_room(self.db,rid);self.assertEqual(r['status'],'waiting')
        for uid in (1,2,3,4):
            replay=f.replay(self.db,r,1,uid)
            self.assertEqual(next(p for p in replay['frames'][0]['state']['players'] if p['user_id']==uid)['card_count'],13)
            for frame in replay['frames']:
                for p in frame['state']['players']:
                    if p['user_id']!=uid:self.assertEqual(p['cards'],[])

    def test_roulette_repeated_result_keeps_distinct_hand_numbers(self):
        rid=self.create(kind='roulette')
        for _ in range(3):
            self.operation(rid,1,'start');r=online.get_room(self.db,rid)
            with patch.object(arcade_engine.secrets,'randbelow',return_value=17):self.operation(rid,1,'action',action='bet',bets=[{'kind':'red','amount':10}],hand_id=r['hand']['id'],turn_id=online.rules(r).turn_id(r['hand']))
        self.assertEqual([r[0] for r in self.db.execute('SELECT hand_number FROM poker_hands ORDER BY hand_number')],[1,2,3])
        for n in (1,2,3):self.assertEqual(f.replay(self.db,online.get_room(self.db,rid),n,1)['frames'][-1]['state']['number'],17)

    def test_private_replay_denies_non_invited_member_after_settlement(self):
        rid=self.create(True);code=online.get_room(self.db,rid)['party']['code'];self.operation(rid,2,'invite',code=code);self.join(rid,2);self.operation(rid,1,'start');r=online.get_room(self.db,rid)
        self.operation(rid,r['hand']['actor'],'action',action='fold',hand_id=r['hand']['id'],turn_id=online.rules(r).turn_id(r['hand']))
        with self.assertRaisesRegex(RuleError,'私人'):f.replay(self.db,online.get_room(self.db,rid),1,3)


class FeatureAPI(ServerTestCase):
    def test_diagnostics_replay_and_private_read_channels_require_auth(self):
        owner,outsider=self.clients[:2]
        self.assertEqual(owner.call('/api/register',{'username':'feature_owner','nickname':'Owner','password':'password123'})[0],200)
        code=owner.call('/api/state')[1]['invite_code']
        self.assertEqual(outsider.call('/api/register',{'username':'feature_other','nickname':'Other','password':'password123','invite_code':code})[0],200)
        self.assertEqual(outsider.call('/api/online/diagnostics')[0],200)
        status,created=owner.call('/api/online/rooms',{'name':'Private HTTP','private':True,'ready_required':True,'game_type':'blackjack','buy_in':100,'stake':10,'operation_id':'feature_http_create_01'})
        self.assertEqual(status,200);rid=created['id']
        for path in (f'/api/online/rooms/{rid}',f'/api/online/events?room={rid}',f'/api/online/rooms/{rid}/replay/1'):
            self.assertEqual(outsider.call(path)[0],400)
        self.assertNotIn('Private HTTP',json.dumps(outsider.call('/api/online/lobby')[1]))
        owner.call('/api/logout',{})
        self.assertEqual(owner.call('/api/online/diagnostics')[0],401)
        self.assertEqual(owner.call(f'/api/online/rooms/{rid}/replay/1')[0],401)

