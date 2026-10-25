/* Real admin controls and high-value form payloads use a disposable SQLite file. */
const {chromium,webkit}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/bet-limit-browser'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 fs.mkdirSync(out,{recursive:true});const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const db=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-limits-')),'isolated.sqlite3'),base='http://127.0.0.1:'+port,python=process.env.PYTHON||'python',browsers=[],errors=[],checks=[];let logs='';
 const server=spawn(python,['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 try{
  browsers.push(['chromium',await chromium.launch({headless:true})],['webkit',await webkit.launch({headless:true})]);
  const seed=await browsers[0][1].newContext(),api=async(c,p,data)=>{const r=data?await c.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data}):await c.request.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
  let ready=false;for(let i=0;i<100;i++){try{await api(seed,'/api/bootstrap');ready=true;break;}catch{await sleep(100);}}assert.ok(ready);
  await api(seed,'/api/register',{username:'limits_fixture',nickname:'上限測試',password:'SyntheticLimits123'});
  const seeded=spawnSync(python,['-c',"import sqlite3,sys,time;d=sqlite3.connect(sys.argv[1]);d.execute('INSERT INTO club_admins VALUES(1,0,?)',(time.time(),));d.execute('UPDATE wallets SET balance=1000000 WHERE user_id=1');d.commit()",db],{windowsHide:true,encoding:'utf8'});assert.equal(seeded.status,0,seeded.stderr);
  const storageState=await seed.storageState();await seed.close();
  for(const [engine,browser] of browsers)for(const mobile of [true,false]){
   const c=await browser.newContext({storageState,viewport:{width:mobile?393:1366,height:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'}),page=await c.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+'/#admin');await page.waitForFunction(()=>lobby&&liveReady);await page.locator('[data-admin-section=settings]').click();await page.locator('[data-rules-game]').selectOption('limits');
   for(const value of [6000,10000]){
    await page.locator('[data-rule-key=max_bet]').fill(String(value));await page.locator('[data-rules-note]').fill('Synthetic cap validation');await page.locator('[data-rules-form] [type=submit]').click();await page.locator('[data-rules-confirm]').click();await page.waitForFunction(()=>!document.querySelector('#game-settings-modal').open);
    const limits=(await api(c,'/api/admin/game-settings')).games.find(g=>g.game_type==='limits');assert.equal(limits.params.max_bet,value);await page.waitForFunction(v=>document.querySelector('[data-rule-key=max_bet]')?.value===String(v),value);
   }
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,engine+'-admin-'+(mobile?'phone':'desktop')+'.png')});
   for(const kind of ['roulette','dice','slot','blackjack']){
    const r=await api(c,'/api/online/rooms',{game_type:kind,buy_in:30000,stake:20,operation_id:crypto.randomUUID()}),rp='/api/online/rooms/'+r.id;await page.goto(base+'/#table/'+r.id);await page.waitForFunction(id=>room?.id===id&&liveReady,r.id);
    if(kind==='dice')for(const value of [6000,10000]){
     const old=(await api(c,'/api/admin/game-settings')).games.find(g=>g.game_type==='limits');
     await api(c,'/api/admin/game-settings',{game_type:'limits',revision:old.revision,params:{max_bet:value},note:'Synthetic live limit propagation',operation_id:crypto.randomUUID()});
     await page.waitForFunction(v=>document.querySelector('#round-stake')?.max===String(v),value);
    }
    let selector;
    if(kind==='roulette'){
     await page.locator('[data-roulette-chip="5000"]').click();await page.locator('[data-roulette=red]').click();await page.locator('[data-roulette=red]').click();assert.equal(await page.locator('#roulette-total').innerText(),'10,000');await page.locator('[data-roulette=black]').click();assert.equal(await page.locator('#roulette-total').innerText(),'10,000');selector='#roulette-confirm';
    }else{
     assert.equal(await page.locator('#round-stake').getAttribute('max'),'10000');await page.locator('#round-stake').fill('10000');
     if(kind==='dice'){await page.locator('[data-dice-bet=big]').click();assert.equal(await page.locator('#dice-total').innerText(),'10,000');await page.locator('[data-dice-bet=odd]').click();assert.equal(await page.locator('#dice-total').innerText(),'10,000');selector='#dice-roll';}else selector='#deal-hand';
    }
    const sent=[];await page.route('**'+rp+'/start',async route=>{sent.push(route.request().postDataJSON());await sleep(700);await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Synthetic request check'})});});
    await page.locator(selector).click();await page.waitForFunction(()=>busy);await page.locator(selector).evaluate(b=>b.click());await page.waitForFunction(()=>!busy&&!pendingOperation);assert.equal(sent.length,1,'One user operation creates one payload');
    const value=kind==='roulette'||kind==='dice'?sent[0].bets.reduce((sum,b)=>sum+b.amount,0):sent[0].stake;assert.equal(value,10000);assert.ok(Number.isInteger(sent[0].expected_bet_limit_revision));
    const unchanged=await api(c,rp);assert.equal(unchanged.hand_no,0);assert.equal(unchanged.seats[0].stack,30000);await page.unroute('**'+rp+'/start');await api(c,rp+'/close',{revision:unchanged.revision,operation_id:crypto.randomUUID()});checks.push({engine,mobile,kind,limit:10000,requests:sent.length});
   }
   await c.close();
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{for(const [,b] of browsers)await b.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
