const assert=require('node:assert/strict');
module.exports=async function blackjackFairnessChecks(page,name){
 if(name!=='blackjack')return;
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
  }finally{room=original;renderTableUpdate();}
  return results;
 });
 assert.equal(views[0].count,2);assert.match(views[0].text,/Blackjack · 兩張 21 點/);
 assert.equal(views[1].count,5);assert.match(views[1].text,/5 張湊成 21 點 · 非 Blackjack/);
 for(const v of views)assert.equal(v.overflow,false);
};
