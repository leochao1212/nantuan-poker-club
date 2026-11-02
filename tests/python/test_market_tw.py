"""Taiwan next-session ROD, limits, holiday boundaries and conservation."""
from datetime import datetime
import unittest
import market,market_tw,market_contracts,wallet,member_accounts
from poker_engine import RuleError
from . import test_market_tradingview as fixtures


def at(value):return datetime.fromisoformat(value).replace(tzinfo=market.TAIPEI).timestamp()


class TaiwanOrders(unittest.TestCase):
    setUp=fixtures.TradingViewRules.setUp
    tick=fixtures.TradingViewRules.tick
    order=fixtures.TradingViewRules.order
    quote=fixtures.TradingViewRules.quote

    def closed(self):
        self.tick(clock=at('2026-11-06T10:00'),current_session='out_of_session')
        return at('2026-11-06T15:00')

    def open_order(self,clock,**extra):
        return market_contracts.mutate(self.db,self.user,'open',dict(operation_id='tw_contract_open_123456',symbol='TW:2330',direction='long',leverage=2,margin=1000,order_kind='limit',limit_price='100')|extra,clock)

    def test_offhours_requires_limit_and_targets_monday(self):
        clock=self.closed()
        with self.assertRaises(RuleError):self.order(symbol='TW:2330',clock=clock)
        self.order(symbol='TW:2330',clock=clock,limit_price='95')
        o=self.db.execute('SELECT * FROM market_orders').fetchone()
        self.assertEqual(o['expires_at'],at('2026-11-09T13:30'))
        self.assertEqual(wallet.view(self.db,1,clock)['balance'],2000)
        self.assertFalse(market.settle(self.db,clock+1))
        self.tick(clock=at('2026-11-09T09:30'),close=100)
        self.assertFalse(market.settle(self.db,at('2026-11-09T09:30')))
        self.tick(clock=at('2026-11-09T09:31'),close=94)
        self.assertTrue(market.settle(self.db,at('2026-11-09T09:31')))
        self.assertEqual(self.db.execute('SELECT status FROM market_orders').fetchone()[0],'filled')

    def test_expiry_and_cancel_refund_exactly_once(self):
        clock=self.closed();self.order(symbol='TW:2330',clock=clock,limit_price='95')
        end=at('2026-11-09T13:30')
        market.settle(self.db,end);market.settle(self.db,end+1)
        self.assertEqual(wallet.view(self.db,1,end)['balance'],3000)
        self.assertEqual(self.db.execute('SELECT status FROM market_orders').fetchone()[0],'expired')

    def test_short_and_cover_limit_direction(self):
        clock=self.closed();self.order(side='short',symbol='TW:2330',clock=clock,limit_price='101')
        t=at('2026-11-09T10:00');self.tick(clock=t,close=100)
        self.assertFalse(market.settle(self.db,t))
        self.tick(clock=t+60,close=102);market.settle(self.db,t+60)
        pid=self.db.execute('SELECT id FROM market_shorts').fetchone()[0]
        self.order(side='cover',symbol='TW:2330',position_id=pid,clock=t+61,limit_price='99')
        self.tick(clock=t+120,close=100);self.assertFalse(market.settle(self.db,t+120))
        self.tick(clock=t+180,close=98);market.settle(self.db,t+180)
        self.assertEqual(self.db.execute('SELECT status FROM market_shorts').fetchone()[0],'closed')

    def test_contract_open_and_close_reservation(self):
        clock=self.closed();self.open_order(clock)
        self.assertEqual(self.db.execute('SELECT expires_at FROM market_contract_orders').fetchone()[0],at('2026-11-09T13:30'))
        t=at('2026-11-09T10:00');self.tick(clock=t,close=99);market.settle(self.db,t)
        pid=self.db.execute('SELECT id FROM market_contracts').fetchone()[0]
        market_contracts.mutate(self.db,self.user,'close',dict(operation_id='tw_contract_close_12345',position_id=pid,limit_price='101'),t+1)
        self.tick(clock=t+60,close=100);self.assertFalse(market.settle(self.db,t+60))
        self.tick(clock=t+120,close=102);market.settle(self.db,t+120)
        self.assertEqual(self.db.execute('SELECT status FROM market_contracts').fetchone()[0],'closed')

    def test_contract_expiry_returns_reserve_including_fee(self):
        clock=self.closed();self.open_order(clock)
        market.settle(self.db,at('2026-11-09T13:30'));market.settle(self.db,at('2026-11-09T13:31'))
        self.assertEqual(wallet.view(self.db,1,at('2026-11-09T13:31'))['balance'],3000)

    def test_calendar_spring_festival_and_unknown_year(self):
        start,end=market_tw.window(self.db,at('2026-02-11T14:00'))
        self.assertEqual(start,at('2026-02-23T09:00'))
        self.assertEqual(end,at('2026-02-23T13:30'))
        self.assertEqual(market_tw.window(self.db,at('2026-10-23T14:00'))[0],at('2026-10-27T09:00'))
        with self.assertRaises(RuleError):market_tw.window(self.db,at('2026-12-31T14:00'))

    def test_preopen_source_cannot_fill_and_close_auction_rejects_market(self):
        clock=self.closed();self.order(symbol='TW:2330',clock=clock,limit_price='100')
        t=at('2026-11-09T09:01');self.tick(clock=t,at=at('2026-11-09T08:59'),close=99)
        self.assertFalse(market.settle(self.db,t))
        with self.assertRaises(RuleError):market_tw.terms(self.db,at('2026-11-09T13:25'),None)

    def test_replay_and_changed_limit_conflict(self):
        clock=self.closed();data=dict(operation_id='tw_spot_same_order_12345',symbol='TW:2330',side='buy',amount=1000,limit_price='95',expected_session_end=at('2026-11-09T13:30'))
        market.mutate(self.db,self.user,'order',data,clock)
        self.assertTrue(market.mutate(self.db,self.user,'order',data,clock+1)['replayed'])
        with self.assertRaises(member_accounts.AccountError):market.mutate(self.db,self.user,'order',data|dict(limit_price='96'),clock+2)
        with self.assertRaises(member_accounts.AccountError):market.mutate(self.db,self.user,'order',data|dict(expected_session_end=at('2026-11-10T13:30')),clock+2)
        self.assertEqual(wallet.view(self.db,1,clock+2)['balance'],2000)


    def test_close_can_be_reserved_after_hours(self):
        t=at('2026-11-06T10:00');self.tick(clock=t,close=99)
        self.open_order(t+1);self.tick(clock=t+60,close=99);market.settle(self.db,t+60)
        pid=self.db.execute('SELECT id FROM market_contracts').fetchone()[0]
        clock=at('2026-11-06T15:00')
        self.tick(clock=clock,current_session='out_of_session')
        market_contracts.mutate(self.db,self.user,'close',dict(operation_id='tw_weekend_close_123456',position_id=pid,limit_price='101'),clock)
        order=self.db.execute("SELECT * FROM market_contract_orders WHERE action='close'").fetchone()
        self.assertEqual(order['expires_at'],at('2026-11-09T13:30'))
        self.assertFalse(market.settle(self.db,clock+1))
        monday=at('2026-11-09T10:00');self.tick(clock=monday,close=102);market.settle(self.db,monday)
        self.assertEqual(self.db.execute('SELECT status FROM market_contracts').fetchone()[0],'closed')


    def test_stale_session_preview_never_silently_moves_to_next_day(self):
        clock=self.closed()
        with self.assertRaises(RuleError):
            self.order(symbol='TW:2330',clock=clock,limit_price='95',expected_session_end=at('2026-11-06T13:30'))
        self.assertEqual(wallet.view(self.db,1,clock)['balance'],3000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM market_orders').fetchone()[0],0)
