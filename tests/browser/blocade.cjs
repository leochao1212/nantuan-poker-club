/* Real HTTP, isolated wallet DB, Chromium/WebKit, touch and desktop. */
const {chromium,webkit}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/blocade/browser'),pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-board-')),db=path.join(tmp,'test.sqlite3');
 const sock=net.createServer();await new Promise(r=>sock.listen(0,'127.0.0.1',r));const port=sock.address().port;await new Promise(r=>sock.close(r));const base=`http://127.0.0.1:${port}`;
 const server=spawn('python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 let logs='',browser,invite;const errors=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 const edit=(rid,code)=>{const r=spawnSync('python',['-c',`import sqlite3,json,sys,time;d=sqlite3.connect(sys.argv[1]);rid=int(sys.argv[2]);s=json.loads(d.execute('SELECT state FROM blocade_rooms WHERE id=?',(rid,)).fetchone()[0]);${code};d.execute('UPDATE blocade_rooms SET state=?,revision=revision+1 WHERE id=?',(json.dumps(s),rid));d.commit()`,db,String(rid)],{cwd:root,windowsHide:true});assert.equal(r.status,0,r.stderr?.toString());};
 try{
  for(const [name,engine] of [['chromium',chromium],['webkit',webkit]].filter(([n])=>!process.env.BOARD_BROWSER||n===process.env.BOARD_BROWSER)){
   browser=await engine.launch({headless:true});
   for(const width of [375,1280].filter(w=>!process.env.BOARD_WIDTH||w===Number(process.env.BOARD_WIDTH))){
    const c=await browser.newContext({viewport:{width,height:920},isMobile:width<500,hasTouch:width<500,reducedMotion:'reduce'}),other=await browser.newContext();
    const api=async(context,url,data)=>{const r=data?await context.request.post(base+url,{headers:{'X-Requested-With':'PokerClub'},data}):await context.request.get(base+url);assert.equal(r.status(),200,await r.text());return r.json();};
    const call=(verb,data={})=>api(c,'/api/blocade/'+verb,{...data,operation_id:crypto.randomUUID()});
    for(let i=0;i<100;i++){try{await api(c,'/api/bootstrap');break;}catch{await pause(100);}}
    await api(c,'/api/register',{username:`board_${name}_${width}`,nickname:'測試玩家',password:'SyntheticBoard123',invite_code:invite});invite||=(await api(c,'/api/state')).invite_code;
    await api(other,'/api/register',{username:`rival_${name}_${width}`,nickname:'棋桌朋友',password:'SyntheticBoard123',invite_code:invite});
    const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base+'/#blocade');await p.locator('[data-bc-create]').waitFor();
    await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:path.join(out,`${name}-${width}-lobby.png`),fullPage:true});
    let once=true;await p.route('**/api/blocade/create',async route=>{if(once){once=false;await route.fetch();await route.abort('failed');}else await route.continue();});
    await p.locator('[name=bots]').uncheck();await p.locator('[data-bc-create] button[type=submit]').click();
    await p.locator('[data-bc-retry]:visible').waitFor();await p.reload();await p.locator('[data-bc-retry]:visible').click();
    await p.locator('[data-bc-message]').filter({hasText:'原操作已確認'}).waitFor();
    let result=await api(c,'/api/blocade'),rid=result.blocade.room.id;
    assert.equal(result.wallet.balance,9900);assert.equal(result.wallet.in_play,100);assert.equal(result.blocade.history.length,1);
    await api(other,'/api/blocade/join',{room_id:rid,operation_id:crypto.randomUUID()});
    await p.locator('[data-bc-start]:enabled').click();await p.waitForFunction(()=>document.querySelector('[data-bc-turn]')?.textContent.startsWith('輪到'));
    edit(rid,"s['game']['turn']=0;s['deadline']=time.time()+120");await p.reload();
    await p.locator('[data-bc-mode=move]:enabled').waitFor();
    assert.equal(await p.locator('.bc-cell small,[data-bc-move],[data-bc-confirm],.bc-wall-inputs').count(),0);
    assert.equal(await p.locator('.bc-pawn').first().textContent(),'');
    await p.locator('[data-bc-mode=wall]').click();await p.locator('[data-bc-endpoint="4,3"]').click();
    assert.equal((await api(c,'/api/blocade')).blocade.room.game.walls.length,0,'First endpoint must not submit');
    await p.screenshot({path:path.join(out,`${name}-${width}-endpoints.png`),fullPage:true});
    assert.equal(await p.locator('[data-bc-endpoint="4,4"]').isDisabled(),true,'One-cell wall is not selectable');
    assert.equal(await p.locator('[data-bc-endpoint="5,4"]').isDisabled(),true,'Diagonal wall is not selectable');
    await p.locator('[data-bc-endpoint="4,3"]').click();assert.equal(await p.locator('.bc-preview').count(),0,'Same endpoint cancels');
    await p.locator('[data-bc-endpoint="4,3"]').click();await p.locator('[data-bc-endpoint="4,5"]').click();
    await p.waitForFunction(()=>document.querySelectorAll('.bc-wall:not(.bc-preview)').length===1);
    assert.deepEqual((await api(c,'/api/blocade')).blocade.room.game.walls,[['h',3,3]]);
    edit(rid,"s['game']['turn']=0;s['deadline']=time.time()+120");await p.reload();
    await p.locator('[data-bc-mode=wall]:enabled').click();
    await p.locator('[data-bc-endpoint="9,1"]').click();await p.locator('[data-bc-endpoint="7,1"]').click();
    await p.waitForFunction(()=>document.querySelectorAll('.bc-wall:not(.bc-preview)').length===2);
    assert.deepEqual((await api(c,'/api/blocade')).blocade.room.game.walls[1],['v',7,0],'Reverse endpoints at the board edge');
    // Focus changes retain a healthy SSE, while closed streams still recover.
    await p.waitForFunction(()=>liveReady&&live?.readyState===1);
    assert.equal(await p.evaluate(()=>{const original=live;lastResumeAt=0;resumeConnections('focus');return original===live;}),true);
    await p.evaluate(()=>{live.close();lastResumeAt=0;resumeConnections('focus');});
    await p.waitForFunction(()=>liveReady&&live?.readyState===1);
    await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:path.join(out,`${name}-${width}-two.png`),fullPage:true});
    assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No page overflow');
    // Leave through confirmation; opponent receives exactly one complete pot.
    await p.locator('[data-bc-leave]').click();await p.locator('#confirm-yes').click();await p.locator('.bc-result').waitFor();
    assert.equal((await api(other,'/api/blocade')).wallet.balance,10100);
    await p.screenshot({path:path.join(out,`${name}-${width}-rematch.png`),fullPage:true});
    const rival=await other.newPage();await rival.goto(base+'/#blocade?room='+rid);
    await rival.locator('[data-bc-rematch]').waitFor();
    await p.locator('[data-bc-rematch]').click();await p.locator('[data-bc-start]').waitFor();
    const next=(await api(c,'/api/blocade')).blocade.room.id;
    assert.notEqual(next,rid);assert.equal((await api(other,'/api/blocade')).wallet.balance,10100,'Friend is not charged until opting in');
    await rival.locator('[data-bc-rematch]').filter({hasText:'加入朋友的下一局'}).waitFor();
    await rival.locator('[data-bc-rematch]').click();
    await rival.waitForFunction(()=>document.querySelector('.bc-waiting h3')?.textContent.includes('2 / 2'));
    assert.equal((await api(other,'/api/blocade')).blocade.room.id,next);
    assert.equal((await api(other,'/api/blocade')).wallet.balance,10000);
    await api(other,'/api/blocade/leave',{room_id:next,operation_id:crypto.randomUUID()});await rival.close();
    await p.locator('[data-bc-leave]').click();await p.locator('#confirm-yes').click();await p.locator('.bc-result').waitFor();

    await p.locator('[data-bc-back]').click();await p.locator('[name=capacity][value="4"]').check();await p.locator('[name=bots]').check();await p.locator('[data-bc-stake="500"]').click();
    await p.locator('[data-bc-create] button[type=submit]').click();await p.locator('[data-bc-start]').click();await p.waitForFunction(()=>document.querySelector('[data-bc-turn]')?.textContent.startsWith('輪到'));
    result=await api(c,'/api/blocade');rid=result.blocade.room.id;
    assert.equal(result.blocade.room.game.players.filter(p=>p.bot).length,3);assert.equal(result.blocade.room.target_pot,2000);
    edit(rid,"s['game']['turn']=0;s['deadline']=time.time()+120");await p.reload();await p.locator('[data-bc-mode=move]:enabled').click();await p.locator('[data-bc-cell]:enabled').first().waitFor();
    await p.locator('[data-bc-cell]:enabled').first().click();
    await p.waitForFunction(()=>document.querySelectorAll('.bc-player.bc-playing').length===1);
    for(let i=0;i<100;i++){result=await api(c,'/api/blocade');if(result.blocade.room.game.ply>=4)break;await pause(150);}
    assert.ok(result.blocade.room.game.ply>=4,'All three bots must make a legal move');
    await p.evaluate(()=>scrollTo(0,0));await p.screenshot({path:path.join(out,`${name}-${width}-four.png`),fullPage:true});
    for(const [w,h] of [[320,740],[768,1024],[844,390],[1440,900]]){await p.setViewportSize({width:w,height:h});assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${name} ${w}x${h}`);}
    await p.setViewportSize({width,height:920});
    // Navigation/reload keeps the same persisted board and exposes invitation links.
    const before=result.blocade.room.game.ply;await p.goto(base+'/#lobby');await p.locator('.bc-lobby-entry').click();await p.locator('.bc-board').waitFor();
    assert.equal((await api(c,'/api/blocade')).blocade.room.id,rid);
    assert.ok((await api(c,'/api/blocade')).blocade.room.game.ply>=before);
    await p.goto(base+'/#blocade?room='+rid);await p.locator('.bc-board').waitFor();
    await call('leave',{room_id:rid});await c.close();await other.close();
   }
   await browser.close();browser=null;
  }
  assert.deepEqual(errors,[]);console.log('Blocade: Chromium/WebKit touch + desktop, 2/4 seats, bots, direct moves, two-endpoint walls, focus recovery, receipts, payouts, reload and responsive layouts passed.');
 }finally{if(browser)await browser.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
