"""Fixed-point paper orders, new-observation fills, conservation and private receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from decimal import Decimal
import json
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
import bank,market,market_data,online,wallet,member_accounts
from poker_engine import RuleError
from .test_app import ServerTestCase,Client


class MarketRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');self.addCleanup(self.db.close)
        self.db.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTONLY');
        INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');""")
        online.initialize(self.db)
        # Keep this transaction scenario at a fixed 3,000-point budget.
        from . import scenario_budget
        scenario_budget(self.db);self.user={'id':1};self.serial=0
        self.quote(100,100)

    def quote(self,price,clock,symbol='CC:BTC',**fields):
        r=dict(symbol=symbol,price=str(price),bid=str(price),ask=str(price),native=str(price),fx='1',fx_at=clock,asof=clock,source='test')|fields
        market.apply_quotes(self.db,[r],clock);return r

    def order(self,side='buy',clock=101,**fields):
        self.serial+=1
        return market.mutate(self.db,self.user,'order',dict(operation_id=f'market_test_order_{self.serial:016}',symbol='CC:BTC',side=side,amount=1000)|fields,clock)

    def test_reserve_is_not_loss_and_old_quote_never_fills(self):
        self.order();self.assertEqual(wallet.view(self.db,1,101)['balance'],2000)
        self.assertEqual(wallet.view(self.db,1,101)['total'],3000)
        self.assertFalse(market.settle(self.db,102));self.assertFalse(market.view(self.db,1,102)['positions'])
        self.quote(100,103);self.assertTrue(market.settle(self.db,103))
        v=market.view(self.db,1,103);self.assertEqual(v['positions'][0]['quantity'],'10')
        self.assertEqual(wallet.view(self.db,1,103)['total'],3000)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wealth_events WHERE kind LIKE 'market_%'").fetchone()[0],0)

    def test_actual_next_price_and_sell_existing_units(self):
        self.order();self.quote(200,102);market.settle(self.db,102)
        self.assertEqual(market.view(self.db,1,102)['positions'][0]['quantity'],'5')
        self.order('sell',clock=103,quantity='2.5')
        with self.assertRaises(RuleError):self.order('sell',clock=104,quantity='3')
        self.quote(220,105);market.settle(self.db,105)
        self.assertEqual(wallet.view(self.db,1,105)['balance'],2550)
        self.assertEqual(wallet.view(self.db,1,105)['total'],3100)
        self.assertEqual(market.view(self.db,1,105)['positions'][0]['cost'],500)
        self.assertEqual(market.view(self.db,1,105)['orders'][0]['profit'],50)
        e=self.db.execute("SELECT sum(amount),sum(game_delta),sum(flow_delta),count(*) FROM wealth_events WHERE kind='market_value'").fetchone()
        self.assertEqual(tuple(e),(100,0,0,1),'price marks aggregate hourly without fake inflows or game wins')

    def test_identical_receipt_replays_before_stale_quote_and_conflict(self):
        d=dict(operation_id='market_same_receipt_123456',symbol='CC:BTC',side='buy',amount=1000)
        r=market.mutate(self.db,self.user,'order',d,101)
        self.assertTrue(market.mutate(self.db,self.user,'order',d,9999)['replayed'])
        self.assertEqual(wallet.view(self.db,1,101)['balance'],2000)
        with self.assertRaises(member_accounts.AccountError):market.mutate(self.db,self.user,'order',d|dict(amount=999),102)
        cancel=dict(operation_id='market_cancel_123456789',order_id=r['order_id'])
        market.mutate(self.db,self.user,'cancel',cancel,102)
        self.assertTrue(market.mutate(self.db,self.user,'cancel',cancel,103)['replayed'])
        self.assertEqual(wallet.view(self.db,1,103)['balance'],3000)
        self.assertFalse(market.settle(self.db,104))

    def test_expiry_refunds_once_and_stale_fx_blocks_orders(self):
        self.order();market.settle(self.db,222);market.settle(self.db,223)
        self.assertEqual(wallet.view(self.db,1,223)['balance'],3000)
        self.assertEqual(market.view(self.db,1,223)['orders'][0]['status'],'expired')
        with self.assertRaises(RuleError):self.order(clock=1000)
        self.quote(100,300000,fx_at=1)
        with self.assertRaises(RuleError):self.order(clock=300001)

    def test_integer_rounding_cannot_mint_points(self):
        self.quote('3.1415926535',100)
        for i in range(20):
            at=101+3*i;self.order(clock=at,amount=100)
            self.quote('3.1415926535',at+1);market.settle(self.db,at+1)
            quantity=market.view(self.db,1,at+1)['positions'][0]['quantity']
            self.order('sell',clock=at+1,quantity=quantity);self.quote('3.1415926535',at+2);market.settle(self.db,at+2)
        self.assertLessEqual(wallet.view(self.db,1,200)['balance'],3000)
        self.assertEqual(market.assets(self.db).get(1,0),0)

    def test_stock_retrieval_is_not_new_price_and_split_halts(self):
        at=datetime(2026,10,28,2,tzinfo=timezone.utc).timestamp()
        self.quote(100,at,'TW:2330',source=market.TW_SOURCE)
        self.order(clock=at+1,symbol='TW:2330')
        self.quote(100,at+10,'TW:2330',asof=at,source=market.TW_SOURCE)
        self.assertFalse(market.settle(self.db,at+10))
        self.quote(110,at+20,'TW:2330',source=market.TW_SOURCE);market.settle(self.db,at+20)
        self.assertEqual(market.view(self.db,1,at+20)['orders'][0]['status'],'filled')
        old=market.assets(self.db)[1]
        self.quote(55,at+25,'TW:2330',source=market.TW_SOURCE)
        q=dict(self.db.execute("SELECT * FROM market_quotes WHERE symbol='TW:2330'").fetchone())
        self.assertTrue(q['halted']);self.assertEqual(market.assets(self.db)[1],old)
        with self.assertRaises(RuleError):self.order(clock=at+26,symbol='TW:2330')

    def test_sell_reservation_released_on_cancel_and_blocked_user_refunded(self):
        self.order();self.quote(100,102);market.settle(self.db,102)
        r=self.order('sell',clock=103,quantity='10')
        self.assertEqual(market.view(self.db,1,103)['positions'][0]['available_quantity'],'0')
        market.mutate(self.db,self.user,'cancel',dict(operation_id='cancel_release_12345678',order_id=r['order_id']),104)
        self.assertEqual(market.view(self.db,1,104)['positions'][0]['available_quantity'],'10')
        self.order(clock=105)
        self.db.execute("INSERT INTO account_states VALUES(1,'blocked',1,'test',106)")
        self.quote(100,107);market.settle(self.db,107)
        self.assertEqual(market.view(self.db,1,107)['orders'][0]['status'],'cancelled')
        self.assertEqual(wallet.view(self.db,1,107)['balance'],2000)

    def test_input_validation(self):
        for fields in [dict(amount=True),dict(amount=0),dict(amount=1000001),dict(symbol=[]),dict(symbol='fake')]:
            with self.assertRaises(RuleError):self.order(**fields)
        for raw in ['0','NaN','Infinity','1e2','1.000000001','-1']:
            with self.assertRaises(RuleError):self.order('sell',quantity=raw)
        self.assertEqual(wallet.view(self.db,1,101)['balance'],3000)

    def test_regressing_future_and_empty_quotes_do_not_replace_mark(self):
        self.quote(90,99);self.quote(80,101,asof=200)
        q=self.db.execute("SELECT price FROM market_quotes WHERE symbol='CC:BTC'").fetchone()[0]
        self.assertEqual(q,'100')

    def test_short_margin_profit_cover_and_wealth_conservation(self):
        self.order('short',clock=101,amount=1000)
        self.assertEqual(wallet.view(self.db,1,101)['balance'],2000)
        self.assertEqual(wallet.view(self.db,1,101)['total'],3000)
        self.quote(100,102);market.settle(self.db,102)
        short=market.view(self.db,1,102)['shorts'][0]
        self.assertEqual(short['quantity'],'10');self.assertEqual(short['margin'],1000)
        self.assertEqual(Decimal(short['liquidation_price']),200)
        self.assertEqual(wallet.view(self.db,1,102)['total'],3000)
        self.quote(80,103);market.settle(self.db,103)
        self.assertEqual(market.view(self.db,1,103)['shorts'][0]['profit'],200)
        self.assertEqual(wallet.view(self.db,1,103)['balance'],2000,'short proceeds never enter the wallet')
        self.assertEqual(wallet.view(self.db,1,103)['total'],3200)
        request=dict(symbol='CC:BTC',side='cover',position_id=short['id'],operation_id='short_cover_receipt_123456')
        market.mutate(self.db,self.user,'order',request,104)
        with self.assertRaises(RuleError):self.order('cover',clock=104,position_id=short['id'])
        self.quote(80,105);market.settle(self.db,105)
        self.assertFalse(market.view(self.db,1,105)['shorts'])
        self.assertEqual(wallet.view(self.db,1,105)['balance'],3200)
        self.assertTrue(market.mutate(self.db,self.user,'order',request,999)['replayed'])
        self.assertEqual(wallet.view(self.db,1,105)['balance'],3200)
        row=self.db.execute("SELECT sum(amount),sum(game_delta),sum(flow_delta) FROM wealth_events WHERE kind='market_value'").fetchone()
        self.assertEqual(tuple(row),(200,0,0))

    def test_short_gap_liquidation_caps_loss_and_cancels_cover(self):
        self.order('short',clock=101,amount=1000);self.quote(100,102);market.settle(self.db,102)
        short=market.view(self.db,1,102)['shorts'][0]
        self.order('cover',clock=103,position_id=short['id'])
        self.quote(500,104);market.settle(self.db,104);market.settle(self.db,105)
        v=market.view(self.db,1,105)
        self.assertEqual(v['shorts'],[]);self.assertEqual(v['short_history'][0]['status'],'liquidated')
        self.assertEqual(v['short_history'][0]['profit'],-1000)
        self.assertEqual(v['short_history'][0]['returned'],0)
        self.assertEqual(v['orders'][0]['status'],'cancelled')
        self.assertEqual(wallet.view(self.db,1,105)['balance'],2000)
        self.assertEqual(wallet.view(self.db,1,105)['total'],2000)
        e=self.db.execute("SELECT sum(amount) FROM wealth_events WHERE kind='market_value'").fetchone()[0]
        self.assertEqual(e,-1000)
        with self.assertRaises(RuleError):self.order('cover',clock=105,position_id=short['id'])

    def test_short_cancel_expiry_spread_and_sell_are_distinct(self):
        request=self.order('short',clock=101,amount=1000)
        market.mutate(self.db,self.user,'cancel',dict(order_id=request['order_id'],operation_id='short_cancel_receipt_1234'),102)
        self.assertEqual(wallet.view(self.db,1,102)['balance'],3000)
        self.order('short',clock=103,amount=1000);market.settle(self.db,224)
        self.assertEqual(wallet.view(self.db,1,224)['balance'],3000)
        self.quote(100,225,bid='99',ask='101');self.order('short',clock=226,amount=1000)
        self.quote(100,227,bid='99',ask='101');market.settle(self.db,227)
        p=market.view(self.db,1,227)['shorts'][0]
        self.assertLess(p['profit'],0);self.assertGreaterEqual(p['profit'],-p['margin'])
        with self.assertRaises(RuleError):self.order('sell',clock=228,quantity='1')
        self.order('cover',clock=228,position_id=p['id'])
        market.settle(self.db,349)
        self.assertEqual(market.view(self.db,1,349)['shorts'][0]['id'],p['id'],'expired cover does not release the open margin')

    def test_short_account_isolation_and_position_limit(self):
        for n in range(20):
            at=101+n*3;self.order('short',clock=at,amount=10);self.quote(100,at+1);market.settle(self.db,at+1)
        self.assertEqual(len(market.view(self.db,1,161)['shorts']),20)
        with self.assertRaises(RuleError):self.order('short',clock=162,amount=10)
        pid=market.view(self.db,1,162)['shorts'][0]['id']
        with self.assertRaises(RuleError):market.mutate(self.db,{'id':2},'order',dict(symbol='CC:BTC',side='cover',position_id=pid,operation_id='other_cover_not_owner_1234'),162)
        self.assertFalse(market.view(self.db,2,162)['shorts'])

    def test_chart_real_time_coordinates_bounded_points_and_no_future(self):
        self.db.execute('DELETE FROM market_prices')
        rows=[('CC:BTC',n*3,str(100+n/100)) for n in range(1200)]
        self.db.executemany('INSERT INTO market_prices VALUES(?,?,?)',rows)
        self.db.execute("INSERT INTO market_prices VALUES('CC:BTC',9999,'123')")
        value=market.chart(self.db,'CC:BTC','1h',3600)
        actual={(at,price) for _,at,price in rows}
        self.assertLessEqual(len(value['points']),241)
        self.assertTrue(all((p['at'],p['price']) in actual for p in value['points']))
        self.assertTrue(all(p['at']<=3600 for p in value['points']))
        self.assertEqual(value['from_at'],0);self.assertEqual(value['to_at'],3600)
        self.assertEqual(value['points'],sorted(value['points'],key=lambda p:p['at']))
        for code,period in [('unknown','1h'),('CC:BTC','bad')]:
            with self.assertRaises(RuleError):market.chart(self.db,code,period,3600)
        self.assertEqual(market.view(self.db,1,3600,'CC:BTC','1h')['chart']['points'],value['points'])


    def test_high_precision_quotes_use_exact_integer_ratio_not_decimal_context(self):
        high='100.000000000000000000000000000001'
        low='99.999999999999999999999999999999'
        self.assertEqual(market.units_for_budget(1000,high),999999999)
        self.assertEqual(market.value_points(1000000000,high,up=True),1001)
        self.assertEqual(market.value_points(1000000000,low),999)
        self.quote(high,100);self.order(clock=101,amount=1000);self.quote(high,102);market.settle(self.db,102)
        p=market.view(self.db,1,102)['positions'][0]
        self.assertEqual(p['units'],999999999);self.assertEqual(p['cost'],1000)
        self.assertEqual(wallet.view(self.db,1,102)['balance'],2000,'cannot take a point beyond the reserved budget')

    def test_deployment_gate_blocks_new_margin_but_allows_known_receipts(self):
        request=dict(symbol='CC:BTC',side='short',amount=1000,operation_id='deploy_margin_receipt_1234')
        first=market.mutate(self.db,self.user,'order',request,101)
        self.db.execute("INSERT INTO settings VALUES('deploy_pause_until','1000')")
        self.assertTrue(market.mutate(self.db,self.user,'order',request,102)['replayed'])
        before=wallet.view(self.db,1,102)['balance']
        with self.assertRaises(member_accounts.AccountError) as e:self.order('short',clock=103,amount=1000)
        self.assertEqual(e.exception.status,503);self.assertEqual(wallet.view(self.db,1,103)['balance'],before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM market_orders').fetchone()[0],1)
        self.db.execute("DELETE FROM settings WHERE key='deploy_pause_until'")
        self.order('short',clock=104,amount=1000)
        self.assertEqual(wallet.view(self.db,1,104)['balance'],1000)


class Providers(unittest.TestCase):
    def test_official_formats_and_currency_conversion(self):
        at=datetime(2026,10,27,7,tzinfo=timezone.utc).timestamp()
        payload={'error':[],'result':{k:dict(a=['101'],b=['99'],c=['100']) for k in ['XXBTZUSD','XETHZUSD','SOLUSD']}}
        with patch('market_data.fetch_json',return_value=payload):
            rows,_,_,_=market_data.read_provider('CC',at,dict(rate='32',asof=at))
        self.assertEqual(rows[0]['ask'],'3232');self.assertEqual(rows[0]['bid'],'3168')

    def test_missing_fx_and_upstream_failure_stop_and_back_off_without_errors(self):
        with patch('market_data.fetch_json') as fetch:
            result=market_data.refresh(['US','CC'],100,None);fetch.assert_not_called()
            self.assertEqual([r[2] for r in result],['fx_unavailable','fx_unavailable'])
        with patch('market_data.fetch_json',side_effect=ValueError('SECRET')):
            result=market_data.refresh(['US'],100,dict(rate='32',asof=100))
        self.assertNotIn('SECRET',str(result));self.assertEqual(result[0][3],160)


def mis_fixture(clock,code='2330',**fields):
    local=datetime.fromtimestamp(clock,market.TAIPEI)
    return dict(c=code,ex='tse',d=local.strftime('%Y%m%d'),t=local.strftime('%H:%M:%S'),tlong=str(int(clock)*1000),z='100',b='99_98_97_',a='101_102_103_',g='10_20_30_',f='10_20_30_')|fields


class MISProviders(unittest.TestCase):
    def setUp(self):self.at=datetime(2026,10,28,2,tzinfo=timezone.utc).timestamp()

    def test_legacy_parser_preserves_original_source_time(self):
        payload=dict(rtcode='0000',msgArray=[mis_fixture(self.at-10),mis_fixture(self.at-5,'2317')])
        rows=market_data.mis_rows(payload,self.at)
        self.assertEqual(rows[0]['asof'],self.at-10)
        self.assertEqual(rows[0]['source'],market.TW_SOURCE)

    def test_missing_invalid_crossed_stale_future_or_ambiguous_rows_rejected(self):
        variants=[dict(z=None),dict(z='0'),dict(z='NaN'),dict(z='Infinity'),dict(b='-'),dict(a='-'),dict(g='0'),dict(f='-'),dict(b='102_',a='101_'),dict(t=''),dict(tlong=''),dict(tlong=str(int(self.at-5)*1000)),dict(ex='otc'),dict(d='20261399'),dict(z=100),dict(b=None)]
        for fields in variants:
            with self.subTest(fields=fields):self.assertEqual(market_data.mis_rows(dict(rtcode='0000',msgArray=[mis_fixture(self.at,**fields)]),self.at),[])
        for clock in (self.at-31,self.at+6,self.at-86400):
            self.assertEqual(market_data.mis_rows(dict(rtcode='0000',msgArray=[mis_fixture(clock)]),self.at),[])
        row=mis_fixture(self.at)
        self.assertEqual(market_data.mis_rows(dict(rtcode='0000',msgArray=[row,row]),self.at),[])
        self.assertEqual(market_data.mis_rows(dict(rtcode='0000',msgArray=[row,None,{},mis_fixture(self.at,'9999')]),self.at)[0]['symbol'],'TW:2330')
        for data in ([],{},dict(rtcode='5000',msgArray=[]),dict(rtcode='0000',msgArray={})):
            with self.assertRaises(ValueError):market_data.mis_rows(data,self.at)

    def test_missing_last_trade_can_use_explicit_fresh_bbo_reference_not_fake_trade(self):
        rows=market_data.mis_rows(dict(rtcode='0000',msgArray=[mis_fixture(self.at,z='-',b='99_',a='101_')]),self.at)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],'100');self.assertEqual(rows[0]['source'],market.TW_MID_SOURCE)
        self.assertEqual((rows[0]['bid'],rows[0]['ask']),('99','101'))
        self.assertFalse(market_data.mis_rows(dict(rtcode='0000',msgArray=[mis_fixture(self.at-31,z='-')]),self.at))

    def test_stock_failure_retries_bounded(self):
        with patch('market_data.fetch_json',side_effect=TimeoutError):
            result=market_data.refresh(['TW'],self.at,None)
        self.assertEqual(result,[('TW',[],'unavailable',self.at+60)])


