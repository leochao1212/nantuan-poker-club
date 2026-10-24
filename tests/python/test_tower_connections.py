"""Four-choice payouts, legacy hands, and replaceable SSE subscriptions."""
import itertools
import json
import threading
import time
import unittest
from fractions import Fraction
from contextlib import ExitStack,closing
from unittest.mock import patch
import bonus_engine as b
from .test_bonus import room,points
from realtime import Hub
from .test_app import ServerTestCase
from .test_realtime import Stream

class FourChoiceTower(unittest.TestCase):
    def test_four_options_and_independent_return_table(self):
        with patch.object(b.secrets,'randbelow',return_value=3) as random:
            r=room('tower',100);b.start_hand(r,101)
        self.assertEqual([call.args for call in random.call_args_list],[(4,)]*6)
        view=b.public_view(r,1)
        self.assertEqual(view['hand']['tower_options'],4)
        self.assertNotIn('hazards',view['hand'])
        self.assertEqual(view['hand']['returns'],[129,172,229,306,408,545])
        for stake in (1,2,10,100,1000):
            for k in range(1,7):
                exact=Fraction(stake*97,100)/Fraction(3,4)**k
                self.assertEqual(b.risk_return('tower',stake,k),exact.numerator//exact.denominator)
    def test_fourth_option_can_win_or_lose_and_fifth_rejected(self):
        for bomb,expected in [(0,129),(3,0)]:
            r=room('tower',100);before=points(r);b.start_hand(r,101);r['hand']['hazards']=[bomb]*6
            with self.assertRaises(b.RuleError):b.act(r,1,'pick',102,{'cell':4})
            self.assertEqual(r['hand']['selected'],[])
            b.act(r,1,'pick',102,{'cell':3})
            if r['status']=='playing':b.act(r,1,'cashout',103)
            self.assertEqual(r['hand']['results'][0]['payout'],expected);self.assertEqual(points(r),before)
    def test_all_bomb_arrangements_and_auto_settlement(self):
        winners=0
        for bombs in itertools.product(range(4),repeat=6):
            r=room('tower',100);before=points(r);b.start_hand(r,101);r['hand']['hazards']=list(bombs)
            for k in range(6):
                if r['status']!='playing':break
                b.act(r,1,'pick',102+k,{'cell':0})
            self.assertEqual(points(r),before)
            self.assertEqual(r['status'],'waiting')
            payout=r['hand']['results'][0]['payout'];self.assertIn(payout,(0,545));winners+=payout>0
        self.assertEqual(winners,3**6)
        self.assertLessEqual(Fraction(winners*545,4**6*100),Fraction(97,100))
    def test_legacy_three_choice_saved_hand_keeps_payouts(self):
        r=room('tower',100);before=points(r);b.start_hand(r,101)
        r['hand'].pop('tower_options');r['hand']['hazards']=[2]*6
        r=json.loads(json.dumps(r));view=b.public_view(r,1)
        self.assertEqual(view['hand']['tower_options'],3)
        self.assertEqual(view['hand']['returns'][0],145)
        with self.assertRaises(b.RuleError):b.act(r,1,'pick',102,{'cell':3})
        b.act(r,1,'pick',102,{'cell':0});b.act(r,1,'cashout',103)
        self.assertEqual(r['hand']['results'][0]['payout'],145);self.assertEqual(points(r),before)
        b.start_hand(r,107);self.assertEqual(r['hand']['tower_options'],4)

class SubscriptionLeases(unittest.TestCase):
    def test_replacement_does_not_accumulate_or_remove_successor(self):
        hub=Hub();contexts=[];latest=None
        try:
            for _ in range(40):
                context=hub.subscribe(1,'page');lease=context.__enter__();contexts.append(context)
                if latest:self.assertTrue(latest.is_set())
                latest=lease;self.assertEqual(hub.clients,{1:1})
            for context in contexts[:-1]:context.__exit__(None,None,None)
            self.assertEqual(hub.clients,{1:1});self.assertFalse(latest.is_set())
            contexts=contexts[-1:]
        finally:
            for context in contexts:context.__exit__(None,None,None)
        self.assertEqual(hub.clients,{})
    def test_replacement_wakes_old_wait_immediately(self):
        hub=Hub()
        with hub.subscribe(1,'page') as lease:
            ready=threading.Event();done=threading.Event()
            def wait():
                ready.set();hub.wait(hub.version_for(),timeout=5,cancelled=lease);done.set()
            thread=threading.Thread(target=wait);thread.start();ready.wait(1)
            with hub.subscribe(1,'page'):self.assertTrue(done.wait(.5))
            thread.join(1)
    def test_limits_and_account_isolation_are_preserved(self):
        hub=Hub()
        with ExitStack() as stack:
            old=stack.enter_context(hub.subscribe(1,'same'))
            other=stack.enter_context(hub.subscribe(2,'same'))
            for n in range(4):stack.enter_context(hub.subscribe(1,str(n)))
            with self.assertRaises(ValueError):stack.enter_context(hub.subscribe(1,'sixth'))
            with hub.subscribe(1,'same'):
                self.assertTrue(old.is_set());self.assertFalse(other.is_set());self.assertEqual(hub.clients[1],5)
            self.assertEqual(hub.clients[1],4)
        with ExitStack() as stack:
            for uid in range(80):stack.enter_context(hub.subscribe(uid,'page'))
            with self.assertRaises(ValueError):stack.enter_context(hub.subscribe(100,'page'))
            with hub.subscribe(0,'page'):self.assertEqual(sum(hub.clients.values()),80)
        self.assertEqual(hub.clients,{})
    def test_legacy_subscribers_still_work(self):
        hub=Hub()
        with hub.subscribe(1) as first:
            with hub.subscribe(1) as second:
                self.assertFalse(first.is_set());self.assertFalse(second.is_set());self.assertEqual(hub.clients[1],2)
        self.assertFalse(hub.clients)

class ChannelSwitchAPI(ServerTestCase):
    def test_fast_switch_same_page_without_429_and_private_views(self):
        c=self.clients[0]
        c.call('/api/register',{'username':'channeltest','nickname':'Channel','password':'password123'})
        rid=c.call('/api/online/rooms',{'name':'Switch','game_type':'tower','stake':100})[1]['id']
        page='browser_page_000001';streams=[]
        try:
            for i in range(12):
                suffix=f'&room={rid}' if i%2 else ''
                s=Stream(c,f'/api/online/events?presence=client&client={page}'+suffix);streams.append(s)
                state=s.state()
                if i%2:self.assertEqual(state['id'],rid)
                else:self.assertIn('users',state)
            view=c.call(f'/api/online/rooms/{rid}')[1]
            result=c.call(f'/api/online/rooms/{rid}/start',{'revision':view['revision'],'operation_id':'four_choice_start_001'})
            self.assertEqual(result[0],200);state=streams[-1].state(result[1]['state']['revision'])
            self.assertEqual(state['hand']['tower_options'],4);self.assertNotIn('hazards',state['hand'])
            self.assertEqual(c.call('/api/online/events?client=bad')[0],400)
        finally:
            for stream in streams:stream.close()

if __name__=='__main__':unittest.main()
