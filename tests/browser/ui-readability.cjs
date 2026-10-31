const {chromium,webkit}=require('playwright');
const {spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),phase=process.env.AUDIT_PHASE||'after',out=path.join(root,'artifacts/ui-readability',phase);fs.mkdirSync(out,{recursive:true});
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'readability-')),probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const base='http://127.0.0.1:'+port,server=spawn('python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_DB:path.join(dir,'test.sqlite3'),POKER_MARKET_DATA:'0',POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONUTF8:'1'}});let logs='',browser,invite;const result=[];server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{for(const [engine,driver] of [['chromium',chromium],['webkit',webkit]]){
 browser=await driver.launch({headless:true});const c=await browser.newContext({viewport:{width:393,height:852},reducedMotion:'reduce'}),p=await c.newPage();
 for(let i=0;i<100;i++){try{if((await c.request.get(base+'/api/bootstrap')).ok())break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const reg=await c.request.post(base+'/api/register',{headers:{'X-Requested-With':'PokerClub'},data:{username:'readability_'+engine,nickname:'這是一個比較長的好友暱稱',password:'SyntheticReadability123',invite_code:invite}});assert.equal(reg.status(),200);invite??=(await(await c.request.get(base+'/api/state')).json()).invite_code;
 for(const route of ['lobby','rewards','collection','clubhouse','bank','lottery','market'].filter(r=>!process.env.READABILITY_ONLY||process.env.READABILITY_ONLY.split(',').includes(r))){
 await p.goto(base+'/#'+route);await p.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);await p.evaluate(()=>document.fonts.ready);
 for(const width of [320,393,768,1366]){
 await p.setViewportSize({width,height:852});await p.evaluate(()=>scrollTo(0,0));await p.waitForTimeout(100);
 const audit=await p.evaluate(()=>{
 const reminder=document.querySelector('.reminder-readable'),style=getComputedStyle(reminder),bg=getComputedStyle(document.querySelector('.play-reminder'));
 const lum=c=>{const a=c.match(/[\d.]+/g).slice(0,3).map(x=>{x=Number(x)/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;});return a[0]*.2126+a[1]*.7152+a[2]*.0722;};const a=lum(style.color),b=lum(bg.backgroundColor);
 const targets=[...document.querySelectorAll('.topbar button,.topbar a')].filter(e=>e.checkVisibility()).map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e,'::after'),n=k=>parseFloat(s[k])||0,l=r.left+Math.min(0,n('left')),t=r.top+Math.min(0,n('top')),right=r.right-Math.min(0,n('right')),bottom=r.bottom-Math.min(0,n('bottom'));const hits=[[l+2,t+2],[right-2,t+2],[l+2,bottom-2],[right-2,bottom-2]].map(([x,y])=>e.contains(document.elementFromPoint(x,y)));return {id:e.id||e.className,width:r.width,height:r.height,effectiveWidth:right-l,effectiveHeight:bottom-t,left:l,right,cornerHits:hits.filter(Boolean).length};});
 return {overflow:document.documentElement.scrollWidth>innerWidth+1,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),targets,broken:[...document.images].filter(i=>i.complete&&!i.naturalWidth).map(i=>i.src),titlePadding:document.querySelector('.title-bonus-summary')?getComputedStyle(document.querySelector('.title-bonus-summary')).padding:null};
 });result.push({engine,route,width,...audit});assert.equal(audit.overflow,false);assert.deepEqual(audit.broken,[]);
 if(phase==='after'){assert.ok(audit.contrast>=4.5,'reminder contrast');if(route==='collection')assert.ok(parseFloat(audit.titlePadding)>=16,'title card padding');if(width<=393)for(const t of audit.targets){assert.ok(t.effectiveWidth>=43.5&&t.effectiveHeight>=43.5,'expanded header touch target');assert.equal(t.cornerHits,4,'header target corners remain tappable');}}
 if(width===393||width===1366)await p.screenshot({path:path.join(out,`${engine}-${route}-${width}.png`)});
 }
 if(phase==='after'){
  await p.setViewportSize({width:320,height:852});
  await p.evaluate(()=>{const nodes=[...document.querySelectorAll('#main *')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(e=>[e,parseFloat(getComputedStyle(e).fontSize)]);for(const [e,size]of nodes)e.style.fontSize=size*1.3+'px';});
  await p.waitForTimeout(200);
  const wide=await p.evaluate(()=>[...document.querySelectorAll('#main *')].filter(e=>e.checkVisibility()).map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,cls:e.className,text:(e.innerText||'').slice(0,70),left:r.left,right:r.right,width:r.width};}).filter(e=>e.right>innerWidth+1));
  fs.writeFileSync(path.join(out,`${engine}-${route}-large-text-geometry.json`),JSON.stringify(wide,null,2));
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route+' enlarged text overflow');
  await p.screenshot({path:path.join(out,`${engine}-${route}-320-large-text.png`)});
  if(route==='collection'){await p.locator('[data-open-title-rewards]').click();await p.waitForSelector('[data-hub-panel=titles]:not([hidden])');assert.equal(await p.locator('[data-hub-tab=titles]').getAttribute('aria-pressed'),'true');}
 }
 }
 await c.close();await browser.close();browser=null;
 }fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2));console.log(`${phase}: ${result.length} page/viewport checks complete`);
 }finally{await browser?.close();server.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
