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
 function worldPosition(f,clock,effects=[]){let t=Math.max(0,clock-f.spawned_at);for(const e of effects)t-=Math.max(0,Math.min(clock,e.ends_at)-Math.max(f.spawned_at,e.starts_at));return {x:f.x0+f.vx*t,y:f.y0+f.amplitude*Math.sin(t*f.frequency+f.phase)};}
 function fishY(data,at){const t=Math.max(0,at-data.hooked_at),p=data.path;return Math.min(.93,Math.max(.07,.5+p.a*Math.sin(t*p.speed+p.phase)+p.b*Math.sin(t*p.speed*2.17+p.phase*.7)));}
 function skillProjection(source,clock,holding){if(!source||source.phase!=='playing')return source;const d={...source},target=Math.min(clock,d.deadline);d.holding=holding;d.input_at=clock;let count=0;while(d.sim_at+.05<=target+1e-7&&d.phase==='playing'&&count++<80){const at=d.sim_at+.05,held=d.holding&&at-d.input_at<=1.1;let v=Math.max(-.85,Math.min(.85,d.velocity*.86+(held?-.125:.105))),y=d.zone_y+v*.05,half=d.width/2;if(y<half){y=half;v=0;}if(y>1-half){y=1-half;v=0;}const inside=Math.abs(fishY(d,at)-y)<=half;d.progress=Math.max(0,Math.min(1,d.progress+(inside?.155*d.rate:-.105)*.05));d.escape=Math.max(0,Math.min(1,d.escape+(inside?-.055:.145)*.05));Object.assign(d,{sim_at:at,zone_y:y,velocity:v});if(d.progress>=1)d.phase='caught';else if(d.escape>=1)d.phase='escaped';}return d;}
 function create(canvas,callbacks){
  let model=null,frame=0,last=0,alive=true,visible=true,localShots=new Map(),castAt=0,lastHud=0,aim={x:500,y:250},targetId=null;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),c=canvas.getContext('2d'),assets={};
  function imagePart(name,sx,sy,sw,sh,x,y,w,h){const img=assets[name];if(img?.complete&&img.naturalWidth)c.drawImage(img,sx,sy,sw,sh,x,y,w,h);}
  function fish(id,x,y,size,dir=1,angle=0,alpha=1){const img=assets['fish-atlas'],i=ids.indexOf(id);if(!img?.naturalWidth||i<0)return;const [rx,ry,rw]=regions[i],unit=img.naturalWidth/4,sw=unit*rw,sh=img.naturalHeight/2;c.save();c.translate(x,y);c.rotate(angle);c.scale(dir,1);c.globalAlpha=alpha;imagePart('fish-atlas',rx*unit,ry*sh,sw,sh,-size/2,-size*sh/sw/2,size,size*sh/sw);c.restore();}
  function gear(kind,index,x,y,size,angle=0){const img=assets['gear-atlas'];if(!img?.naturalWidth)return;const sw=img.naturalWidth/3,sy=kind==='rod'?0:img.naturalHeight*.46,sh=kind==='rod'?img.naturalHeight*.46:img.naturalHeight*.54;c.save();c.translate(x,y);c.rotate(angle);imagePart('gear-atlas',index*sw,sy,sw,sh,-size/2,-size*.8,size,size*sh/sw);c.restore();}
  function text(value,x,y,size=13,color='#f9e8bd'){c.font='600 '+size+'px system-ui';c.textAlign='center';c.fillStyle=color;c.shadowColor='#082b31';c.shadowBlur=3;c.fillText(value,x,y);c.shadowBlur=0;}
  function projectile(s,clock,own){if(clock<s.born_at)return;const age=clock-s.born_at,color=own?'#ffe29b':'#9bdbf2';if(s.state==='flying'||!s.state){if(age>1.3)return;const x=s.x0+s.vx*age,y=s.y0+s.vy*age;c.strokeStyle=color;c.lineWidth=own?4:2;c.beginPath();c.moveTo(x-s.vx*.035,y-s.vy*.035);c.lineTo(x,y);c.stroke();c.fillStyle=color;c.beginPath();c.arc(x,y,own?6:4,0,Math.PI*2);c.fill();}else if(s.hit_x!==undefined&&clock-s.resolved_at<.65){const r=s.radius+15;c.save();c.globalAlpha=Math.max(0,1-(clock-s.resolved_at)/.65);c.translate(s.hit_x,s.hit_y);c.strokeStyle=s.caught?'#ffe29b':color;c.lineWidth=2;c.beginPath();c.arc(0,0,r,0,Math.PI*2);for(let j=-2;j<=2;j++){const v=j*r/3,e=Math.sqrt(r*r-v*v);c.moveTo(-e,v);c.lineTo(e,v);c.moveTo(v,-e);c.lineTo(v,e);}c.stroke();if(s.caught)text('＋'+s.gross,0,-r-10,20);c.restore();}}
  function draw(now=performance.now()){
   if(!alive||!model||document.hidden||!visible)return;const r=canvas.getBoundingClientRect(),w=r.width,h=r.height,ratio=Math.min(w<600?1.5:2,devicePixelRatio||1);if(!w||!h)return;
   if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,w,h);c.fillStyle='#123c43';c.fillRect(0,0,w,h);
   const bg=assets[model.mode==='leisure'?'harbor':'reef'];if(bg?.naturalWidth){const scale=Math.max(w/bg.naturalWidth,h/bg.naturalHeight),bw=bg.naturalWidth*scale,bh=bg.naturalHeight*scale;c.drawImage(bg,(w-bw)/2,(h-bh)/2,bw,bh);}const clock=model.now();
   if(model.mode==='arcade'){
    const world=model.world;c.save();c.scale(w/1000,h/600);
    if(world){
     for(const f of world.entities){if(clock<f.spawned_at||clock>=f.expires_at)continue;const p=worldPosition(f,clock,world.effects);fish(f.species,p.x,p.y,f.radius_x*2.65,f.vx<0?-1:1,reduced.matches?0:Math.sin(clock*2+f.phase)*.035);text((f.boss?'巨獸 ':'')+f.multiplier+'×',p.x,p.y+f.radius_y+14,f.boss?28:24);if(f.id===targetId){c.strokeStyle='#ffe4a4';c.lineWidth=2;c.setLineDash([7,6]);c.beginPath();c.ellipse(p.x,p.y,f.radius_x+10,f.radius_y+8,0,0,Math.PI*2);c.stroke();c.setLineDash([]);}}
     for(const p of world.players){const x=80+p.seat*168,own=p.user_id===model.user;const angle=own?Math.atan2(aim.y-562,aim.x-x)+Math.PI/2:0;gear('cannon',own?model.cannon:p.cannon||0,x,562,own?110:74,angle);text((own?'你・':'')+p.nickname.slice(0,5),x,594,own?25:23,own?'#ffe4a4':'#d2e7de');}
     for(const s of world.projectiles)projectile(s,clock,s.user_id===model.user);
     if(world.effects.some(e=>e.starts_at<=clock&&e.ends_at>clock)){c.fillStyle='#a3dff525';c.fillRect(0,0,1000,600);text('魚場冰凍中',500,95,22,'#e2f6ff');}
    }
    for(const [token,s] of localShots){if(world?.projectiles.some(p=>p.token===token&&p.user_id===model.user)||clock-s.born_at>1.5){localShots.delete(token);continue;}projectile(s,clock,true);}
    if(!targetId){c.strokeStyle='#fff0b9cc';c.lineWidth=2;c.beginPath();c.arc(aim.x,aim.y,22,0,Math.PI*2);c.moveTo(aim.x-32,aim.y);c.lineTo(aim.x+32,aim.y);c.moveTo(aim.x,aim.y-32);c.lineTo(aim.x,aim.y+32);c.stroke();}
    if(!model.connected)text('正在同步共享魚場…',500,290,22);
    c.restore();
   }else{
    const active=model.pending,biting=active?.phase==='waiting'&&clock>=active.ready_at;
    const t=reduced.matches?0:now/1000,progress=active?.phase==='playing'?active.progress:0;
    const floatX=w*(.61-progress*.15),floatY=h*(.57-progress*.12)+(reduced.matches?0:Math.sin(t*(biting?8:2))*(biting?4:1.4));
    const rodSize=Math.min(w*.52,280),rodX=w*.2,rodY=h*.9;gear('rod',model.rod,rodX,rodY,rodSize,-progress*.15);
    if(active||model.sending){const travel=castAt&&!reduced.matches?Math.min(1,(now-castAt)/600):1,x=w*.27+(floatX-w*.27)*travel,y=floatY-Math.sin(travel*Math.PI)*h*.28;
     c.strokeStyle='#f8ecd1cc';c.lineWidth=.9;c.beginPath();c.moveTo(rodX+rodSize*.36,rodY-rodSize*.68);c.quadraticCurveTo(w*.5,h*.3,x,y);c.stroke();c.strokeStyle='#f3e5be99';c.beginPath();c.ellipse(x,y+6,18,5,0,0,Math.PI*2);c.stroke();c.fillStyle='#d96955';c.beginPath();c.ellipse(x,y,4,10,0,0,Math.PI*2);c.fill();c.fillStyle='#fff3d3';c.fillRect(x-3,y-5,6,4);if(biting)text('提竿！',x,y-24,17);}
    if(active?.phase==='playing'){
     const d=skillProjection(active,clock,model.holding),fy=fishY(d,clock),panelX=w*.8,panelY=h*.22,panelH=h*.58,panelW=Math.max(32,w*.07);c.fillStyle='#082b31df';c.fillRect(panelX-panelW/2-6,panelY-7,panelW+12,panelH+14);c.fillStyle='#dfca7b88';c.fillRect(panelX-panelW/2,panelY+(d.zone_y-d.width/2)*panelH,panelW,d.width*panelH);fish(d.species,panelX,panelY+fy*panelH,panelW*1.8,1,0);text('收線區',panelX,panelY-15,12);text('逃脫 '+Math.round(d.escape*100)+'%',w*.48,h*.24,13,d.escape>.65?'#ffc0ad':'#fff0cd');if(now-lastHud>100){callbacks.skillFrame?.(d);lastHud=now;}
    }
   }
   const failed=Object.values(assets).some(img=>img.complete&&!img.naturalWidth);canvas.dataset.artState=failed?'failed':'ready';if(failed)text('部分素材未載入，可使用操作按鈕',w/2,h-20,12);
  }
  function tick(now){frame=0;if(!alive||document.hidden||!visible)return;if(now-last>=(reduced.matches?50:33.3)){draw(now);last=now;}frame=requestAnimationFrame(tick);}
  function resume(){if(alive&&visible&&!document.hidden&&!frame)frame=requestAnimationFrame(tick);}
  function visibility(){if(document.hidden){cancelAnimationFrame(frame);frame=0;}else{draw();resume();}}
  function point(event){if(model?.mode!=='arcade'||!model.world)return null;const r=canvas.getBoundingClientRect(),x=(event.clientX-r.left)/r.width*1000,y=(event.clientY-r.top)/r.height*600;let selected=null,dist=Infinity;for(const f of model.world.entities){if(model.now()<f.spawned_at||model.now()>=f.expires_at)continue;const p=worldPosition(f,model.now(),model.world.effects),d=((x-p.x)/f.radius_x)**2+((y-p.y)/f.radius_y)**2;if(d<=1.5&&d<dist){selected=f;dist=d;}}aim={x,y:Math.min(525,y)};targetId=selected?.id||null;callbacks.aim?.(aim.x,aim.y,targetId);return {x,y,id:targetId};}
  function down(e){if(model?.mode!=='arcade')return;point(e);e.preventDefault();canvas.setPointerCapture(e.pointerId);callbacks.shootStart?.();}
  function move(e){if(model?.mode==='arcade')point(e);}
  function up(){callbacks.shootStop?.();}
  canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);document.addEventListener('visibilitychange',visibility);
  const resize=new ResizeObserver(()=>draw());resize.observe(canvas);const intersection=new IntersectionObserver(entries=>{visible=entries.at(-1).isIntersecting;if(visible){draw();resume();}else{cancelAnimationFrame(frame);frame=0;callbacks.shootStop?.();}});intersection.observe(canvas);
  for(const name of ['fish-atlas','gear-atlas','harbor','reef'])assets[name]=image(name,()=>{if(alive)draw();});
  return {update(next){model=next;resume();},aim(id){targetId=id;},cast(){castAt=performance.now();draw();},
   shotLocal(s,cannon){const player=model?.world?.players.find(p=>p.user_id===model.user);if(!player)return;const x0=80+player.seat*168,y0=562,d=Math.hypot(s.x-x0,s.y-y0);localShots.set(s.token,{token:s.token,born_at:s.fired_at,x0,y0,vx:(s.x-x0)/d*1150,vy:(s.y-y0)/d*1150,radius:model.cannons?.[cannon]?.radius||15});},
   rejectShots(tokens){for(const token of tokens)localShots.delete(token);},draw,
   destroy(){alive=false;cancelAnimationFrame(frame);resize.disconnect();intersection.disconnect();canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);document.removeEventListener('visibilitychange',visibility);}
  };
 }
 return {create,portrait,gearArt,gearNames,traits,worldPosition,fishY,skillProjection};
})();
