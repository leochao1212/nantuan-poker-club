/* Real transactions, including an HTTP response lost after the server commits. */
const {chromium,webkit}=require('playwright'),{spawn,spawnSync}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/reward-hub');fs.mkdirSync(out,{recursive:true});
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'reward-hub-')),db=path.join(dir,'demo.sqlite3'),probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port;
 const server=spawn('python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONUTF8:'1'}});
 let logs='',browser,serial=0,invite;const errors=[],checks=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{for(const [name,driver] of [['chromium',chromium],['webkit',webkit]]){
  browser=await driver.launch({headless:true});
  for(const width of [393,1366]){
   const c=await browser.newContext({viewport:{width,height:852},reducedMotion:'reduce'}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));
   const api=async(url,data)=>{const r=data?await c.request.post(base+url,{headers:{'X-Requested-With':'PokerClub'},data}):await c.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
   for(let i=0;i<100;i++){try{await api('/api/bootstrap');break;}catch{await new Promise(r=>setTimeout(r,100));}}
   const username='hub_demo_'+(++serial);await api('/api/register',{username,nickname:'好友測試'+serial,password:'SyntheticHub2026',invite_code:invite});invite??=(await api('/api/state')).invite_code;
   const seed=`import sqlite3,sys,time,json\nd=sqlite3.connect(sys.argv[1]);u=d.execute('SELECT id FROM users WHERE username=?',(sys.argv[2],)).fetchone()[0];t=time.time();d.execute('UPDATE club_income SET stored_units=0,last_at=? WHERE user_id=?',(t+3600,u));s=json.dumps(dict(game_type='slot',players=[dict(user_id=u,contribution=10)]));start=u*100000\nd.executemany('INSERT INTO poker_hands VALUES(?,?,?,?,?)',[(start+i,999+u,i,s,t) for i in range(1,101)]);d.executemany('INSERT INTO poker_results VALUES(?,?,?,?,?)',[(start+i,u,0,10,'fixture') for i in range(1,101)]);d.commit()`;
   const seeded=spawnSync('python',['-c',seed,db,username],{cwd:root,encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stderr);
   await p.goto(base+'/#rewards');await p.waitForSelector('[data-reward-all]');await p.waitForFunction(()=>liveReady);
   assert.ok(await p.locator('.club-missions').isVisible());assert.ok(!await p.locator('#game-milestones').isVisible());
   await p.screenshot({path:path.join(out,`${name}-${width}-before.png`),fullPage:true});await p.screenshot({path:path.join(out,`${name}-${width}-screen.png`)});
   const posts=[];p.on('request',r=>{if(r.url().endsWith('/api/club/claim-all'))posts.push(r.postDataJSON());});
   if(serial===1){let fail=true;await p.route('**/api/club/claim-all',async route=>{if(fail){fail=false;await route.fetch();await route.abort();}else await route.continue();});}
   await p.locator('[data-reward-all]').click();
   if(serial===1){await p.getByRole('button',{name:'重試確認領取'}).waitFor();await p.getByRole('button',{name:'重試確認領取'}).click();}
   await p.waitForFunction(()=>document.querySelector('.reward-receipt')?.textContent.includes('錢包入帳'));
   const state=await api('/api/online/lobby');assert.equal(state.wallet.balance,13000);assert.ok(state.club.items.find(x=>x.id==='title_ms_slot_100').owned);assert.ok(!state.club.equipped.title);
   if(serial===1){assert.equal(posts.length,2);assert.equal(posts[0].operation_id,posts[1].operation_id);}
   await p.locator('.reward-receipt [data-item="title_ms_slot_100"]').click();await p.waitForFunction(()=>lobby.club.equipped.title?.id==='title_ms_slot_100');
   assert.equal(new URL(p.url()).hash,'#rewards');await p.locator('[data-hub-tab="titles"]').click();assert.ok(await p.locator('.title-bonus-summary h2').getByText('拉霸新秀',{exact:true}).isVisible());
   await p.screenshot({path:path.join(out,`${name}-${width}-titles.png`),fullPage:true});
   await p.locator('[data-hub-tab="daily"]').click();await p.locator('[data-reward-all]').click();await p.waitForFunction(()=>document.querySelector('.reward-receipt')?.textContent.includes('目前沒有待領'));
   assert.equal((await api('/api/online/lobby')).wallet.balance,13000);
   for(const w of [320,393,768,1366]){await p.setViewportSize({width:w,height:852});assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
   await p.setViewportSize({width,height:852});await p.screenshot({path:path.join(out,`${name}-${width}-after.png`),fullPage:true});
   checks.push({engine:name,width,claim_all:true,retry_after_commit:serial===1,inline_equip:true,no_duplicate:true});await c.close();
  }await browser.close();browser=null;
 }assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser?.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
