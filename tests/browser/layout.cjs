/* Release layout checks use disposable accounts/database, never the live server. */
const {chromium,webkit}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/layout');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const only=new Set((process.env.LAYOUT_ONLY||'').split(',').filter(Boolean));
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-layout-')),db=path.join(dir,'isolated.sqlite3'),port=await freePort(),base='http://127.0.0.1:'+port,python=process.env.PYTHON||'python';
 const proc=spawn(python,['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:db,POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});
 let logs='',serial=0,invite;const browsers=[],accounts=[],results=[],errors=[];
 proc.stdout.on('data',d=>logs+=d);proc.stderr.on('data',d=>logs+=d);
 try{
  browsers.push(['chromium',await chromium.launch({headless:true})],['webkit',await webkit.launch({headless:true})]);
  const api=async(c,p,d)=>{const r=d?await c.request.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data:d}):await c.request.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
  const account=async()=>{const c=await browsers[0][1].newContext();accounts.push(c);const id=++serial;await api(c,'/api/register',{username:'layout_test_'+id,nickname:'排版測試'+id,password:'SyntheticLayout123',invite_code:invite});if(!invite)invite=(await api(c,'/api/state')).invite_code;return c;};
  const ready=await browsers[0][1].newContext();accounts.push(ready);
  for(let i=0;i<100;i++){try{await api(ready,'/api/bootstrap');break;}catch{await pause(100);}}
  const admin=await account();
  // Only this freshly created disposable SQLite file receives the test role.
  const seeded=spawnSync(python,['-c','import sqlite3,sys,time; d=sqlite3.connect(sys.argv[1]); d.execute("INSERT INTO club_admins(user_id,password_change_required,created_at) VALUES(1,0,?)",(time.time(),)); d.commit()',db],{cwd:root,windowsHide:true,encoding:'utf8'});
  assert.equal(seeded.status,0,seeded.stderr);
  const member=await account();
  async function checkRoute(owner,route,name,selector){
   if(only.size&&!only.has(name))return;
   const storageState=await owner.storageState();let inspected=0;
   for(const [engine,browser] of browsers){
    for(const mobile of [true,false]){
     const context=await browser.newContext({storageState,isMobile:mobile,hasTouch:mobile,viewport:{width:mobile?393:1366,height:900},reducedMotion:'reduce'});
     const page=await context.newPage();
     page.on('pageerror',e=>{errors.push(engine+' '+name+': '+e.message);console.error('page error: '+engine+' '+name+' '+e.message);});
     page.on('response',r=>{if(['script','stylesheet','image'].includes(r.request().resourceType())&&r.status()>=400)errors.push(engine+' '+r.status()+' '+r.url());});
     await page.goto(base+'/#'+route);await page.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);
     if(selector)try{await page.waitForSelector(selector,{timeout:10000});}catch(e){await page.screenshot({path:path.join(out,'failure-'+engine+'-'+name+'.png')});throw e;}
     await page.evaluate(()=>document.fonts.ready);await pause(120);
     await require('./table-controls.cjs')(page,engine,mobile,name,out);
     await require('./gate-protection-checks.cjs')(page,name);await require('./blackjack-fairness-checks.cjs')(page,name);
     if(name==='holdem'){const colors=await page.evaluate(()=>{const html=document.documentElement,old=html.dataset.cardBack,card=document.querySelector('.playing-card.covered'),values={};for(const key of ['jade','crimson']){html.dataset.cardBack=key;values[key]=getComputedStyle(card).backgroundColor;}if(old===undefined)delete html.dataset.cardBack;else html.dataset.cardBack=old;return values;});assert.deepEqual(colors,{jade:'rgb(22, 75, 63)',crimson:'rgb(101, 42, 58)'},'Equipped card backs must override the default theme');}
     if(name==='gate'){
      const choices=page.locator('[data-gate-direction]:not(:disabled)');
      if(await choices.count())await choices.first().click();
      const expected=await page.evaluate(()=>{const q=room.hand.gate_quotes[room.hand.direction||((room.hand.gate_quotes||{}).between?'between':document.querySelector('[data-gate-direction][aria-pressed=true]')?.dataset.gateDirection)];return q?(100*(q.win_numerator??q.winning_cards)/(q.win_denominator??q.total_cards)).toFixed(1).replace(/\.0$/,'')+'%':'0%';});
      assert.equal(await page.locator('#gate-chance').innerText(),expected);
      assert.match(await page.locator('.gate-mode-note').allTextContents().then(a=>a.join(' ')),/本副牌第 2 局/);
     }
     if(name==='slot'&&engine==='chromium'&&mobile){
      const y=await page.locator('#deal-hand').evaluate(e=>e.getBoundingClientRect().top);
      for(let spin=0;spin<3;spin++){const before=await page.evaluate(()=>room.hand_no);await page.locator('#deal-hand').click();await page.waitForFunction(n=>room.hand_no>n&&!busy&&!pendingOperation,before);assert.ok(Math.abs((await page.locator('#deal-hand').evaluate(e=>e.getBoundingClientRect().top))-y)<2,'Slot start button moved after result');}
     }
     const sizes=mobile?[[320,800],[375,812],[393,852],[844,390]]:[[768,1024],[1366,900],[1920,1080]];
     if(name==='gate')sizes.push([760,740],[761,740],[800,740],[1000,740],[1024,768]);
     for(const [width,height] of sizes){
      await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));await pause(40);
      const snapshot=await page.evaluate(()=>[...document.querySelectorAll('button,.playing-card,.slot-reel,.die-face,.mj-tile,.game-art,.table-arena,.arcade-surface,.table-control-area')].map((e,i)=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {i,id:e.id,class:e.className,label:e.getAttribute('aria-label'),x:r.x,y:r.y,width:r.width,height:r.height,color:s.color,font:s.fontSize};}));
      fs.writeFileSync(path.join(out,`${engine}-${name}-${width}-${height}-geometry.json`),JSON.stringify(snapshot));
      const m=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,broken:[...document.images].filter(i=>i.complete&&!i.naturalWidth).map(i=>i.src),main:!!document.querySelector('#main')}));
      if(m.scroll>m.width+1){await page.screenshot({path:path.join(out,`${engine}-${name}-${width}-overflow.png`),fullPage:true});const overflowing=await page.evaluate(()=>[...document.querySelectorAll('#main *')].map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,class:e.className,right:r.right,width:r.width};}).filter(e=>e.width>0&&e.right>innerWidth+1).slice(-20));fs.writeFileSync(path.join(out,`${engine}-${name}-${width}-overflow.json`),JSON.stringify(overflowing,null,2));}
      assert.ok(m.main,name+' missing main');assert.ok(m.scroll<=m.width+1,engine+' '+name+' overflow '+JSON.stringify(m));assert.deepEqual(m.broken,[],engine+' '+name+' broken images');
      if(name==='slot'){
       await page.waitForFunction(()=>[...document.querySelectorAll('.slot-reel .current-art')].every(i=>i.complete&&i.naturalWidth));
       for(const scale of ['100%','130%']){
        await page.evaluate(s=>{document.documentElement.style.fontSize=s;scrollTo(0,0);},scale);
        const before=await page.locator('#deal-hand').evaluate(e=>e.getBoundingClientRect().top);
        await page.evaluate(()=>{pendingOperation={action:'start'};feedback('連線中斷，正在確認這筆操作。請確認原本的操作結果，避免重複下注。'.repeat(3),true);});
        const g=await page.evaluate(()=>{const a=document.querySelector('#retry-operation'),r=a.getBoundingClientRect(),f=document.querySelector('#action-feedback').getBoundingClientRect(),h=document.querySelector('.topbar').getBoundingClientRect(),d=document.querySelector('#deal-hand').getBoundingClientRect();return {height:r.height,inside:r.top>=f.top&&r.bottom<=f.bottom,headerClear:r.top>=h.bottom,spinTop:d.top,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth};});
        assert.ok(g.height>=44&&g.inside&&g.headerClear,engine+' slot recovery control obscured '+JSON.stringify(g));
        assert.ok(Math.abs(g.spinTop-before)<2,engine+' slot spin button moved on error');
        assert.ok(g.scroll<=g.width+1,engine+' slot error overflows at '+scale);
        await page.locator('#retry-operation').scrollIntoViewIfNeeded();
        assert.ok(await page.locator('#retry-operation').evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'Slot retry cannot be tapped');
        await page.evaluate(()=>{pendingOperation=null;actionFeedback=null;refreshControls();document.documentElement.style.fontSize='';scrollTo(0,0);});
       }
      }
      if(name==='holdem'){
       assert.equal(await page.locator('.is-me .seat-cards .playing-card').count(),2);
       const g=await page.evaluate(()=>({captionBottom:document.querySelector('.spot-3 .seat-caption').getBoundingClientRect().bottom,potTop:document.querySelector('.pot-total').getBoundingClientRect().top,boardBottom:document.querySelector('.community-cards').getBoundingClientRect().bottom,holeTop:Math.min(...[...document.querySelectorAll('.is-me .seat-cards .playing-card')].map(e=>e.getBoundingClientRect().top))}));
       const cards=await page.evaluate(()=>({own:[...document.querySelectorAll('.is-me .seat-cards .playing-card')].map(e=>e.offsetWidth),board:[...document.querySelectorAll('.community-cards>*')].map(e=>e.offsetWidth)}));
       if(width>=1024){assert.ok(cards.own.every(w=>w>=110),'desktop hold’em hand size '+JSON.stringify(cards));assert.ok(cards.board.every(w=>w>=59),'desktop community size '+JSON.stringify(cards));}
       if(width<=760){assert.ok(cards.own.every(w=>w===76),'mobile hold’em cards stay unchanged');}
       assert.ok(g.captionBottom+2<=g.potTop,engine+' '+width+' top seat overlaps pot '+JSON.stringify(g));
       assert.ok(g.boardBottom+2<=g.holeTop,engine+' '+width+' hole cards overlap community '+JSON.stringify(g));
      }
      if(width===393||width===1366||width===844&&name==='holdem')await page.screenshot({path:path.join(out,engine+'-'+name+'-'+width+'.png')});
      inspected++;
     }
     if(name==='slot'&&mobile){
      const fallback=await context.newPage();
      fallback.on('pageerror',e=>errors.push(engine+' slot fallback: '+e.message));
      await fallback.route('**/assets/pieces/*',r=>r.abort());
      await fallback.goto(base+'/#'+route);await fallback.waitForSelector('.slot-reel .current-art[data-art-failed]',{state:'attached'});await pause(150);
      assert.equal(await fallback.locator('.slot-reel svg').count(),0,'Retired artwork must never return on failure');
      assert.equal(await fallback.locator('.slot-reel .current-art[data-art-failed]').count(),3,'Failed current images retain a labelled placeholder');
      await fallback.close();
     }
     if(name==='lobby'&&!mobile)await require('./round4-checks.cjs')(page,engine,out);
     await context.close();
    }
   }
   results.push({name,route,viewports:inspected});console.log('layout OK: '+name+' ('+inspected+' views)');
  }
  for(const [route,name,selector] of [['lobby','lobby','#lobby-games'],['stats','ranking','.rank-row'],['members','members','.member-panel'],['clubhouse','clubhouse','.clubhouse-scene'],['rewards','rewards','.rewards-hub'],['collection','collection','.collection-card'],['profile','profile','#profile-console'],['bank','bank','#bank-amount'],['wallet','transfers','#transfer-form'],['admin','admin','#admin-console']])await checkRoute(route==='admin'?admin:member,route,name,selector);
  const games=[['holdem',6,'.table-arena'],['big2',4,'.arcade-surface'],['blackjack',6,'.blackjack-player'],['mahjong',4,'.mj-table'],['roulette',1,'.roulette-stage'],['baccarat',1,'.arcade-surface'],['slot',1,'.slot-machine'],['mines',1,'.risk-cell'],['tower',1,'.tower-floor'],['dice',2,'.dice-board'],['inbetween',1,'.gate-board']];
  for(const [kind,count,selector] of games){
   if(only.size&&!only.has(kind==='inbetween'?'gate':kind))continue;
   const members=[];for(let i=0;i<count;i++)members.push(await account());const owner=members[0];
   const room=await api(owner,'/api/online/rooms',{game_type:kind,buy_in:kind==='mahjong'?2000:1000,stake:kind==='big2'?10:20,name:'整合排版 '+kind,operation_id:crypto.randomUUID()}),rp='/api/online/rooms/'+room.id;
   for(let i=1;i<count;i++)await api(members[i],rp+'/join',{buy_in:kind==='mahjong'?2000:1000,operation_id:crypto.randomUUID()});
   if(kind==='blackjack'){for(const member of members)await api(member,rp+'/start',{stake:20,expected_hand_number:1,operation_id:crypto.randomUUID()});}
   else if(kind!=='slot')await api(owner,rp+'/start',{stake:20,operation_id:crypto.randomUUID()});
   if(kind==='inbetween'){
    let h=(await api(owner,rp)).hand;const shoe=h.shoe_id;
    await api(owner,rp+'/action',{action:'skip',hand_id:h.id,turn_id:h.turn_id,operation_id:crypto.randomUUID()});
    await api(owner,rp+'/start',{operation_id:crypto.randomUUID()});h=(await api(owner,rp)).hand;assert.equal(h.shoe_id,shoe);assert.equal(h.shoe_round,2);assert.equal(h.remaining_cards,48);
   }
   await checkRoute(owner,'table/'+room.id,kind==='inbetween'?'gate':kind,selector);
   if(kind==='inbetween'){
    let r=await api(owner,rp);if(r.legal?.actions.includes('shoot')){const request={action:'shoot',direction:r.legal.directions[0],stake:20,hand_id:r.hand.id,turn_id:r.hand.turn_id,operation_id:crypto.randomUUID()};await api(owner,rp+'/action',request);const stack=(await api(owner,rp)).seats[0].stack;assert.equal((await api(owner,rp+'/action',request)).replayed,true);assert.equal((await api(owner,rp)).seats[0].stack,stack);}
   }
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({results,errors,scope:'Chromium/WebKit engines; responsive/touch emulation, not physical phones'},null,2));console.log('Release layout checks passed: '+results.length+' pages, '+results.reduce((n,x)=>n+x.viewports,0)+' views');
 }finally{for(const [,b] of browsers)await b.close();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);fs.writeFileSync(path.join(out,'errors.json'),JSON.stringify(errors,null,2));}
})().catch(e=>{console.error(e);process.exitCode=1;});
