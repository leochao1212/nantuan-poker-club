'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
module.exports=async function adaptiveLayout({p,adb,api,roomId,out,checks,getPage}){
 const serial=adb('get-serialno').toString().trim();assert.match(serial,/^emulator-\d+$/,'Adaptive settings are emulator-only');
 const sim=(...args)=>adb('-s',serial,...args),pause=ms=>new Promise(r=>setTimeout(r,ms)),results=[],failures=[];
 const profiles=[['small',640,1280],['standard',786,1704],['large',864,1920],['landscape',1560,720],['tablet',1280,800,160]];
 async function configured(){await pause(1800);sim('shell','am','start','-n','org.nantuan.nantuan_club/.MainActivity');p=await getPage();await p.waitForFunction(()=>typeof lobby!=='undefined'&&lobby&&liveReady&&document.visibilityState==='visible',{},{timeout:30000});await p.emulateMedia({reducedMotion:'reduce'});}
 await p.emulateMedia({reducedMotion:'reduce'});
 async function open(view){await p.evaluate(v=>go(v),view);await p.waitForFunction(v=>typeof lobby!=='undefined'&&lobby&&(typeof v==='number'?view==='table'&&room?.id===v:view===v),view);await pause(220);}
 async function capture(name,{keyboard=false}={}){
  console.log('Adaptive capture: '+name);await p.waitForFunction(()=>document.visibilityState==='visible',{}, {timeout:15000});await pause(150);
  const png=sim('exec-out','screencap','-p');fs.writeFileSync(path.join(out,'layout-'+name+'.png'),png);
  const geometry=await p.evaluate(()=>({headers:document.querySelectorAll('.topbar').length,width:innerWidth,height:innerHeight,visualHeight:visualViewport?.height,visualTop:visualViewport?.offsetTop,dpr:devicePixelRatio,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,scrollY,body:getComputedStyle(document.body).backgroundColor,nav:(()=>{const n=document.querySelector('.sidebar');if(!n||getComputedStyle(n).display==='none')return null;const r=n.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height};})(),feedback:(()=>{const n=document.querySelector('.bet-submit-bar>#action-feedback');if(!n)return null;const r=n.getBoundingClientRect();return {height:r.height,text:n.textContent,visibility:getComputedStyle(n).visibility};})()}));
  try{await p.screenshot({path:path.join(out,'web-layout-'+name+'.png'),timeout:3000});}catch(e){console.warn('Optional DevTools screenshot unavailable: '+e.message);}
  const pixels=await p.evaluate(async encoded=>{const img=new Image();img.src='data:image/png;base64,'+encoded;await img.decode();const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,0,0);const data=ctx.getImageData(0,0,canvas.width,canvas.height).data;let run=0,longest=0;const left=Math.floor(canvas.width*.1),right=Math.ceil(canvas.width*.9);for(let y=Math.floor(canvas.height*.65);y<canvas.height;y++){let white=0;for(let x=left;x<right;x+=2){const k=(y*canvas.width+x)*4;if(data[k]>=248&&data[k+1]>=248&&data[k+2]>=248)white++;}const fraction=white/Math.ceil((right-left)/2);run=fraction>.95?run+1:0;longest=Math.max(longest,run);}return {width:canvas.width,height:canvas.height,longestWhiteBand:longest};},png.toString('base64'));
  results.push({name,keyboard,...geometry,pixels});
  fs.writeFileSync(path.join(out,'adaptive-layout.json'),JSON.stringify({results,failures},null,2));
  if(geometry.headers!==1)failures.push(name+': duplicate header DOM');
  if(geometry.scrollWidth>geometry.width+1)failures.push(name+': horizontal overflow');
  if(!keyboard&&pixels.longestWhiteBand>=8)failures.push(name+': blank white band '+pixels.longestWhiteBand+'px');
  if(geometry.nav&&geometry.width<=760&&!keyboard&&Math.abs(geometry.nav.bottom-geometry.height)>3)failures.push(name+': navigation does not reach viewport bottom');
 }
 try{
  sim('shell','settings','put','secure','show_ime_with_hard_keyboard','1');
  for(const mode of ['gestural','threebutton']){
   sim('shell','cmd','overlay','enable-exclusive','--category','com.android.internal.systemui.navbar.'+mode);await configured();
   for(const [label,width,height,density=320] of profiles){
    sim('shell','wm','size',width+'x'+height);sim('shell','wm','density',String(density));await configured();
    await open('lobby');await capture(mode+'-'+label+'-lobby');
    await open(roomId);await p.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));await pause(150);await capture(mode+'-'+label+'-game-bottom');
   }
   sim('shell','wm','size','786x1704');sim('shell','wm','density','320');await configured();await open('members');
   const height=await p.evaluate(()=>innerHeight);await p.locator('#member-search').tap();await p.locator('#member-search').fill('Android');
   let keyboardShown=false;try{await p.waitForFunction(h=>(visualViewport?.height||innerHeight)<h-100,height,{timeout:10000});keyboardShown=true;}catch{failures.push(mode+': software keyboard did not open');fs.writeFileSync(path.join(out,'ime-'+mode+'.txt'),sim('shell','dumpsys','input_method'));}
   await capture(mode+'-keyboard-open',{keyboard:true});
   if(keyboardShown){sim('shell','input','keyevent','4');try{await p.waitForFunction(h=>Math.abs(innerHeight-h)<4&&Math.abs((visualViewport?.height||innerHeight)-h)<4,height,{timeout:10000});}catch{failures.push(mode+': viewport did not recover after keyboard');}}
   else await p.locator('#member-search').blur();
   await open(roomId);await p.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));await capture(mode+'-keyboard-return');
  }
  sim('shell','settings','put','system','font_scale','1.5');await configured();await open('rewards');await capture('large-font-rewards');
 }finally{
  try{if(sim('get-state').toString().trim()==='device'){sim('shell','settings','put','system','font_scale','1');sim('shell','wm','size','reset');sim('shell','wm','density','reset');sim('shell','cmd','overlay','enable-exclusive','--category','com.android.internal.systemui.navbar.gestural');await configured();}}catch{console.warn('Emulator unavailable during cleanup; preserving original failure');}
  fs.writeFileSync(path.join(out,'adaptive-layout.json'),JSON.stringify({results,failures,scope:'Android emulator; gesture/three-button, small/standard/large/landscape/tablet, keyboard, font scale'},null,2));
 }
 assert.deepEqual(failures,[]);checks.push('Adaptive native layouts: gesture/three-button, 5 sizes, keyboard return and large text');
};
