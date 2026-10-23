"""Shared-table updates must reach all participants without a polling delay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack,closing
import sqlite3,time,unittest
from test_app import ServerTestCase
from test_realtime import Stream
import online,arcade_engine as a

class AllGamePush(ServerTestCase):
    def test_multiplayer_push_for_every_game(self):
        first=self.clients[0]
        first.call('/api/register',{'username':'latency0','nickname':'P0','password':'password123'})
        code=first.call('/api/state')[1]['invite_code']
        for i in range(1,6):self.assertEqual(self.clients[i].call('/api/register',{'username':f'latency{i}','nickname':f'P{i}','password':'password123','invite_code':code})[0],200)
        for kind,count in (('holdem',6),('big2',4),('blackjack',6),('roulette',6),('baccarat',6),('slot',1),('mines',1),('tower',1),('dice',6)):
            rid=first.call('/api/online/rooms',{'name':'Latency '+kind,'game_type':kind})[1]['id'];path=f'/api/online/rooms/{rid}'
            for c in self.clients[1:count]:
                v=c.call(path)[1];self.assertEqual(c.call(path+'/join',{'revision':v['revision']})[0],200)
            if kind=='blackjack':
                for c in self.clients[1:count]:
                    status,state=c.call(path+'/start',{'revision':first.call(path)[1]['revision'],'stake':10,'expected_hand_number':1})
                    self.assertEqual(status,200);self.assertEqual(state['state']['hand_no'],0)
            with ExitStack() as stack:
                streams=[stack.enter_context(closing(Stream(c,f'/api/online/events?presence=client&room={rid}'))) for c in self.clients[:count]]
                v=streams[0].state()
                for s in streams[1:]:s.state()
                begin=time.perf_counter();status,result=first.call(path+'/start',{'revision':v['revision'],**({'bets':[{'key':'big','amount':10}]} if kind=='dice' else {'stake':10,'expected_hand_number':1} if kind=='blackjack' else {})})
                self.assertEqual(status,200);revision=result['state']['revision']
                with ThreadPoolExecutor(count) as pool:views=list(pool.map(lambda s:s.state(revision),streams))
                elapsed=time.perf_counter()-begin
                print(f'{kind}: start HTTP + push to {count} clients = {elapsed*1000:.1f} ms',flush=True)
                self.assertLess(elapsed,.8)
                self.assertTrue(all(v['revision']==revision for v in views))
                for v in views:self.assertNotIn('deck',v['hand'])
            # End synthetic rounds only, then refund seats before testing next type.
            with closing(sqlite3.connect(self.db_path)) as db:
                db.row_factory=sqlite3.Row;r=online.get_room(db,rid)
                for seat in r['seats']:seat['away']=True
                online.rules(r).tick(r,time.time()+31);online.save(db,r,time.time());db.commit()
            for c in self.clients[:count]:
                v=c.call(path)[1];self.assertEqual(c.call(path+'/leave',{'revision':v['revision']})[0],200)

if __name__=='__main__':unittest.main()
