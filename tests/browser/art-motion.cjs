/* Real component renderers + normal WAAPI animation, isolated synthetic accounts. */
const {chromium,webkit}=require('playwright');
const {spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/art-motion'),pause=ms=>new Promise(r=>setTimeout(r,ms));
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
(async()=>{
 fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-art-')),address='http://127.0.0.1:'+await port();
 const proc=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',new URL(address).port],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:path.join(tmp,'isolated.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 let logs='',serial=0,invite;const browsers=[],errors=[],checks=[];proc.stdout.on('data',x=>logs+=x);proc.stderr.on('data',x=>logs+=x);
 try{
  browsers.push(['chromium',await chromium.launch({headless:true})],['webkit',await webkit.launch({headless:true})]);
  const api=async(c,p,data)=>{const r=data?await c.request.post(address+p,{headers:{'X-Requested-With':'PokerClub'},data}):await c.request.get(address+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
  const ready=await browsers[0][1].newContext();for(let i=0;i<100;i++){try{await api(ready,'/api/bootstrap');break;}catch{await pause(100);}}await ready.close();
  async function account(browser,mobile){const c=await browser.newContext({viewport:{width:mobile?393:1366,height:mobile?660:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'no-preference'});const n=++serial;await api(c,'/api/register',{username:'art_motion_'+n,nickname:'圖片測試'+n,password:'SyntheticArtMotion123',invite_code:invite});if(!invite)invite=(await api(c,'/api/state')).invite_code;return c;}
  async function open(c,requests){const p=await c.newPage();if(requests)p.on('request',r=>requests.push(r.url()));p.on('pageerror',e=>errors.push(e.message));await p.goto(address+'/#lobby');await p.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);return p;}
  async function model(c,game){const x=await api(c,'/api/online/rooms',{game_type:game,buy_in:1000,stake:20,operation_id:crypto.randomUUID()}),r=await api(c,'/api/online/rooms/'+x.id);await api(c,'/api/online/rooms/'+x.id+'/leave',{operation_id:crypto.randomUUID()});return r;}
  async function fixture(page,r,value,animate=true,waitReady=true){return page.evaluate(async({r,value,animate,waitReady})=>{
   const prior=structuredClone(r);prior.hand={id:'prior',phase:'dice'};
   r.hand={id:'fixture-'+Math.random(),phase:'showdown',results:[],players:[],summary:'合成動畫檢查',reels:[value,value,value],dice:[value,value,value],game_settings:r.next_game_settings,slot_payout_version:3,selected:[0],hazards:r.game_type==='tower'?Array.from({length:6},()=>[1]):[1],steps:1,returns:[],bomb_counts:[1,1,1,1,1,1]};r.status='waiting';
   const template=document.createElement('template');template.innerHTML='<section id="art-fixture" class="arcade-table arcade-'+r.game_type+'">'+ClubBonus.board(r,me(),card)+'</section>';
   const current=document.querySelector('#art-fixture');if(current)patchNode(current,template.content.firstElementChild);else dialog(template.innerHTML);
   const host=document.querySelector('#art-fixture');ClubArt.prepare(r.game_type);const decoded=Promise.all([...host.querySelectorAll('.current-art')].map(ClubArt.ready));if(waitReady)await decoded;
   if(animate){ClubBonus.prepare(prior,r);ClubBonus.play();}
   return {images:host.querySelectorAll('.current-art').length,legacy:host.querySelectorAll('svg.sym,.mj-symbol').length};
  },{r,value,animate,waitReady});}
  for(const [engine,browser] of browsers)for(const mobile of [true,false]){
   const c=await account(browser,mobile),requested=[],page=await open(c,requested);
   assert.equal(await page.locator('link[rel=stylesheet]').count(),1);
   assert.equal(await page.locator('.game-art svg').count(),0);
   assert.equal(await page.locator('.game-art>.current-art').count(),11);
   assert.equal(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches),false);
   const models={slot:await model(c,'slot'),dice:await model(c,'dice')};
   assert.equal(requested.filter(u=>/\/assets\/pieces\/(?:slot-|dice-)/.test(u)).length,0,'Lobby must not preload unrelated game pieces');
   let frames=0;
   for(const game of ['slot','dice'])for(const value of game==='slot'?[0,0,1,2,3,4,5,5]:[1,1,2,3,4,5,6,6]){
    const result=await fixture(page,models[game],value);assert.equal(result.images,3);assert.equal(result.legacy,0);
    await page.waitForFunction(()=>document.querySelector('#art-fixture').getAnimations({subtree:true}).length>=3);
    await page.evaluate(()=>{window.artTracks=document.querySelector('#art-fixture').getAnimations({subtree:true});artTracks.forEach(a=>a.pause());});
    for(const time of [0,40,120,250,500,900]){
     const f=await page.evaluate(async time=>{artTracks.forEach(a=>a.currentTime=time);await new Promise(r=>requestAnimationFrame(r));const h=document.querySelector('#art-fixture');return {legacy:h.querySelectorAll('svg.sym,.mj-symbol').length,images:[...h.querySelectorAll('.current-art')].map(i=>({src:i.getAttribute('src'),decoded:i.complete&&i.naturalWidth>0,failed:i.hasAttribute('data-art-failed'),loading:i.hasAttribute('data-art-loading')})),extra:[...h.querySelectorAll('.slot-reel>span,.die-face')].map(e=>getComputedStyle(e,'::after').content)};},time);
     assert.equal(f.legacy,0);assert.ok(f.images.every(i=>i.decoded&&!i.failed&&!i.loading));assert.ok(f.extra.every(x=>x==='none'||x==='normal'),'No legacy cover layer during animation');
     if(value===(game==='slot'?0:1)&&[0,250,900].includes(time))await page.locator('#art-fixture').screenshot({path:path.join(out,`${engine}-${mobile?'phone':'desktop'}-${game}-${time}.png`)});
     frames++;
    }
    await page.evaluate(()=>ClubBonus.cancel());
   }
   for(const game of ['mines','tower']){
    const r=await model(c,game),v=await fixture(page,r,0,false);assert.equal(v.images,game==='mines'?25:24);assert.equal(v.legacy,0);
    const inside=await page.locator('#art-fixture .risk-cell>.current-art').evaluateAll(imgs=>imgs.every(i=>{const a=i.getBoundingClientRect(),b=i.parentElement.getBoundingClientRect();return a.left>=b.left&&a.right<=b.right&&a.top>=b.top&&a.bottom<=b.bottom;}));assert.ok(inside,'Risk artwork escaped its tile');
    assert.equal(await page.locator('#art-fixture .risk-cell>span').count(),0);
    await page.locator('#art-fixture').screenshot({path:path.join(out,`${engine}-${mobile?'phone':'desktop'}-${game}.png`)});
   }
   checks.push({engine,mobile,frames,risk_pieces:49});await c.close();
  }
  // Cold loading and failure use a fresh context so no warm memory cache hides problems.
  for(const [engine,browser] of browsers){
   const c=await account(browser,true),p=await open(c),r=await model(c,'dice');
   await p.route('**/assets/pieces/dice-*.webp*',async route=>{await pause(180);await route.continue();});
   await fixture(p,r,3,false,false);assert.ok(await p.locator('#art-fixture .current-art[data-art-loading]').count()>0,'Cold image must use current placeholder');await p.waitForFunction(()=>[...document.querySelectorAll('#art-fixture .current-art')].every(i=>i.complete&&i.naturalWidth&&!i.hasAttribute('data-art-loading')));assert.equal(await p.locator('#art-fixture .current-art').count(),3);assert.equal(await p.locator('#art-fixture svg').count(),0);await c.close();
   const bad=await account(browser,true),q=await open(bad),broken=await model(bad,'dice');await q.route('**/assets/pieces/dice-*.webp*',route=>route.abort());
   await fixture(q,broken,4,false);assert.equal(await q.locator('#art-fixture .current-art[data-art-failed]').count(),3);assert.equal(await q.locator('#art-fixture svg').count(),0);
   const state=await q.evaluate(()=>{const h=document.querySelector('.die-face'),next=h.cloneNode(true);next.querySelector('img').removeAttribute('data-art-failed');next.querySelector('img').setAttribute('data-art-loading','');patchNode(h,next);return {failed:h.querySelector('img').hasAttribute('data-art-failed'),text:getComputedStyle(h,'::after').content};});
   assert.ok(state.failed&&state.text.includes('4 點'),'Failed image state must survive an ordinary DOM update');
   await q.unroute('**/assets/pieces/dice-*.webp*');await fixture(q,broken,5,false);assert.equal(await q.locator('#art-fixture .current-art[data-art-failed]').count(),0);await bad.close();
   checks.push({engine,cold_load:true,failed_load:true,recovery:true});
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors,scope:'Real renderers, normal animation; isolated synthetic accounts and presentation fixtures, no live games'},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{for(const [,b] of browsers)await b.close();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
