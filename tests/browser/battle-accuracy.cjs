/* Actual two-client moving firefight through an isolated server, with 90 ms each-way transport delay.
 * Deterministic zero spread isolates hit registration; no production accounts or game outcomes. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/battle/accuracy'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 fs.mkdirSync(out,{recursive:true});const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port,tmp=fs.mkdtempSync(path.join(os.tmpdir(),'battle-accuracy-'));
 const driver=`import runpy,battle_engine,os,json
battle_engine.make_map=lambda seed:dict(seed=seed,radius=355,structures=[],cover=[])
original=battle_engine.Match.start
def start(self,clock,bots=True):
 original(self,clock,False)
 self.rng.gauss=lambda *_:0
 for i,p in enumerate(self.players.values()):
  p.x=1.05*i;p.z=-15*i;p.yaw=0;p.pitch=0;p.slot='rifle';p.weapons={'rifle':30};p.reserve=90
battle_engine.Match.start=start
if os.environ.get('BATTLE_ACCURACY_DIAGNOSTIC'):
 shoot=battle_engine.Match.shoot
 def diagnostic(self,p,pending=None):
  ammo=p.weapons.get(p.slot);target=next((q for q in self.players.values() if q.id!=p.id),None);health=target.hp if target else 0
  shoot(self,p,pending)
  if ammo!=p.weapons.get(p.slot):print('accuracy_shot '+json.dumps(dict(clock=self.clock,view=p.intent.get('view_at'),age=self.clock-p.intent.get('view_at',self.clock),point=p.intent.get('aim_point'),origin=(p.x,p.y,p.z),target=self.target_pose(target,p.intent.get('view_at')),current=(target.x,target.y,target.z),hit=target.hp<health)),flush=True)
 battle_engine.Match.shoot=diagnostic
runpy.run_path('server.py',run_name='__main__')`;
 const proc=spawn(process.env.PYTHON||'python',['-c',driver,'--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,BATTLE_ACCURACY_DIAGNOSTIC:'1',PYTHONUTF8:'1',POKER_DB:path.join(tmp,'isolated.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_MARKET_DATA:'0',POKER_PUBLIC_ORIGIN:''}});let logs='',browser;proc.stdout.on('data',d=>logs+=d);proc.stderr.on('data',d=>logs+=d);
 try{
  browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const results=[];let rootInvite='';
  for(const compensation of (process.env.BATTLE_ACCURACY_DIAGNOSTIC?[true]:[true,false])){
   const aContext=await browser.newContext({viewport:{width:1280,height:720}}),bContext=await browser.newContext({viewport:{width:844,height:390},isMobile:true,hasTouch:true});
   const api=async(c,url,data)=>{const r=data===undefined?await c.request.get(base+url):await c.request.post(base+url,{headers:{'X-Requested-With':'PokerClub'},data});assert.equal(r.status(),200,url+' '+await r.text());return r.json();};
   let ready=false;for(let i=0;i<80;i++){try{await api(aContext,'/api/bootstrap');ready=true;break;}catch{}await sleep(100);}assert.ok(ready,logs);
   const suffix=compensation?'with':'without';await api(aContext,'/api/register',{username:'accuracy_a_'+suffix,nickname:'精準甲',password:'SyntheticPreview123',invite_code:rootInvite});const invite=(await api(aContext,'/api/state')).invite_code;rootInvite=invite;await api(bContext,'/api/register',{username:'accuracy_b_'+suffix,nickname:'精準乙',password:'SyntheticPreview123',invite_code:invite});
   const created=await api(aContext,'/api/battle/create',{title:'移動命中隔離測試',bots:false});await api(bContext,'/api/battle/join',{code:created.code});
   await aContext.addInitScript(({compensation})=>{const Native=WebSocket;window.WebSocket=class extends Native{constructor(...args){super(...args);this.delayed=String(args[0]).includes('/api/battle/socket');if(this.delayed)super.addEventListener('message',e=>setTimeout(()=>this.handler?.call(this,e),90));}set onmessage(value){if(this.delayed)this.handler=value;else super.onmessage=value;}get onmessage(){return this.delayed?this.handler:super.onmessage;}send(value){if(!this.delayed)return super.send(value);let message=JSON.parse(value);if(!compensation&&message.type==='input'){delete message.view_at;delete message.view_tick;}const data=JSON.stringify(message);setTimeout(()=>{if(this.readyState===Native.OPEN)super.send(data);},90);}};},{compensation});
   const a=await aContext.newPage(),b=await bContext.newPage(),states=new Map(),errors=[],events=new Map();let source;
   for(const page of [a,b]){page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(page===a&&r.url().includes('/battle-scene.js?'))source=r.url();});page.on('websocket',ws=>{if(!ws.url().includes('/api/battle/socket'))return;ws.on('framereceived',frame=>{const v=JSON.parse(frame.payload.toString());if(v.type==='state'){states.set(page,v);if(page===a)for(const e of v.events||[])events.set(e.id,e);}});});await page.goto(base+'/#battle');await page.waitForSelector('[data-battle-resume]:visible');await page.waitForSelector('[data-battle-join]:enabled');await page.locator('[data-battle-resume]').click();await page.waitForSelector('[data-battle-waiting]:visible');}
   // Track after beforeFrame drains snapshots and interpolation presents this frame.
   // A pre-frame tracker aims one frame behind on a slow software GPU, testing its own error.
   await a.evaluate(async url=>{const {IslandScene}=await import(url),updateAimPoint=IslandScene.prototype.updateAimPoint;IslandScene.prototype.updateAimPoint=function(follow,direction){window.__accuracyScene=this;if(window.__trackAccuracy&&this.state?.phase==='playing'){const target=[...this.actors.values()].find(x=>x.id!==this.state.self.id&&x.group.visible);if(target){const point=target.group.position.clone();point.y+=1.34;direction.copy(point).sub(this.camera.position).normalize();this.yaw=Math.atan2(direction.x,-direction.z);this.pitch=Math.asin(direction.y)-(this.recoil||0);this.toggles.aim=true;this.camera.lookAt(point);this.camera.updateMatrixWorld(true);const projected=point.clone().project(this.camera);window.__accuracyTrackError=Math.max(window.__accuracyTrackError||0,Math.hypot(projected.x,projected.y));}}return updateAimPoint.call(this,follow,direction);};},source);
   await a.locator('[data-battle-start]:enabled').click();for(let i=0;i<200&&states.get(b)?.phase!=='playing';i++)await sleep(100);assert.equal(states.get(b)?.phase,'playing');await a.waitForFunction(()=>window.__accuracyScene?.state?.phase==='playing');
   await a.evaluate(()=>window.__trackAccuracy=true);await b.keyboard.down('KeyD');await sleep(900);await a.keyboard.down('KeyW');await sleep(250);await a.screenshot({path:path.join(out,suffix+'-before-fire.png')});events.clear();const ammo=states.get(a).self.weapons.rifle,shooter=states.get(a).self.id;await a.keyboard.down('KeyF');
   for(let i=0;i<35;i++){await sleep(100);const fired=[...events.values()].filter(e=>e.kind==='shot'&&e.player===shooter);if(fired.length>=6)break;if(states.get(a).phase==='finished')break;}
   await a.keyboard.up('KeyF');await a.keyboard.up('KeyW');await b.keyboard.up('KeyD');await sleep(500);const hits=[...events.values()].filter(e=>e.kind==='hit'&&e.by===shooter),shots=[...events.values()].filter(e=>e.kind==='shot'&&e.player===shooter);
   const trackError=await a.evaluate(()=>window.__accuracyTrackError||0);assert.ok(trackError<.001,'Test tracker must center the presented target');const result={compensation,transportDelayEachWayMs:90,spread:'zero, test only',trackError,shots:shots.length,hits:hits.length,damage:hits.reduce((n,e)=>n+e.damage,0),ammoSpent:ammo-states.get(a).self.weapons.rifle,errors};results.push(result);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(result));assert.equal(errors.length,0,errors.join('\n'));if(compensation)assert.ok(hits.length>=2&&hits.length/Math.max(1,shots.length)>=.6,JSON.stringify(result));
   await api(aContext,'/api/battle/leave',{});await api(bContext,'/api/battle/leave',{});await aContext.close();await bContext.close();
  }
  if(results.length===2)assert.ok(results[0].hits>results[1].hits,'Compensated moving shots must improve on the same delayed view without compensation');fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({movingFirefight:results}));
 }finally{await browser?.close();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
