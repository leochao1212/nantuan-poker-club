/* Full-deck loading and photo mapping; only used by the disposable layout server. */
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async function deckChecks(parent,engine,out){
 const page=await parent.context().newPage(),requests=new Set();page.on('request',r=>{if(r.url().includes('/assets/cards/'))requests.add(new URL(r.url()).pathname);});
 try{
  await page.goto(new URL('/#lobby',parent.url()).href);await page.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady);
  await page.evaluate(()=>{credentialsChanging=true;stopLive();ClubArt.prepare('holdem');});
  assert.equal(requests.size,0,'Opening a card game must not download all 52 portraits');
  const hidden=await page.evaluate(()=>card(null));assert.ok(!hidden.includes('data-photo-card')&&!hidden.includes('/cards/'),'Hidden cards must never request a face');
  await page.evaluate(async()=>{await Promise.all(['As','Ah'].map(async c=>{const i=new Image();i.src=ClubArt.cardFace(c);await i.decode();}));});
  assert.deepEqual([...requests].sort(),['/assets/cards/ah.webp','/assets/cards/as.webp']);
  const count=await page.evaluate(async()=>{
   const codes=[...'shdc'].flatMap(s=>[...'A23456789TJQK'].map(r=>r+s));
   await Promise.all(codes.map(async c=>{const i=new Image();i.src=ClubArt.cardFace(c);await i.decode();if(!i.naturalWidth)throw Error('Missing '+c);}));
   const sheet=document.createElement('section');sheet.id='full-friend-deck';sheet.className='panel';sheet.style.cssText='position:fixed;left:0;top:0;z-index:1000;display:grid;grid-template-columns:repeat(13,88px);gap:8px;width:fit-content;padding:16px;background:#eadfc8';sheet.innerHTML=codes.map(c=>card(c)).join('');document.querySelector('#app').append(sheet);
   for(const e of sheet.children){e.style.width='88px';e.style.height='132px';}
   return {count:sheet.children.length,unique:new Set(codes.map(c=>ClubArt.cardFace(c))).size};
  });
  assert.deepEqual(count,{count:52,unique:52});await page.waitForFunction(()=>[...document.querySelectorAll('#full-friend-deck [data-photo-card]')].every(e=>e.dataset.faceState==='ready'));await page.setViewportSize({width:1366,height:900});await page.locator('#full-friend-deck').screenshot({path:path.join(out,engine+'-friends-deck.png')});
  await page.setViewportSize({width:393,height:852});await page.evaluate(()=>{const s=document.querySelector('#full-friend-deck');s.style.gridTemplateColumns='repeat(4,78px)';s.innerHTML=['As','Ah','Ad','Ac','2s','2h','2d','2c'].map(c=>card(c)).join('');for(const e of s.children){e.style.width='78px';e.style.height='117px';}});await page.locator('#full-friend-deck').screenshot({path:path.join(out,engine+'-friends-deck-phone.png')});
  console.log('full deck OK: '+engine+' 52 distinct decoded pictures; on-demand loading; hidden-card privacy');
 }finally{await page.close();await parent.bringToFront();}
};
