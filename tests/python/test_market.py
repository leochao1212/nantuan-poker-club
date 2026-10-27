"""Fixed-point paper orders, new-observation fills, conservation and private receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
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
