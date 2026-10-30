"""Concurrent supply requests lock the equipped bonus into one ledger entry."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3,time,unittest
from .test_app import ServerTestCase

class TitleSuppliesAPI(ServerTestCase):
    def test_concurrent_claims_then_title_change_cannot_mint_again(self):
        c=self.clients[0]
        self.assertEqual(c.call('/api/register',dict(username='title_supply_test',nickname='Title test',password='SyntheticTest123'))[0],200)
        with closing(sqlite3.connect(self.db_path)) as db:
            uid=db.execute("SELECT id FROM users WHERE username='title_supply_test'").fetchone()[0]
            db.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(uid,'title_treasury',time.time()));db.commit()
        self.assertEqual(c.call('/api/club/equip',dict(item_id='title_treasury',operation_id='supply_equip_00001'))[0],200)
        def claim(i):
            return c.call('/api/wallet/claim',{}) if i%2 else c.call('/api/wallet/hourly',dict(operation_id=f'supply_parallel_{i:04d}'))
        with ThreadPoolExecutor(8) as pool:results=list(pool.map(claim,range(16)))
        self.assertTrue(all(status==200 for status,_ in results))
        self.assertEqual(sum(r['claimed'] for _,r in results),2)
        self.assertEqual(c.call('/api/online/lobby')[1]['wallet']['balance'],12590)
        op=next(f'supply_parallel_{i:04d}' for i,(_,r) in enumerate(results) if i%2==0 and r['claimed'])
        c.call('/api/club/equip',dict(item_id='title_treasury',remove=True,operation_id='supply_remove_0001'))
        self.assertTrue(c.call('/api/wallet/hourly',dict(operation_id=op))[1]['replayed'])
        self.assertFalse(c.call('/api/wallet/hourly',dict(operation_id='supply_newretry_0001'))[1]['claimed'])
        self.assertFalse(c.call('/api/wallet/claim',{})[1]['claimed'])
        v=c.call('/api/online/lobby')[1]['wallet']
        self.assertEqual(v['balance'],12590);self.assertEqual(v['daily_amount'],2000);self.assertEqual(v['hourly_amount'],500)
        with closing(sqlite3.connect(self.db_path)) as db:
            self.assertEqual(list(db.execute("SELECT kind,amount FROM wallet_ledger WHERE user_id=? AND kind IN ('daily','hourly') ORDER BY kind",(uid,))),[('daily',2040),('hourly',550)])

if __name__=='__main__':unittest.main()
