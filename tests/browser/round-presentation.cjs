/* Real commands, receipts and presentation on isolated accounts. Never uses production. */
const {chromium,webkit}=require('playwright'),{spawn}=require('child_process'),fs=require('fs'),path=require('path'),os=require('os'),net=require('net'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/round-presentation'),pause=ms=>new Promise(r=>setTimeout(r,ms));
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const n=s.address().port;await new Promise(r=>s.close(r));return n;}
(async()=>{
 fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'round-presentation-')),base='http://127.0.0.1:'+await port();
 const server=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',new URL(base).port],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8',POKER_DB:path.join(tmp,'isolated.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:''}});
 let logs='',invite,serial=0;const browsers=[],checks=[],errors=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 const api=async(c,p,d)=>{const r=d?await c.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data:d}):await c.request.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
 try{
  for(const [engine,driver] of [['chromium',chromium],['webkit',webkit]]){
   const browser=await driver.launch({headless:true});browsers.push(browser);
   for(const mobile of [true,false])for(const game of ['roulette','slot']){
    const context=await browser.newContext({viewport:{width:mobile?393:1366,height:mobile?852:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'no-preference'});
    for(let i=0;i<100;i++){try{await api(context,'/api/bootstrap');break;}catch{await pause(100);}}
    const id=++serial;await api(context,'/api/register',{username:'round_present_'+id,nickname:'轉動測試'+id,password:'SyntheticRound123',invite_code:invite});if(!invite)invite=(await api(context,'/api/state')).invite_code;
    const room=await api(context,'/api/online/rooms',{game_type:game,name:'轉動測試',buy_in:1000,stake:10,operation_id:crypto.randomUUID()}),page=await context.newPage(),posts=[];
    page.on('pageerror',e=>errors.push(engine+' '+game+': '+e.message));
    page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/'+room.id+'/start'))posts.push(r.postDataJSON());});
    await page.goto(base+'/#table/'+room.id);await page.waitForFunction(()=>typeof room!=='undefined'&&room&&liveReady);
    const delayed=mobile;
    if(delayed)await page.evaluate(()=>live.close());
    await page.route('**/api/online/rooms/'+room.id+'/start',async route=>{if(!delayed)await pause(600);const response=await route.fetch();if(delayed)await pause(1800);await route.fulfill({response});});
    const before=await page.evaluate(()=>({number:room.hand_no,now:performance.now()}));
    const click=game==='slot'?'#deal-hand':'#roulette-confirm';if(game==='roulette')await page.locator('[data-roulette="red"]').click();
    await page.locator(click).click();await page.locator(click).evaluate(b=>{b.click();b.click();});
    await page.waitForFunction(()=>ClubRoundPresentation.masked(room));
    const started=await page.evaluate(()=>({elapsed:performance.now(),caption:ClubRoundPresentation.caption(room),running:document.getAnimations().filter(a=>a.effect?.target?.closest('.roulette-wheel,.slot-reels')).length}));
    assert.ok(started.running>=3,'Click must begin motion before any outcome');
    const target=game==='slot'?'.slot-track':'.roulette-wheel.is-spinning .roulette-rotor';
    const first=await page.locator(target).first().evaluate(e=>getComputedStyle(e).transform);await pause(120);assert.notEqual(await page.locator(target).first().evaluate(e=>getComputedStyle(e).transform),first,'Visual must actually move');
    await page.waitForFunction(n=>room.hand_no>n&&!busy&&!pendingOperation,before.number);
    assert.ok(await page.evaluate(()=>ClubRoundPresentation.masked(room)),'Receipt must not expose result early');
    if(game==='roulette'){assert.equal(await page.locator('.roulette-stage h2').innerText(),'轉盤運轉中…');assert.ok((await page.locator('.roulette-wheel .wheel-hub').allTextContents()).every(x=>x==='♠'));}
    else{assert.equal(await page.locator('.slot-track').count(),3);assert.doesNotMatch(await page.locator('.slot-machine p[role=status]').innerText(),/總返還|未中獎|三連/);}
    await page.evaluate(()=>applyState(structuredClone(room),true,false,'duplicate-check'));
    assert.ok(await page.evaluate(()=>ClubRoundPresentation.masked(room)),'Duplicate snapshot must not cancel the presentation');
    await page.screenshot({path:path.join(out,`${engine}-${mobile?'phone':'desktop'}-${game}-spinning.png`)});
    await page.waitForFunction(()=>!ClubRoundPresentation.masked(room),null,{timeout:9000});
    const settled=await page.evaluate(()=>({number:room.hand.number,reels:room.hand.reels,hand:room.hand_no,total:room.wallet.total,at:performance.now()}));
    assert.ok(settled.at-before.now>=(game==='slot'?3000:4200),'Normal animation should not finish immediately');
    if(game==='roulette')assert.ok((await page.locator('.roulette-wheel .wheel-hub').allTextContents()).every(x=>x===String(settled.number)));
    else{assert.equal(await page.locator('.slot-track').count(),0);const src=await page.locator('.slot-reel>span>.current-art').evaluateAll(a=>a.map(i=>i.getAttribute('src')));const names=['777','crown','diamond','bell','cherry','bar'];assert.deepEqual(src.map(s=>s.split('?')[0].split('/').at(-1)),settled.reels.map(n=>'slot-'+names[n]+'.webp'));}
    assert.equal(posts.length,1);assert.equal(settled.hand,before.number+1);
    const replay=await api(context,'/api/online/rooms/'+room.id+'/start',posts[0]);assert.equal(replay.state.hand_no,settled.hand);assert.equal(replay.state.wallet.total,settled.total,'Receipt replay must not debit again');
    await page.evaluate(()=>applyState(structuredClone(room),true,false,'reconnect-check'));assert.equal(await page.evaluate(()=>ClubRoundPresentation.stage(room)),'idle');
    await page.screenshot({path:path.join(out,`${engine}-${mobile?'phone':'desktop'}-${game}-result.png`)});
    // A second confirmed round can be skipped without another POST or debit.
    await page.unroute('**/api/online/rooms/'+room.id+'/start');
    if(game==='roulette')await page.locator('[data-roulette="red"]').click();await page.locator(click).click();await page.waitForFunction(n=>room.hand_no>n&&!busy&&!pendingOperation,settled.hand);await page.locator('[data-skip-reveal]').click();
    assert.equal(await page.evaluate(()=>ClubRoundPresentation.stage(room)),'idle');assert.equal(posts.length,2);
    await page.locator('[data-fast-reveal]').check();
    if(game==='roulette')await page.locator('[data-roulette="red"]').click();await page.locator(click).click();await page.waitForFunction(n=>room.hand_no>n&&!busy&&!pendingOperation,settled.hand+1);assert.equal(await page.evaluate(()=>ClubRoundPresentation.stage(room)),'idle');assert.equal(posts.length,3);
    await page.locator('[data-fast-reveal]').uncheck();
    await page.route('**/api/online/rooms/'+room.id+'/start',async route=>{await pause(600);await route.continue();});
    if(game==='roulette')await page.locator('[data-roulette="red"]').click();await page.locator(click).click();
    await page.evaluate(()=>{window.testHidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>testHidden});Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>testHidden?'hidden':'visible'});document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForFunction(n=>room.hand_no===n&&!busy&&!pendingOperation,settled.hand+3);
    await page.evaluate(()=>{testHidden=false;document.dispatchEvent(new Event('visibilitychange'));});await pause(250);
    assert.equal(await page.evaluate(()=>ClubRoundPresentation.stage(room)),'idle','Returning from background must not replay a retired operation');assert.equal(posts.length,4);
    checks.push({engine,mobile,game,verification_first:delayed,real_motion:true,delayed_reveal:true,duplicate_snapshot:true,receipt_replay:true,skip:true,fast:true,rapid_clicks:true,background_return:true});
    await context.close();
   }
  }
  // Two real roulette players share the outcome and each sees a full reveal.
  const shared=[];
  for(let i=0;i<2;i++){
   const c=await browsers[0].newContext({viewport:{width:1366,height:900},reducedMotion:'no-preference'});serial++;await api(c,'/api/register',{username:'shared_wheel_'+serial,nickname:'同桌測試'+i,password:'SyntheticRound123',invite_code:invite});shared.push(c);
  }
  const room=await api(shared[0],'/api/online/rooms',{game_type:'roulette',name:'共用輪盤測試',buy_in:1000,stake:10,operation_id:crypto.randomUUID()});
  await api(shared[1],'/api/online/rooms/'+room.id+'/join',{buy_in:1000,seat:1,operation_id:crypto.randomUUID()});
  const pages=[];for(const c of shared){const p=await c.newPage();pages.push(p);p.on('pageerror',e=>errors.push(e.message));await p.goto(base+'/#table/'+room.id);await p.waitForFunction(()=>typeof room!=='undefined'&&room&&liveReady);}
  await pages[0].locator('[data-roulette="red"]').click();await pages[0].locator('#roulette-confirm').click();await pages[0].waitForFunction(()=>room.status==='playing'&&!busy&&!pendingOperation);
  await pages[1].waitForFunction(()=>room.status==='playing');await pages[1].locator('[data-roulette="black"]').click();await pages[1].locator('#roulette-confirm').click();
  for(const p of pages){await p.waitForFunction(()=>room.hand?.phase==='showdown');assert.ok(await p.evaluate(()=>ClubRoundPresentation.masked(room)));}
  const numbers=[];for(const p of pages){await p.waitForFunction(()=>!ClubRoundPresentation.masked(room),null,{timeout:9000});numbers.push(await p.evaluate(()=>room.hand.number));}assert.equal(numbers[0],numbers[1]);
  checks.push({shared_roulette:true,players:2,matching_result:true});
  // Production card renderer and CSS, with actual decoded selected artwork.
  const p=pages[0];await p.evaluate(()=>live.close());
  for(const mobile of [false,true]){
   await p.setViewportSize({width:mobile?393:1366,height:900});
   await p.evaluate(async mobile=>{
    document.querySelector('#friend-card-fixture')?.remove();const host=document.createElement('section');host.id='friend-card-fixture';host.className='panel';host.style.cssText='display:flex;flex-wrap:wrap;gap:8px;padding:16px;background:#e9dcc1';host.innerHTML=card('Ks')+card('Qh')+card('Jc')+card(null);document.querySelector('#main').prepend(host);for(const c of host.children)c.style.cssText='width:'+(mobile?76:140)+'px;height:'+(mobile?114:210)+'px;transform:none';
    await Promise.all(['card-k','card-q','card-j','card-back-friends'].map(async n=>{const im=new Image();im.src=ClubArt.url('pieces/'+n+'.webp');await im.decode();}));await document.fonts.ready;
   },mobile);
   const artwork=await p.evaluate(()=>[...document.querySelectorAll('#friend-card-fixture .playing-card[data-rank]')].map(e=>getComputedStyle(e,'::before').backgroundImage));assert.ok(artwork.every((s,i)=>s.includes(['card-k.webp','card-q.webp','card-j.webp'][i])));
   const back=await p.evaluate(()=>getComputedStyle(document.querySelector('#friend-card-fixture .covered')).backgroundImage);assert.ok(back.includes('card-back-friends.webp'));
   const flight=await p.evaluate(()=>{const t=document.createElement('template');t.innerHTML=card(null);const g=t.content.firstElementChild;document.querySelector('#deal-layer').append(g);const b=getComputedStyle(g).backgroundImage;g.remove();return b;});assert.ok(flight.includes('card-back-friends.webp'),'Flight must use the same current back');
   await p.locator('#friend-card-fixture').screenshot({path:path.join(out,'friends-cards-'+(mobile?'phone':'desktop')+'.png')});
  }
  await p.evaluate(()=>document.documentElement.dataset.cardBack='jade');assert.ok(!(await p.locator('#friend-card-fixture .covered').evaluate(e=>getComputedStyle(e).backgroundImage)).includes('card-back-friends.webp'));const sameBack=await p.evaluate(()=>{const t=document.createElement('template');t.innerHTML=card(null);const g=t.content.firstElementChild;document.querySelector('#deal-layer').append(g);const same=getComputedStyle(g).backgroundImage===getComputedStyle(document.querySelector('#friend-card-fixture .covered')).backgroundImage;g.remove();return same;});assert.ok(sameBack,'Equipped back must also match during dealing');checks.push({friends_deck:true,desktop:true,phone:true,collectible_back:true});
  for(const c of shared)await c.close();
  // An unconfirmed operation pauses visual work, then retries the same receipt.
  const uncertain=await browsers[0].newContext({viewport:{width:393,height:852},isMobile:true,hasTouch:true,reducedMotion:'no-preference'});serial++;
  await api(uncertain,'/api/register',{username:'uncertain_spin_'+serial,nickname:'確認測試',password:'SyntheticRound123',invite_code:invite});
  const ur=await api(uncertain,'/api/online/rooms',{game_type:'slot',buy_in:1000,stake:10,operation_id:crypto.randomUUID()}),up=await uncertain.newPage(),attempts=[];
  up.on('pageerror',e=>errors.push(e.message));up.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/'+ur.id+'/start'))attempts.push(r.postDataJSON().operation_id);});
  await up.goto(base+'/#table/'+ur.id);await up.waitForFunction(()=>typeof room!=='undefined'&&room&&liveReady);
  await up.route('**/api/online/rooms/'+ur.id+'/start',r=>r.abort());await up.locator('#deal-hand').click();
  await up.waitForFunction(()=>ClubRoundPresentation.stage(room)==='confirming',null,{timeout:12000});assert.equal(await up.locator('.slot-track').count(),0);assert.equal(await up.locator('.slot-await').count(),3);
  assert.match(await up.locator('.slot-machine p[role=status]').innerText(),/仍在確認/);
  await up.unroute('**/api/online/rooms/'+ur.id+'/start');await up.locator('#retry-operation').click();await up.waitForFunction(()=>room.hand_no===1&&!busy&&!pendingOperation);await up.locator('[data-skip-reveal]').click();
  assert.equal(new Set(attempts).size,1,'Retries must retain the original operation id');assert.equal(await up.evaluate(()=>room.hand_no),1);checks.push({uncertain_wait:true,visual_work_pauses:true,same_receipt_retry:true});await uncertain.close();
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{for(const b of browsers)await b.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
