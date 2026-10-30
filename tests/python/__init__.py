"""Isolated Python regression suite and its shared test fixtures."""


def scenario_budget(db, balance=3000):
    """Transaction fixtures use a known budget independently of welcome rewards."""
    for uid,current in db.execute('SELECT user_id,balance FROM wallets').fetchall():
        db.execute('UPDATE wallets SET balance=? WHERE user_id=?',(balance,uid))
        db.execute("UPDATE wallet_ledger SET amount=?,balance_after=? WHERE user_id=? AND kind='initial'",(balance,balance,uid))
        db.execute('UPDATE wealth_accounts SET initial_total=? WHERE user_id=?',(balance,uid))
