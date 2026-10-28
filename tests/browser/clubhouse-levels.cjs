/* Ten real clubhouse scenes and upgrade controls, disposable accounts/SQLite. */
const {chromium,webkit}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/clubhouse-levels'),pause=ms=>new Promise(r=>setTimeout(r,ms));
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const n=s.address().port;await new Promise(r=>s.close(r));return n;}
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-clubhouse-levels-')),db=path.join(tmp,'isolated.sqlite3'),base='http://127.0.0.1:'+await port(),python=process.env.PYTHON||'python';
 const proc=spawn(python,['server.py','--host','127.0.0.1','--port',new URL(base).port],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 let logs='',browser;const errors=[],checks=[];proc.stdout.on('data',x=>logs+=x);proc.stderr.on('data',x=>logs+=x);
 const api=async(ctx,url,data)=>{const r=data?await ctx.request.post(base+url,{headers:{'X-Requested-With':'PokerClub'},data}):await ctx.request.get(base+url);assert.equal(r.status(),200,url+' '+await r.text());return r.json();};
 const seed=level=>{
  const code=`import sqlite3,sys,time\nimport wallet\nd=sqlite3.connect(sys.argv[1]); d.row_factory=sqlite3.Row\nassert d.execute('SELECT username FROM users WHERE id=1').fetchone()[0]=='clubhouse_levels_test'\nnow=time.time()\nif not d.execute("SELECT 1 FROM wallet_ledger WHERE event_key='ten-browser-fixture'").fetchone(): wallet.transfer(d,1,10000000,'admin_adjustment','ten-browser-fixture',now)\nd.execute('UPDATE club_income SET production_level=?,storage_level=?,decor_level=?,stored_units=0,last_at=?,revision=revision+1 WHERE user_id=1',(int(sys.argv[2]),int(sys.argv[2]),int(sys.argv[2]),now))\nfor key in ('host','steward'): d.execute('INSERT OR IGNORE INTO staff_roster VALUES(1,?,?)',(key,now))\nd.commit()`;
  const r=spawnSync(python,['-c',code,db,String(level)],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});assert.equal(r.status,0,r.stderr);
 };
 try{
  browser=await chromium.launch({headless:true});const owner=await browser.newContext();
  let ready=false;for(let i=0;i<100;i++){try{await api(owner,'/api/bootstrap');ready=true;break;}catch{await pause(100);}}assert(ready,'Server did not start');
  await api(owner,'/api/register',{username:'clubhouse_levels_test',nickname:'十級會所測試',password:'SyntheticClubhouse123'});
  const storageState=await owner.storageState();await owner.close();await browser.close();browser=null;
  for(const [engine,type] of [['chromium',chromium],['webkit',webkit]]){
   browser=await type.launch({headless:true});
   for(const width of [393,1366]){
    const ctx=await browser.newContext({storageState,viewport:{width,height:900},isMobile:width<760,hasTouch:width<760,reducedMotion:'no-preference'}),page=await ctx.newPage();
    page.on('pageerror',e=>errors.push(engine+': '+e.message));
    page.on('response',r=>{if(['image','script','stylesheet'].includes(r.request().resourceType())&&r.status()>=400)errors.push(r.url()+' '+r.status());});
    for(let level=0;level<10;level++){
     if(level===0){seed(0);await page.goto(base+'/#clubhouse');await page.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);}
     else for(const track of ['production','storage','decor']){const income=(await api(ctx,'/api/online/lobby')).wallet.income;await api(ctx,'/api/wallet/clubhouse-upgrade',{track,expected_level:level-1,revision:income.revision,operation_id:crypto.randomUUID()});}
     await page.evaluate(()=>sync(true));
     await page.waitForFunction(level=>lobby.wallet.income.decor_level===level&&document.querySelector('.clubhouse-scene')?.dataset.estateLevel===String(level),level);
     await page.locator('.estate-render').evaluate(i=>i.decode());
     assert.equal(await page.locator('.clubhouse-scene').getAttribute('data-estate-level'),String(level));
     assert.equal(await page.evaluate(()=>ClubhouseScene.names.length),10);
     assert.match(await page.locator('.estate-render').evaluate(i=>i.currentSrc),new RegExp('/tier-'+(level+1)+(width<760?'-small':'')+'\\.webp\\?v='));
     for(const el of await page.locator('.facility-levels').all()){
      assert.equal(await el.locator('li').count(),10);assert.equal(await el.locator('.unlocked').count(),level+1);
     }
     assert.equal(await page.locator('[data-club-upgrade]:disabled').count(),level===9?3:0);
     const g=await page.evaluate(()=>{const image=document.querySelector('.clubhouse-scene').getBoundingClientRect(),title=document.querySelector('.estate-copy h2').getBoundingClientRect(),button=document.querySelector('.clubhouse-estate [data-open-upgrades]').getBoundingClientRect();return {width:innerWidth,scroll:document.documentElement.scrollWidth,image:{top:image.top,bottom:image.bottom},titleBottom:title.bottom,buttonTop:button.top,buttonHeight:button.height};});
     assert(g.scroll<=g.width+1,engine+' Lv.'+(level+1)+' overflow');
     if(width<760){assert(g.titleBottom<=g.image.top+1,'Title covers building');assert(g.buttonTop>=g.image.bottom-1,'Button covers building');assert(g.buttonHeight>=44);}
     if(engine==='chromium')await page.locator('.clubhouse-estate').screenshot({path:path.join(out,engine+'-'+width+'-lv-'+(level+1)+'.png')});
    }
    assert.match(await page.locator('.estate-copy h2').innerText(),/楠團天宮/);
    assert.match(await page.locator('.estate-copy [data-open-upgrades]').innerText(),/已全數滿級/);
    assert.match(await page.locator('.clubhouse-rules').innerText(),/5\.5×/);
    for(const [w,h] of [[320,844],[768,1024],[844,390]]){
     await page.setViewportSize({width:w,height:h});await page.locator('.estate-render').evaluate(i=>i.decode());
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Lv.10 narrow/landscape overflow');
    }
    checks.push(engine+' '+width+': ten distinct tiers, ten progress segments, mobile separation and max-level controls');console.log('clubhouse OK: '+engine+' '+width);
    await ctx.close();
   }
   // Use the actual confirmation dialog and server receipt for the new 4->5 step.
   seed(3);const ctx=await browser.newContext({storageState,viewport:{width:393,height:852},reducedMotion:'reduce'}),page=await ctx.newPage();
   await page.goto(base+'/#clubhouse');await page.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);await page.evaluate(()=>sync(true));await page.waitForFunction(()=>lobby.wallet.income.decor_level===3);
   await page.locator('[data-club-upgrade="decor"]').click();
   await page.getByRole('button',{name:'確認升級',exact:true}).click();
   await page.waitForFunction(()=>lobby.wallet.income.decor_level===4);
   await page.locator('.estate-render').evaluate(i=>i.decode());
   assert.match(await page.locator('.estate-copy h2').innerText(),/翡翠御苑/);
   assert.match(await page.locator('.estate-render').getAttribute('src'),/tier-5\.webp/);
   checks.push(engine+': actual fourth-to-fifth upgrade confirmation, receipt and new image');await ctx.close();
   await browser.close();browser=null;
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors,scope:'Disposable local account/database; no production data'},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser?.close();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
