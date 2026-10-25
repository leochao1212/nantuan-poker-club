const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async function round4Checks(page,engine,out){
 await page.waitForFunction(()=>document.documentElement.dataset.ui==='current');
 const measurements=[];
 for(const width of [320,375,393,768,1093,1094,1095,1096,1097,1098,1099,1100,1366,1440,1600,1920]){
  await page.setViewportSize({width,height:900});
  for(const open of [false,true]){
   await page.evaluate(value=>document.querySelectorAll('.game-choice>details').forEach(d=>d.open=value),open);
   const bad=await page.evaluate(()=>{
    const hits=[];const overlap=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>.1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>.1;
    for(const card of document.querySelectorAll('.game-choice')){
     const elements=[card.querySelector('summary'),...card.querySelectorAll('footer>span,footer>button')].filter(Boolean);
     for(let i=0;i<elements.length;i++)for(let j=i+1;j<elements.length;j++){
      const a=elements[i].getBoundingClientRect(),b=elements[j].getBoundingClientRect();
      if(overlap(a,b))hits.push({game:card.querySelector('h2').textContent,a:elements[i].textContent,b:elements[j].textContent,intersection:Math.min(a.right,b.right)-Math.max(a.left,b.left)});
     }
    }return hits;
   });
   measurements.push({width,open,overlaps:bad});
  }
 }
 fs.writeFileSync(path.join(out,'round4-'+engine+'.json'),JSON.stringify(measurements,null,2));
 assert.deepEqual(measurements.filter(x=>x.overlaps.length),[],engine+' lobby controls overlap');
 await page.evaluate(()=>{document.querySelectorAll('.game-choice>details').forEach(d=>d.open=false);});
 await page.setViewportSize({width:1097,height:900});
 await page.locator('.game-dice').screenshot({path:path.join(out,engine+'-dice-card-1097.png')});
 // Use the actual card renderer/styles, not a copied template. All ranks and
 // suits are checked at common card widths, including the narrow J glyph.
 const clips=await page.evaluate(()=>{
  const fixture=document.createElement('section');fixture.id='round4-card-fixture';fixture.className='panel';fixture.style.cssText='display:flex;flex-wrap:wrap;gap:12px;padding:16px';
  for(const width of [28,40,52,72])for(const rank of 'A23456789TJQK')for(const suit of 'shdc'){
   const holder=document.createElement('div');holder.innerHTML=card(rank+suit);const face=holder.firstElementChild;
   face.style.cssText='width:'+width+'px;height:'+Math.round(width*1.4)+'px;transform:none';fixture.append(holder);
  }
  document.querySelector('#main').prepend(fixture);
  const bad=[];
  for(const face of fixture.querySelectorAll('.playing-card'))for(const i of face.querySelectorAll('b>i')){
   const s=getComputedStyle(i);if(s.display==='none'||!i.clientHeight)continue;
   const size=s.backgroundSize;const percent=/auto\s+([\d.]+)%/.exec(size);
   if(percent&&i.clientHeight*Number(percent[1])/100>i.clientWidth+.5)bad.push({rank:face.dataset.rank,suit:face.dataset.suit,width:face.offsetWidth,iconWidth:i.clientWidth,iconHeight:i.clientHeight,size});
  }
  return bad;
 });
 assert.deepEqual(clips,[],engine+' card corner suit is clipped');
 await page.locator('#round4-card-fixture').screenshot({path:path.join(out,engine+'-face-cards.png')});
 await page.evaluate(()=>document.querySelector('#round4-card-fixture').remove());
 await require('./court-checks.cjs')(page,engine,out);
 await require('./deck-checks.cjs')(page,engine,out);
 console.log('round4 OK: '+engine+' 32 lobby states and all card ranks/suits');
};
