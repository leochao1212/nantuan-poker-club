const assert=require('node:assert/strict');
module.exports=async function blackjackFairnessChecks(page,name){
 if(name==='admin'){
  await page.locator('[data-admin-section=settings]').click();await page.locator('[data-rules-game]').selectOption('blackjack');
  for(const [mode,tie,bust] of [['easy','50','25'],['fun','100','50'],['off','0','0'],['easy','50','25']]){
   await page.locator('[data-benefit-preset='+mode+']').click();assert.equal(await page.locator('[data-rule-key=tie_win_bps]').inputValue(),tie);assert.equal(await page.locator('[data-rule-key=bust_refund_bps]').inputValue(),bust);assert.equal(await page.locator('[data-benefit-preset='+mode+']').getAttribute('aria-pressed'),'true');
  }
  await page.locator('[data-rules-form] [type=submit]').click();await page.locator('#game-settings-modal').waitFor({state:'visible'});assert.match(await page.locator('#game-settings-modal').innerText(),/普通同點轉勝/);assert.match(await page.locator('#game-settings-modal').innerText(),/爆牌全額退注/);await page.locator('[data-rules-cancel]').click();
  await page.locator('[data-rules-defaults]').click();assert.equal(await page.locator('[data-benefit-preset=off]').getAttribute('aria-pressed'),'true');
  await page.locator('[data-rule-key=tie_win_bps]').fill('37.5');assert.equal(await page.locator('[data-benefit-preset=off]').getAttribute('aria-pressed'),'false');
  await page.locator('[data-rule-key=bust_refund_bps]').fill('101');assert.equal(await page.locator('[data-rule-key=bust_refund_bps]').evaluate(e=>e.validity.rangeOverflow),true);
  await page.locator('[data-admin-section=accounts]').click();
 }
 if(name!=='blackjack')return;
 const luminance=s=>{const rgb=s.match(/[\d.]+/g).slice(0,3).map(n=>Number(n)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
 const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
 const views=await page.evaluate(()=>{
  const original=room,results=[];
  try{
   for(const dealer of [['As','Kh'],['2c','3d','4h','5s','7c']]){
    const fixture=structuredClone(original);fixture.hand.id='bj-natural-ui-'+dealer.length;
    fixture.status='waiting';fixture.hand.phase='showdown';fixture.hand.dealer=dealer;fixture.hand.board=dealer;
    room=fixture;renderTableUpdate();
    results.push({count:document.querySelectorAll('.blackjack-dealer .playing-card').length,
     text:document.querySelector('.blackjack-dealer>strong').textContent,
     overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1});
   }
   for(const kind of ['tie_win','bust_refund']){
    const fixture=structuredClone(original);fixture.hand.id='benefit-ui-'+kind;fixture.status='waiting';fixture.hand.phase='showdown';fixture.hand.dealer=['9c','9d'];fixture.hand.game_settings.params.tie_win_bps=5000;fixture.hand.game_settings.params.bust_refund_bps=2500;
    const own=fixture.hand.players.find(p=>p.user_id===lobby.me.id)||fixture.hand.players[0];own.hands=[{cards:kind==='tie_win'?['Tc','8d']:['9c','7h','Ts'],bet:100,status:kind==='tie_win'?'stand':'bust',split:false,payout:kind==='tie_win'?200:100,outcome:kind==='tie_win'?'同點優待 · 玩家勝出':'爆牌保護 · 本手全額退注',benefit:{kind,rate_bps:kind==='tie_win'?5000:2500,triggered:true}}];
    room=fixture;renderTableUpdate();const banner=document.querySelector('.blackjack-benefit-banner'),style=getComputedStyle(banner),small=getComputedStyle(banner.querySelector('small'));results.push({kind,colors:[style.color,small.color,style.backgroundColor],banner:banner.textContent,awarded:!!document.querySelector('.blackjack-hand.has-benefit'),text:document.querySelector('.blackjack-hand.has-benefit').textContent,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1});
   }
  }finally{room=original;renderTableUpdate();}
  return results;
 });
 assert.equal(views[0].count,2);assert.match(views[0].text,/Blackjack · 兩張 21 點/);
 assert.equal(views[1].count,5);assert.match(views[1].text,/5 張湊成 21 點 · 非 Blackjack/);
 for(const v of views){assert.equal(v.overflow,false);if(v.kind){assert.ok(contrast(v.colors[0],v.colors[2])>=4.5,'benefit text contrast '+JSON.stringify(v.colors));assert.ok(contrast(v.colors[1],v.colors[2])>=4.5,'benefit note contrast '+JSON.stringify(v.colors));assert.ok(v.awarded);assert.match(v.banner,/普通同點 50% 轉勝/);assert.match(v.banner,/爆牌 25% 全額退注/);assert.match(v.text,v.kind==='tie_win'?/總返還 200 點/:/總返還 100 點/);}}
};
