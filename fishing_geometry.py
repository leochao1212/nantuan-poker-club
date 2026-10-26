"""Shared canonical fish geometry; rendering metadata has no runtime image dependency."""
from pathlib import Path
import json,math
ART=json.loads((Path(__file__).parent/'static/fishing-art.json').read_text(encoding='utf-8'))

def elapsed(fish,clock,effects=()):
    t=max(0,clock-fish['spawned_at'])
    return t-sum(max(0,min(clock,e['ends_at'])-max(fish['spawned_at'],e['starts_at'])) for e in effects if e.get('kind','freeze')=='freeze')

def heading(fish,clock,effects=()):
    if fish.get('geometry_version',1)<2:return 0.
    t=elapsed(fish,clock,effects)
    return math.atan2(fish['amplitude']*fish['frequency']*math.cos(t*fish['frequency']+fish['phase']),fish['vx'])

def collides(fish,fx,fy,x,y,radius,clock,effects=()):
    angle=heading(fish,clock,effects);dx=x-fx;dy=y-fy;c=math.cos(angle);s=math.sin(angle)
    return ((dx*c+dy*s)/(fish['radius_x']+radius))**2+((-dx*s+dy*c)/(fish['radius_y']+radius))**2<=1

def beam_hit(fish,fx,fy,x,y,ux,uy,length,radius,clock,effects=()):
    """Closest point on a finite beam, transformed into the same fish ellipse."""
    angle=heading(fish,clock,effects);c=math.cos(angle);s=math.sin(angle)
    dx=x-fx;dy=y-fy;rx=fish['radius_x']+radius;ry=fish['radius_y']+radius
    px=(dx*c+dy*s)/rx;py=(-dx*s+dy*c)/ry
    vx=(ux*c+uy*s)/rx;vy=(-ux*s+uy*c)/ry
    at=max(0,min(length,-(px*vx+py*vy)/(vx*vx+vy*vy)))
    return (px+at*vx)**2+(py+at*vy)**2<=1