class MISRules(unittest.TestCase):
    quote=MarketRules.quote
    order=MarketRules.order

    def setUp(self):
        MarketRules.setUp(self)
        self.at=datetime(2026,10,28,2,tzinfo=timezone.utc).timestamp()

    def tick(self,clock,rows=None,status='partial'):
        payload=dict(rtcode='0000',msgArray=rows if rows is not None else [mis_fixture(clock)])
        observations=market_data.mis_rows(payload,clock)
        market_data.apply(self.db,[('TW',observations,status,clock+5)],clock)

    def test_old_eod_never_trades_and_upgrade_does_not_wait_hourly_schedule(self):
        self.quote(100,self.at,'TW:2330',source='TWSE 開放資料')
        self.db.execute('INSERT INTO market_providers VALUES(?,?,?,?)',('TW',self.at+3600,self.at,'ok'))
        self.assertIn('TW',market_data.due(self.db,self.at))
        with self.assertRaises(RuleError):self.order(clock=self.at+1,symbol='TW:2330')
        self.tick(self.at+2);self.order(clock=self.at+3,symbol='TW:2330')
        self.assertNotIn('TW',market_data.due(self.db,self.at+3))
        self.assertIn('TW',market_data.due(self.db,self.at+7))

    def test_partial_quote_immediately_blocks_only_missing_symbol_and_resumes(self):
        self.tick(self.at,[mis_fixture(self.at),mis_fixture(self.at,'2317')])
        self.order(clock=self.at+1,symbol='TW:2330')
        self.tick(self.at+2,[mis_fixture(self.at+2,z='-',a='-'),mis_fixture(self.at+2,'2317')])
        self.assertFalse(market.settle(self.db,self.at+2))
        instruments={r['symbol']:r for r in market.view(self.db,1,self.at+2)['instruments']}
        self.assertFalse(instruments['TW:2330']['available']);self.assertTrue(instruments['TW:2317']['available'])
        with self.assertRaises(RuleError):self.order(clock=self.at+2,symbol='TW:2330')
        self.assertEqual(wallet.view(self.db,1,self.at+2)['balance'],2000)
        self.tick(self.at+5);self.assertTrue(market.settle(self.db,self.at+5));self.assertFalse(market.settle(self.db,self.at+6))
        self.assertEqual(len(market.view(self.db,1,self.at+6)['positions']),1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='market_reserve'").fetchone()[0],1)

    def test_failure_staleness_repeated_source_time_and_closed_session_never_fill(self):
        self.tick(self.at);self.order(clock=self.at+1,symbol='TW:2330')
        market_data.apply(self.db,[('TW',[],'unavailable',self.at+7)],self.at+2)
        self.assertFalse(market.settle(self.db,self.at+2))
        self.tick(self.at+5,[mis_fixture(self.at)])
        self.assertFalse(market.settle(self.db,self.at+5),'same source time is not new')
        with self.assertRaises(RuleError):self.order(clock=self.at+26,symbol='TW:2330')
        self.tick(self.at+31,[mis_fixture(self.at)])
        self.assertFalse(market.settle(self.db,self.at+31))
        self.tick(self.at+32);self.assertTrue(market.settle(self.db,self.at+32))
        self.assertFalse(market.quote_ready(self.db.execute("SELECT * FROM market_quotes WHERE symbol='TW:2330'").fetchone(),self.at+4*3600))
        self.assertEqual(wallet.view(self.db,1,self.at+4*3600)['balance'],2000)

    def test_missing_quote_does_not_liquidate_short_and_old_marks_are_preserved(self):
        self.tick(self.at);self.order('short',clock=self.at+1,symbol='TW:2330');self.tick(self.at+2);market.settle(self.db,self.at+2)
        before=market.assets(self.db)[1]
        self.tick(self.at+5,[mis_fixture(self.at+5,z='-',a='-')]);market.settle(self.db,self.at+5)
        self.assertEqual(market.assets(self.db)[1],before)
        self.assertEqual(market.view(self.db,1,self.at+5)['shorts'][0]['status'],'open')
        self.assertEqual(wallet.view(self.db,1,self.at+5)['balance'],2000)

    def test_receipt_replay_and_cancel_remain_safe_when_mis_disappears(self):
        self.tick(self.at)
        request=dict(symbol='TW:2330',side='buy',amount=1000,operation_id='mis_receipt_recovery_1234')
        first=market.mutate(self.db,self.user,'order',request,self.at+1)
        market_data.apply(self.db,[('TW',[],'unavailable',self.at+7)],self.at+2)
        self.assertTrue(market.mutate(self.db,self.user,'order',request,self.at+3)['replayed'])
        cancel=dict(order_id=first['order_id'],operation_id='mis_cancel_recovery_1234')
        market.mutate(self.db,self.user,'cancel',cancel,self.at+4)
        self.assertTrue(market.mutate(self.db,self.user,'cancel',cancel,self.at+5)['replayed'])
        self.assertEqual(wallet.view(self.db,1,self.at+5)['balance'],3000)
        self.tick(self.at+6);self.assertFalse(market.settle(self.db,self.at+6))
        self.assertEqual(len(market.view(self.db,1,self.at+6)['orders']),1)

    def test_health_table_keeps_original_quote_schema_rollback_compatible(self):
        self.tick(self.at)
        self.assertEqual(len(self.db.execute('PRAGMA table_info(market_quotes)').fetchall()),12)
        self.db.execute("INSERT INTO market_quotes VALUES('TW:0050','100','99','101','100','1',?,?,?,'old version','token',0)",(self.at,self.at,self.at))
        self.assertFalse(next(i for i in market.view(self.db,1,self.at)['instruments'] if i['symbol']=='TW:0050')['available'])


class MarketHTTP(ServerTestCase):
    def test_private_concurrent_receipts(self):
        a=Client(self.base);self.assertEqual(a.call('/api/market')[0],401)
        status,reg=a.call('/api/register',dict(username='market_http',nickname='交易測試',password='SyntheticMarket123'))
        self.assertEqual(status,200)
        uid=a.call('/api/online/lobby')[1]['me']['id']
        import time
        with closing(sqlite3.connect(self.db_path)) as db:
            db.row_factory=sqlite3.Row
            market.apply_quotes(db,[dict(symbol='CC:BTC',price='100',bid='100',ask='100',native='100',fx='1',fx_at=time.time(),asof=time.time(),source='test')],time.time());db.commit()
        data=dict(symbol='CC:BTC',side='buy',amount=1000,operation_id='http_market_duplicate_12345')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:a.call('/api/market/order',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results)
        self.assertEqual(len({r[1]['order_id'] for r in results}),1)
        value=a.call('/api/market')[1];self.assertEqual(value['wallet']['balance'],9000)
        self.assertEqual(value['wallet']['total'],10000);self.assertEqual(len(value['market']['orders']),1)
        b=Client(self.base);code=a.call('/api/state')[1]['invite_code']
        self.assertEqual(b.call('/api/register',dict(username='market_other',nickname='另一位',password='SyntheticMarket123',invite_code=code))[0],200)
        self.assertEqual(b.call('/api/market')[1]['market']['orders'],[])
        self.assertEqual(b.call('/api/market/cancel',dict(order_id=value['market']['orders'][0]['id'],operation_id='http_cancel_foreign_12345'))[0],400)


    def test_short_concurrent_reserve_and_cover_receipts(self):
        import time
        with closing(sqlite3.connect(self.db_path)) as db:
            invite=db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]
        a=Client(self.base)
        self.assertEqual(a.call('/api/register',dict(username='short_http_owner',nickname='做空測試',password='SyntheticMarket123',invite_code=invite))[0],200)
        uid=a.call('/api/online/lobby')[1]['me']['id']
        def tick(price,settle=True):
            with closing(sqlite3.connect(self.db_path,timeout=10)) as db:
                db.row_factory=sqlite3.Row;t=time.time()
                market.apply_quotes(db,[dict(symbol='CC:BTC',price=str(price),bid=str(price),ask=str(price),native=str(price),fx='1',fx_at=t,asof=t,source='test')],t)
                if settle:market.settle(db,t)
                db.commit()
        tick(100,False)
        data=dict(symbol='CC:BTC',side='short',amount=1000,operation_id='http_short_same_reserve_1234')
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:a.call('/api/market/order',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results)
        self.assertEqual(len({r[1]['order_id'] for r in results}),1)
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],9000)
        tick(100);short=a.call('/api/market')[1]['market']['shorts'][0]
        data=dict(symbol='CC:BTC',side='cover',position_id=short['id'],operation_id='http_short_same_cover_12345')
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:a.call('/api/market/order',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results)
        self.assertEqual(len({r[1]['order_id'] for r in results}),1)
        tick(90)
        value=a.call('/api/market')[1]
        self.assertEqual(value['wallet']['balance'],10100);self.assertEqual(value['market']['shorts'],[])
        self.assertTrue(a.call('/api/market/order',data)[1]['replayed'])
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],10100)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=? AND kind='market_reserve'",(uid,)).fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=? AND event_key=?",(uid,'market:cover:'+str(short['id']))).fetchone()[0],1)


