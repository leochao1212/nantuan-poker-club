/* Late treasure replies may never replace a different open treasure. No server or money. */
const {chromium,webkit}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 for(const [name,driver] of [['chromium',chromium],['webkit',webkit]]){
  const browser=await driver.launch({headless:true});
  try{
   const page=await browser.newPage({viewport:{width:393,height:852}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<!doctype html><html><body></body></html>');
   await page.evaluate(()=>{window.ClubFishingScene={portrait:()=>'<span>寶箱</span>'};});
   await page.addScriptTag({path:path.resolve(__dirname,'../../static/fishing-bonus.js')});
   await page.evaluate(()=>{
    window.bonusA={id:'a'.repeat(32),status:'ready',stake:100,rounds:3};
    window.bonusB={id:'b'.repeat(32),status:'ready',stake:200,rounds:3};
    window.calls=[];
    window.widget=ClubFishingBonus.create({pause(){},command:async(action,data)=>{calls.push(data.bonus_id);return new Promise(resolve=>window.resolveClaim=resolve);}});
    widget.open(bonusA);
   });
   await page.locator('[data-bonus-start]').click();
   await page.locator('[data-bonus-close]').click();
   await page.evaluate(()=>widget.open(bonusB));
   assert.equal(await page.locator('[data-bonus-start]').isDisabled(),true);
   await page.evaluate(()=>resolveClaim({result:{bonus:{...bonusA,status:'settled',draws:[2,3,5],gross:1000,item:'freeze'}}}));
   await page.waitForFunction(()=>!document.querySelector('[data-bonus-start]').disabled);
   assert.match(await page.locator('.fish-bonus-modal').textContent(),/200/);
   assert.equal(await page.locator('[data-bonus-total]').textContent(),'寶藏獎勵');
   await page.locator('[data-bonus-start]').click();
   await page.evaluate(()=>resolveClaim({result:{bonus:{...bonusB,status:'settled',draws:[2,3,5],gross:2000,item:'laser'}}}));
   await page.locator('[data-bonus-skip]').click();
   assert.equal(await page.locator('[data-bonus-total]').textContent(),'＋2,000');
   assert.deepEqual(await page.evaluate(()=>calls),['a'.repeat(32),'b'.repeat(32)]);
   await page.locator('[data-bonus-close]').click();
   await page.evaluate(()=>widget.open(bonusA));await page.locator('[data-bonus-start]').click();
   await page.evaluate(()=>{widget.destroy();resolveClaim({result:{bonus:{...bonusA,status:'settled',draws:[2,3,5],gross:1000,item:'freeze'}}});});
   await page.waitForFunction(()=>!document.querySelector('.fish-bonus-modal'));
   assert.deepEqual(errors,[]);console.log(name+': late bonus isolation, enabled next box, skip and unmount OK');
  }finally{await browser.close();}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
