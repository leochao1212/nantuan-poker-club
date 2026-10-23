'use strict';
// Speech only, 16 kHz mono. Slow receivers discard old audio; nothing is recorded.
class ClubCapture extends AudioWorkletProcessor {
  constructor(){super();this.frame=new Int16Array(640);this.at=0;this.sum=0;this.count=0;this.phase=0;this.energy=0;this.hang=0;this.muted=false;this.port.onmessage=e=>{this.muted=!!e.data.muted;};}
  process(inputs){const input=inputs[0]?.[0];if(!input)return true;
    for(const value of input){this.sum+=value;this.count++;this.phase+=16000;if(this.phase<sampleRate)continue;this.phase-=sampleRate;
      const x=Math.max(-1,Math.min(1,this.sum/this.count));this.sum=0;this.count=0;this.frame[this.at++]=Math.round(x*32767);this.energy+=x*x;
      if(this.at===640){const level=Math.sqrt(this.energy/640);if(level>.008)this.hang=8;this.port.postMessage({type:'level',level:this.muted?0:level});
        if(!this.muted&&this.hang>0){const buffer=this.frame.buffer;this.port.postMessage({type:'pcm',buffer},[buffer]);this.frame=new Int16Array(640);this.hang--;}this.at=0;this.energy=0;
      }
    }return true;
  }
}
class ClubPlayback extends AudioWorkletProcessor {
  constructor(){super();this.sources=new Map();this.deaf=false;this.ticks=0;this.port.onmessage=e=>{const d=e.data;
    if(d.type==='deaf'){this.deaf=!!d.value;this.sources.clear();return;}if(d.type!=='pcm'||this.deaf||d.buffer.byteLength!==1280)return;
    let s=this.sources.get(d.uid);if(!s){if(this.sources.size>=24)return;s={queue:[],position:0,ready:false,seen:currentTime};this.sources.set(d.uid,s);}
    s.seen=currentTime;s.queue.push(new Int16Array(d.buffer));if(s.queue.length>8){s.queue.splice(0,s.queue.length-2);s.position=0;}if(s.queue.length>=2)s.ready=true;
  };}
  process(inputs,outputs){const out=outputs[0]?.[0];if(!out)return true;let energy=0;
    for(const [uid,s] of this.sources){if(currentTime-s.seen>3){this.sources.delete(uid);continue;}if(!s.ready)continue;
      for(let i=0;i<out.length;i++){if(!s.queue.length){s.ready=false;break;}const f=s.queue[0],n=Math.floor(s.position),fraction=s.position-n,next=n+1<f.length?f[n+1]:(s.queue[1]?.[0]??f[n]);
        out[i]+=(f[n]*(1-fraction)+next*fraction)/32768;s.position+=16000/sampleRate;if(s.position>=640){s.position-=640;s.queue.shift();}
      }
    }for(let i=0;i<out.length;i++){out[i]=Math.max(-1,Math.min(1,out[i]));energy+=out[i]*out[i];}if(++this.ticks%40===0)this.port.postMessage({type:'output',level:Math.sqrt(energy/out.length)});return true;
  }
}
registerProcessor('club-voice-capture',ClubCapture);
registerProcessor('club-voice-playback',ClubPlayback);