def yahoo_fixture(clock,code='AAPL',**meta_fields):
    start=datetime.fromtimestamp(clock,timezone.utc).replace(hour=13,minute=30,second=0,microsecond=0).timestamp()
    meta=dict(symbol=code,currency='USD',instrumentType='EQUITY',dataGranularity='1m',regularMarketTime=clock,regularMarketPrice=100,
        currentTradingPeriod=dict(regular=dict(start=start,end=start+23400)))|meta_fields
    return dict(chart=dict(error=None,result=[dict(meta=meta,timestamp=[clock-180,clock-120,clock-60,clock],indicators=dict(quote=[dict(close=[98,99,100,101])]))]))


class YahooFormats(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,10,28,15,tzinfo=timezone.utc).timestamp();self.fx=dict(rate='32',asof=self.at)

    def test_trade_and_minute_history_are_distinct_with_original_times_and_fx(self):
        p=market_data.yahoo_packet(yahoo_fixture(self.at),'US:AAPL',self.at,self.fx)
        self.assertEqual(p['quote']['asof'],self.at);self.assertEqual(p['quote']['price'],'3200')
        self.assertEqual(p['quote']['source'],market.US_SOURCE)
        self.assertEqual([r[1] for r in p['history']],[self.at-180,self.at-120,self.at-60])
        self.assertEqual(p['history'][0][2:],(str(98*32),'98','32',self.at))
        self.assertEqual(p['end']-p['start'],23400)

    def test_missing_or_invalid_snapshot_keeps_chart_only_never_synthesizes_quote(self):
        for fields in [dict(regularMarketPrice=None),dict(regularMarketPrice=0),dict(regularMarketPrice=float('nan')),dict(regularMarketTime=True),dict(regularMarketTime=self.at+6),dict(regularMarketTime=self.at-9*86400)]:
            p=market_data.yahoo_packet(yahoo_fixture(self.at,**fields),'US:AAPL',self.at,self.fx)
            self.assertIsNone(p['quote']);self.assertEqual(len(p['history']),3)
        data=yahoo_fixture(self.at);r=data['chart']['result'][0]
        r['timestamp']=[self.at-180,self.at-120,self.at-120,self.at-60,self.at,self.at+60]
        r['indicators']['quote'][0]['close']=[None,98,99,100,101,102]
        self.assertEqual([r[1] for r in market_data.yahoo_packet(data,'US:AAPL',self.at,self.fx)['history']],[self.at-60])
        r['timestamp']=[self.at-60];r['indicators']['quote'][0]['close']=[0]
        self.assertEqual(market_data.yahoo_packet(data,'US:AAPL',self.at,self.fx)['history'],[])

    def test_next_session_metadata_keeps_last_close_and_history_for_display_only(self):
        data=yahoo_fixture(self.at)
        r=data['chart']['result'][0]['meta']['currentTradingPeriod']['regular']
        r['start']+=86400;r['end']+=86400
        packet=market_data.yahoo_packet(data,'US:AAPL',self.at+12*3600,self.fx)
        self.assertIsNotNone(packet['quote'])
        self.assertEqual(len(packet['history']),4)
        self.assertLess(packet['quote']['asof'],packet['start'])

    def test_wrong_instrument_currency_session_and_error_rejected(self):
        for fields in [dict(symbol='OTHER'),dict(currency='TWD'),dict(instrumentType='MUTUALFUND'),dict(dataGranularity='1d'),dict(currentTradingPeriod={}),dict(currentTradingPeriod=dict(regular=dict(start=True,end=self.at)))]:
            with self.subTest(fields=fields),self.assertRaises((ValueError,KeyError)):
                market_data.yahoo_packet(yahoo_fixture(self.at,**fields),'US:AAPL',self.at,self.fx)
        with self.assertRaises(ValueError):market_data.yahoo_packet(dict(chart=dict(error=dict(code='Not Found'),result=None)),'US:AAPL',self.at,self.fx)

    def test_fixed_catalog_partial_failure_bounded_retry_and_closed_poll(self):
        def fetch(url):
            code=url.split('/chart/')[1].split('?')[0]
            if code=='NVDA':raise ValueError('private upstream details')
            return yahoo_fixture(self.at,code)
        with patch('market_data.fetch_json',side_effect=fetch) as mocked:
            rows,status,next_at,_=market_data.yahoo_batch(self.at,self.fx)
        self.assertEqual((len(rows),status,next_at),(2,'partial',self.at+60))
        self.assertEqual(mocked.call_count,3)
        self.assertTrue(all(c.args[0].startswith('https://query1.finance.yahoo.com/v8/finance/chart/') and c.args[0].endswith('?interval=1m&range=1d&includePrePost=false') for c in mocked.call_args_list))
        with patch('market_data.fetch_json',side_effect=lambda u:yahoo_fixture(self.at,u.split('/chart/')[1].split('?')[0])):
            self.assertEqual(market_data.yahoo_batch(self.at,self.fx)[2],self.at+10)
            self.assertEqual(market_data.yahoo_batch(self.at+6*3600,self.fx)[1:3],('closed',self.at+6*3600+60))


