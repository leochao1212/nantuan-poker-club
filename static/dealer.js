'use strict';
// A visual queue only. Cards, actions and deadlines remain authoritative on the server.
window.ClubDealer=(()=>{
  let state=null,epoch=0;
  const timers=new Set(),effects=new Set(),layer=document.createElement('div');
  layer.id='deal-layer';layer.setAttribute('aria-hidden','true');document.body.append(layer);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),target=key=>document.querySelector(`[data-card-key="${key}"]`);
  function cancel(){epoch++;for(const t of timers)clearTimeout(t);timers.clear();for(const effect of effects)effect.cancel();effects.clear();layer.replaceChildren();document.querySelectorAll('.deal-pending').forEach(el=>el.classList.remove('deal-pending'));state=null;}
  function prepare(previous,next){
    const fresh=previous?.hand?.id!==next.hand?.id;
    if(reduced.matches||document.visibilityState!=='visible'||!next.hand||!previous||previous.id!==next.id||(fresh&&next.server_time-next.hand.started_at>6)){cancel();return;}
    if(state&&(state.hand!==next.hand.id||state.room!==next.id))cancel();
    // New streets must never wait behind an old mobile animation queue.
    if(state&&(state.deadline&&performance.now()>=state.deadline||previous.hand?.phase!==next.hand.phase))cancel();
    if(!state)state={room:next.id,hand:next.hand.id,jobs:new Map(),running:false,deadline:0,watchdog:null};
    if(fresh){
      // Participant order is clockwise left of the button, matching the real engine deal.
      for(let round=0;round<2;round++)for(const player of next.hand.players)state.jobs.set(`hole-${player.user_id}-${round}`,{kind:'hole'});
    }
    const from=fresh?0:previous.hand?.board.length||0;
    if(next.hand.board.length>from)for(let i=from;i<next.hand.board.length;i++)state.jobs.set(`board-${i}`,{kind:'board'});
    if(state.jobs.size&&!state.deadline)state.deadline=performance.now()+(fresh?3200:1200);
  }
  function watch(effect){effects.add(effect);effect.finished.then(()=>effects.delete(effect),()=>effects.delete(effect));return effect;}
  function reveal(key,token){
    if(token!==epoch||!state?.jobs.has(key))return;state.jobs.delete(key);const el=target(key);if(!el)return;el.classList.remove('deal-pending');
    if(!el.classList.contains('covered')){const rest=getComputedStyle(el).transform;watch(el.animate([{opacity:.2,transform:(rest==='none'?'':rest)+' rotateY(90deg)'},{opacity:1,transform:rest}],{duration:170,easing:'ease-out'}));}
  }
  async function fly(key,job,token){
    if(token!==epoch||!state?.jobs.has(key))return;const el=target(key),felt=document.querySelector('.poker-felt');if(!el||!felt){reveal(key,token);return;}
    const box=el.getBoundingClientRect(),deck=felt.getBoundingClientRect(),ghost=document.createElement('span');ghost.className='playing-card covered deal-flight';ghost.innerHTML='<span>♠</span>';
    ghost.style.width=box.width+'px';ghost.style.height=box.height+'px';layer.append(ghost);
    const x=deck.left+deck.width/2-box.width/2,y=deck.top+24;
    try{
      const effect=watch(ghost.animate([{opacity:0,transform:`translate(${x}px,${y}px) rotate(-12deg) scale(.7)`},{opacity:1,offset:.12,transform:`translate(${x}px,${y}px) rotate(-12deg) scale(.85)`},{opacity:1,transform:`translate(${box.left}px,${box.top}px) rotate(0deg) scale(1)`}],{duration:job.kind==='hole'?190:160,easing:'cubic-bezier(.2,.65,.2,1)',fill:'both'}));
      await effect.finished;ghost.remove();reveal(key,token);
    }catch{ghost.remove();if(token===epoch)cancel();}
  }
  function play(){
    if(!state||state.running||!state.jobs.size)return;state.running=true;const token=epoch;
    const watchdog=setTimeout(()=>{timers.delete(watchdog);if(token===epoch)cancel();},Math.max(0,state.deadline-performance.now()));
    state.watchdog=watchdog;timers.add(watchdog);
    async function step(){
      if(token!==epoch||!state)return;const item=state.jobs.entries().next().value;
      if(!item){state.running=false;state.deadline=0;clearTimeout(state.watchdog);timers.delete(state.watchdog);state.watchdog=null;return;}const [key,job]=item;await fly(key,job,token);
      if(token!==epoch||!state)return;
      // Schedule from completion so a busy mobile browser cannot bunch overdue cards together.
      const timer=setTimeout(()=>{timers.delete(timer);step();},job.kind==='hole'?40:110);timers.add(timer);
    }
    const timer=setTimeout(()=>{timers.delete(timer);step();},30);timers.add(timer);
  }
  window.addEventListener('resize',cancel,{passive:true});window.addEventListener('wheel',cancel,{passive:true});window.addEventListener('touchmove',cancel,{passive:true});document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='visible')cancel();});reduced.addEventListener?.('change',cancel);
  return {prepare,play,cancel,pending:key=>!!state?.jobs.has(key)};
})();
