"""Fixed-step button/slider tension fight, independent of renderer frame rate."""
import math

def start(data,clock,index,rod):
    data.update(phase='playing',hooked_at=clock,sim_at=clock,deadline=clock+30,
                holding=False,input_at=clock,sequence=0,control=None,tension=.5,
                danger=0.,progress=0.,combo=0.,best_combo=0.,perfect_time=0.,
                width=rod['width'],rate=rod['rate'],fish_power=1+index*.06,
                path={'speed':.85+index*.055,'phase':data.get('pull_phase',0)})

def pull(data,at):
    p=data['path'];t=max(0,at-data['hooked_at'])
    return .21+.075*math.sin(t*p['speed']+p['phase'])+.025*math.sin(t*2.17+p['phase']*.7)

def advance(data,clock):
    if data.get('phase')!='playing':return
    target=min(clock,data['deadline'])
    while data['sim_at']+.05<=target+1e-7 and data['phase']=='playing':
        at=data['sim_at']+.05;fresh=at-data['input_at']<=1.1
        control=(data.get('control') if data.get('control') is not None else float(data['holding'])) if fresh else 0.
        tension=max(0.,min(1.,data['tension']+(control*.62-pull(data,at)*data['fish_power'])*.05))
        center=abs(tension-.5);safe=center<=data['width']*.70;perfect=center<=.075
        progress=min(1.,data['progress']+(.115*data['rate'] if safe else .012)*.05)
        danger=max(0.,min(1.,data['danger']+(.56 if center>.40 else -.21)*.05))
        combo=max(0.,min(1.,data['combo']+(.13 if perfect else -.085)*.05))
        data.update(sim_at=at,tension=tension,progress=progress,danger=danger,combo=combo,
                    best_combo=max(data['best_combo'],combo),perfect_time=data['perfect_time']+(.05 if perfect else 0))
        if progress>=1:data.update(phase='caught',finished_at=at)
        elif danger>=1:data.update(phase='escaped',finished_at=at,reason='張力過高，魚線斷了' if tension>.5 else '張力過低，魚脫鉤了')
    if clock>=data['deadline'] and data['phase']=='playing':data.update(phase='escaped',finished_at=data['deadline'],reason='收線逾時，魚逃走了')

def result(data,size,value):
    elapsed=max(.05,data['finished_at']-data['hooked_at'])
    quality=min(1.,data['perfect_time']/elapsed)
    data.update(stars=max(1,min(5,round(1+quality*4))),score=round(size*(1+data['best_combo'])*10),reward=value)
