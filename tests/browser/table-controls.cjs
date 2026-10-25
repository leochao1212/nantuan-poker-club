/* Interaction regressions run only inside layout.cjs's disposable server. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
module.exports=async function tableControls(page,engine,mobile,name,out){
 if(!await page.locator('.live-room,.mj-room').count())return;
 const viewport=page.viewportSize();
 if(await page.locator('[data-leave-table]').count()){
  await page.locator('[data-leave-table]').click();
  assert.match(await page.locator('#modal-title').innerText(),/確定離開牌桌/);
  await page.locator('#confirm-no').click();
 }
 if(['slot','gate','baccarat'].includes(name)&&await page.locator('[data-table-help]').count()){
  await page.locator('[data-table-help]').first().click();
  assert.ok(await page.locator('#modal .table-help-dialog').isVisible());
  assert.ok((await page.locator('#modal .table-help-dialog').innerText()).length>10);
  await page.locator('#modal [data-close]').click();
 }
 if(mobile&&['dice','roulette'].includes(name)){
  const selector=name==='dice'?'#dice-roll':'#roulette-confirm';
  const bet=name==='dice'?'[data-dice-bet]':'[data-roulette]';
  for(const width of [320,393]){
   await page.setViewportSize({width,height:660});
   const empty=await page.locator(selector).evaluate(b=>{const r=b.getBoundingClientRect();return {top:r.top,position:getComputedStyle(b.closest('.bet-submit-bar')).position};});
   assert.equal(empty.position,'fixed','Empty draft keeps the same dock');
   assert.equal(await page.locator(selector).count(),1,'Only one submit button');
   await page.locator(bet).first().click();
   assert.ok(Math.abs((await page.locator(selector).boundingBox()).y-empty.top)<1,'Selection must not relocate submit');
   await page.locator(bet).last().scrollIntoViewIfNeeded();
   const geometry=()=>page.locator(selector).evaluate(b=>{const r=b.getBoundingClientRect();return {top:r.top,bottom:r.bottom,position:getComputedStyle(b.closest('.bet-submit-bar')).position,disabled:b.disabled,targetHeight:r.height,height:innerHeight};});
   const before=await geometry();assert.ok(before.targetHeight>=44,'Submit must keep a 44px touch target');let requests=0;
   await page.route('**/api/online/rooms/*/action',async route=>{requests++;await pause(900);await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Synthetic delayed response'})});});
   try{
    await page.locator(selector).click();await page.waitForFunction(()=>busy);await pause(80);
    const pending=await geometry();
    assert.equal(pending.position,'fixed',name+' dock collapsed during submission');
    assert.ok(pending.disabled&&pending.top>=0&&pending.bottom<=pending.height,name+' pending control left viewport');
    assert.ok(Math.abs(before.top-pending.top)<1,name+' pending button moved');
    await page.waitForFunction(()=>!busy&&!pendingOperation);
    const restored=await geometry();assert.ok(Math.abs(before.top-restored.top)<1,name+' error moved button');
    assert.equal(requests,1,'One tap must create one submission');
    fs.writeFileSync(path.join(out,`${engine}-${name}-${width}-pending.json`),JSON.stringify({before,pending,restored,requests},null,2));
   }finally{await page.unroute('**/api/online/rooms/*/action');}
   await page.locator(name==='dice'?'#dice-clear':'#roulette-clear').click();
   assert.equal((await geometry()).position,'fixed','Clearing must keep the same dock');
   assert.ok(Math.abs((await geometry()).top-before.top)<1,'Clearing must not relocate submit');
   await page.evaluate(()=>{actionFeedback=null;refreshControls();scrollTo(0,0);});
  }
  await page.setViewportSize(viewport);
 }
 if(mobile&&name==='holdem'){
  await page.setViewportSize({width:320,height:660});
  for(const fontSize of ['100%','130%']){
   const result=await page.evaluate(size=>{
    scrollTo(0,0);document.documentElement.style.fontSize=size;
    const old={connected,connectionMode,recoveryAttempt};
    connected=false;connectionMode='syncing';recoveryAttempt={startedAt:Date.now()-6001};updateRecoveryNotice();
    const b=document.querySelector('[data-resync]'),r=b.getBoundingClientRect(),h=document.querySelector('.topbar').getBoundingClientRect();
    const result={hidden:b.hidden,height:r.height,top:r.top,headerBottom:h.bottom,clickable:b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};
    connected=old.connected;connectionMode=old.connectionMode;recoveryAttempt=old.recoveryAttempt;updateRecoveryNotice();return result;
   },fontSize);
   assert.ok(!result.hidden&&result.height>=44&&result.top>=result.headerBottom&&result.clickable,'Resync touch target obscured '+JSON.stringify(result));
  }
  await page.evaluate(()=>{document.documentElement.style.fontSize='';});await page.setViewportSize(viewport);
 }
 if(name==='slot'){
  await page.evaluate(()=>{feedback('Synthetic slot error',true);notice('Synthetic slot error');});
  const toast=await page.locator('#toast').evaluate(e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:innerHeight};});
  assert.ok(toast.top>=0&&toast.bottom<=toast.height,'Slot error toast escaped viewport '+JSON.stringify(toast));
  await page.evaluate(()=>{clearTimeout(toastTimer);document.querySelector('#toast').classList.remove('visible');actionFeedback=null;refreshControls();});
 }
 await page.evaluate(()=>scrollTo(0,0));
};
