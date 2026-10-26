"""Public attack packs: fixed 10-point trials, no player-dependent odds."""
import secrets

AMMO=[dict(stake=10,power=1,name='巡航彈',color='#78eaff'),
      dict(stake=100,power=10,name='雷霆彈',color='#bca1ff'),
      dict(stake=1000,power=100,name='龍焰彈',color='#ffc35c')]

def resolve(shot,multiplier):
    if 'power' not in shot:
        hits=int(secrets.randbelow(10000*multiplier)<shot['target_bps'])
        return hits,shot['stake']*hits
    hits=sum(secrets.randbelow(10000*multiplier)<shot['target_bps'] for _ in range(shot['power']))
    return hits,10*hits
