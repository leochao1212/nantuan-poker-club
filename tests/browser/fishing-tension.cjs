const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.resolve(__dirname,'../../static/fishing-scene.js'),'utf8');
function harness(reduce=false){
 let clock=0,id=0,draws=0;const frames=new Map(),listeners=new Map(),media={matches:reduce};
 const context=new Proxy({clearRect(){draws++;}},{get(target,key){return key in target?target[key]:()=>{};}});
 const canvas={width:0,height:0,dataset:{},getContext:()=>context,getBoundingClientRect:()=>({width:393,height:748}),addEventListener(){},removeEventListener(){}};
 const scope={window:{ClubArt:{url:n=>n}},devicePixelRatio:1,document:{hidden:false,body:{dataset:{}},addEventListener(k,fn){listeners.set(k,fn);},removeEventListener(k){listeners.delete(k);}},performance:{now:()=>clock},matchMedia:()=>media,
 Image:class{constructor(){this.complete=true;this.naturalWidth=0;}},ResizeObserver:class{observe(){}disconnect(){}},IntersectionObserver:class{observe(){}disconnect(){}},requestAnimationFrame(fn){frames.set(++id,fn);return id;},cancelAnimationFrame(i){frames.delete(i);}};
 vm.createContext(scope);vm.runInContext(source,scope);return {scope,canvas,frames,listeners,media,api:scope.window.ClubFishingScene,now:()=>clock/1000,draws:()=>draws,step(ms=1000/60){clock+=ms;const batch=[...frames.values()];frames.clear();batch.forEach(fn=>fn(clock));}};
}
const base={id:'synthetic_tension',phase:'playing',mechanic:'tension',hooked_at:0,sim_at:0,deadline:30,input_at:0,holding:false,control:null,tension:.5,progress:.1,danger:0,combo:.2,width:.3,rate:1,fish_power:1,path:{speed:.85,phase:0}};
(async()=>{
 const h=harness(),api=h.api,original=JSON.stringify(base);
 const partial=[.01,.02,.03,.04].map(t=>api.skillFrameProjection(base,t,true).tension);
 assert.ok(partial.every((n,i)=>!i||n>partial[i-1]),'fractional simulation steps must animate between 50ms boundaries');
 assert.equal(api.skillFrameProjection(base,.05,true).tension,api.skillProjection(base,.05,true).tension);
 assert.equal(JSON.stringify(base),original,'visual prediction cannot mutate authoritative state');
 assert.equal(api.skillFrameProjection(base,20,true).tension,api.skillFrameProjection(base,1.1,true).tension,'stale network data has a bounded prediction horizon');
 const almost={...base,progress:.99999};assert.ok(api.skillFrameProjection(almost,.5,true).progress<1,'never visually confirm an unconfirmed catch');assert.equal(api.skillFrameProjection(almost,.5,true).phase,'playing');
 const old={...base,tension:.9,progress:.7},correction={...base,tension:.1,progress:.1};let visual=old;
 for(let i=0;i<120;i++){const next=api.smoothSkillFrame(visual,correction,1/60);assert.ok(Math.abs(next.tension-visual.tension)<=.015000001,'network reconciliation may not snap the marker');visual=next;}
 assert.ok(Math.abs(visual.tension-.1)<.001);assert.equal(api.smoothSkillFrame(old,{...base,id:'next_cast',tension:.2},1/60).tension,.2,'new cast resets the visual');
 for(const reduced of [false,true]){
  const h=harness(reduced),samples=[],r=h.api.create(h.canvas,{skillFrame(d,at){samples.push({at,tension:d.tension});}});
  r.update({mode:'leisure',pending:base,holding:true,control:null,rod:0,now:h.now});for(let i=0;i<60;i++)h.step();
  assert.ok(samples.length>=(reduced?15:55)&&samples.length<=(reduced?21:61),JSON.stringify({reduced,samples:samples.length}));
  assert.ok(h.draws()<=(reduced?21:31),'higher HUD rate must not raise the canvas redraw budget');
  h.scope.document.hidden=true;h.listeners.get('visibilitychange')();const count=samples.length;for(let i=0;i<60;i++)h.step();assert.equal(samples.length,count);assert.equal(h.frames.size,0,'background has no active RAF');
  h.scope.document.hidden=false;h.listeners.get('visibilitychange')();h.step();assert.ok(samples.length>count);
  r.destroy();assert.equal(h.frames.size,0);console.log(JSON.stringify({reduced,hud:samples.length,canvas:h.draws()}));
 }
 const jitter=harness(),jitterSamples=[],jitterScene=jitter.api.create(jitter.canvas,{skillFrame(d,at){jitterSamples.push(at);}});jitterScene.update({mode:'leisure',pending:base,holding:true,control:null,rod:0,now:jitter.now});for(let i=0;i<60;i++)jitter.step(i%2?18:15);assert.ok(jitterSamples.length>=55&&jitterSamples.length<=60,'jittery 15/18ms RAF must not lose every short frame: '+jitterSamples.length);assert.ok(jitter.draws()>=28&&jitter.draws()<=31,'jittery canvas cadence must retain the 30fps budget: '+jitter.draws());jitterScene.destroy();console.log('Jittery RAF HUD updates: '+jitterSamples.length);
 // User input updates presentation synchronously, even while the previous request is pending.
 const scope={window:{},document:{hidden:false,addEventListener(){},removeEventListener(){}},setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){}};
 vm.createContext(scope);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../static/fishing-play.js'),'utf8'),scope);
 let changes=0,requests=0,resolve;const state={pending:{...base,sequence:0}},play=scope.window.ClubFishingPlay.create({id:()=>String(++requests),user:1,state:()=>state,now:()=>.2,control:()=>null,inputChanged(){changes++;},api(){return new Promise(r=>resolve=r);},skill(){},world(){}});
 play.hold(true);const sent=requests;assert.equal(changes,1);play.hold(false);assert.equal(changes,2);assert.equal(play.holding(),false);assert.equal(requests,sent,'render feedback must not add concurrent requests');resolve({skill:{pending:base}});await Promise.resolve();play.destroy();
 console.log('Tension fractional interpolation, bounded corrections, 60/20 HUD, 30/20 canvas, visibility and immediate input: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
