"""Delayed simulations use source observations, never fetch timestamps."""
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
import market,market_data,market_contracts,wallet
from . import test_market as original


def fixture(at,code='2330',group='TW',**fields):
    exchange='TWSE' if group=='TW' else 'NASDAQ'
    values={'name':code,'close':100,'currency':'TWD' if group=='TW' else 'USD',
        'exchange':exchange,'type':'stock','typespecs':[],
        'update_mode':'delayed_streaming_900','last-price-update-time':at,
        'current_session':'market','time|1':at-at%60-60,
        'open|1':99,'high|1':101,'low|1':98,'close|1':100,'volume|1':1000}
    values.update(fields)
    return {'s':exchange+':'+code,'d':[values[k] for k in market_data.TV_COLUMNS]}


class TradingViewRules(unittest.TestCase):
    quote=original.MarketRules.quote
    order=original.MarketRules.order

    def setUp(self):
        original.MarketRules.setUp(self)
        self.at=datetime(2026,10,28,2,tzinfo=timezone.utc).timestamp()

    def tick(self,clock=None,at=None,group='TW',**fields):
        clock=self.at if clock is None else clock
        at=clock-900 if at is None else at
        code='2330' if group=='TW' else 'AAPL'
        rows=market_data.tradingview_rows({'data':[fixture(at,code,group,**fields)]},group,clock,
            {'rate':'1','asof':clock},market.INSTRUMENTS)
        market_data.apply(self.db,[(group,rows,'partial',clock+30)],clock)
        return self.db.execute(market.QUOTE_SQL+' WHERE q.symbol=?',(group+':'+code,)).fetchone()

    def test_spot_waits_for_source_update_even_when_price_unchanged(self):
        self.tick()
        self.order(symbol='TW:2330',clock=self.at+1)
        self.assertEqual(wallet.view(self.db,1,self.at+1)['balance'],2000)
        self.tick(clock=self.at+30,at=self.at-900)
        self.assertFalse(market.settle(self.db,self.at+30))
        self.tick(clock=self.at+60,at=self.at-840)
        self.assertTrue(market.settle(self.db,self.at+60))
        order=self.db.execute('SELECT * FROM market_orders').fetchone()
        self.assertLess(order['fill_asof'],order['submitted_at'])
        self.assertEqual(order['status'],'filled')
        self.assertFalse(market.settle(self.db,self.at+61))
        self.assertEqual(wallet.view(self.db,1,self.at+61)['total'],3000)

    def test_old_pending_orders_do_not_change_execution_contract(self):
        self.tick();self.order(symbol='TW:2330',clock=self.at+1)
        self.db.execute('DELETE FROM market_order_quote_refs')
        self.tick(clock=self.at+60)
        self.assertFalse(market.settle(self.db,self.at+60))

    def test_short_and_cover_both_require_new_source_observations(self):
        self.tick();self.order(side='short',symbol='TW:2330',clock=self.at+1)
        self.tick(clock=self.at+60);market.settle(self.db,self.at+60)
        p=self.db.execute('SELECT * FROM market_shorts').fetchone()
        self.order(side='cover',symbol='TW:2330',position_id=p['id'],clock=self.at+61)
        self.tick(clock=self.at+80,at=self.at-840)
        self.assertFalse(market.settle(self.db,self.at+80))
        self.tick(clock=self.at+120);market.settle(self.db,self.at+120)
        self.assertEqual(self.db.execute('SELECT status FROM market_shorts').fetchone()[0],'closed')
        self.assertEqual(wallet.view(self.db,1,self.at+120)['balance'],3000)

    def test_contract_open_and_close_use_same_rule(self):
        self.tick(group='US')
        market_contracts.mutate(self.db,self.user,'open',dict(operation_id='tv_contract_open_123456',
            symbol='US:AAPL',direction='long',leverage=2,margin=1000),self.at+1)
        self.tick(clock=self.at+30,at=self.at-900,group='US')
        self.assertFalse(market.settle(self.db,self.at+30))
        self.tick(clock=self.at+60,group='US');market.settle(self.db,self.at+60)
        p=self.db.execute('SELECT * FROM market_contracts').fetchone()
        self.assertIsNotNone(p)
        market_contracts.mutate(self.db,self.user,'close',dict(operation_id='tv_contract_close_12345',position_id=p['id']),self.at+61)
        self.assertFalse(market.settle(self.db,self.at+62))
        self.tick(clock=self.at+120,group='US');market.settle(self.db,self.at+120)
        self.assertEqual(self.db.execute('SELECT status FROM market_contracts').fetchone()[0],'closed')

    def test_unavailable_closed_stale_and_unknown_modes_fail_closed(self):
        self.assertTrue(market.quote_ready(self.tick(),self.at))
        self.assertFalse(market.quote_ready(self.tick(at=self.at-1021),self.at))
        self.assertFalse(market.quote_ready(self.tick(current_session='out_of_session'),self.at))
        self.assertFalse(market.quote_ready(self.tick(update_mode='unknown'),self.at))
        self.tick();q=self.tick(clock=self.at+1,close=None)
        self.assertFalse(market.quote_ready(q,self.at+1))

    def test_cancel_replay_refunds_once_and_migration_preserves_ledger(self):
        self.tick();result=self.order(symbol='TW:2330',clock=self.at+1)
        data=dict(operation_id='tv_cancel_operation_123',order_id=result['order_id'])
        market.mutate(self.db,self.user,'cancel',data,self.at+2)
        market.mutate(self.db,self.user,'cancel',data,self.at+3)
        before=[tuple(r) for r in self.db.execute('SELECT * FROM wallet_ledger')]
        market.initialize(self.db)
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM wallet_ledger')])
        self.assertEqual(wallet.view(self.db,1,self.at+3)['balance'],3000)

    def test_batch_validation_partial_and_no_key(self):
        data={'data':[fixture(self.at-900),fixture(self.at-900,'2317')]}
        with patch('market_data.fetch_json',return_value=data) as fetch:
            rows,status,next_at,_=market_data.read_provider('TW',self.at,None)
        self.assertEqual((len(rows),status,next_at),(2,'partial',self.at+60))
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.args[0],'https://scanner.tradingview.com/taiwan/scan')
        self.assertIn('TWSE:2330',fetch.call_args.kwargs['payload']['symbols']['tickers'])
        self.assertEqual(rows[0]['asof'],self.at-900)
        for fields in ({'currency':'USD'},{'close':float('nan')},{'last-price-update-time':True},
                       {'last-price-update-time':self.at+10},{'exchange':'OTHER'},{'type':'index'}):
            with self.subTest(fields=fields):
                self.assertEqual(market_data.tradingview_rows({'data':[fixture(self.at-900,**fields)]},'TW',self.at,None,market.INSTRUMENTS),[])
        self.assertEqual(market_data.tradingview_rows({'data':[data['data'][0]]*2},'TW',self.at,None,market.INSTRUMENTS),[])
        with patch('market_data.fetch_json',side_effect=TimeoutError):
            self.assertEqual(market_data.read_provider('US',self.at,{'rate':'32','asof':self.at})[1:3],('unavailable',self.at+60))

    def test_public_quote_does_not_invent_bid_ask(self):
        self.tick()
        item=next(i for i in market.view(self.db,1,self.at)['instruments'] if i['symbol']=='TW:2330')
        self.assertTrue(item['available']);self.assertGreater(item['valid_until'],self.at)
        self.assertIsNone(item['quote']['bid']);self.assertIsNone(item['quote']['ask'])
        self.assertEqual(item['quote']['delay_seconds'],900)

    def test_limit_then_take_profit_require_new_observations(self):
        self.tick(group='US')
        market_contracts.mutate(self.db,self.user,'open',dict(operation_id='tv_limit_open_12345678',
            symbol='US:AAPL',direction='long',leverage=2,margin=1000,
            order_kind='limit',limit_price='99',take_profit='105'),self.at+1)
        self.tick(clock=self.at+60,group='US');market.settle(self.db,self.at+60)
        self.assertEqual(self.db.execute('SELECT count(*) FROM market_contracts').fetchone()[0],0)
        self.tick(clock=self.at+120,group='US',close=99);market.settle(self.db,self.at+120)
        self.assertEqual(self.db.execute('SELECT status FROM market_contracts').fetchone()[0],'open')
        self.tick(clock=self.at+180,group='US',close=105);market.settle(self.db,self.at+180)
        self.assertEqual(self.db.execute('SELECT status FROM market_contracts').fetchone()[0],'closed')

    def test_delayed_chart_window_and_first_failure_backoff(self):
        self.tick()
        self.assertEqual(market.chart(self.db,'TW:2330','15m',self.at)['to_at'],self.at-900)
        self.db.execute("DELETE FROM market_quotes WHERE symbol LIKE 'TW:%'")
        self.db.execute("INSERT OR REPLACE INTO market_providers VALUES('TW',?,?,'unavailable')",(self.at+60,self.at))
        self.assertNotIn('TW',market_data.due(self.db,self.at+1))
        self.assertIn('TW',market_data.due(self.db,self.at+60))
