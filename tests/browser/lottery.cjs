/* Disposable local DB: real purchases, lost responses, responsive views. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/lottery/browser'),pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'friends-lottery-')),db=path.join(tmp,'test.sqlite3');
 const sock=net.createServer();await new Promise(r=>sock.listen(0,'127.0.0.1',r));const port=sock.address().port;await new Promise(r=>sock.close(r));const base=`http://127.0.0.1:${port}`;
 const server=spawn('python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});let logs='',browser;server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{
  browser=await chromium.launch({headless:true});let invite;const errors=[];
  for(const width of [393,1366]){
   const c=await browser.newContext({viewport:{width,height:900},isMobile:width<500,hasTouch:width<500});
   const api=async(url,data)=>{const r=data?await c.request.post(base+url,{headers:{'X-Requested-With':'PokerClub'},data}):await c.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
   for(let i=0;i<100;i++){try{await api('/api/bootstrap');break;}catch{await pause(100);}}
   await api('/api/register',{username:'lottery_ui_'+width,nickname:'樂透測試',password:'SyntheticLottery123',invite_code:invite});invite||=(await api('/api/state')).invite_code;
   // Keep tests independent of wall-clock sales cutoff, only in this disposable DB.
   const update=spawnSync('python',['-c',"import sqlite3,time,sys; d=sqlite3.connect(sys.argv[1]);d.execute('UPDATE lottery_draws SET cutoff=?,draw_at=? WHERE settled_at IS NULL',(time.time()+3600,time.time()+3900));d.commit()",db],{cwd:root});assert.equal(update.status,0);
   const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base+'/#lottery');
   await p.locator('[data-lottery-number="1"]:enabled').waitFor();
   assert.equal(await p.locator('nav .nav-item:visible').count(),width<500?5:7);
   const before=await api('/api/lottery');assert.equal(before.lottery.current.seed,undefined);
   for(let i=1;i<=5;i++)await p.locator(`[data-lottery-number="${i}"]`).click();
   await p.locator('[data-lottery-buy]').click();await p.locator('[data-lottery-message]').filter({hasText:'購票成功'}).waitFor();
   assert.equal((await api('/api/lottery')).wallet.balance,before.wallet.balance-100);
   let once=true;await p.route('**/api/lottery/buy',async route=>{if(once){once=false;await route.fetch();await route.abort('failed');}else await route.continue();});
   await p.locator('[data-lottery-buy]').click();await p.getByRole('button',{name:'確認原購票結果',exact:true}).waitFor();
   await p.reload();await p.getByRole('button',{name:'確認原購票結果',exact:true}).click();
   await p.locator('[data-lottery-message]').filter({hasText:'原購票已確認'}).waitFor();
   assert.equal((await api('/api/lottery')).wallet.balance,before.wallet.balance-200);
   assert.equal((await api('/api/lottery')).lottery.bought,2);
   assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
   await p.evaluate(()=>scrollTo(0,0));
   await p.screenshot({path:path.join(out,`${width}.png`),fullPage:true});
   const settle=spawnSync('python',['-c',"import sqlite3,sys,time,lottery; d=sqlite3.connect(sys.argv[1]);d.row_factory=sqlite3.Row;d.execute('BEGIN IMMEDIATE');at=d.execute('SELECT max(draw_at) FROM lottery_draws').fetchone()[0];lottery.maintenance(d,max(at+1,lottery.upcoming(time.time())[1]+1));d.commit()",db],{cwd:root});assert.equal(settle.status,0);
   await p.reload();await p.locator('[data-lottery-results] article').first().waitFor();
   const after=await api('/api/lottery');assert.ok(after.lottery.results[0].seed);assert.ok(after.lottery.tickets.every(t=>t.prize!==null));
   await p.locator('[data-lottery-results] summary').first().click();
   await p.evaluate(()=>scrollTo(0,0));
   await p.screenshot({path:path.join(out,`${width}-results.png`),fullPage:true});await c.close();
  }
  assert.deepEqual(errors,[]);console.log('Lottery UI: mobile + desktop purchases, reload receipts, balance checks, no overflow/errors passed.');
 }finally{if(browser)await browser.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
