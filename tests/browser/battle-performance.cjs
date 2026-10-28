/* Deterministic synthetic render workload; software GPU measurements are comparative, not device FPS. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const out=path.join(root,'artifacts/battle/performance');fs.mkdirSync(out,{recursive:true});
 const code=process.env.BATTLE_PROFILE_BASE_SHA?spawnSync('git',['show',process.env.BATTLE_PROFILE_BASE_SHA+':static/battle-scene.js'],{cwd:root,encoding:'utf8'}):{status:0,stdout:fs.readFileSync(path.join(root,'static/battle-scene.js'),'utf8')};assert.equal(code.status,0,code.stderr);
 const fixture=spawnSync(process.env.PYTHON||'python',['-c',`import json
from battle_engine import Match,WEAPONS
m=Match(41);m.add(1,'合成玩家');m.start(0,True);m.advance(5)
for i,p in enumerate(m.players.values()):
 p.x=(i%4)*4;p.z=-(i//4)*5;p.y=20;p.slot='rifle';p.weapons={'rifle':30};p.reserve=90
m.loot={i+1:dict(id=i+1,x=(i%8)*3-12,z=-(i//8)*3-8,kind='rifle' if i%3==0 else 'ammo') for i in range(40)}
print(json.dumps(dict(map=m.map,state=m.snapshot(1),weapons=WEAPONS)))`],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(fixture.status,0,fixture.stderr);const data=JSON.parse(fixture.stdout);
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port,tmp=fs.mkdtempSync(path.join(os.tmpdir(),'battle-perf-'));
 const server=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:path.join(tmp,'test.sqlite3'),POKER_MARKET_DATA:'0',PYTHONUTF8:'1'}});let logs='';server.stderr.on('data',d=>logs+=d);server.stdout.on('data',d=>logs+=d);let browser;
 try{
  browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const results=[];
  for(const [device,viewport,touch]of [['desktop',{width:1280,height:720},false],['phone',{width:393,height:852},true]]){
   const context=await browser.newContext({viewport,hasTouch:touch,isMobile:touch,deviceScaleFactor:1});
   const page=await context.newPage();page.setDefaultTimeout(60000);
   await page.route('**/__battle_performance',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/night.css"><script src="/battle.js"></script><div id="app"></div>'}));
   let ready=false;for(let i=0;i<80;i++){try{const r=await context.request.get(base+'/api/bootstrap');if(r.ok()){ready=true;break;}}catch{}await sleep(100);}assert.ok(ready,logs);
   await page.route('**/battle-scene.js',r=>r.fulfill({contentType:'text/javascript',body:code.stdout}));
   await page.goto(base+'/__battle_performance');
   const result=await page.evaluate(async({data,device,frames})=>{
    document.getElementById('app').innerHTML=ClubBattle.view();const root=document.getElementById('battle-console');root.classList.add('battle-active');document.documentElement.classList.add('island-active');root.querySelector('[data-battle-entry]').hidden=true;root.querySelector('[data-battle-hud]').hidden=false;root.querySelector('[data-battle-touch]').hidden=false;
    const {IslandScene}=await import('/battle-scene.js');const scene=new IslandScene(root,{action(){},pause(){}});scene.renderer.setAnimationLoop(null);scene.weapons=data.weapons;scene.setMap(data.map);scene.active=true;scene.pause(false);
    const gl=scene.renderer.getContext(),nativeBuffer=gl.createBuffer;let buffers=0;gl.createBuffer=function(...args){buffers++;return nativeBuffer.apply(this,args);};let time=performance.now(),sample=0;const phases=[];
    for(const phase of ['drop','move','fire']){
     const state=structuredClone(data.state);state.phase=phase==='drop'?'drop':'playing';state.clock=12;state.drop_left=4;
     for(const p of state.players){p.y=phase==='drop'?20:0;p.animation=phase==='drop'?'drop':'run';p.vz=phase==='drop'?0:-4.5;}
     scene.update(state);for(let i=0;i<3;i++){time=Math.max(performance.now(),time+34);scene.frame(time);gl.finish();}
     const timings=[],calls=[],startBuffers=buffers;
     for(let i=0;i<frames;i++){
      scene.yaw+=.035;scene.stick.y=phase==='drop'?0:-1;scene.input();if(i%3===0){state.clock+=.15;state.drop_left=Math.max(0,state.drop_left-.15);for(const p of state.players){if(phase==='drop')p.y=Math.max(0,p.y-.73);else p.z-=.675;}scene.update(state);}
      if(phase==='fire')for(const id of [1,2,3,4])scene.effect({kind:'shot',player:id,start:[0,1,0],end:[20,1,-30]});
      time=Math.max(performance.now(),time+34);const at=performance.now();scene.frame(time);gl.finish();timings.push(performance.now()-at);calls.push(scene.renderer.info.render.calls);sample++;
     }
     timings.sort((a,b)=>a-b);phases.push({phase,frames,frameP50:timings[Math.floor(timings.length*.5)],frameP95:timings[Math.min(timings.length-1,Math.floor(timings.length*.95))],maxDrawCalls:Math.max(...calls),gpuBufferAllocations:buffers-startBuffers,geometries:scene.renderer.info.memory.geometries});
    }
    const world=scene.world.children[0],yaw=scene.yaw,at=performance.now();scene.setMap(data.map);const reuse={sameWorld:scene.world.children[0]===world,sameYaw:scene.yaw===yaw,ms:performance.now()-at};
    let motion;if(scene.coverGrid){
     const state=structuredClone(data.state);state.phase='playing';state.self.slot='rifle';state.self.weapons={rifle:30};for(const p of state.players){p.y=0;p.vx=0;p.vz=0;p.animation='idle';}scene.update(state);let collisionParity=true;for(let x=-300;x<=300;x+=20)for(let z=-300;z<=300;z+=20){const full=Math.hypot(x,z)<=scene.map.radius-.5&&!scene.map.cover.some(b=>1.8>b.y-b.h/2&&0<b.y+b.h/2&&Math.abs(x-b.x)<b.w/2+.45&&Math.abs(z-b.z)<b.d/2+.45);if(scene.safe(x,z,0)!==full)collisionParity=false;}scene.control.jump=true;scene.input(false);const preservedJump=scene.input().jump;scene.coverGrid.clear();scene.correction.set(0,0,0);scene.ownPosition.set(state.players[0].x,0,state.players[0].z);scene.stick.y=-1;
     const initial=scene.ownPosition.clone();for(let i=0;i<10;i++){time+=34;scene.lastSnapshot=performance.now();scene.frame(time);}const moved=scene.ownPosition.distanceTo(initial);scene.clearInput();const stopped=scene.ownPosition.clone();for(let i=0;i<10;i++){time+=34;scene.frame(time);}const idlePullback=scene.ownPosition.distanceTo(stopped);
     const actor=scene.actors.get(state.self.id),head=actor.group.position.clone().add(new (scene.cameraTarget.constructor)(0,1.65,0));scene.camera.updateMatrixWorld(true);const before=head.clone().project(scene.camera);scene.yaw+=.8;time+=34;scene.frame(time);scene.camera.updateMatrixWorld(true);const after=head.clone().project(scene.camera);const orbitShift=Math.abs(before.x-after.x);
     const ammo=scene.state.self.weapons.rifle,parts=actor.parts.length;scene.localAmmo=ammo;scene.localNextShot=0;scene.previewShot();const immediateFlash=actor.flashFrames>0,unchangedAmmo=scene.state.self.weapons.rifle===ammo;for(let i=0;i<24;i++)scene.effect({kind:'explosion',x:i,y:0,z:0});time+=34;scene.frame(time);scene.effect({kind:'hit',player:state.self.id});const damageStarted=scene.damage.getAnimations().length===1;await new Promise(r=>setTimeout(r,350));const damageFaded=getComputedStyle(scene.damage).opacity==='0';scene.effect({kind:'hit',player:state.self.id});const damageRestarts=scene.damage.getAnimations().length===1;scene.clearTransient();motion={damageStarted,damageFaded,damageRestarts,collisionParity,preservedJump,moved,idlePullback,orbitShift,immediateFlash,unchangedAmmo,parts,explosionPool:scene.explosions.length};
    }
    scene.destroy();return {device,phases,reuse,motion};
   },{data,device,frames:Number(process.env.BATTLE_PROFILE_FRAMES||8)});
   if(!process.env.BATTLE_PROFILE_BASE_SHA){assert.ok(result.reuse.sameWorld&&result.reuse.sameYaw,'Reconnect must preserve the map and look direction');for(const phase of result.phases){assert.ok(phase.maxDrawCalls<80,'Bound multi-player draw calls');assert.equal(phase.gpuBufferAllocations,0,'No steady-state GPU buffer allocation');}assert.ok(result.motion.moved>.8,'Prediction must move before a server update');assert.ok(result.motion.idlePullback<.02,'A stale snapshot must not drag a stopped player backwards');assert.ok(result.motion.orbitShift<.05,'One-frame camera turn must keep the avatar framing stable');assert.ok(result.motion.immediateFlash&&result.motion.unchangedAmmo,'Local visual feedback cannot alter authoritative ammunition');assert.equal(result.motion.explosionPool,6);assert.ok(result.motion.damageStarted&&result.motion.damageFaded&&result.motion.damageRestarts,'Damage feedback must restart and fade without a forced layout');assert.ok(result.motion.collisionParity,'Spatial lookup must preserve full-map collision results');assert.ok(result.motion.preservedJump,'Rendering cannot consume a queued jump');}
   results.push(result);await context.close();
  }
  const label=process.env.BATTLE_PROFILE_LABEL||'current';assert.match(label,/^[a-z0-9-]+$/);const report={sourceHash:crypto.createHash('sha256').update(code.stdout).digest('hex'),scope:'Synthetic scene with 16 actors / 40 supplies / four concurrent shooters; visibility varies with viewport. Chromium SwiftShader, viewport DPR 1, GPU completion measured. Not physical-device FPS.',results};fs.writeFileSync(path.join(out,label+'.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser?.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
