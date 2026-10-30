"""Quarantine recovery, permissions, stale review, atomic close-outs and replay."""
from copy import deepcopy
from datetime import datetime,timezone
import json,unittest
from unittest.mock import patch
import market,market_contracts,market_review,wallet,club_admin
from poker_engine import RuleError
from member_accounts import AccountError
from . import test_admin as admin_tests

class MarketHaltRules(unittest.TestCase):
 def setUp(self):
  admin_tests.AdminRules.setUp(self);self.t=datetime(2026,10,30,2,0,tzinfo=timezone.utc).timestamp();self.user={'id':2};self.admin={'id':1};self.seq=0
  self.q(100,self.t)
 def q(self,n,t):
  return market.apply_quotes(self.db,[dict(symbol='TW:2330',price=str(n),native=str(n),bid=str(n),ask=str(n),fx='1',asof=t,fx_at=t,source=market.TW_SOURCE)],t)
 def intent(self,action='resume'):
  c=market_review.view(self.db,self.admin,self.t+20)['cases'][0]
  return dict(symbol=c['symbol'],case_id=c['case_id'],quote_key=c['quote_key'],action=action,note='Synthetic reviewed source',operation_id='halt_review_once_00001')
 def resolve(self,d=None,t=None):return market_review.resolve(self.db,self.admin,d or self.intent(),t or self.t+20)
 def order(self,side='buy',amount=1000,t=None,**other):
  self.seq+=1;return market.mutate(self.db,self.user,'order',dict(symbol='TW:2330',side=side,amount=amount,operation_id=f'halt_fixture_order_{self.seq:05d}',**other),t or self.t+1)
 def halt(self,recover=101):
  self.q(160,self.t+10);self.q(recover,self.t+11)
 def test_admin_resumes_recovered_quote_once_and_preserves_spot(self):
  self.order();self.q(100,self.t+2);market.settle(self.db,self.t+2);self.halt()
  d=self.intent()
  with self.assertRaises(club_admin.AdminError):market_review.resolve(self.db,self.user,d,self.t+20)
  before=wallet.view(self.db,2,self.t+20)['total'];self.assertEqual(before,3000)
  result=self.resolve(d);self.assertTrue(result['ok'])
  self.assertEqual(wallet.view(self.db,2,self.t+20)['total'],3010)
  self.assertTrue(self.resolve(d)['replayed']);self.assertEqual(wallet.view(self.db,2,self.t+20)['total'],3010)
  self.assertEqual(self.db.execute('SELECT count(*) FROM market_halt_events').fetchone()[0],1)
  self.assertEqual(market_review.view(self.db,self.admin,self.t+20)['cases'],[])
 def test_candidate_can_advance_in_time_but_not_change_price_without_review(self):
  self.halt();d=self.intent();self.q(101,self.t+12);self.assertTrue(self.resolve(d)['ok'])
  self.q(160,self.t+21);self.q(101,self.t+22);d=self.intent();d['operation_id']='halt_second_review_001'
  self.q(102,self.t+23)
  with self.assertRaises(AccountError):self.resolve(d,self.t+24)
 def test_missing_expired_and_large_corporate_change_require_safe_handling(self):
  self.order();self.q(100,self.t+2);market.settle(self.db,self.t+2);self.halt(50);d=self.intent()
  with self.assertRaises(RuleError):self.resolve(d)
  with self.assertRaises(RuleError):self.resolve({**d,'action':'settle'},self.t+90)
  self.db.execute("INSERT INTO market_quote_health VALUES('TW:2330','missing_data')")
  with self.assertRaises(RuleError):self.resolve({**d,'action':'settle'})
  self.assertEqual(self.db.execute('SELECT halted FROM market_quotes WHERE symbol=?',('TW:2330',)).fetchone()[0],1)
 def seed_exposures(self):
  self.order(t=self.t+1);self.order('short',500,t=self.t+1)
  market_contracts.mutate(self.db,self.user,'open',dict(symbol='TW:2330',direction='long',leverage=5,margin=100,operation_id='halt_contract_open_0001'),self.t+1)
  self.q(100,self.t+2);market.settle(self.db,self.t+2)
  self.order(amount=100,t=self.t+3)
  market_contracts.mutate(self.db,self.user,'open',dict(symbol='TW:2330',direction='short',leverage=2,margin=50,order_kind='limit',limit_price='120',operation_id='halt_contract_limit_001'),self.t+3)
  self.halt(50)
 def test_company_action_closes_trusted_marks_and_refunds_all_pending_once(self):
  self.seed_exposures();before=wallet.view(self.db,2,self.t+20)['total'];d=self.intent('settle')
  result=self.resolve(d);self.assertEqual(result['exposure'],dict(spot=1,shorts=1,contracts=1,orders=2))
  self.assertEqual(wallet.view(self.db,2,self.t+20)['balance'],before)
  self.assertEqual(wallet.view(self.db,2,self.t+20)['investments'],0)
  self.assertEqual(market_review.exposure(self.db,'TW:2330'),dict(spot=0,shorts=0,contracts=0,orders=0))
  cash=wallet.view(self.db,2,self.t+20)['balance'];ledger=self.db.execute('SELECT count(*) FROM wallet_ledger').fetchone()[0]
  self.assertTrue(self.resolve(d)['replayed']);self.assertEqual(wallet.view(self.db,2,self.t+20)['balance'],cash)
  self.assertEqual(self.db.execute('SELECT count(*) FROM wallet_ledger').fetchone()[0],ledger)
  quote=self.db.execute(market.QUOTE_SQL+" WHERE q.symbol='TW:2330'").fetchone();self.assertTrue(market.quote_ready(quote,self.t+20));self.assertEqual(quote['native'],'50')
  with self.assertRaises(AccountError):self.resolve({**d,'note':'Changed intent'})
 def test_failed_closeout_rolls_back_every_refund_position_and_audit(self):
  self.seed_exposures();d=self.intent('settle')
  tables=('wallets','wallet_ledger','market_positions','market_orders','market_contract_orders','market_contracts','market_shorts','market_halts','market_halt_events','market_quotes')
  snap=lambda:{t:[tuple(r) for r in self.db.execute('SELECT * FROM '+t)] for t in tables}
  before=snap();real=wallet.transfer;calls=0
  def fail(*args,**kwargs):
   nonlocal calls
   calls+=1
   if calls==2:raise RuntimeError('Synthetic write failure')
   return real(*args,**kwargs)
  with patch.object(wallet,'transfer',side_effect=fail),self.assertRaises(RuntimeError):self.resolve(d)
  self.assertEqual(snap(),before)
 def test_quarantine_never_regresses_to_an_older_candidate(self):
  self.halt();d=self.intent();self.q(99,self.t+9)
  self.assertEqual(self.intent()['quote_key'],d['quote_key'])
 def test_original_halt_without_a_case_is_recoverable_after_next_observation(self):
  self.db.execute("UPDATE market_quotes SET halted=1 WHERE symbol='TW:2330'")
  self.assertFalse(market_review.view(self.db,self.admin,self.t)['cases'][0]['ready'])
  self.q(101,self.t+1);self.assertTrue(self.resolve()['ok'])

if __name__=='__main__':unittest.main()
