/* Fishing command loops: one durable wallet request, separate skill input and world SSE. */
'use strict';
window.ClubFishingPlay=(()=>{
 const version=3;
 function create(ctx){
  let alive=true,stream=null,room=1,world=null,connected=false,lastWorld=0,streamId=ctx.id(),heartbeat=0,monitor=0,inputTimer=0,inputBusy=false,inputPending=null,held=false,shootTimer=0,shooting=false,auto=false,queue=[],flushTimer=0,flushing=false,flushAt=0,pendingCost=0,generation=0,lastInterval=0,lastFire=-1e10,aim={x:500,y:250},target=null,seen=new Set(),readTimer=0;
  const now=()=>ctx.now(),get=()=>ctx.state();
  function notice(text,error=false){if(alive)ctx.notice(text,error);}
  function stop(){const changed=shooting||auto;shooting=false;auto=false;clearInterval(shootTimer);shootTimer=0;if(changed)ctx.firing?.(false);if(queue.length)void flush();}
  function discard(){ctx.rejectShots?.(queue.map(s=>s.token));queue=[];clearTimeout(flushTimer);flushTimer=0;}
  function closeWorld(){generation++;discard();stop();stream?.close();stream=null;connected=false;ctx.world(null,false);clearInterval(heartbeat);clearInterval(monitor);heartbeat=monitor=0;}
  function refreshSoon(){if(readTimer)return;readTimer=setTimeout(()=>{readTimer=0;if(alive)ctx.refresh();},650);}
  function open(rid){
   if(!alive)return;if(stream&&room===rid)return;closeWorld();room=rid;lastWorld=Date.now();const subscription=generation;world=null;
   stream=new EventSource('/api/fishing/events?room='+rid+'&client=fish_'+streamId);
   stream.addEventListener('world',event=>{if(!alive||subscription!==generation)return;let next;try{next=JSON.parse(event.data);}catch{return;}if(world&&next.room_id===world.room_id&&next.server_time<world.server_time)return;world=next;lastWorld=Date.now();connected=true;ctx.world(next,true);
    let own=false;for(const s of next.projectiles){if(s.user_id!==ctx.user||s.state==='flying'||seen.has(s.id))continue;seen.add(s.id);ctx.outcome?.(s);own=true;}
    if(seen.size>500)seen=new Set([...seen].slice(-250));if(own)refreshSoon();
   });
   stream.addEventListener('auth',()=>{closeWorld();notice('登入已失效，請重新登入。',true);});
   stream.onerror=()=>{if(subscription!==generation)return;connected=false;discard();stop();ctx.world(world,false);notice('魚場重新連線中，已停止連發。');};
   heartbeat=setInterval(async()=>{if(!alive||document.hidden||get()?.member?.room_id!==room)return;try{await ctx.api('/api/fishing/heartbeat',{gameplay_version:version,room_id:room,operation_id:ctx.id()});}catch(e){stop();notice(e.message,true);}},12000);
   monitor=setInterval(()=>{if(connected&&Date.now()-lastWorld>6000){connected=false;discard();stop();ctx.world(world,false);notice('魚場同步較慢，已停止發射。');}},1000);
  }
  function point(id){const f=world?.entities.find(v=>v.id===id&&v.spawned_at<=now()&&v.expires_at>now());if(!f)return null;const me=world.players.find(p=>p.user_id===ctx.user),origin=window.ClubFishingScene.origin(me?.seat||0);let position=window.ClubFishingScene.worldPosition(f,now(),world.effects);for(let i=0;i<2;i++){const lead=Math.hypot(position.x-origin.x,position.y-origin.y)/1150+.14;position=window.ClubFishingScene.worldPosition(f,now()+lead,world.effects);}return {x:Math.max(0,Math.min(1000,position.x)),y:Math.max(0,Math.min(600,position.y))};}
  function emit(){
   const state=get();if(!alive||!state||!connected||!state.member||state.member.room_id!==room||ctx.blocked()||document.hidden)return stop();
   if(flushing&&Date.now()-flushAt>900){queue.splice(0).forEach(s=>ctx.rejectShots?.([s.token]));stop();notice('網路確認較慢，已停止連發，請先確認原操作。');return;}if(queue.length>=4)return;
   const weapon=state.cannons[ctx.gears().cannon],clock=now();if(clock-lastFire<Math.max(lastInterval,weapon.interval))return;
   const reserve=queue.length*ctx.stake()+pendingCost;if(state.wallet.balance-reserve<ctx.stake()){stop();notice('可用點數不足，已停止發射。');return;}
   if(target){const p=point(target);if(!p){target=null;stop();notice('目標已離開或被捕獲，請重新瞄準。');return;}aim=p;}
   const shot={token:ctx.id(),fired_at:clock,x:aim.x,y:aim.y};queue.push(shot);lastFire=clock;lastInterval=weapon.interval;ctx.localShot(shot,ctx.gears().cannon);
   if(queue.length>=3)void flush();else if(!flushTimer)flushTimer=setTimeout(()=>{flushTimer=0;void flush();},220);
  }
  async function flush(){
   if(flushing||!queue.length||!alive)return;clearTimeout(flushTimer);flushTimer=0;flushing=true;flushAt=Date.now();
   const shots=queue.splice(0,4),data={room_id:room,cannon:ctx.gears().cannon,stake:ctx.stake(),shots};pendingCost=shots.length*data.stake;
   try{const reply=await ctx.command('burst',data);if(!reply){stop();queue=[];ctx.rejectShots?.(shots.map(s=>s.token));}}
   finally{flushing=false;pendingCost=0;if(queue.length){if(ctx.blocked()){queue=[];stop();}else flushTimer=setTimeout(()=>{flushTimer=0;void flush();},50);}}
  }
  function start(automatic=false){if(shooting)return;auto=automatic;shooting=true;emit();if(!shooting)return;ctx.firing?.(true);shootTimer=setInterval(emit,30);}
  async function input(){
   const cast=get()?.pending;if(!alive||document.hidden||cast?.phase!=='playing'||inputBusy)return;
   inputBusy=true;const id=cast.id;
   if(!inputPending||inputPending.cast_id!==id){inputPending={gameplay_version:version,operation_id:ctx.id(),cast_id:id,sequence:cast.sequence+1,holding:held};const value=ctx.control?.();if(cast.mechanic==='tension'&&value!==null&&value!==undefined)inputPending.control=value;}
   try{const reply=await ctx.api('/api/fishing/input',inputPending);if(!alive)return;inputPending=null;ctx.skill(reply.skill);}
   catch(e){if(!alive)return;if(!e.retryable){inputPending=null;try{const synced=await ctx.api('/api/fishing/skill-state?version=3');ctx.skill(synced);if(!synced.pending&&synced.last_cast?.id===id)return;notice('收線狀態已同步');return;}catch{}}notice(e.message,true);}
   finally{inputBusy=false;}
  }
  function watchSkill(){clearInterval(inputTimer);inputTimer=setInterval(input,300);}
  function visibility(){if(document.hidden){closeWorld();held=false;if(get()?.pending?.phase==='playing')void input();closeWorld();}else if(alive){ctx.refresh();if(ctx.mode()==='arcade'&&get()?.member)open(get().member.room_id);}}
  document.addEventListener('visibilitychange',visibility);watchSkill();
  return {
   open,close:closeWorld,pause(){discard();stop();},world:()=>world,connected:()=>connected,
   aim(x,y,id=null){aim={x:Math.max(0,Math.min(1000,x)),y:Math.max(0,Math.min(600,y))};target=ctx.locked?.()?id||target:null;},
   target(id){target=id;const p=point(id);if(p)aim=p;},
   tap(){emit();},start,stop,release(){if(!auto)stop();},toggle(){shooting?stop():start(true);},
   hold(value){held=value;const cast=get()?.pending;if(cast?.phase==='playing'&&now()-cast.input_at>.08)void input();},
   holding:()=>held,
   modeChanged(){stop();held=false;if(ctx.mode()!=='arcade'){closeWorld();if(get()?.member)ctx.api('/api/fishing/leave',{gameplay_version:version,operation_id:ctx.id()}).then(r=>{if(alive)ctx.accept(r.state);}).catch(()=>{});}},
   destroy(){alive=false;closeWorld();held=false;clearInterval(inputTimer);clearTimeout(flushTimer);clearTimeout(readTimer);document.removeEventListener('visibilitychange',visibility);if(get()?.member)ctx.api('/api/fishing/leave',{gameplay_version:version,operation_id:ctx.id()}).catch(()=>{});},
  };
 }
 return {create};
})();
