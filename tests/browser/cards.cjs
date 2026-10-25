/* Card loading, backs and legibility on real components; isolated accounts/database. */
const {chromium,webkit}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/cards'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 fs.mkdirSync(out,{recursive:true});const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));const base='http://127.0.0.1:'+port;
 const db=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-cards-')),'isolated.sqlite3'),server=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8',POKER_DB:db,POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:''}}),browsers=[],checks=[],errors=[];let logs='',invite,serial=0;
 server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 const api=async(c,p,data)=>{const r=data?await c.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data}):await c.request.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
 try{
  for(const [engine,driver] of [['chromium',chromium],['webkit',webkit]]){
   const browser=await driver.launch({headless:true});browsers.push(browser);
   for(const mobile of [true,false]){
    const c=await browser.newContext({viewport:{width:mobile?393:1366,height:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'});
    let ready=false;for(let i=0;i<100;i++){try{await api(c,'/api/bootstrap');ready=true;break;}catch{await sleep(100);}}assert.ok(ready);
    await api(c,'/api/register',{username:'cards_test_'+(++serial),nickname:'人物牌測試',password:'SyntheticCards123',invite_code:invite});if(!invite)invite=(await api(c,'/api/state')).invite_code;
    const p=await c.newPage();p.on('pageerror',e=>errors.push(engine+' '+mobile+' '+e.message));await p.goto(base+'/#lobby');await p.waitForFunction(()=>lobby&&liveReady);await p.evaluate(()=>{credentialsChanging=true;stopLive();document.querySelector('#app').innerHTML='<main id="main"><section class="panel" id="card-loading-fixture"></section></main>';});
    let releaseA,releaseK;const heldA=new Promise(r=>releaseA=r),heldK=new Promise(r=>releaseK=r);
    await p.route('**/assets/cards/as.webp?*',async r=>{await heldA;await r.continue();});await p.route('**/assets/cards/kh.webp?*',async r=>{await heldK;await r.continue();});
    await p.evaluate(()=>document.querySelector('#card-loading-fixture').innerHTML=card('As'));
    const state=()=>p.locator('#card-loading-fixture .playing-card').evaluate(e=>({code:e.dataset.photoCard,state:e.dataset.faceState,photo:getComputedStyle(e,'::before').visibility,paper:getComputedStyle(e).backgroundImage,label:e.getAttribute('aria-label'),width:e.offsetWidth,height:e.offsetHeight}));
    let before=await state();assert.equal(before.state,'loading');assert.equal(before.photo,'hidden');assert.equal(before.paper,'none');assert.equal(before.label,'A♠');
    await p.evaluate(()=>{const t=document.createElement('template');t.innerHTML=card('Kh');patchNode(document.querySelector('#card-loading-fixture .playing-card'),t.content.firstElementChild);});
    releaseA();await p.waitForFunction(()=>ClubArt.cardState('As')==='ready');let pending=await state();assert.equal(pending.code,'Kh');assert.equal(pending.state,'loading');assert.equal(pending.photo,'hidden','Old decode must not reveal the new card');assert.equal(pending.label,'K♥');
    releaseK();await p.waitForFunction(()=>document.querySelector('#card-loading-fixture .playing-card').dataset.faceState==='ready');let after=await state();assert.equal(after.photo,'visible');assert.deepEqual([after.width,after.height],[before.width,before.height]);
    await p.unroute('**/assets/cards/as.webp?*');await p.unroute('**/assets/cards/kh.webp?*');await p.route('**/assets/cards/jd.webp?*',r=>r.abort());await p.evaluate(()=>document.querySelector('#card-loading-fixture').innerHTML=card('Jd'));await p.waitForFunction(()=>document.querySelector('#card-loading-fixture .playing-card').dataset.faceState==='failed');const failed=await state();assert.equal(failed.paper,'none');assert.equal(failed.photo,'hidden');assert.equal(failed.label,'J♦');assert.equal(await p.evaluate(()=>busy),false);await p.unroute('**/assets/cards/jd.webp?*');
    // The identical inherited back is used by every table, deck marker and flight layer.
    for(const back of ['', 'jade','crimson']){
     const backs=await p.evaluate(back=>{document.documentElement.dataset.cardBack=back;const host=document.querySelector('#card-loading-fixture');host.innerHTML=['holdem-room','arcade-blackjack','arcade-big2','arcade-baccarat','arcade-inbetween'].map(k=>'<div class="'+k+'">'+card(null)+'</div>').join('')+'<div class="arcade-deck"><span>♠</span></div><div class="big2-stack"><i></i></div>';const list=[...host.querySelectorAll('.covered,.arcade-deck>span,.big2-stack>i')];for(const id of ['deal-layer','arcade-motion-layer']){const t=document.createElement('template');t.innerHTML=card(null);const el=t.content.firstElementChild;document.getElementById(id).append(el);list.push(el);}const values=list.map(e=>({image:getComputedStyle(e).backgroundImage,color:getComputedStyle(e).backgroundColor,face:e.dataset.photoCard||null}));for(const id of ['deal-layer','arcade-motion-layer'])document.getElementById(id).replaceChildren();return values;},back);
     assert.equal(new Set(backs.map(b=>b.image)).size,1,engine+' '+back+' all backs must match '+JSON.stringify(backs.map((b,i)=>({i,image:b.image.slice(0,120)}))));assert.ok(backs.every(b=>!b.face));assert.ok(backs[0].image.includes(back?'data:image/svg':'card-back-friends.webp'));
    }
    await p.evaluate(()=>document.documentElement.dataset.cardBack='');
    const r=await api(c,'/api/online/rooms',{game_type:'blackjack',buy_in:1000,stake:20,operation_id:crypto.randomUUID()});await api(c,'/api/online/rooms/'+r.id+'/start',{stake:20,expected_hand_number:1,operation_id:crypto.randomUUID()});await p.evaluate(id=>{credentialsChanging=false;go(id);},r.id);await p.waitForFunction(id=>room?.id===id&&liveReady,r.id);await p.evaluate(()=>{credentialsChanging=true;stopLive();window.cardsFixture=structuredClone(room);});
    let cases=0;
    for(const width of mobile?[320,393]:[768,1366]){
     await p.setViewportSize({width,height:900});
     for(const count of [2,3,4,5])for(const split of [1,2,4]){
      await p.evaluate(({count,split})=>{const r=structuredClone(window.cardsFixture);r.status='playing';r.hand.phase='blackjack';r.hand.actor=me().id;r.hand.active_index=0;r.legal={actions:['hit','stand','double','split'],active_index:0};r.hand.dealer=['9d',null];const own=r.hand.players.find(q=>q.user_id===me().id);own.hands=Array.from({length:split},()=>({cards:['2s','3h','4d','5c','6s'].slice(0,count),bet:20,status:'playing',split:split>1}));r.hand.players=[own,{...structuredClone(own),user_id:999,nickname:'同桌玩家'}];document.querySelector('#app').innerHTML='<main id="main">'+ClubArcade.table(r,me(),{card,icon,feedback:''})+'</main>';}, {count,split});
      await p.waitForFunction(()=>[...document.querySelectorAll('[data-photo-card]')].every(e=>e.dataset.faceState==='ready'));
      const geometry=await p.evaluate(()=>({viewport:innerWidth,pageWidth:document.documentElement.scrollWidth,own:[...document.querySelectorAll('.blackjack-hands .playing-card')].map(e=>e.getBoundingClientRect().width),rows:[...document.querySelectorAll('.blackjack-cards')].map(row=>{const r=row.getBoundingClientRect(),cards=[...row.children].map(e=>e.getBoundingClientRect());return {rowWidth:r.width,right:Math.max(...cards.map(c=>c.right))-r.left,lines:new Set(cards.map(c=>Math.round(c.top))).size};}),dealer:[...document.querySelectorAll('.blackjack-dealer .playing-card')].map(e=>e.offsetWidth)}));
      assert.ok(geometry.pageWidth<=geometry.viewport+1,engine+' card page overflow '+JSON.stringify({width,count,split,geometry}));assert.ok(geometry.own.every(w=>w>=(mobile?64:96)-1));assert.ok(geometry.dealer.every(w=>w>=59));for(const row of geometry.rows){assert.ok(row.right<=row.rowWidth+1,engine+' hand overflow '+JSON.stringify({width,count,split,row}));assert.equal(row.lines,1,'Keep a hand together');}cases++;
      if(split===1&&[2,5].includes(count)&&width===(mobile?393:1366))await p.locator('.arcade-surface').screenshot({path:path.join(out,engine+'-'+(mobile?'phone':'desktop')+'-'+count+'-cards.png')});
     }
    }
    for(const width of mobile?[320,393]:[768,1366]){
     await p.setViewportSize({width,height:900});await p.evaluate(()=>{const r=structuredClone(window.cardsFixture);r.game_type='baccarat';r.status='waiting';r.hand.phase='showdown';r.hand.summary='百家樂 · 合成版面';r.hand.player_cards=['2s','3h','4d'];r.hand.banker_cards=['5c','6s','Ah'];r.hand.player_total=9;r.hand.banker_total=2;delete r.next_game_settings;delete r.hand.game_settings;document.querySelector('#app').innerHTML='<main id="main">'+ClubArcade.table(r,me(),{card,icon,feedback:''})+'</main>';});
     await p.waitForFunction(()=>[...document.querySelectorAll('[data-photo-card]')].every(e=>e.dataset.faceState==='ready'));
     const groups=await p.evaluate(()=>[...document.querySelectorAll('.baccarat-cards')].map(row=>{const box=row.getBoundingClientRect();return {width:box.width,cards:[...row.children].map(c=>{const r=c.getBoundingClientRect();return {width:r.width,left:r.left-box.left,right:r.right-box.left};})};}));
     for(const group of groups){assert.equal(group.cards.length,3);assert.ok(group.cards.every(c=>c.width>=51&&c.left>=-1&&c.right<=group.width+1),engine+' baccarat overflow '+JSON.stringify({width,group}));}
     if(width===(mobile?393:1366))await p.locator('.arcade-surface').screenshot({path:path.join(out,engine+'-baccarat-'+(mobile?'phone':'desktop')+'.png')});
    }
    checks.push({engine,mobile,loading:true,stale_decode:true,failed_image:true,backs:27,blackjack_cases:cases,baccarat_cases:2});await c.close();
   }
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{for(const b of browsers)await b.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