class YahooRules(unittest.TestCase):
    quote=MarketRules.quote
    order=MarketRules.order

    def setUp(self):
        MarketRules.setUp(self)
        self.at=datetime(2026,10,28,15,tzinfo=timezone.utc).timestamp()
        self.fx=dict(rate='1',asof=self.at)

    def tick(self,clock,**fields):
        packet=market_data.yahoo_packet(yahoo_fixture(clock,**fields),'US:AAPL',clock,self.fx)
        market_data.apply(self.db,[('US',[packet],'partial',clock+10)],clock)
        return packet

    def instrument(self,clock):
        return next(i for i in market.view(self.db,1,clock)['instruments'] if i['symbol']=='US:AAPL')

    def test_reference_fills_once_after_submission_not_on_history_or_refetch(self):
        self.tick(self.at);self.order(clock=self.at+1,symbol='US:AAPL')
        self.tick(self.at+10,regularMarketTime=self.at)
        self.assertFalse(market.settle(self.db,self.at+10))
        self.assertEqual(wallet.view(self.db,1,self.at+10)['balance'],2000)
        self.tick(self.at+11,regularMarketPrice=110);self.assertTrue(market.settle(self.db,self.at+11))
        self.assertFalse(market.settle(self.db,self.at+12))
        v=market.view(self.db,1,self.at+12)
        self.assertEqual(v['orders'][0]['fill_price'],'110');self.assertEqual(v['orders'][0]['fill_asof'],self.at+11)
        i=self.instrument(self.at+12);self.assertTrue(i['available']);self.assertIsNone(i['quote']['bid']);self.assertIsNone(i['quote']['ask'])
        self.assertEqual(i['quote']['execution'],'reference_trade')
        self.assertEqual(wallet.view(self.db,1,self.at+12)['total'],2999)

    def test_missing_snapshot_or_history_only_never_fills_and_recovery_is_safe(self):
        self.tick(self.at)
        d=dict(symbol='US:AAPL',side='buy',amount=1000,operation_id='yahoo_receipt_recovery_1234')
        market.mutate(self.db,self.user,'order',d,self.at+1)
        self.tick(self.at+5,regularMarketPrice=None)
        self.assertFalse(market.settle(self.db,self.at+5));self.assertFalse(self.instrument(self.at+5)['available'])
        self.assertGreater(len(market.chart(self.db,'US:AAPL','15m',self.at+5)['points']),1)
        self.assertTrue(market.mutate(self.db,self.user,'order',d,self.at+6)['replayed'])
        with self.assertRaises(RuleError):self.order(clock=self.at+6,symbol='US:AAPL')
        self.tick(self.at+10);self.assertTrue(market.settle(self.db,self.at+10))
        self.assertEqual(wallet.view(self.db,1,self.at+10)['balance'],2000)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='market_reserve'").fetchone()[0],1)

    def test_freshness_fx_session_and_source_are_required_for_accept_and_fill(self):
        self.tick(self.at)
        for clock in (self.at-1,self.at+31,self.at+6*3600):
            with self.subTest(clock=clock),self.assertRaises(RuleError):self.order(clock=clock,symbol='US:AAPL')
        self.tick(self.at+91,regularMarketTime=self.at)
        self.assertFalse(self.instrument(self.at+91)['available'])
        self.tick(self.at+92);self.db.execute("UPDATE market_quotes SET fx_at=? WHERE symbol='US:AAPL'",(self.at-4*86400,))
        self.assertFalse(self.instrument(self.at+92)['available'])
        self.db.execute("UPDATE market_quotes SET source='Marketstack 免費收盤行情' WHERE symbol='US:AAPL'")
        self.assertFalse(self.instrument(self.at+92)['available'])

    def test_session_bounds_support_dst_and_half_days_without_local_clock_guess(self):
        for start in (datetime(2026,10,28,13,30,tzinfo=timezone.utc).timestamp(),datetime(2026,11,27,14,30,tzinfo=timezone.utc).timestamp()):
            self.db.execute("DELETE FROM market_quotes WHERE symbol='US:AAPL'")
            self.fx['asof']=start
            packet=market_data.yahoo_packet(yahoo_fixture(start+60,currentTradingPeriod=dict(regular=dict(start=start,end=start+12600))),'US:AAPL',start+60,self.fx)
            market_data.apply(self.db,[('US',[packet],'partial',start+70)],start+60)
            self.assertTrue(self.instrument(start+61)['available'])
            q=dict(self.db.execute(market.QUOTE_SQL+" WHERE q.symbol='US:AAPL'").fetchone());q.update(asof=start+12600-1,checked_at=start+12600-1)
            self.assertTrue(market.quote_ready(q,start+12600-1));self.assertFalse(market.quote_ready(q,start+12600))

    def test_regression_failure_and_stale_data_do_not_liquidate_or_change_last_mark(self):
        self.tick(self.at);self.order('short',clock=self.at+1,symbol='US:AAPL');self.tick(self.at+2);market.settle(self.db,self.at+2)
        self.tick(self.at+3,regularMarketTime=self.at)
        self.assertFalse(self.instrument(self.at+3)['available'])
        before=wallet.view(self.db,1,self.at+3)['total']
        self.tick(self.at+4,regularMarketPrice=None)
        market_data.apply(self.db,[('US',[],'unavailable',self.at+65)],self.at+5)
        self.assertFalse(market.settle(self.db,self.at+5))
        self.assertEqual(wallet.view(self.db,1,self.at+5)['total'],before)
        self.assertEqual(len(market.view(self.db,1,self.at+5)['shorts']),1)
        self.tick(self.at+6);self.order('cover',clock=self.at+7,symbol='US:AAPL',position_id=1)
        self.tick(self.at+8,regularMarketPrice=90);market.settle(self.db,self.at+8)
        self.assertEqual(wallet.view(self.db,1,self.at+8)['balance'],3100)
        self.assertEqual(market.view(self.db,1,self.at+8)['shorts'],[])

    def test_history_is_deduplicated_not_revalued_and_never_creates_holdings(self):
        self.tick(self.at);before=wallet.view(self.db,1,self.at)['total']
        first=list(map(tuple,self.db.execute("SELECT * FROM market_history WHERE symbol='US:AAPL' ORDER BY asof")))
        self.fx['rate']='1.1';self.tick(self.at)
        self.assertEqual(list(map(tuple,self.db.execute("SELECT * FROM market_history WHERE symbol='US:AAPL' ORDER BY asof"))),first)
        self.assertEqual(wallet.view(self.db,1,self.at)['total'],before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM market_positions').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM market_quotes').fetchone()[0],2)
        points=market.chart(self.db,'US:AAPL','15m',self.at)['points']
        self.assertEqual([p['at'] for p in points],[self.at-180,self.at-120,self.at-60,self.at])
        self.assertIn('分鐘',market.chart(self.db,'US:AAPL','15m',self.at)['basis'])
        self.assertEqual(len(self.db.execute('PRAGMA table_info(market_quotes)').fetchall()),12)

    def test_weekend_chart_ends_at_last_real_point_but_does_not_reopen_trading(self):
        self.tick(self.at)
        chart=market.chart(self.db,'US:AAPL','15m',self.at+3*86400)
        self.assertEqual(chart['to_at'],self.at)
        self.assertEqual(chart['from_at'],self.at-900)
        self.assertEqual(len(chart['points']),4)
        self.assertFalse(self.instrument(self.at+3*86400)['available'])
        self.assertIn('休市',self.instrument(self.at+3*86400)['notice'])

    def test_short_chart_queries_do_not_scan_all_accumulated_history(self):
        self.tick(self.at)
        self.db.executemany('INSERT INTO market_history VALUES(?,?,?,?,?,?)',
            [('US:AAPL',self.at-86400-n,'100','100','1',self.at) for n in range(25000)])
        calls=0
        def budget():
            nonlocal calls
            calls+=1
            return int(calls>100)
        self.db.set_progress_handler(budget,1000)
        try:
            chart=market.chart(self.db,'US:AAPL','15m',self.at)
            self.assertEqual(len(chart['points']),4)
            chart=market.chart(self.db,'US:AAPL','15m',self.at+3*86400)
            self.assertEqual(chart['to_at'],self.at)
        finally:self.db.set_progress_handler(None,0)

    def test_daily_schedule_migration_and_retry_are_persisted(self):
        self.db.execute('INSERT INTO market_providers VALUES(?,?,?,?)',('US',self.at+86400,self.at,'missing_key'))
        self.assertIn('US',market_data.due(self.db,self.at))
        market_data.apply(self.db,[('US',[],'unavailable',self.at+60)],self.at)
        self.assertNotIn('US',market_data.due(self.db,self.at+59))
        self.assertIn('US',market_data.due(self.db,self.at+60))
