const assert=require('node:assert/strict');
module.exports=async function gateProtectionChecks(page,name){
 if(name==='admin'){
  await page.locator('[data-admin-section=settings]').click();
  await page.locator('[data-rules-game]').selectOption('inbetween');
  const field=page.locator('[data-rule-key=post_protection_bps]');
  await field.waitFor();assert.equal(await field.inputValue(),'50');
  assert.equal(await field.getAttribute('min'),'0');assert.equal(await field.getAttribute('max'),'100');
  await field.fill('101');assert.equal(await field.evaluate(e=>e.validity.rangeOverflow),true);
  await field.fill('0');await page.locator('[data-rules-note]').fill('Synthetic protection preview');
  await page.locator('[data-rules-form] [type=submit]').click();
  await page.locator('#game-settings-modal').waitFor({state:'visible'});
  assert.match(await page.locator('#game-settings-modal').innerText(),/撞柱保護觸發率/);
  assert.match(await page.locator('#game-settings-modal').innerText(),/保留原倍率/);
  await page.locator('[data-rules-cancel]').click();
  await field.fill('50');await page.locator('[data-admin-section=accounts]').click();
 }
 if(name!=='gate')return;
 // Exercise public settlement variants locally. Never submit synthetic bets.
 const checks=await page.evaluate(()=>{
  const original=room,results=[];
  try{
   for(const rate of [0,5000,10000]){
    const fixture=structuredClone(original);fixture.hand.id='protection-ui-'+rate;
    fixture.status='waiting';fixture.hand.phase='showdown';fixture.hand.gate_rules_version=4;
    fixture.hand.game_settings.params.post_protection_bps=rate;
    fixture.hand.pillars=['5c','9c'];fixture.hand.third='5d';fixture.hand.direction='between';
    fixture.hand.post_protection_triggered=rate>0;fixture.hand.protected_discards=[];fixture.hand.charged=rate?0:200;fixture.hand.protection_event=rate?{mode:'refund',nickname:'保護成功測試玩家',user_id:fixture.hand.players[0].user_id,avoided_charge:200}:null;
    const win=0.24,post=0.12*(1-rate/10000);
    fixture.hand.gate_quotes={between:{winning_cards:12,total_cards:50,post_cards:6,loss_multiplier:2,
     post_protection_bps:rate,max_loss_multiplier:rate===10000?1:2,
     win_numerator:win,win_denominator:1,post_numerator:post,post_denominator:1,
     charge_numerator:1.12-0.24*(rate/10000),charge_denominator:1,return_numerator:679,return_denominator:150}};
    room=fixture;renderTableUpdate();
    const note=document.querySelector('.gate-protection-note').textContent;
    const postText=document.querySelector('#gate-post-chance').textContent;
    const count=document.querySelectorAll('.gate-discard-cards .playing-card').length;
    const protection=document.querySelector('.gate-protection-discards');if(protection)protection.open=true;
    results.push({rate,note,postText,count,banner:document.querySelector('.gate-protection-success')?.textContent||'',win:document.querySelector('#gate-chance').textContent,rtp:document.querySelector('#gate-rtp').textContent,
     overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1});
   }
  }finally{room=original;renderTableUpdate();}
  return results;
 });
 for(const c of checks){assert.match(c.note,new RegExp('撞柱保護 '+c.rate/100+'%'));assert.equal(c.postText,(12*(1-c.rate/10000)).toFixed(2)+'%');assert.equal(c.count,0);if(c.rate){assert.match(c.banner,/保護成功測試玩家 觸發撞柱保護/);assert.match(c.banner,/本局扣點 0/);assert.match(c.banner,/免除 200/);}assert.ok(!c.overflow,JSON.stringify(c));assert.notEqual(c.rtp,'—');}
};
