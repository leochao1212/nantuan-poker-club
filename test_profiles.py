"""Profile privacy, account enforcement, safe avatars and audit conservation."""
import base64,copy,json,sqlite3,struct,time,unittest,zlib,random
from contextlib import closing
import member_accounts as m,online,wallet,club_admin,rewards,transfers,social
import test_admin as fixtures
from test_app import ServerTestCase
from test_realtime import Stream
from poker_engine import RuleError

def image(metadata=False):
    raw=b'\x89PNG\r\n\x1a\n'+m._chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,6,0,0,0))
    if metadata:raw+=m._chunk(b'tEXt',b'Comment\x00private-camera-info')
    return 'data:image/png;base64,'+base64.b64encode(raw+m._chunk(b'IDAT',zlib.compress(b'\x00'+b'\xff\x00\x00\xff'*2+b'\x00'+b'\x00\xff\x00\xff'*2))+m._chunk(b'IEND',b'')).decode()

class ProfileRules(unittest.TestCase):
    def setUp(self):
        fixtures.AdminRules.setUp(self)
        self.db.execute("INSERT INTO settings VALUES('invite_code','TESTONLY')")
    def edit_request(self,**extra):return {'nickname':'新暱稱','avatar_key':'photo','avatar_data':image(True),'profile_revision':0,'operation_id':'profile_test_0000001',**extra}
    def control(self,action='block',**extra):return {'user_id':2,'action':action,'reason':'測試處理','state_revision':0,'operation_id':'account_test_0000001',**extra}
    def test_photo_is_bounded_metadata_stripped_and_retries_do_not_overwrite(self):
        before=wallet.view(self.db,2,self.clock)['total'];r=m.update(self.db,{'id':2},self.edit_request(user_id=1,is_admin=True),self.clock)
        self.assertEqual(r['profile']['nickname'],'新暱稱');self.assertEqual(r['profile']['profile_revision'],1)
        picture=self.db.execute('SELECT avatar_png FROM member_profiles WHERE user_id=2').fetchone()[0]
        self.assertNotIn(b'private-camera-info',picture);self.assertEqual(m.png_image('data:image/png;base64,'+base64.b64encode(picture).decode()),picture)
        self.assertTrue(m.update(self.db,{'id':2},self.edit_request(user_id=1,is_admin=True),self.clock)['replayed'])
        with self.assertRaises(m.AccountError):m.update(self.db,{'id':2},self.edit_request(nickname='不一致'),self.clock)
        with self.assertRaises(m.AccountError):m.update(self.db,{'id':2},self.edit_request(operation_id='profile_stale_000001'),self.clock)
        self.assertEqual(wallet.view(self.db,2,self.clock)['total'],before)
        self.assertEqual(self.db.execute('SELECT nickname FROM users WHERE id=1').fetchone()[0],'Player1')
        self.assertNotIn('avatar_png',json.dumps(m.public_profiles(self.db)))

    def test_bad_images_control_names_and_non_owned_cosmetics_are_rejected(self):
        bads=['data:image/svg+xml;base64,AAAA','data:image/png;base64,%%%%',image()+'AA',image()[:-8],False]
        header=b'\x89PNG\r\n\x1a\n'+m._chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,6,0,0,0))
        bads.append('data:image/png;base64,'+base64.b64encode(header+m._chunk(b'IDAT',zlib.compress(b'X'*1000000))+m._chunk(b'IEND',b'')).decode())
        for value in bads:
            with self.assertRaises(RuleError):m.update(self.db,{'id':2},self.edit_request(avatar_data=value),self.clock)
        for nickname in ('', 'a'*17,'user\x00name','\u202Efake'):
            with self.assertRaises(RuleError):m.update(self.db,{'id':2},self.edit_request(nickname=nickname),self.clock)
        with self.assertRaises(RuleError):rewards.mutate(self.db,'/api/club/equip',{'item_id':'effect_aurora'},{'id':2},self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM member_profiles').fetchone()[0],0)

    def test_high_detail_thumbnail_stays_inside_payload_and_pixel_limits(self):
        rng=random.Random(724);pixels=b''.join(b'\x00'+rng.randbytes(128*4) for _ in range(128))
        raw=b'\x89PNG\r\n\x1a\n'+m._chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,6,0,0,0))+m._chunk(b'IDAT',zlib.compress(pixels))+m._chunk(b'IEND',b'')
        data='data:image/png;base64,'+base64.b64encode(raw).decode()
        self.assertGreater(len(data),32768);self.assertLess(len(data),100000)
        self.assertEqual(m.png_image(data),raw)

    def test_chat_reuses_identity_without_repeating_photo_or_equipment_per_message(self):
        rid=online.mutate(self.db,'/api/online/rooms',{}, {'id':2,'nickname':'Player2'},self.clock)['id']
        m.update(self.db,{'id':2},self.edit_request(),self.clock)
        self.db.execute("INSERT INTO cosmetic_items VALUES(2,'title_ace',?)",(self.clock,))
        rewards.mutate(self.db,'/api/club/equip',{'item_id':'title_ace'},{'id':2},self.clock)
        for i in range(50):self.db.execute('INSERT INTO room_chat(room_id,user_id,message,nonce,created_at) VALUES(?,?,?,?,?)',(rid,2,'hello',f'synthetic_chat_{i}',self.clock))
        view=social.view(self.db,rid,1,self.clock)
        self.assertEqual(len(view['messages']),50);self.assertEqual(len(view['identities']),1)
        self.assertEqual(view['identities']['2']['cosmetics']['title']['id'],'title_ace')
        self.assertTrue(view['identities']['2']['avatar_url'].endswith('/1.png'))
        self.assertNotIn('avatar_png',json.dumps(view));self.assertTrue(all('cosmetics' not in row for row in view['messages']))

    def test_profile_changes_update_current_seat_without_changing_cards_or_turn(self):
        rid=online.mutate(self.db,'/api/online/rooms',{}, {'id':2,'nickname':'Player2'},self.clock)['id'];path=f'/api/online/rooms/{rid}'
        online.mutate(self.db,path+'/join',{'revision':online.get_room(self.db,rid)['revision']},{'id':3,'nickname':'Player3'},self.clock)
        online.mutate(self.db,path+'/start',{'revision':online.get_room(self.db,rid)['revision']},{'id':2},self.clock+1)
        before=copy.deepcopy(online.get_room(self.db,rid)['hand']);m.update(self.db,{'id':2},self.edit_request(),self.clock+2)
        after=online.get_room(self.db,rid)['hand'];next(q for q in before['players'] if q['user_id']==2)['nickname']='新暱稱';self.assertEqual(before,after)
        for uid in (2,3):
            view=online.room_view(self.db,rid,uid,self.clock+2);other=next(s for s in view['seats'] if s['user_id']==2)
            self.assertEqual(other['nickname'],'新暱稱');self.assertTrue(other['avatar_url'].endswith('/1.png'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands').fetchone()[0],0)

    def test_permissions_first_password_gate_and_admin_protection(self):
        with self.assertRaises(club_admin.AdminError):m.moderate(self.db,{'id':3},self.control(),self.clock)
        self.db.execute('UPDATE club_admins SET password_change_required=1')
        with self.assertRaises(club_admin.AdminError):m.moderate(self.db,self.actor,self.control(),self.clock)
        self.db.execute('UPDATE club_admins SET password_change_required=0')
        with self.assertRaises(m.AccountError):m.moderate(self.db,self.actor,self.control(user_id=1),self.clock)
        self.db.execute('INSERT INTO club_admins VALUES(3,0,?)',(self.clock,))
        with self.assertRaises(m.AccountError):m.moderate(self.db,self.actor,self.control(user_id=3),self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_account_events').fetchone()[0],0)

    def test_state_races_and_retry_preserve_history_and_points(self):
        self.db.commit();before=wallet.view(self.db,2,self.clock)['total']
        request=self.control();m.moderate(self.db,self.actor,request,self.clock)
        self.assertTrue(m.moderate(self.db,self.actor,request,self.clock)['replayed'])
        with self.assertRaises(m.AccountError):m.moderate(self.db,self.actor,self.control(action='unblock',operation_id='unblock_stale_00001'),self.clock)
        with self.assertRaises(m.AccountError):m.moderate(self.db,self.actor,self.control(reason='different'),self.clock)
        unblock=self.control('unblock',state_revision=1,operation_id='unblock_correct_0001');m.moderate(self.db,self.actor,unblock,self.clock)
        self.assertEqual(m.state(self.db,2)['status'],'active')
        with self.assertRaises(RuleError):m.moderate(self.db,self.actor,self.control('delete',state_revision=2,operation_id='delete_account_0001',confirm_username='wrong'),self.clock)
        delete=self.control('delete',state_revision=2,operation_id='delete_account_0001',confirm_username='user_2');m.moderate(self.db,self.actor,delete,self.clock)
        self.assertTrue(m.moderate(self.db,self.actor,delete,self.clock)['replayed'])
        self.assertIn('已刪除',m.profile(self.db,2)['nickname']);self.assertEqual(wallet.view(self.db,2,self.clock)['total'],before)
        self.assertNotIn(2,[u['id'] for u in online.lobby(self.db,{'id':1,'username':'user_1','nickname':'Player1'},self.clock)['users']])
        self.assertEqual(len(club_admin.accounts(self.db,self.actor,self.clock)['account_history']),3)
        self.assertEqual(self.db.execute('SELECT count(*) FROM users').fetchone()[0],3)

    def test_moderation_rollback_restores_seat_wallet_and_access(self):
        rid=online.mutate(self.db,'/api/online/rooms',{}, {'id':2,'nickname':'Player2'},self.clock)['id'];self.db.commit()
        before=online.get_room(self.db,rid);balance=wallet.view(self.db,2,self.clock)['balance']
        with self.assertRaises(RuntimeError):
            with self.db:
                m.moderate(self.db,self.actor,self.control(),self.clock)
                raise RuntimeError('forced rollback')
        self.assertEqual(online.get_room(self.db,rid),before);self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],balance);self.assertEqual(m.state(self.db,2)['status'],'active')
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_account_events').fetchone()[0],0)

    def test_block_in_progress_big_two_settles_once_without_minting(self):
        self.db.execute("INSERT INTO users VALUES(4,'user_4','Player4','2026-10-20')");wallet.create(self.db,4,self.clock)
        users={i:{'id':i,'username':f'user_{i}','nickname':f'Player{i}'} for i in range(1,5)}
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'big2'},users[2],self.clock)['id'];path=f'/api/online/rooms/{rid}'
        for uid in (1,3,4):online.mutate(self.db,path+'/join',{'revision':online.get_room(self.db,rid)['revision']},users[uid],self.clock)
        online.mutate(self.db,path+'/start',{'revision':online.get_room(self.db,rid)['revision']},users[2],self.clock+1)
        r=online.get_room(self.db,rid)
        # Make the moderated user the holder of the mandatory opening card.
        actor=r['hand']['actor']
        if actor!=2:
            first=next(q for q in r['hand']['players'] if q['user_id']==actor);target=next(q for q in r['hand']['players'] if q['user_id']==2)
            first['cards'],target['cards']=target['cards'],first['cards'];r['hand']['actor']=2;online.save(self.db,r,self.clock+1)
        m.moderate(self.db,self.actor,self.control(),self.clock+2)
        r=online.get_room(self.db,rid);self.assertIsNone(r['hand']['first_card']);self.assertTrue(next(s for s in r['seats'] if s['user_id']==2)['leaving'])
        for seat in r['seats']:seat['away']=True
        online.rules(r).tick(r,self.clock+3);online.save(self.db,r,self.clock+3)
        self.assertEqual(sum(wallet.view(self.db,u,self.clock)['total'] for u in users),12000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT sum(profit) FROM poker_results').fetchone()[0],0)
        self.assertIsNone(online.current_room(self.db,2))

class ProfileAPI(ServerTestCase):
    def test_edit_password_avatar_enforcement_and_account_audit(self):
        admin,alice,bob,alice_other,anon=self.clients[:5];old='Password123';new='MyNewPassword456'
        self.assertEqual(admin.call('/api/register',{'username':'profile_admin','nickname':'管理員','password':old})[0],200)
        invite=admin.call('/api/state')[1]['invite_code']
        for c,name in ((alice,'profile_alice'),(bob,'profile_bob')):self.assertEqual(c.call('/api/register',{'username':name,'nickname':name,'password':old,'invite_code':invite})[0],200)
        with closing(sqlite3.connect(self.db_path)) as db:db.execute('INSERT INTO club_admins VALUES(1,0,?)',(time.time(),));db.commit()
        self.assertEqual(anon.call('/api/profile')[0],401)
        payload={'nickname':'新名字','avatar_key':'photo','avatar_data':image(),'profile_revision':0,'user_id':3,'operation_id':'profile_http_00000001'}
        status,res=alice.call('/api/profile',payload);self.assertEqual(status,200,res);url=res['profile']['avatar_url']
        self.assertEqual(alice.call('/api/profile',payload)[1]['replayed'],True)
        self.assertEqual(anon.call(url)[0],401);self.assertEqual(bob.call(url)[0],200);self.assertEqual(bob.call('/api/profile')[1]['profile']['nickname'],'profile_bob')
        self.assertEqual(alice_other.call('/api/login',{'username':'profile_alice','password':old})[0],200)
        self.assertEqual(alice.call('/api/profile/password',{'current_password':'WrongPassword','new_password':new})[0],403)
        self.assertEqual(alice.call('/api/profile/password',{'current_password':old,'new_password':new})[0],200)
        self.assertEqual(alice_other.call('/api/profile')[0],401);self.assertEqual(alice.call('/api/profile')[0],200)
        block={'user_id':2,'action':'block','reason':'暫停測試','state_revision':0,'operation_id':'block_http_000000001'}
        self.assertEqual(bob.call('/api/admin/account-action',block)[0],403)
        with closing(Stream(alice,'/api/online/events?presence=client')) as stream:
            stream.state();self.assertEqual(admin.call('/api/admin/account-action',block)[0],200)
            for _ in range(5):
                if stream.event()[0]=='auth':break
            else:self.fail('blocked member stream did not revoke')
        self.assertEqual(alice.call('/api/profile')[0],401);self.assertEqual(alice.call('/api/login',{'username':'profile_alice','password':new})[0],401)
        self.assertEqual(bob.call('/api/wallet/recipients?search=profile_alice')[1]['recipients'],[])
        self.assertEqual(bob.call('/api/wallet/transfers',{'recipient_id':2,'recipient_username':'profile_alice','amount':10,'operation_id':'disabled_transfer_0001'})[0],409)
        self.assertEqual(admin.call('/api/admin/account-action',{**block,'action':'unblock','state_revision':1,'operation_id':'unblock_http_0000001'})[0],200)
        self.assertEqual(alice.call('/api/login',{'username':'profile_alice','password':new})[0],200)
        delete={**block,'action':'delete','state_revision':2,'operation_id':'delete_http_00000001','confirm_username':'profile_alice'}
        self.assertEqual(admin.call('/api/admin/account-action',delete)[0],200)
        self.assertEqual(alice.call('/api/profile')[0],401);self.assertEqual(alice.call('/api/login',{'username':'profile_alice','password':new})[0],401)
        self.assertEqual(admin.call('/api/admin/account-action',delete)[1]['replayed'],True)
        admin_state=admin.call('/api/admin/accounts')[1];self.assertEqual(len(admin_state['account_history']),3)
        self.assertNotIn(2,[a['id'] for a in admin_state['accounts']])
        self.assertEqual(admin_state['total_accounts'],2)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute('SELECT sum(balance) FROM wallets').fetchone()[0],9000)
            self.assertIsNone(db.execute('SELECT avatar_png FROM member_profiles WHERE user_id=2').fetchone()[0])
            self.assertEqual(db.execute('SELECT status FROM account_states WHERE user_id=2').fetchone()[0],'deleted')

if __name__=='__main__':unittest.main()
