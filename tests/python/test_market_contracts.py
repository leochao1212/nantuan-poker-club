"""Contract collateral, fees, native-FX P&L, isolated liquidation and safe receipts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from fractions import Fraction
import json
import sqlite3
import time
import unittest
from unittest.mock import patch
import market,market_contracts as contracts,market_catalog as catalog,market_charts as charts,market_data,wallet,member_accounts
from poker_engine import RuleError
from . import test_market as original
Client=original.Client
yahoo_fixture=original.yahoo_fixture


class ContractRules(unittest.TestCase):
    quote=original.MarketRules.quote
    def setUp(self):original.MarketRules.setUp(self)

    def order(self,clock=101,**fields):
        self.serial+=1
        return contracts.mutate(self.db,self.user,'open',dict(operation_id='contract_receipt_'+str(self.serial).zfill(18),symbol='CC:BTC',direction='long',leverage=10,margin=1000)|fields,clock)

    def positions(self,clock=103):return market.view(self.db,1,clock)['contracts']['positions']
    def cash(self,clock=103):return wallet.view(self.db,1,clock)
    def fill(self,direction='long',**fields):
        r=self.order(direction=direction,**fields);self.quote(100,102);market.settle(self.db,102);return r

    def test_reserve_includes_fee_but_is_not_loss_until_fill(self):
        data=dict(operation_id='same_contract_receipt_1234',symbol='CC:BTC',direction='long',leverage=10,margin=1000)
        first=contracts.mutate(self.db,self.user,'open',data,101)
        self.assertEqual(self.cash()['balance'],1995);self.assertEqual(self.cash()['total'],3000)
        self.assertFalse(market.settle(self.db,101));self.assertFalse(self.positions())
        self.assertTrue(contracts.mutate(self.db,self.user,'open',data,1000)['replayed'])
        self.assertEqual(self.cash()['balance'],1995)
        self.quote(100,102);self.assertTrue(market.settle(self.db,102));self.assertFalse(market.settle(self.db,103))
        p=self.positions()[0];self.assertEqual((p['units'],p['opening_fee'],p['value']),(str(100*market.SCALE),5,995))
        self.assertEqual(self.cash()['total'],2990)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE event_key=?",('contract:reserve:'+str(first['order_id']),)).fetchone()[0],1)

    def test_long_native_profit_close_fee_and_wealth_conservation(self):
        self.fill();self.quote(110,103);market.settle(self.db,103)
        p=self.positions()[0];self.assertEqual((p['unrealized_profit'],p['value'],p['profit']),(1000,1994,989))
        d=dict(position_id=p['id'],operation_id='contract_close_once_12345')
        contracts.mutate(self.db,self.user,'close',d,104)
        self.assertFalse(market.settle(self.db,104));self.quote(110,105);market.settle(self.db,105)
        self.assertEqual(self.cash()['balance'],3989);self.assertEqual(self.cash()['total'],3989)
        self.assertTrue(contracts.mutate(self.db,self.user,'close',d,2000)['replayed'])
        self.assertEqual(self.cash()['balance'],3989)
        row=self.db.execute("SELECT sum(amount),sum(game_delta),sum(flow_delta) FROM wealth_events WHERE kind='market_value'").fetchone()
        self.assertEqual(tuple(row),(989,0,0))

    def test_short_profit_and_hedged_directions_are_independent(self):
        self.fill('short');self.quote(90,103);market.settle(self.db,103)
        p=self.positions()[0];self.assertEqual((p['unrealized_profit'],p['value'],p['profit']),(1000,1995,990))
        self.order(clock=104,direction='long',margin=100,leverage=5);self.quote(90,105);market.settle(self.db,105)
        self.assertEqual({p['direction'] for p in self.positions(105)},{'long','short'})

    def test_liquidation_at_maintenance_plus_fee_not_equity_zero(self):
        self.fill();self.quote('90.42',103);market.settle(self.db,103);self.assertEqual(len(self.positions()),1)
        self.quote('90.41',104);market.settle(self.db,104);market.settle(self.db,105)
        self.assertFalse(self.positions());self.assertEqual(self.cash()['balance'],1995)
        h=market.view(self.db,1,105)['contracts']['history'][0]
        self.assertEqual((h['status'],h['returned'],h['profit']),('liquidated',0,-1005))
        self.assertEqual(self.cash()['total'],1995)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE event_key='contract:close:1'").fetchone()[0],1)

    def test_short_liquidation_gap_never_charges_other_wallet_points(self):
        self.fill('short');p=self.positions()[0]
        contracts.mutate(self.db,self.user,'close',dict(position_id=p['id'],operation_id='short_pending_close_1234'),103)
        self.quote(100000,104);market.settle(self.db,104);market.settle(self.db,105)
        self.assertEqual(self.cash()['balance'],1995)
        self.assertEqual(market.view(self.db,1,105)['contracts']['orders'][0]['status'],'cancelled')
        self.assertFalse(self.positions())

    def test_outage_stale_fx_and_recovery_do_not_execute_or_liquidate(self):
        self.fill('short');before=self.cash()['total']
        market_data.apply(self.db,[('CC',[],'unavailable',163)],103)
        self.assertFalse(market.settle(self.db,103));self.assertEqual(self.cash()['total'],before)
        self.assertTrue(self.positions()[0]['stale'])
        with self.assertRaises(RuleError):self.order(clock=104)
        self.quote(100,105);self.assertFalse(self.positions(105)[0]['stale'])
        self.quote(100,106,fx_at=-4*86400);self.assertTrue(self.positions(106)[0]['stale'])
        self.assertFalse(market.settle(self.db,106));self.assertEqual(len(self.positions(106)),1)

    def test_cancelling_or_expiring_returns_all_fee_reserve_once(self):
        r=self.order();d=dict(order_id=r['order_id'],operation_id='contract_cancel_once_1234')
        contracts.mutate(self.db,self.user,'cancel',d,102)
        self.assertTrue(contracts.mutate(self.db,self.user,'cancel',d,103)['replayed'])
        self.assertEqual(self.cash()['balance'],3000)
        self.order(clock=104);market.settle(self.db,225);market.settle(self.db,226)
        self.assertEqual(self.cash()['balance'],3000);self.assertFalse(self.positions())

    def test_currency_conversion_does_not_create_underlying_profit(self):
        self.quote(3200,100,native='100',fx='32');self.order();self.quote(3200,102,native='100',fx='32');market.settle(self.db,102)
        self.quote(3300,103,native='100',fx='33');market.settle(self.db,103)
        p=self.positions()[0];self.assertEqual(p['unrealized_profit'],0)
        self.assertEqual(p['notional'],10313)
        self.assertEqual(p['closing_fee'],6)
        self.assertEqual(p['value'],994)

    def test_tiers_aggregate_same_direction_and_cannot_be_bypassed_by_split_orders(self):
        wallet.transfer(self.db,1,100000,'test','test_funding',100)
        self.order(margin=6000,leverage=100)
        with self.assertRaises(RuleError):self.order(clock=101,margin=6000,leverage=100)
        self.quote(100,102);market.settle(self.db,102)
        with self.assertRaises(RuleError):self.order(clock=103,margin=15000,leverage=50)
        # Opposite-side hedge has its own isolated exposure.
        self.order(clock=103,direction='short',margin=6000,leverage=100)
        self.quote(100,104);market.settle(self.db,104)
        self.assertEqual(len(self.positions(104)),2)

    def test_invalid_requests_are_atomic_and_accounts_are_isolated(self):
        for fields in [dict(margin=True),dict(margin=9),dict(margin=1000001),dict(leverage=True),dict(leverage=125),dict(direction='x'),dict(symbol='US:FAKE')]:
            with self.subTest(fields=fields),self.assertRaises(RuleError):self.order(**fields)
        self.assertEqual(self.cash()['balance'],3000)
        self.fill();p=self.positions()[0]
        with self.assertRaises(RuleError):contracts.mutate(self.db,{'id':2},'close',dict(position_id=p['id'],operation_id='cannot_close_other_1234'),103)
        with self.assertRaises(RuleError):contracts.mutate(self.db,{'id':2},'cancel',dict(order_id=1,operation_id='cannot_cancel_other_1234'),103)

    def test_cross_endpoint_receipt_conflict_and_deployment_gate(self):
        d=dict(operation_id='shared_receipt_namespace_1234',symbol='CC:BTC',direction='long',leverage=5,margin=100)
        contracts.mutate(self.db,self.user,'open',d,101)
        with self.assertRaises(member_accounts.AccountError):market.mutate(self.db,self.user,'order',dict(operation_id=d['operation_id'],symbol='CC:BTC',side='buy',amount=100),102)
        self.db.execute("INSERT INTO settings VALUES('deploy_pause_until','2000')")
        self.assertTrue(contracts.mutate(self.db,self.user,'open',d,103)['replayed'])
        with self.assertRaises(member_accounts.AccountError):self.order(clock=103)

    def test_blocked_pending_order_refunds_without_filling(self):
        self.order();self.db.execute("INSERT INTO account_states VALUES(1,'blocked',1,'test',102)")
        self.quote(100,103);market.settle(self.db,103);market.settle(self.db,104)
        self.assertFalse(self.positions());self.assertEqual(self.cash()['balance'],3000)


class CandleRules(unittest.TestCase):
    quote=original.MarketRules.quote
    def setUp(self):original.MarketRules.setUp(self);self.at=1793199600

    def test_real_ohlc_native_currency_and_interval_aggregation(self):
        rows=[charts.bar('US:AAPL',self.at-300+n*60,'100','102','99',str(100+n/10),'1000',self.at,'test OHLC') for n in range(5)]
        charts.apply(self.db,rows,self.at)
        v=market.chart(self.db,'US:AAPL','15m',self.at,'5m')
        self.assertEqual(v['currency'],'USD');self.assertEqual(len(v['candles']),1)
        b=v['candles'][0];self.assertEqual((b['open'],b['high'],b['low'],b['close'],b['volume']),('100','102','99','100.4','5000'))
        self.assertTrue(b['complete'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM market_quotes WHERE symbol='US:AAPL'").fetchone()[0],0)
        self.assertFalse(market.settle(self.db,self.at))

    def test_bad_ohlc_future_duplicates_and_incomplete_updates(self):
        for args in [('100','99','98','101'),('100','102','101','100'),('0','102','99','100'),('NaN','102','99','100')]:
            self.assertIsNone(charts.bar('US:AAPL',self.at-60,*args,None,self.at,'test'))
        self.assertIsNone(charts.bar('US:AAPL',self.at+60,'100','102','99','101',1,self.at,'test'))
        b=charts.bar('US:AAPL',self.at,'100','102','99','101',1,self.at+20,'test');self.assertFalse(b[7]);charts.apply(self.db,[b],self.at+20)
        revised=charts.bar('US:AAPL',self.at,'100','104','99','103',2,self.at+60,'test');charts.apply(self.db,[revised],self.at+60)
        self.assertEqual(self.db.execute('SELECT close,complete FROM market_candles').fetchone()[0],'103')
        revised=list(revised);revised[5]='999';charts.apply(self.db,[tuple(revised)],self.at+120)
        self.assertEqual(self.db.execute('SELECT close FROM market_candles').fetchone()[0],'103','completed source bars are immutable')

    def test_yahoo_raw_ohlc_and_legacy_line_never_fakes_candles(self):
        data=yahoo_fixture(self.at);r=data['chart']['result'][0];r['indicators']['quote'][0].update(open=[98,99,100,101],high=[99,100,101,102],low=[97,98,99,100],volume=[1,2,3,4])
        parsed=charts.yahoo(data,'US:AAPL',self.at);self.assertEqual(len(parsed),4)
        self.assertFalse(parsed[-1][7])
        with self.assertRaises(ValueError):charts.yahoo(data,'US:MSFT',self.at)
        self.db.execute("INSERT INTO market_prices VALUES('US:AAPL',?,'3200')",(self.at,))
        v=market.chart(self.db,'US:AAPL','15m',self.at)
        self.assertFalse(v['candles']);self.assertFalse(v['display_points'])


class InstrumentRules(unittest.TestCase):
    quote=original.MarketRules.quote
    def setUp(self):original.MarketRules.setUp(self)

    def test_verified_search_activation_unknown_and_owner_watches(self):
        item=dict(symbol='US:TSLA',name='Tesla',market='US',currency='USD',exchange='NMS',feed='TSLA',kind='EQUITY')
        with catalog._LOCK:catalog._INDEX['TEST']={'US:TSLA':item}
        self.addCleanup(lambda:catalog._INDEX.pop('TEST',None))
        with self.assertRaises(RuleError):catalog.watch(self.db,1,'US:GUESS',100)
        catalog.watch(self.db,1,'US:TSLA',100)
        self.assertIsNotNone(catalog.get(self.db,'US:TSLA'))
        self.assertIn('US:TSLA',[i['symbol'] for i in catalog.visible(self.db,1,market.CATALOG)])
        self.assertNotIn('US:TSLA',[i['symbol'] for i in catalog.visible(self.db,2,market.CATALOG)])
        self.assertIn('US:TSLA',catalog.active(self.db,101,market.CATALOG))
        self.assertNotIn('US:TSLA',catalog.active(self.db,221,market.CATALOG))

    def test_us_exchange_and_instrument_filtering(self):
        payload={'quotes':[dict(symbol='TSLA',shortname='Tesla',exchange='NMS',quoteType='EQUITY'),dict(symbol='SPY',shortname='SPY',exchange='PCX',quoteType='ETF'),dict(symbol='2330.TW',shortname='Other',exchange='TAI',quoteType='EQUITY'),dict(symbol='BAD<script>',shortname='x',exchange='NMS',quoteType='EQUITY'),dict(symbol='FX',shortname='x',exchange='NMS',quoteType='CURRENCY')]}
        with patch('market_catalog._fetch',return_value=payload):rows=catalog._lookup('US','test')
        self.assertEqual([r['symbol'] for r in rows],['US:TSLA','US:SPY'])

    def test_tw_index_covers_listed_otc_and_filters_warrants(self):
        with catalog._LOCK:catalog._INDEX.pop('TW',None);catalog._INDEX_AT.pop('TW',None)
        self.addCleanup(lambda:catalog._INDEX.pop('TW',None));self.addCleanup(lambda:catalog._INDEX_AT.pop('TW',None))
        with patch('market_catalog._fetch',side_effect=[[dict(Code='2330',Name='台積電'),dict(Code='006208',Name='富邦台50')],[dict(SecuritiesCompanyCode='6488',CompanyName='環球晶'),dict(SecuritiesCompanyCode='700001',CompanyName='權證')]]):
            rows=catalog.index('TW')
        self.assertEqual(set(rows),{'TW:2330','TW:006208','TW:6488'})
        self.assertEqual(rows['TW:6488']['exchange'],'otc')
        self.assertEqual(catalog._lookup('TW','環球')[0]['symbol'],'TW:6488')


class ContractHTTP(original.ServerTestCase):
    def test_concurrent_contract_receipts_authentication_and_chart_data(self):
        a=Client(self.base);self.assertEqual(a.call('/api/market/search?market=US&q=TSLA')[0],401)
        self.assertEqual(a.call('/api/register',dict(username='contracts_http',nickname='合約測試',password='SyntheticMarket123'))[0],200)
        def tick(price):
            with closing(sqlite3.connect(self.db_path,timeout=10)) as db:
                db.row_factory=sqlite3.Row;t=time.time();market.apply_quotes(db,[dict(symbol='CC:BTC',price=str(price),bid=str(price),ask=str(price),native=str(price),fx='1',fx_at=t,asof=t,source='test')],t);market.settle(db,t);db.commit()
        tick(100)
        data=dict(symbol='CC:BTC',direction='long',leverage=10,margin=1000,operation_id='http_contract_duplicate_1234')
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:a.call('/api/market/contracts/open',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results);self.assertEqual(len({r[1]['order_id'] for r in results}),1)
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],1995)
        tick(100);p=a.call('/api/market')[1]['market']['contracts']['positions'][0]
        data=dict(position_id=p['id'],operation_id='http_contract_close_once_1234')
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:a.call('/api/market/contracts/close',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results)
        tick(110);value=a.call('/api/market?symbol=CC%3ABTC&period=15m&interval=5m')[1]
        self.assertEqual(value['wallet']['balance'],3989)
        self.assertEqual(value['market']['chart']['currency'],'USD')
        self.assertTrue(a.call('/api/market/contracts/close',data)[1]['replayed'])
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],3989)
