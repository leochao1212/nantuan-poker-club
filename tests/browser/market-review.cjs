/* Admin quarantine review and response-loss replay on disposable accounts. */
const {chromium,webkit}=require('playwright'),{spawn,spawnSync}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/market-review/browser');fs.mkdirSync(out,{recursive:true});const dir=fs.mkdtempSync(path.join(os.tmpdir(),'market-review-')),db=path.join(dir,'test.sqlite3'),probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port,python=process.env.PYTHON||'python';
 const server=spawn(python,['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONUTF8:'1'}});fs.writeFileSync(path.join(out,'server-pid.txt'),String(server.pid));let logs='',browser,serial=0,invite;const errors=[],checks=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{
  for(const [engine,driver] of [['chromium',chromium],['webkit',webkit]]){
   browser=await driver.launch({headless:true});
   for(const mobile of [true,false]){
    const context=await browser.newContext({viewport:{width:mobile?393:1366,height:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'}),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    const api=async(p,data)=>{const r=data===undefined?await context.request.get(base+p):await context.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data});assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
    for(let i=0;i<100;i++){try{await api('/api/bootstrap');break;}catch{await new Promise(r=>setTimeout(r,100));}}
    const name='review_ui_'+(++serial);await api('/api/register',{username:name,nickname:'審核測試'+serial,password:'SyntheticReview123',invite_code:invite});const initial=await api('/api/state');invite??=initial.invite_code;const uid=initial.me?.id||initial.user?.id;
    const seed=(settle)=>{
     const script=`import sqlite3,time,json,sys\nimport market,wallet\nd=sqlite3.connect(sys.argv[1]);d.row_factory=sqlite3.Row;name=sys.argv[2];assert name.startswith('review_ui_');u=d.execute('SELECT id FROM users WHERE username=?',(name,)).fetchone()[0];d.execute('INSERT OR IGNORE INTO club_admins VALUES(?,0,?)',(u,time.time()));t=time.time();symbol='US:AAPL'\nassert 'market-review-' in sys.argv[1];d.execute('DELETE FROM market_quotes WHERE symbol=?',(symbol,));d.execute('INSERT OR REPLACE INTO market_quote_meta VALUES(?,?,?)',(symbol,t-1800,t+7200))\ndef q(n,at):market.apply_quotes(d,[dict(symbol=symbol,price=str(n),native=str(n),bid=str(n),ask=str(n),fx='1',asof=at,fx_at=t,source=market.US_SOURCE)],t)\nq(100,t-5)\nif sys.argv[3]=='1':\n wallet.transfer(d,u,-1000,'market_reserve','review-seed-position',t);d.execute('INSERT OR REPLACE INTO market_positions VALUES(?,?,?,?)',(u,symbol,10*market.SCALE,1000))\nq(160,t-2);q(50 if sys.argv[3]=='1' else 101,t-1);d.commit();print(u)`;
     const r=spawnSync(python,['-c',script,db,name,settle?'1':'0'],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(r.status,0,r.stderr);return Number(r.stdout.trim());
    };
    seed(false);await page.goto(base+'/#admin');await page.locator('[data-admin-section="market"]').click();await page.locator('[data-halt-case]').waitFor();
    const form=page.locator('[data-halt-case]').first();await form.locator('[name=note]').fill('已核對合成行情：排除錯價');await form.locator('[name=confirm]').check();const resumeReply=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/api/admin/market-halts'));await form.locator('[type=submit]').click();assert.equal((await resumeReply).status(),200);await page.waitForFunction(()=>document.querySelectorAll('[data-halt-case]').length===0);
    const owned=seed(true);const before=(await api('/api/online/lobby')).wallet.total;await page.locator('[data-halt-refresh]').click();await page.locator('[data-halt-case]').waitFor();const closeForm=page.locator('[data-halt-case]').first();await closeForm.locator('[name=action]').selectOption('settle');await closeForm.locator('[name=note]').fill('已核對公司行動：按停牌前可信價結清');await closeForm.locator('[name=confirm]').check();
    const posts=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/admin/market-halts'))posts.push(r.postDataJSON());});
    let dropped=false;if(serial===1)await page.route('**/api/admin/market-halts',async route=>{if(route.request().method()!=='POST'||dropped)return route.continue();dropped=true;const real=await route.fetch();assert.equal(real.status(),200);await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic lost response'})});});
    await closeForm.locator('[type=submit]').click();
    if(serial===1){await page.locator('[data-halt-retry]').waitFor();await page.locator('[data-halt-retry]').click();}
    await page.waitForFunction(()=>document.querySelectorAll('[data-halt-case]').length===0&&!document.querySelector('[data-halt-retry]')?.offsetParent);
    const after=await api('/api/online/lobby');assert.equal(after.wallet.balance,before);assert.equal(after.wallet.investments,0);
    const receipt=posts[0];assert.ok(receipt);assert.ok((await api('/api/admin/market-halts',receipt)).replayed);assert.equal((await api('/api/online/lobby')).wallet.balance,before);if(serial===1)assert.equal(posts[1].operation_id,receipt.operation_id);
    const noAuth=await browser.newContext();assert.equal((await noAuth.request.get(base+'/api/admin/market-halts')).status(),401);await noAuth.close();
    for(const width of [320,393,768,1366]){await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Market review fits '+width);}
    await page.setViewportSize({width:mobile?393:1366,height:900});await page.screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'.png'),fullPage:true});checks.push({engine,mobile,resume:true,close_at_trusted_price:true,replay_once:true,response_loss_retry:serial===1,overflow:false,uid:owned});await context.close();
   }
   await browser.close();browser=null;
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser?.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
