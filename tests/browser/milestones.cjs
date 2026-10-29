/* Real isolated account history, claims, price confirmation and single-title effects. */
const {chromium,webkit}=require('playwright'),{spawn,spawnSync}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/milestones/browser');fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'milestones-ui-')),db=path.join(tmp,'test.sqlite3'),probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port,python=process.env.PYTHON||'python';
 const server=spawn(python,['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONUTF8:'1'}});let logs='',browser,serial=0,invite;const checks=[],errors=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{
  for(const [engine,driver]of [['chromium',chromium],['webkit',webkit]]){
   browser=await driver.launch({headless:true});
   for(const mobile of [true,false]){
    const context=await browser.newContext({viewport:{width:mobile?393:1366,height:mobile?852:960},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'}),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    const api=async(p,data)=>{const r=data===undefined?await context.request.get(base+p):await context.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data});assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
    for(let i=0;i<100;i++){try{await api('/api/bootstrap');break;}catch{}await new Promise(r=>setTimeout(r,100));}
    const username='milestone_ui_'+(++serial);await api('/api/register',{username,nickname:'里程碑測試'+serial,password:'SyntheticMilestone123',invite_code:invite});const initial=await api('/api/state');invite??=initial.invite_code;
    const room=await api('/api/online/rooms',{game_type:'slot',buy_in:1000,stake:10,operation_id:crypto.randomUUID()});
    const count=serial===1?10000:100;
    const seed=`import sqlite3,sys,time,json\nimport wallet\nd=sqlite3.connect(sys.argv[1]);d.row_factory=sqlite3.Row;u=d.execute('SELECT id FROM users WHERE username=?',(sys.argv[2],)).fetchone()[0];assert sys.argv[2].startswith('milestone_ui_');clock=time.time();wallet.transfer(d,u,2000000,'admin_adjustment','milestone-ui-credit',clock);state=json.dumps(dict(game_type='slot',players=[dict(user_id=u,contribution=10)]));rid=int(sys.argv[3]);n=int(sys.argv[4]);start=u*100000\nd.executemany('INSERT INTO poker_hands VALUES(?,?,?,?,?)',[(start+i,rid,i,state,clock) for i in range(1,n+1)])\nd.executemany('INSERT INTO poker_results VALUES(?,?,?,?,?)',[(start+i,u,0,10,'fixture') for i in range(1,n+1)]);d.commit();d.close()`;
    const seeded=spawnSync(python,['-c',seed,db,username,String(room.id),String(count)],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(seeded.status,0,seeded.stderr);
    const posts=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/club/'))posts.push({path:new URL(r.url()).pathname,data:r.postDataJSON()});});
    await page.goto(base+'/#rewards');await page.locator('#game-milestones').waitFor();assert.equal(await page.locator('.milestone-game').count(),11);await page.locator('[data-milestones-jump]').click();assert.ok(await page.locator('#game-milestones').evaluate(e=>e===document.activeElement));
    const before=(await api('/api/online/lobby')).wallet.balance;await page.locator('[data-milestone="slot_100"]').click();await page.waitForFunction(()=>lobby.club.items.some(i=>i.id==='title_ms_slot_100'&&i.owned));assert.equal((await api('/api/online/lobby')).wallet.balance,before);
    const claim=posts.find(x=>x.path.endsWith('/milestone'));await api(claim.path,claim.data);assert.equal((await api('/api/online/lobby')).wallet.balance,before);assert.ok(await page.locator('[data-milestone="slot_100"]').isDisabled());
    if(serial===1){assert.ok(await page.locator('[data-milestone="slot_10000"]').isEnabled());await page.locator('[data-milestone="slot_10000"]').click();await page.waitForFunction(()=>lobby.club.items.some(i=>i.id==='title_ms_slot_10000'&&i.owned));}
    for(const width of [320,393,768,1366]){await page.setViewportSize({width,height:852});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Milestones must fit '+width);}
    await page.setViewportSize({width:mobile?393:1366,height:mobile?852:960});await page.screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'-progress.png'),fullPage:true});
    await page.goto(base+'/#collection');await page.locator('[data-item="title_ms_slot_100"]').click();await page.waitForFunction(()=>lobby.club.equipped.title?.id==='title_ms_slot_100');assert.equal((await api('/api/online/lobby')).wallet.income.title_bonus.storage_bps,100);
    await page.locator('[data-item="title_patron"][data-item-action="buy"]').click();await page.waitForFunction(()=>lobby.club.items.some(i=>i.id==='title_patron'&&i.owned));assert.equal(posts.find(p=>p.data.item_id==='title_patron').data.expected_cost,80000);assert.equal((await api('/api/online/lobby')).wallet.balance,before-80000);
    await page.locator('[data-item="title_patron"][data-item-action="equip"]').click();await page.waitForFunction(()=>lobby.club.equipped.title?.id==='title_patron');const bonus=(await api('/api/online/lobby')).wallet.income.title_bonus;assert.equal(bonus.production_bps,75);assert.equal(bonus.storage_bps,200);assert.ok(await page.locator('.title-bonus-summary').getByText('鎏金贊助人',{exact:true}).isVisible());
    await page.locator('[data-cosmetic-filter="title"]').click();for(const width of [320,393,768,1366]){await page.setViewportSize({width,height:852});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Collection must fit '+width);}
    await page.setViewportSize({width:mobile?393:1366,height:mobile?852:960});await page.screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'-titles.png'),fullPage:true});
    await page.goto(base+'/#clubhouse');await page.locator('.income-panel .cosmetic-bonus').waitFor();assert.ok((await page.locator('.income-panel .cosmetic-bonus').textContent()).includes('鎏金贊助人'));
    checks.push({engine,mobile,historical_count:count,claim_no_mint:true,retry_once:true,quoted_purchase:true,single_equipped_title:true,overflow:false});await context.close();
   }
   await browser.close();browser=null;
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser?.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
