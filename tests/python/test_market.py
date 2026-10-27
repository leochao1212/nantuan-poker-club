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
        online.initialize(self.db);self.user={'id':1};self.serial=0
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

    def test_stock_close_retrieval_is_not_new_price_and_split_halts(self):
        self.quote(100,100,'TW:2330')
        self.order(clock=101,symbol='TW:2330')
        self.quote(100,200,'TW:2330',asof=100)
        self.assertFalse(market.settle(self.db,200))
        self.quote(110,300,'TW:2330');market.settle(self.db,300)
        self.assertEqual(market.view(self.db,1,300)['orders'][0]['status'],'filled')
        old=market.assets(self.db)[1]
        self.quote(55,400,'TW:2330')
        q=dict(self.db.execute("SELECT * FROM market_quotes WHERE symbol='TW:2330'").fetchone())
        self.assertTrue(q['halted']);self.assertEqual(market.assets(self.db)[1],old)
        with self.assertRaises(RuleError):self.order(clock=401,symbol='TW:2330')

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


class Providers(unittest.TestCase):
    def test_official_formats_and_currency_conversion(self):
        at=datetime(2026,10,27,7,tzinfo=timezone.utc).timestamp()
        with patch('market_data.fetch_json',return_value=[dict(Code='2330',Date='1151027',ClosingPrice='1,000.00')]):
            rows,status,_,_=market_data.read_provider('TW',at,None)
        self.assertEqual(rows[0]['price'],'1000.00');self.assertEqual(rows[0]['asof'],at-5400)
        payload={'error':[],'result':{k:dict(a=['101'],b=['99'],c=['100']) for k in ['XXBTZUSD','XETHZUSD','SOLUSD']}}
        with patch('market_data.fetch_json',return_value=payload):
            rows,_,_,_=market_data.read_provider('CC',at,dict(rate='32',asof=at))
        self.assertEqual(rows[0]['ask'],'3232');self.assertEqual(rows[0]['bid'],'3168')

    def test_missing_key_failure_budget_and_no_secret_leak(self):
        with patch.dict('os.environ',{},clear=True),patch('market_data.fetch_json') as fetch:
            result=market_data.refresh(['US','CC'],100,None);fetch.assert_not_called()
            self.assertEqual(result[0][2],'missing_key');self.assertEqual(result[1][2],'fx_unavailable')
        with patch.dict('os.environ',{'POKER_MARKETSTACK_KEY':'SECRET'}),patch('market_data.fetch_json',side_effect=ValueError('SECRET')):
            result=market_data.refresh(['US'],100,dict(rate='32',asof=100))
        self.assertNotIn('SECRET',str(result));self.assertEqual(result[0][3],86500)


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
        value=a.call('/api/market')[1];self.assertEqual(value['wallet']['balance'],2000)
        self.assertEqual(value['wallet']['total'],3000);self.assertEqual(len(value['market']['orders']),1)
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
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],2000)
        tick(100);short=a.call('/api/market')[1]['market']['shorts'][0]
        data=dict(symbol='CC:BTC',side='cover',position_id=short['id'],operation_id='http_short_same_cover_12345')
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:a.call('/api/market/order',data),range(8)))
        self.assertTrue(all(r[0]==200 for r in results),results)
        self.assertEqual(len({r[1]['order_id'] for r in results}),1)
        tick(90)
        value=a.call('/api/market')[1]
        self.assertEqual(value['wallet']['balance'],3100);self.assertEqual(value['market']['shorts'],[])
        self.assertTrue(a.call('/api/market/order',data)[1]['replayed'])
        self.assertEqual(a.call('/api/market')[1]['wallet']['balance'],3100)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=? AND kind='market_reserve'",(uid,)).fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=? AND event_key=?",(uid,'market:cover:'+str(short['id']))).fetchone()[0],1)
