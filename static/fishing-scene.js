/* Original Nantuan marine artwork; one capped canvas with no game decisions. */
'use strict';
window.ClubFishingScene=(()=>{
 const ids=['sardine','clownfish','mackerel','snapper','tuna','ray','swordfish','goldfish'];
 const traits={
  sardine:{habitat:'近岸魚群',detail:'銀藍細鱗，常成群穿過淺水。',size:.82,speed:1.25},
  clownfish:{habitat:'珊瑚礁',detail:'橙白條紋與圓潤魚身，穿梭珊瑚之間。',size:.76,speed:.65},
  mackerel:{habitat:'沿岸洄游',detail:'青綠背紋，魚群行進俐落。',size:.98,speed:1.1},
  snapper:{habitat:'礁岩海域',detail:'胭脂紅鱗與高背輪廓，緩游礁石邊緣。',size:1.06,speed:.7},
  tuna:{habitat:'外海洄游',detail:'深藍流線魚身與金色小鰭，快速掠過外海。',size:1.27,speed:1.25},
  ray:{habitat:'深海沙地',detail:'月光般的斑紋，雙翼舒展如海中滑翔。',size:1.4,speed:.45},
  swordfish:{habitat:'外海水層',detail:'長吻與高帆背鰭，沿著深藍洋流前行。',size:1.45,speed:.9},
  goldfish:{habitat:'楠團傳說',detail:'幻想魚種。鎏金鱗甲與赤金長鰭，是漁港的珍藏。',size:1.25,speed:.5}
 };
 const regions=[[0,0,1.03],[1.08,0,.86],[2.04,0,.96],[3.03,0,.97],[0,1,1.08],[1.08,1,.92],[2.03,1,.97],[3.02,1,.98]];
 let spriteSerial=0;
 const gearNames=['經典黃銅','翡翠夜航','曜金典藏'];
 const url=name=>window.ClubArt.url('fishing/'+name+'.webp');
 function portrait(id){const i=ids.indexOf(id);if(i<0)return '';const [x,y,width]=regions[i],clip='fish-sprite-'+(++spriteSerial);return `<svg class="fish-portrait" viewBox="${x} ${y} ${width} 1" aria-hidden="true"><defs><clipPath id="${clip}"><rect x="${x}" y="${y}" width="${width}" height="1"/></clipPath></defs><image width="4" height="2" href="${url('fish-atlas')}" clip-path="url(#${clip})"/></svg>`;}
 function gearArt(kind,index){const x=index*100,y=kind==='rod'?0:92,h=kind==='rod'?92:108,clip='fish-gear-'+(++spriteSerial);return `<svg class="fish-gear-art" viewBox="${x} ${y} 100 ${h}" aria-hidden="true"><defs><clipPath id="${clip}"><rect x="${x}" y="${y}" width="100" height="${h}"/></clipPath></defs><image width="300" height="200" href="${url('gear-atlas')}" clip-path="url(#${clip})"/></svg>`;}

 const cache=new Map();
 function image(name,redraw){if(!cache.has(name)){const img=new Image();img.decoding='async';img.src=url(name);cache.set(name,img);}const img=cache.get(name);if(!img.complete){const done=()=>{img.removeEventListener('load',done);img.removeEventListener('error',done);redraw();};img.addEventListener('load',done);img.addEventListener('error',done);}return img;}
 function create(canvas,{pick,ready}){
  let model=null,frame=0,last=0,alive=true,visible=true,entities=[],mode=null,flight=null,castAt=0,aim={x:.5,y:.4},resultKey=null,celebration=null,pickedAim=null;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),c=canvas.getContext('2d'),assets={};
  function drawImage(name,sx,sy,sw,sh,x,y,w,h){const img=assets[name];if(img?.complete&&img.naturalWidth)c.drawImage(img,sx,sy,sw,sh,x,y,w,h);}
  function fish(id,x,y,size,dir=1,angle=0,alpha=1){const img=assets['fish-atlas'],i=ids.indexOf(id);if(!img?.naturalWidth||i<0)return;const [rx,ry,rw]=regions[i],unit=img.naturalWidth/4,sw=unit*rw,sh=img.naturalHeight/2;c.save();c.translate(x,y);c.rotate(angle);c.scale(dir,1);c.globalAlpha=alpha;drawImage('fish-atlas',rx*unit,ry*sh,sw,sh,-size/2,-size*sh/sw/2,size,size*sh/sw);c.restore();}
  function gear(kind,index,x,y,size,angle=0){const img=assets['gear-atlas'];if(!img?.naturalWidth)return;const sw=img.naturalWidth/3,sy=kind==='rod'?0:img.naturalHeight*.46,sh=kind==='rod'?img.naturalHeight*.46:img.naturalHeight*.54;c.save();c.translate(x,y);c.rotate(angle);drawImage('gear-atlas',index*sw,sy,sw,sh,-size/2,-size*.8,size,size*sh/sw);c.restore();}
  function setup(){entities=[];for(let i=0;i<8;i++){const id=ids[i],v=traits[id];entities.push({id,seed:i*.147+.08,lane:.22+(i%4)*.15,dir:i%2?1:-1,size:v.size,speed:v.speed,main:true});if(i<3)for(let j=0;j<2;j++)entities.push({id,seed:i*.147+.1+j*.045,lane:.25+(i%4)*.15+j*.045,dir:i%2?1:-1,size:v.size*.64,speed:v.speed,main:false});}}
  function position(f,t,w,h){const phase=(t*.014*f.speed+f.seed)%1,size=Math.min(w*.22,145)*f.size;let x=(reduced.matches?.12+(ids.indexOf(f.id)%4)*.25:f.dir>0?phase:1-phase)*w;if(reduced.matches)x=Math.max(size*.45+4,Math.min(w-size*.45-4,x));return {x,y:(reduced.matches?.34+Math.floor(ids.indexOf(f.id)/4)*.3+(ids.indexOf(f.id)%2)*.025:f.lane+Math.sin(t*.65+f.seed*20)*.025)*h,size};}

  function draw(now=performance.now()){
   if(!alive||!model||document.hidden||!visible)return;const r=canvas.getBoundingClientRect(),w=r.width,h=r.height,ratio=Math.min(w<600?1.5:2,devicePixelRatio||1);if(!w||!h)return;
   if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,w,h);
   const bg=assets[model.mode==='leisure'?'harbor':'reef'];c.fillStyle='#123c43';c.fillRect(0,0,w,h);
   if(bg?.naturalWidth){const scale=Math.max(w/bg.naturalWidth,h/bg.naturalHeight),bw=bg.naturalWidth*scale,bh=bg.naturalHeight*scale;c.drawImage(bg,(w-bw)/2,(h-bh)/2,bw,bh);}else{c.font='14px system-ui';c.textAlign='center';c.fillStyle='#f5e7c4';c.fillText(bg?.complete?'場景暫時無法載入，仍可使用下方按鈕':'正在展開海圖…',w/2,h/2);}
   const t=reduced.matches?0:now/1000;
   if(model.mode==='arcade'){
    for(const f of entities){if(reduced.matches&&!f.main)continue;const p=position(f,t,w,h);fish(f.id,p.x,p.y,p.size,f.dir,Math.sin(t*2+f.seed)*.055);if(f.main){c.textAlign='center';c.font='600 11px system-ui';c.fillStyle='#f9e7b9';c.fillText(model.catalog.find(v=>v.id===f.id)?.multiplier+'×',p.x,p.y+p.size*.23);if(model.selected===f.id){c.strokeStyle='#f2d793';c.lineWidth=1.4;c.setLineDash([5,5]);c.beginPath();c.ellipse(p.x,p.y,p.size*.45,p.size*.25,0,0,Math.PI*2);c.stroke();c.setLineDash([]);}}}
    // Slow bubbles; fixed count and no allocations or particle timers.
    if(!reduced.matches){c.strokeStyle='#d0f3df50';c.lineWidth=1;for(let i=0;i<8;i++){c.beginPath();c.arc((i*.137+.08)*w,(1-(t*.035+i*.137)%1)*h,1.5+i%3,0,Math.PI*2);c.stroke();}}
    const target=aim,angle=Math.atan2(target.y*h-h*.92,target.x*w-w*.5)+Math.PI/2;
    const recoil=flight&&!reduced.matches?Math.max(0,1-(now-flight.at)/150)*7:0;
    c.save();c.translate(w*.5,h*.92+recoil);c.rotate(angle);gear('cannon',model.cannon,0,0,Math.min(120,w*.25));c.restore();
    if(flight){const elapsed=now-flight.at,p=Math.min(1,elapsed/360),sx=w*.5,sy=h*.84,tx=flight.x*w,ty=flight.y*h,x=sx+(tx-sx)*p,y=sy+(ty-sy)*p;
     if(p<1&&!reduced.matches){c.strokeStyle='#efcd78';c.lineWidth=3;c.beginPath();c.moveTo(sx+(tx-sx)*Math.max(0,p-.14),sy+(ty-sy)*Math.max(0,p-.14));c.lineTo(x,y);c.stroke();c.fillStyle='#fff2b8';c.beginPath();c.arc(x,y,4,0,Math.PI*2);c.fill();}
     if(p>=1&&(elapsed<1300||model.sending)){const radius=reduced.matches?23:Math.min(35,16+(elapsed-360)/25);c.save();c.translate(tx,ty);c.strokeStyle=model.sending?'#e8cd8d99':'#f1d58b';c.lineWidth=1;c.globalAlpha=model.sending?1:Math.max(0,1-(elapsed-650)/650);c.beginPath();c.arc(0,0,radius,0,Math.PI*2);for(let j=-2;j<=2;j++){const v=j*radius/3,extent=Math.sqrt(radius*radius-v*v);c.moveTo(-extent,v);c.lineTo(extent,v);c.moveTo(v,-extent);c.lineTo(v,extent);}c.stroke();c.restore();}
    }
   }else{
    const progress=model.reelProgress||0,active=!!model.pending,biting=active&&model.now()>=model.pending.ready_at;
    const travel=castAt&&!reduced.matches?Math.min(1,(now-castAt)/600):1;
    const floatX=w*(.61-progress*.18),floatY=h*(.57-progress*.12)+(reduced.matches?0:Math.sin(t*(biting?8:2))*(biting?4:1.4));
    for(let i=0;i<3;i++){const x=((t*.008+i*.31)%1)*w;fish(ids[i+2],x,h*(.7+i*.08),65,i%2?1:-1,0,.17);}
    const rodSize=Math.min(w*.52,280),rodX=w*.2,rodY=h*.9;
    c.save();c.translate(rodX,rodY);c.rotate(-progress*.16);gear('rod',model.rod,0,0,rodSize);c.restore();
    if(active||model.sending||travel<1){const x=w*.27+(floatX-w*.27)*travel,y=travel<1?h*.45+(floatY-h*.45)*travel-Math.sin(travel*Math.PI)*h*.28:floatY;
     c.strokeStyle='#f8ecd1cc';c.lineWidth=.9;c.beginPath();c.moveTo(rodX+rodSize*.36,rodY-rodSize*.68);c.quadraticCurveTo(w*.5,h*.3,x,y);c.stroke();
     c.strokeStyle='#f3e5be99';c.lineWidth=1;for(let i=0;i<2;i++){c.beginPath();const pulse=reduced.matches?i*5:(t*12+i*9)%24;c.ellipse(x,y+6,10+pulse,(10+pulse)*.28,0,0,Math.PI*2);c.stroke();}
     c.fillStyle='#d96955';c.beginPath();c.ellipse(x,y,4,10,0,0,Math.PI*2);c.fill();c.fillStyle='#fff3d3';c.fillRect(x-3,y-5,6,4);
     if(biting&&!model.reeling){c.textAlign='center';c.font='600 15px system-ui';c.fillStyle='#fff4d3';c.shadowColor='#142f38';c.shadowBlur=4;c.fillText('咬鉤了',x,y-23);c.shadowBlur=0;}
    }
   }
   if(celebration&&now-celebration.at<1800){const age=(now-celebration.at)/1800;c.save();c.globalAlpha=reduced.matches?1:Math.min(1,(1-age)*4);fish(celebration.id,w*.64,h*.48,Math.min(230,w*.55),1,reduced.matches?0:-.08);c.restore();}
   const failed=Object.values(assets).some(img=>img.complete&&!img.naturalWidth);canvas.dataset.artState=failed?'failed':'ready';
   if(failed){c.fillStyle='#082b31ed';c.fillRect(8,h-39,w-16,30);c.fillStyle='#fff0c9';c.font='12px system-ui';c.textAlign='center';c.fillText('部分素材未載入，可使用魚種選單與操作按鈕',w/2,h-20);}
   ready?.();
  }
  function tick(now){frame=0;if(!alive||document.hidden||!visible||reduced.matches)return;if(now-last>=33.3){draw(now);last=now;}frame=requestAnimationFrame(tick);}
  function resume(){if(alive&&visible&&!document.hidden&&!reduced.matches&&!frame)frame=requestAnimationFrame(tick);}
  function visibility(){if(document.hidden){cancelAnimationFrame(frame);frame=0;}else{draw();resume();}}
  function motion(){cancelAnimationFrame(frame);frame=0;draw();resume();}
  function pointer(event){if(model?.mode!=='arcade'||model.sending||model.blocked)return;const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top,t=reduced.matches?0:performance.now()/1000;let found=null,distance=Infinity;for(const f of entities){if(reduced.matches&&!f.main)continue;const p=position(f,t,r.width,r.height),d=Math.hypot((x-p.x),((y-p.y)*1.7));if(d<Math.max(36,p.size*.45)&&d<distance){found={id:f.id,x:p.x/r.width,y:p.y/r.height};distance=d;}}if(found){aim={x:found.x,y:found.y};pickedAim={...found,at:performance.now()};pick?.(found.id);}}
  canvas.addEventListener('click',pointer);document.addEventListener('visibilitychange',visibility);reduced.addEventListener('change',motion);
  const resize=new ResizeObserver(()=>draw());resize.observe(canvas);
  const intersection=new IntersectionObserver(entries=>{visible=entries.at(-1).isIntersecting;if(visible){draw();resume();}else{cancelAnimationFrame(frame);frame=0;}});intersection.observe(canvas);
  for(const name of ['fish-atlas','gear-atlas','harbor','reef'])assets[name]=image(name,()=>{if(alive)draw();});
  return {
   update(next){if(mode!==next.mode){mode=next.mode;setup();flight=null;celebration=null;}model=next;const result=next.result;if(result?.operation_id!==resultKey){resultKey=result?.operation_id;if(result?.species&&(result.caught||result.action==='reel'))celebration={id:result.species,at:performance.now()};}draw();resume();},
   fire(id){const r=canvas.getBoundingClientRect(),f=entities.find(v=>v.id===id&&v.main);if(pickedAim?.id===id&&performance.now()-pickedAim.at<1000){aim={x:pickedAim.x,y:pickedAim.y};pickedAim=null;}else if(f){const p=position(f,reduced.matches?0:performance.now()/1000,r.width,r.height);aim={x:p.x/r.width,y:p.y/r.height};}flight={...aim,at:performance.now()};draw();},
   cast(){castAt=performance.now();draw();},
   draw,
   destroy(){alive=false;cancelAnimationFrame(frame);resize.disconnect();intersection.disconnect();canvas.removeEventListener('click',pointer);document.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',motion);}
  };
 }
 return {create,portrait,gearArt,gearNames,traits};
})();
