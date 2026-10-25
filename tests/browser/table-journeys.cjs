/* Player journeys use disposable accounts and real receipts; no production writes. */
const {chromium,webkit}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/table-ux'),pause=ms=>new Promise(r=>setTimeout(r,ms));
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
(async()=>{
 fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'table-ux-')),base='http://127.0.0.1:'+await port(),checks=[],errors=[];let logs='',serial=0,invite,browser;
 const proc=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',new URL(base).port],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:path.join(tmp,'isolated.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 proc.stdout.on('data',d=>logs+=d);proc.stderr.on('data',d=>logs+=d);
 const api=async(c,p,d)=>{const r=d?await c.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data:d}):await c.request.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
 try{
  for(const [engine,driver] of [['chromium',chromium],['webkit',webkit]]){
   browser=await driver.launch({headless:true});
   for(const mobile of [true,false]){
    if(process.env.UX_ONLY&&process.env.UX_ONLY!==engine+'-'+(mobile?'phone':'desktop'))continue;console.log('journey '+engine+' '+mobile);
    const c=await browser.newContext({viewport:{width:mobile?393:1366,height:mobile?852:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'});
    for(let i=0;i<100;i++){try{await api(c,'/api/bootstrap');break;}catch{await pause(100);}}
    await api(c,'/api/register',{username:'ux_test_'+(++serial),nickname:'流程測試'+serial,password:'SyntheticJourney123',invite_code:invite});if(!invite)invite=(await api(c,'/api/state')).invite_code;
    const p=await c.newPage(),posts=[];p.on('pageerror',e=>errors.push(engine+' '+e.message));p.on('request',r=>{if(r.method()==='POST'&&/\/rooms\/\d+\/(leave|close|start)$/.test(r.url()))posts.push({path:new URL(r.url()).pathname,body:r.postDataJSON()});});
    const open=async id=>{await p.goto(base+'/#table/'+id);await p.waitForFunction(id=>room?.id===id&&liveReady,id);};
    const initialWallet=(await api(c,'/api/online/lobby')).wallet.balance;
    let r=await api(c,'/api/online/rooms',{game_type:'holdem',name:'流程測試・長桌名也要能操作',buy_in:1000,operation_id:crypto.randomUUID()});await open(r.id);
    for(const width of (mobile?[320,393,844]:[768,1366])){
     await p.setViewportSize({width,height:width===844?390:900});
     const g=await p.locator('[data-leave-table]').evaluate(e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height,font:parseFloat(getComputedStyle(e).fontSize),text:e.textContent,clickable:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),overflow:document.documentElement.scrollWidth>innerWidth+1};});
     assert.ok(g.w>=44&&g.h>=44&&g.font>=12&&g.clickable&&!g.overflow,JSON.stringify(g));assert.match(g.text,/離開牌桌/);assert.equal(await p.locator('[data-leave-table]').count(),1);
    }
    await p.setViewportSize({width:mobile?393:1366,height:mobile?852:900});
    await p.locator('[data-leave-table]').click();assert.equal(await p.locator('#confirm-no').innerText(),'繼續留桌');assert.ok(await p.locator('#confirm-no').evaluate(e=>e===document.activeElement));await p.keyboard.press('Escape');assert.equal(posts.length,0);
    assert.equal(await p.locator('#close-table').isVisible(),false);await p.locator('.table-manage summary').click();await p.locator('#close-table').click();assert.match(await p.locator('.confirm-dialog').innerText(),/所有玩家/);await p.locator('#confirm-no').click();assert.equal(posts.length,0);
    await p.locator('.table-manage summary').click();await p.locator('.room-heading').screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'-navigation.png')});
    await p.locator('#back-lobby').click();await p.waitForFunction(()=>view==='lobby'&&liveReady);assert.equal((await api(c,'/api/online/lobby')).current_room_id,r.id);assert.ok(await p.locator('.current-table-notice').isVisible());
    await p.evaluate(()=>go('stats'));await p.waitForFunction(()=>view==='stats');await p.locator('.current-table-notice a').click();await p.waitForFunction(id=>room?.id===id&&liveReady,r.id);assert.equal(posts.length,0,'Viewing lobby/stats must never send leave');
    await p.locator('[data-leave-table]').click();await p.locator('#confirm-yes').click();await p.waitForFunction(()=>view==='lobby'&&liveReady&&!busy&&!pendingOperation);assert.equal((await api(c,'/api/online/lobby')).current_room_id,null);assert.equal(await p.locator('.current-table-notice').count(),0);assert.equal((await api(c,'/api/online/lobby')).wallet.balance,initialWallet,'Waiting leave must return the complete buy-in');assert.equal(posts.filter(x=>x.path.endsWith('/leave')).length,1);
    // Hold a real spin response. Navigation must retain the receipt and button geometry.
    r=await api(c,'/api/online/rooms',{game_type:'slot',name:'慢回應流程測試',buy_in:1000,stake:10,operation_id:crypto.randomUUID()});await open(r.id);await p.evaluate(()=>{credentialsChanging=true;stopLive();});
    let release;const held=new Promise(resolve=>release=resolve),pattern='**/api/online/rooms/'+r.id+'/start';
    await p.route(pattern,async route=>{const response=await route.fetch();await held;await route.fulfill({response});});
    const before=await p.locator('#deal-hand').boundingBox();
    try{
     await p.locator('#deal-hand').click();await p.waitForFunction(()=>busy&&pendingOperation);const receipt=await p.evaluate(()=>pendingOperation.payload.operation_id);
     await p.locator('#back-lobby').click();assert.equal(await p.evaluate(()=>view),'table');assert.equal(await p.evaluate(()=>pendingOperation.payload.operation_id),receipt);
     await p.evaluate(()=>go('stats'));assert.equal(await p.evaluate(()=>view),'table');
     await p.evaluate(()=>location.hash='#stats');await p.waitForFunction(id=>location.hash==='#table/'+id,r.id);assert.equal(await p.evaluate(()=>pendingOperation.payload.operation_id),receipt);
     const pending=await p.locator('#deal-hand').boundingBox();assert.ok(Math.abs(before.y-pending.y)<2,'Pending feedback moved the spin action');assert.ok(await p.locator('[data-leave-table]').isDisabled());
    }finally{release();}
    await p.waitForFunction(()=>!busy&&!pendingOperation);await p.unroute(pattern);assert.equal(posts.filter(x=>x.path.endsWith('/'+r.id+'/start')).length,1);const spin=posts.find(x=>x.path.endsWith('/'+r.id+'/start'));const state=await api(c,'/api/online/rooms/'+r.id),replay=await api(c,'/api/online/rooms/'+r.id+'/start',spin.body);assert.equal(replay.state.wallet.total,state.wallet.total,'Receipt replay changed assets');assert.equal(replay.state.hand_no,state.hand_no);
    await p.evaluate(()=>{credentialsChanging=false;resumeConnections('ux-test');});await p.waitForFunction(()=>liveReady);assert.equal(await p.locator('[data-leave-table]').isDisabled(),false);
    // Server rejection must remain on the table and restore the leave control.
    const leave='**/api/online/rooms/'+r.id+'/leave';await p.route(leave,route=>route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'測試：此刻無法離桌，請再試一次。'})}));await p.locator('[data-leave-table]').click();await p.locator('#confirm-yes').click();await p.waitForFunction(()=>!busy&&!pendingOperation&&actionFeedback?.text==='測試：此刻無法離桌，請再試一次。');assert.equal(await p.evaluate(()=>view),'table');assert.equal(await p.locator('[data-leave-table]').isDisabled(),false,JSON.stringify(await p.evaluate(()=>({busy,pending:pendingOperation,seat:seated(),feedback:actionFeedback,html:document.querySelector('[data-leave-table]').outerHTML}))));await p.unroute(leave);
    await p.screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'-table.png'),fullPage:false});
    // A room may change while a confirmation dialog is open: never apply it elsewhere.
    await p.locator('[data-leave-table]').click();await p.evaluate(()=>go('lobby'));await p.waitForFunction(()=>view==='lobby');const leaveCount=posts.filter(x=>x.path.endsWith('/leave')).length;await p.locator('#confirm-yes').click();await pause(100);assert.equal(posts.filter(x=>x.path.endsWith('/leave')).length,leaveCount);await p.locator('.current-table-notice a').click();await p.waitForFunction(id=>room?.id===id&&liveReady,r.id);
    await p.locator('[data-leave-table]').click();await p.locator('#confirm-yes').click();await p.waitForFunction(()=>view==='lobby'&&!busy&&!pendingOperation);
    // An unknown leave receipt later confirmed by a snapshot must complete the same navigation.
    r=await api(c,'/api/online/rooms',{game_type:'holdem',name:'離桌收據恢復',buy_in:1000,operation_id:crypto.randomUUID()});await open(r.id);await p.evaluate(()=>{credentialsChanging=true;stopLive();});
    const unknown='**/api/online/rooms/'+r.id+'/leave';let first=true;await p.route(unknown,async route=>{if(first){first=false;await route.fetch();}await route.abort();});
    await p.locator('[data-leave-table]').click();await p.locator('#confirm-yes').click();await p.waitForFunction(()=>!busy&&pendingOperation&&actionFeedback?.error);const original=await p.evaluate(()=>pendingOperation.payload.operation_id);const accepted=await api(c,'/api/online/rooms/'+r.id);assert.ok(accepted.accepted_operations.includes(original));await p.evaluate(next=>applyState(next,false,false,'late-receipt-test'),accepted);await p.waitForFunction(()=>view==='lobby'&&!pendingOperation);await p.unroute(unknown);await p.evaluate(()=>{credentialsChanging=false;resumeConnections('late-ack-test');});await p.waitForFunction(()=>liveReady);
    r=await api(c,'/api/online/rooms',{game_type:'holdem',name:'房主管理結束測試',buy_in:1000,operation_id:crypto.randomUUID()});await open(r.id);await p.locator('.table-manage summary').click();await p.locator('#close-table').click();await p.locator('#confirm-yes').click();await p.waitForFunction(()=>view==='lobby'&&!busy&&!pendingOperation);assert.equal((await api(c,'/api/online/rooms/'+r.id)).status,'closed');
    // A confirmed active blackjack departure returns to the lobby but keeps its seat until settlement.
    const peers=[];for(let k=0;k<2;k++){const peer=await browser.newContext();await api(peer,'/api/register',{username:'ux_peer_'+(++serial),nickname:'同桌測試'+serial,password:'SyntheticJourney123',invite_code:invite});peers.push(peer);}
    r=await api(c,'/api/online/rooms',{game_type:'blackjack',name:'離桌結算測試',buy_in:1000,stake:20,operation_id:crypto.randomUUID()});for(const peer of peers)await api(peer,'/api/online/rooms/'+r.id+'/join',{buy_in:1000,operation_id:crypto.randomUUID()});
    let active;for(let attempt=0;attempt<8;attempt++){const waiting=await api(c,'/api/online/rooms/'+r.id);const next=waiting.hand_no+1;const delay=Math.max(0,((waiting.next_hand_at||0)-waiting.server_time)*1000);if(delay)await pause(delay+25);for(const who of [c,...peers])await api(who,'/api/online/rooms/'+r.id+'/start',{stake:20,expected_hand_number:next,operation_id:crypto.randomUUID()});active=await api(c,'/api/online/rooms/'+r.id);if(active.status==='playing')break;}assert.equal(active.status,'playing');
    await open(r.id);await p.locator('[data-leave-table]').click();assert.match(await p.locator('.confirm-dialog').innerText(),/自動停牌/);assert.doesNotMatch(await p.locator('.confirm-dialog').innerText(),/大老二/);await p.locator('#confirm-yes').click();await p.waitForFunction(()=>view==='lobby'&&liveReady&&!busy&&!pendingOperation);
    let after=await api(c,'/api/online/rooms/'+r.id);const uid=(await api(c,'/api/online/lobby')).me.id;
    if(after.status==='playing'){
     assert.equal(after.seats.find(s=>s.user_id===uid).leaving,true);assert.match(await p.locator('.current-table-notice').innerText(),/結算後離桌/);await p.locator('.current-table-notice a').click();await p.waitForFunction(id=>room?.id===id&&liveReady,r.id);assert.ok(await p.locator('[data-leave-table]').isDisabled());
    }
    const memberContexts=new Map();for(const who of peers)memberContexts.set((await api(who,'/api/online/lobby')).me.id,who);
    for(let turn=0;turn<20&&after.status==='playing';turn++){const who=memberContexts.get(after.hand.actor);assert.ok(who,'Departed player must not retain an active decision');await api(who,'/api/online/rooms/'+r.id+'/action',{action:'stand',hand_id:after.hand.id,turn_id:after.hand.turn_id,operation_id:crypto.randomUUID()});after=await api(c,'/api/online/rooms/'+r.id);}
    assert.equal(after.status,'waiting');assert.ok(!after.seats.some(s=>s.user_id===uid));assert.equal(after.current_room_id,null);for(const peer of peers)await peer.close();
    checks.push({engine,mobile,clear_leave:true,cancel_and_escape:true,owner_menu:true,lobby_retains_seat:true,cross_page_return:true,confirmed_leave_returns_lobby:true,pending_navigation_retains_receipt:true,stable_pending_button:true,same_receipt_replay:true,rejected_leave_stays:true,stale_dialog_safe:true,active_departure_settles:true,late_leave_receipt:true,owner_close:true});await c.close();
   }
   await browser.close();browser=null;
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser?.close();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
