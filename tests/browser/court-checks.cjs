/* Proportions are checked on the real renderer under the actual game selectors. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async function courtChecks(page,engine,out){
 const before=await page.evaluate(()=>{const prior=credentialsChanging;credentialsChanging=true;stopLive();return prior;});
 const results=[];
 try{
  for(const width of [393,1366]){
   await page.setViewportSize({width,height:900});
   const cases=await page.evaluate(()=>{
    const host=document.createElement('section');host.id='court-proportion-checks';host.className='panel';document.querySelector('#main').prepend(host);
    const contexts={
     standalone:['section','div'],
     'holdem-own':['holdem-room','table-seat is-me','seat-cards'],
     'holdem-peer':['holdem-room','table-seat','seat-cards'],
     community:['holdem-room','community-cards'],
     big2:['arcade-big2','hand-card'],
     blackjack:['arcade-blackjack','blackjack-dealer'],
     gate:['arcade-inbetween','gate-cards'],
     history:['history-holes']
    },rows=[];
    for(const [context,classes] of Object.entries(contexts))for(const width of [28,52,72,140])for(const rank of 'A23456789TJQK')for(const suit of 'shdc'){
     let parent=host;for(const cls of classes){const d=document.createElement('div');d.className=cls;d.style.cssText='position:static;display:block;width:auto;height:auto;transform:none';parent.append(d);parent=d;}
     if(context==='blackjack'){const marker=document.createElement('div');marker.className='blackjack-bet-panel';marker.hidden=true;parent.parentElement.append(marker);}
     const t=document.createElement('template');t.innerHTML=card(rank+suit,context.startsWith('holdem')||context==='history');const e=t.content.firstElementChild;e.style.width=width+'px';e.style.height=Math.round(width*1.5)+'px';e.style.transform='none';parent.append(e);
     const art=getComputedStyle(e,'::before'),b=e.querySelector('b'),bs=getComputedStyle(b),i=b.querySelector('i'),s=getComputedStyle(i),w=e.clientWidth;
     rows.push({context,rank,suit,width,inline:e.style.cssText,faceVar:getComputedStyle(e).getPropertyValue("--pc-face"),face:art.backgroundImage,inner:w,art:[art.top,art.right,art.bottom,art.left],size:art.backgroundSize,rankFont:parseFloat(bs.fontSize),suitWidth:i.clientWidth,suitHeight:i.clientHeight,mask:s.maskImage||s.webkitMaskImage,panel:bs.backgroundImage,cornerHeight:b.clientHeight,cardHeight:e.clientHeight});host.replaceChildren();
    }
    host.remove();return rows;
   });
   for(const row of cases){
    assert.deepEqual(row.art,['0px','0px','0px','0px'],engine+' '+JSON.stringify(row)+' artwork must fill the card');
    assert.ok(row.face.includes('/cards/'+row.rank.toLowerCase()+row.suit+'.webp?v='),engine+' each rank and suit must use its own picture '+JSON.stringify(row));
    assert.ok(row.size.includes('cover'),engine+' '+JSON.stringify(row)+' must preserve image aspect ratio');
    assert.ok(Math.abs(row.rankFont-Math.max(8,row.inner*(row.rank==='J'?.20:row.rank==='T'?.15:.17)))<.6,engine+' '+JSON.stringify(row)+' rank must scale with its card');
    assert.ok(row.suitWidth>=5&&row.suitHeight>=5&&row.suitWidth<=Math.max(5,row.inner*(row.rank==='J'?.11:.13))+1&&row.suitHeight<=Math.max(5,row.inner*(row.rank==='J'?.11:.13))+1,engine+' '+JSON.stringify(row)+' suit must not dominate the portrait');
    assert.ok(row.mask.includes('data:image/svg'),engine+' '+JSON.stringify(row)+' suit must remain visible');
    assert.equal(row.panel,'none',engine+' '+JSON.stringify(row)+' do not reintroduce the large white panel');
    if(row.width>=52)assert.ok(row.cornerHeight<row.cardHeight*.26,engine+' '+JSON.stringify(row)+' corner occupies too much portrait space');
   }
   results.push({viewport:width,cases:cases.length});
  }
  fs.writeFileSync(path.join(out,engine+'-court-proportions.json'),JSON.stringify(results,null,2));
  console.log('court proportions OK: '+engine+' '+results.reduce((n,r)=>n+r.cases,0)+' rank/suit/context checks');
 }finally{await page.evaluate(prior=>{document.querySelector('#court-proportion-checks')?.remove();credentialsChanging=prior;if(!prior)startLive();},before);}
};
