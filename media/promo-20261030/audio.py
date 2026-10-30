"""Original 120 BPM instrumental. No samples or third-party recordings."""
from pathlib import Path
import numpy as np
import wave

SR=48000
N=SR*30
mix=np.zeros((N,2),np.float64)
rng=np.random.default_rng(30)

def add(signal,at,volume=1,pan=0):
    start=int(at*SR)
    count=min(len(signal),N-start)
    if count<=0:return
    mix[start:start+count,0]+=signal[:count]*volume*np.sqrt((1-pan)/2)
    mix[start:start+count,1]+=signal[:count]*volume*np.sqrt((1+pan)/2)

def note(midi,duration):
    t=np.arange(int(duration*SR))/SR
    f=440*2**((midi-69)/12)
    env=(1-np.exp(-t*80))*np.exp(-t*2.8)*np.minimum(1,(duration-t)*20)
    return (.75*np.sin(2*np.pi*f*t)+.18*np.sin(2*np.pi*2*f*t)+.07*np.sin(2*np.pi*3*f*t))*env

chords=[[62,65,69,72],[58,62,65,69],[60,65,69,72],[60,64,67,74]]
for beat in range(60):
    at=beat*.5
    if at>=28.5:continue
    t=np.arange(int(.22*SR))/SR
    kick=np.sin(2*np.pi*(48*t+8*(1-np.exp(-t*24))))*np.exp(-t*20)
    add(kick,at,.23)
    if beat%2:
        t=np.arange(int(.12*SR))/SR
        noise=rng.normal(0,1,len(t));noise=np.diff(noise,prepend=0)
        add(noise*np.exp(-t*45),at,.035)
    if beat>=8:
        t=np.arange(int(.05*SR))/SR
        add(rng.normal(0,1,len(t))*np.exp(-t*90),at+.25,.018,.3)
    chord=chords[(beat//8)%4]
    if beat%4==0:
        for i,n in enumerate(chord):add(note(n,2.5),at+i*.018,.09,(i-1.5)*.22)
        add(note(chord[0]-24,.85),at,.22)
    if beat%2==0 and beat>=8:add(note(chord[(beat//2)%4]+12,.6),at+.25,.065,-.25)

for at in [4,9,14,19,24,27]:
    t=np.arange(int(.32*SR))/SR
    noise=rng.normal(0,1,len(t))
    smooth=np.convolve(noise,np.ones(32)/32,mode='same')
    add(smooth*np.sin(np.pi*t/.32)**2,at-.25,.12)
for i,n in enumerate([62,65,69,74]):add(note(n,2.7),27+i*.05,.14,(i-1.5)*.2)
fade=np.minimum(1,np.arange(N)/(.15*SR))*np.minimum(1,(N-np.arange(N))/(.9*SR))
mix*=fade[:,None]
mix=np.tanh(mix*1.5)
mix*=.84/max(.84,np.max(np.abs(mix)))
out=Path(__file__).resolve().parents[2]/'artifacts/promo-20261030';out.mkdir(parents=True,exist_ok=True)
with wave.open(str(out/'soundtrack.wav'),'wb') as w:
    w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes((mix*32767).astype('<i2').tobytes())
print('Original stereo soundtrack: 30.000 seconds')
