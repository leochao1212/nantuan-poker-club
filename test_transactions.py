"""Regression coverage for report: independent turns, FIFO deadlines, receipts."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time
import unittest
import online
import poker_engine as engine
from test_app import ServerTestCase


class TransactionRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,nickname TEXT)')
        self.db.executemany('INSERT INTO users VALUES(?,?)',[(i,f'P{i}') for i in range(1,5)])
        online.initialize(self.db)
        self.users=[{'id':i,'nickname':f'P{i}'} for i in range(1,5)]
        self.rid=online.mutate(self.db,'/api/online/rooms',{'name':'Regression'},self.users[0],100)['id']
        self.path=f'/api/online/rooms/{self.rid}'
        self.call('join',self.users[1],101,seat=4)

    def room(self):return online.get_room(self.db,self.rid)

    def call(self,action,user,clock=105,**extra):
        return online.mutate(self.db,self.path+'/'+action,{'revision':self.room()['revision'],**extra},user,clock)

    def started(self):
        self.call('start',self.users[0],104)
        room=self.room()
        uid=room['hand']['actor']
        return room,self.users[uid-1]

    def test_join_does_not_invalidate_turn_and_preserves_seat(self):
        before,user=self.started()
        self.call('join',self.users[2],105,seat=2)
        self.assertEqual(engine.seated(self.room(),3)['seat'],2)
        self.assertEqual(engine.seated(self.room(),2)['seat'],4)
        result=online.mutate(self.db,self.path+'/action',{'revision':before['revision'],
            'hand_id':before['hand']['id'],'turn_id':engine.turn_id(before['hand']),
            'operation_id':'join_regression_0001','action':'call'},user,106)
        self.assertFalse(result.get('conflict'))
        self.assertNotEqual(engine.turn_id(self.room()['hand']),engine.turn_id(before['hand']))

    def test_same_operation_is_applied_once_and_content_cannot_change(self):
        payload={'revision':self.room()['revision'],'operation_id':'rebuy_regression_001'}
        path=self.path+'/rebuy'
        first=online.mutate(self.db,path,payload,self.users[0],102)
        stack=engine.seated(self.room(),1)['stack']
        replay=online.mutate(self.db,path,payload,self.users[0],110)
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['id'],replay['id'])
        self.assertEqual(engine.seated(self.room(),1)['stack'],stack)
        conflict=online.mutate(self.db,self.path+'/return',payload,self.users[0],111)
        self.assertEqual(conflict['reason'],'operation_mismatch')

    def test_arrival_before_deadline_survives_slow_processing(self):
        before,user=self.started()
        deadline=before['hand']['deadline']
        result=online.mutate(self.db,self.path+'/action',{'revision':before['revision'],
            'hand_id':before['hand']['id'],'turn_id':engine.turn_id(before['hand']),
            'operation_id':'slow_processing_001','action':'call'},user,deadline+5,received_at=deadline-.1)
        self.assertFalse(result.get('conflict'))
        self.assertFalse(engine.seated(self.room(),user['id'])['away'])
        self.assertEqual(self.room()['hand']['deadline'],deadline+35)

    def test_actual_late_action_expires_and_marks_reason(self):
        before,user=self.started()
        clock=before['hand']['deadline']+.1
        result=online.mutate(self.db,self.path+'/action',{'revision':before['revision'],
            'turn_id':engine.turn_id(before['hand']),'hand_id':before['hand']['id'],'action':'call'},user,clock,received_at=clock)
        self.assertEqual(result['reason'],'turn_expired')
        self.assertEqual(engine.seated(self.room(),user['id'])['away_reason'],'timeout')

    def test_old_turn_cannot_apply_again_after_action(self):
        before,user=self.started()
        payload={'revision':before['revision'],'hand_id':before['hand']['id'],
                 'turn_id':engine.turn_id(before['hand']),'action':'call'}
        online.mutate(self.db,self.path+'/action',payload,user,106)
        self.assertEqual(online.mutate(self.db,self.path+'/action',payload,user,107)['reason'],'stale_turn')


class QueuedHTTP(ServerTestCase):
    def test_sqlite_delay_cannot_allow_timeout_to_overtake_action(self):
        a,b=self.clients[:2]
        a.call('/api/register',{'username':'queue_a','nickname':'A','password':'password123'})
        code=a.call('/api/state')[1]['invite_code']
        b.call('/api/register',{'username':'queue_b','nickname':'B','password':'password123','invite_code':code})
        rid=a.call('/api/online/rooms',{'name':'Queue test'})[1]['id']
        path=f'/api/online/rooms/{rid}'
        b.call(path+'/join',{'revision':a.call(path)[1]['revision']})
        a.call(path+'/start',{'revision':a.call(path)[1]['revision']})
        state=a.call(path)[1]
        actor=a if state['hand']['actor']==1 else b
        payload={'revision':state['revision'],'hand_id':state['hand']['id'],
            'turn_id':state['hand']['turn_id'],'action':'call','operation_id':'queued_http_regression_01'}
        # Hold an actual SQLite writer lock across the deadline while the HTTP
        # action and dealer thread compete. Only this isolated DB is touched.
        with closing(sqlite3.connect(self.db_path,timeout=5)) as db:
            stored=json.loads(db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0])
            stored['hand']['deadline']=time.time()+.9
            db.execute('UPDATE poker_rooms SET state=? WHERE id=?',(json.dumps(stored),rid))
            db.commit()
            db.execute('BEGIN IMMEDIATE')
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(actor.call,path+'/action',payload)
                time.sleep(1.6)
                db.commit()
                status,result=future.result(timeout=8)
        self.assertEqual(status,200,result)
        self.assertTrue(result['request_id'])
        after=result['state']
        self.assertNotEqual(after['hand']['actor'],state['hand']['actor'])
        self.assertGreater(after['hand']['deadline'],time.time()+27)
        self.assertFalse(next(s for s in after['seats'] if s['user_id']==state['hand']['actor'])['away'])
        stacks=[s['stack'] for s in after['seats']]
        with ThreadPoolExecutor(2) as pool:
            replays=list(pool.map(lambda _:actor.call(path+'/action',payload),range(2)))
        for status,result in replays:
            self.assertEqual(status,200)
            self.assertTrue(result['replayed'])
            self.assertEqual([s['stack'] for s in result['state']['seats']],stacks)
        other=b if actor is a else a
        self.assertNotIn(payload['operation_id'],other.call(path)[1]['accepted_operations'])
        self.assertIn(payload['operation_id'],actor.call(path)[1]['accepted_operations'])
        status,error=actor.call(path+'/action',{**payload,'action':'fold'})
        self.assertEqual((status,error['reason']),(409,'operation_mismatch'))
        status,error=actor.call(path+'/action',{**payload,'operation_id':'old_turn_rejected_001'})
        self.assertEqual((status,error['reason']),(409,'stale_turn'))
        # Receipts survive a real process restart, like the room itself.
        import os,subprocess
        args=self.proc.args
        self.proc.terminate()
        self.proc.wait(timeout=10)
        env=dict(os.environ,POKER_DB=str(self.db_path),PYTHONIOENCODING='utf-8',POKER_SECURE_COOKIE='0',POKER_REQUIRE_INVITE='0',POKER_PUBLIC_ORIGIN='')
        type(self).proc=subprocess.Popen(args,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.proc.poll() is not None:
                self.fail('Restarted test server stopped unexpectedly')
            try:
                actor.call('/api/bootstrap')
                break
            except OSError:time.sleep(.05)
        status,result=actor.call(path+'/action',payload)
        self.assertEqual(status,200)
        self.assertTrue(result['replayed'])
        self.assertEqual([s['stack'] for s in result['state']['seats']],stacks)


if __name__=='__main__':unittest.main(verbosity=2)
