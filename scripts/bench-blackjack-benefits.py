"""Isolated paired-card comparison; synthetic points only, no database/network."""
from pathlib import Path
import sys;sys.path.insert(0,str(Path.cwd()))
import random,json,collections
from copy import deepcopy
from unittest.mock import patch
import arcade_engine as a,poker_engine as p,game_settings as g
cards_rng=random.Random(20261027);benefit_rng=random.Random(37);totals={'off':collections.Counter(),'easy':collections.Counter()};n=20000
base=a.new_room('Synthetic comparison',1,'blackjack',10000,100);a.sit(base,1,'Synthetic player',0)
configs={name:g.default('blackjack') for name in totals};configs['easy']['params'].update(tie_win_bps=5000,bust_refund_bps=2500)
with patch.object(a.secrets,'randbelow',side_effect=benefit_rng.randrange):
 for i in range(n):
  deck=list(p.DECK)*6;cards_rng.shuffle(deck);seen=[]
  for name,stats in totals.items():
   r=deepcopy(base);before=r['bank']+r['seats'][0]['stack'];a.start_hand(r,1,deck=deck,settings=configs[name])
   while r['status']=='playing':
    h=r['hand']['players'][0]['hands'][r['hand']['active_index']];score=a.blackjack_total(h['cards']);hard=sum(1 if c[0]=='A' else 10 if c[0] in 'TJQK' else int(c[0]) for c in h['cards']);soft=hard!=score
    a.act(r,1,'hit' if score<(18 if soft else 17) else 'stand',2)
   h=r['hand']['players'][0]['hands'][0];result=r['hand']['results'][0]
   assert r['bank']+r['seats'][0]['stack']==before
   stats['staked']+=h['bet'];stats['returned']+=h['payout'];stats['wins']+=result['profit']>0;stats['pushes_or_refunds']+=result['profit']==0;stats['losses']+=result['profit']<0
   stats['tie_bonus']+=bool(h.get('benefit',{}).get('triggered') and h['benefit']['kind']=='tie_win')
   stats['bust_refund']+=bool(h.get('benefit',{}).get('triggered') and h['benefit']['kind']=='bust_refund')
   seen.append((h['cards'],r['hand']['dealer']))
  assert seen[0]==seen[1]
result={'rounds_each':n,'scope':'single player; fresh six-deck shoe each round; stand hard17/soft18; no split/double; not guaranteed live RTP','same_cards':True,'results':{name:{**s,'win_percent':100*s['wins']/n,'return_percent':100*s['returned']/s['staked']} for name,s in totals.items()}}
Path('artifacts/blackjack-benefits').mkdir(parents=True,exist_ok=True)
Path('artifacts/blackjack-benefits/comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
