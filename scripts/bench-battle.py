"""Synthetic CPU budget for 32 humans / 48 participants. No network or database."""
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from battle_engine import Match, STEP
from battle import pack


def main():
    matches=[];humans=[];uid=0
    for index,count in enumerate((16,15,1)):
        match=Match(231+index);ids=[]
        for _ in range(count):
            uid+=1;match.add(uid,'合成玩家'+str(uid));ids.append(uid)
        match.start(0,count<16);matches.append(match);humans.append(ids)
    costs=[];snapshot_costs=[];bytes_sent=0;steps=400;cpu=time.process_time();wall=time.perf_counter()
    for tick in range(steps):
        clock=12+tick*STEP;before=time.perf_counter()
        for match,ids in zip(matches,humans):
            for uid in ids:
                p=match.players[uid]
                if p.hp>0:match.input(uid,dict(type='input',seq=tick,forward=.6,strafe=.2,yaw=tick*.01),clock)
            match.advance(clock)
        if tick%3==0:
            at=time.perf_counter()
            for match,ids in zip(matches,humans):
                for uid in ids:bytes_sent+=len(pack(match.snapshot(uid)))
            snapshot_costs.append((time.perf_counter()-at)*1000)
        costs.append((time.perf_counter()-before)*1000)
    cpu=time.process_time()-cpu;wall=time.perf_counter()-wall
    def p95(values):return sorted(values)[int((len(values)-1)*.95)]
    result=dict(scope='Local synthetic CPU only; excludes HTTP, voice, TLS/tunnel and client GPU. Not production latency or physical-device fps.',
                rooms=3,humans=32,participants=48,simulated_seconds=steps*STEP,cpu_seconds=round(cpu,3),wall_seconds=round(wall,3),
                estimated_one_core_percent=round(cpu/(steps*STEP)*100,1),tick_p95_ms=round(p95(costs),2),max_tick_ms=round(max(costs),2),
                snapshot_batch_p95_ms=round(p95(snapshot_costs),2),bytes_per_second=round(bytes_sent/(steps*STEP)))
    out=Path(__file__).resolve().parents[1]/'artifacts/battle';out.mkdir(parents=True,exist_ok=True)
    (out/'cpu-budget.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))


if __name__=='__main__':main()
