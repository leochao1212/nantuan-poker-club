/* Disposable local economy journeys: never uses production data or accounts. */
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),net=require('node:net');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/friends-economy');
fs.mkdirSync(out,{recursive:true});
const dir=fs.mkdtempSync(path.join(out,'run-')),db=path.join(dir,'test.sqlite3');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const port=await new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});});
 const base='http://127.0.0.1:'+port;
 const server=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_SECURE_COOKIE:'0',POKER_REQUIRE_INVITE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 let browser,logs='';server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 try{
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base+'/api/bootstrap')).ok){ready=true;break;}}catch{}await pause(100);}assert.ok(ready,logs);
  browser=await chromium.launch({headless:true});const context=await browser.newContext();const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const api=async(url,data)=>{const r=await context.request.fetch(base+url,{method:data?'POST':'GET',headers:{'X-Requested-With':'PokerClub'},...(data?{data}:{})});const value=await r.json();assert.ok(r.ok(),JSON.stringify(value));return value;};
  await api('/api/register',{username:'economy_synthetic',nickname:'Economy Test',password:'SyntheticEconomy123'});
  let lobby=await api('/api/online/lobby');assert.equal(lobby.wallet.balance,10000);assert.equal(lobby.wallet.income.rate,120);
  const seed=spawnSync(process.env.PYTHON||'python',['-c',"import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); d.execute(\"INSERT INTO cosmetic_items VALUES(1,'title_ms_blackjack_100',?)\",(time.time(),)); d.execute(\"INSERT INTO cosmetic_equipped VALUES(1,'title','title_ms_blackjack_100')\"); d.commit()",db],{cwd:root,windowsHide:true,encoding:'utf8'});assert.equal(seed.status,0,seed.stderr);
  await page.goto(base+'/#rewards');await page.locator('#daily-claim').waitFor();assert.ok((await page.locator('body').innerText()).includes('6,000'));assert.ok((await page.locator('body').innerText()).includes('1,500'));
  await page.goto(base+'/#bank');await page.waitForFunction(()=>document.querySelector('[data-bank-form] fieldset')?.disabled===false);
  await page.locator('[data-bank-action=borrow]').click();await page.locator('#bank-amount').fill('10000');await page.locator('[data-bank-submit]').click();
  const review=await page.locator('[data-bank-review]').innerText();assert.ok(review.includes('7 天'));assert.ok(review.includes('20%'));assert.ok(review.includes('10,070'));assert.ok(review.includes('從借款起計息'));assert.ok(review.includes('滿 7 天仍未還清'));assert.ok(!review.includes('免息'));assert.equal((await api('/api/bank')).bank.loan,null);
  await page.locator('[data-bank-submit]').click();await page.waitForFunction(()=>document.querySelector('[data-bank-debt]')?.textContent==='10,000');
  const borrowed=await api('/api/bank');assert.equal(borrowed.bank.loan.rate_bps,10);assert.equal(borrowed.bank.loan.auto_repay,1);
  await api('/api/wallet/claim',{});const paid=await api('/api/bank');assert.equal(paid.bank.loan.principal,10000);assert.equal(paid.wallet.balance,22000);
  const overdue=spawnSync(process.env.PYTHON||'python',['-c',"import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); now=int(time.time()); d.execute('UPDATE bank_loans SET started_at=?,grace_until=?,due_at=?,last_at=?,interest_units=?,generated_units=? WHERE user_id=1 AND closed_at IS NULL',(now-7*86400,now-7*86400,now-1,now,70*86400*10000,70*86400*10000)); d.commit()",db],{cwd:root,windowsHide:true,encoding:'utf8'});assert.equal(overdue.status,0,overdue.stderr);
  await api('/api/wallet/hourly',{operation_id:crypto.randomUUID()});const repaid=await api('/api/bank');assert.equal(repaid.wallet.balance,22000+paid.wallet.hourly_amount-Math.floor(paid.wallet.hourly_amount/5));assert.ok(repaid.bank.loan.principal<10000);assert.equal(repaid.bank.history[0].kind,'auto_repay');assert.equal(repaid.bank.history[0].amount,Math.floor(paid.wallet.hourly_amount/5));
  await api('/api/clubhouse/dispatch',{employee:'concierge',mission:'setup',operation_id:crypto.randomUUID()});
  const finishStaff=()=>{const result=spawnSync(process.env.PYTHON||'python',['-c',"import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); d.execute('UPDATE staff_jobs SET finishes_at=? WHERE user_id=1 AND claimed_at IS NULL',(time.time()-1,)); d.commit()",db],{cwd:root,windowsHide:true,encoding:'utf8'});assert.equal(result.status,0,result.stderr);};
  finishStaff();await page.goto(base+'/#clubhouse');await page.locator('[data-staff-redispatch]:enabled').waitFor();
  await page.locator('[data-staff-redispatch]').click();await page.waitForFunction(expected=>lobby.wallet.balance===expected,repaid.wallet.balance+60);
  finishStaff();await page.locator('[data-staff-refresh]').click();await page.locator('[data-staff-collect-all]:enabled').waitFor();
  await page.locator('[data-staff-collect-all]').click();await page.waitForFunction(expected=>lobby.wallet.balance===expected,repaid.wallet.balance+120);
  assert.equal((await api('/api/bank')).bank.loan.principal,repaid.bank.loan.principal,'staff rewards are outside automatic repayment');
  for(const [width,height] of [[320,740],[393,852],[1366,900]]){
   await page.setViewportSize({width,height});
   for(const route of ['rewards','bank','collection','clubhouse']){
    await page.goto(base+'/#'+route);await page.waitForFunction(()=>document.querySelector('#main'));await pause(300);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route+' overflow '+width);
    if(route==='collection')assert.ok((await page.locator('body').innerText()).includes('贏局加碼'));
    await page.screenshot({path:path.join(out,route+'-'+width+'.png'),fullPage:true});
   }
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({viewports:3,pages:4,borrow_consent:true,seven_days:true,overdue_only_repayment:true,title_effects:true,staff_batch:true,errors},null,2));
  console.log('Friends economy UI: 12 responsive views, consent, repayment and title labels OK');
 }finally{if(browser)await browser.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
