'use strict';
// Presentation only: no random outcomes, wallet mutations, or delayed commands.
window.ClubArcadeMotion=(()=>{
  const order=[0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26];
  const reds=new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),effects=new Set(),timers=new Set();
  const layer=document.createElement('div');layer.id='arcade-motion-layer';layer.setAttribute('aria-hidden','true');document.body.append(layer);
  let state=null,epoch=0,resultPanel=null;
  const cardKey=(uid,hand,index)=>`bj-${uid}-${hand}-${index}`;
  function plan(previous,next,uid){
    const jobs=[],h=next?.hand,old=previous?.hand,fresh=h?.id!==old?.id;
    if(!h||!previous||previous.id!==next.id||!['big2','blackjack','roulette','inbetween'].includes(next.game_type))return {jobs,wheel:false};
    if(next.game_type==='inbetween'){if(fresh)jobs.push({key:'gate-left',kind:'card'},{key:'gate-right',kind:'card'});else if(!old.third&&h.third)jobs.push({key:'gate-shot',kind:'flip'});}
    if(next.game_type==='big2'&&fresh){
      for(let i=0;i<13;i++)for(const p of h.players){
        if(p.user_id===uid&&p.cards[i])jobs.push({key:`big2-${p.cards[i]}`,kind:'card'});
        else if(p.user_id!==uid)jobs.push({key:`seat-${p.user_id}-${i}`,seat:p.user_id,kind:'back'});
      }
    }
    if(next.game_type==='blackjack'){
      if(fresh){
        for(let i=0;i<2;i++){for(const p of h.players)jobs.push({key:cardKey(p.user_id,0,i),kind:'card'});jobs.push({key:`bj-dealer-${i}`,kind:'card'});}
      }else for(const p of h.players){
        const prior=old.players.find(q=>q.user_id===p.user_id);if(!prior)continue;
        if(p.hands.length>prior.hands.length){
          const start=p.hands.findIndex((v,i)=>JSON.stringify(v.cards)!==JSON.stringify(prior.hands[i]?.cards));
          for(let i=start;i<=start+p.hands.length-prior.hands.length;i++)jobs.push({key:cardKey(p.user_id,i,1),kind:'card'});
        }else p.hands.forEach((v,i)=>{for(let c=prior.hands[i]?.cards.length||0;c<v.cards.length;c++)jobs.push({key:cardKey(p.user_id,i,c),kind:'card'});});
      }
      if(!fresh&&old.dealer[1]===null&&h.dealer[1]!==null)jobs.push({key:'bj-dealer-1',kind:'flip'});
      for(let i=fresh?2:old.dealer.length;i<h.dealer.length;i++)jobs.push({key:`bj-dealer-${i}`,kind:'card'});
    }
    return {jobs,wheel:next.game_type==='roulette'&&h.phase==='showdown'&&(fresh||old.phase!=='showdown')};
  }
  function removeResult(){resultPanel?.node.remove();resultPanel=null;}
  function clearMotion(){
    epoch++;for(const t of timers)clearTimeout(t);timers.clear();for(const a of effects)a.cancel();effects.clear();layer.replaceChildren();
    document.querySelectorAll('.arcade-card-pending').forEach(e=>e.classList.remove('arcade-card-pending'));
    document.querySelectorAll('.roulette-wheel.is-spinning').forEach(e=>e.classList.remove('is-spinning'));state=null;
  }
  function cancel(){clearMotion();removeResult();}
  function watch(el,frames,options,done=()=>{}){
    try{const a=el.animate(frames,options);effects.add(a);a.finished.then(()=>{effects.delete(a);done();},()=>effects.delete(a));return a;}
    catch{done();return null;}
  }
  function later(fn,delay){const t=setTimeout(()=>{timers.delete(t);fn();},delay);timers.add(t);return t;}
  function prepare(previous,next,uid){
    const h=next?.hand;
    if(resultPanel&&(resultPanel.room!==next?.id||resultPanel.hand!==h?.id||next.status==='closed'))removeResult();
    if(reduced.matches||document.visibilityState!=='visible'||!previous||!h||previous.id!==next.id||!['big2','blackjack','roulette','inbetween'].includes(next.game_type)){clearMotion();return;}
    const fresh=h.id!==previous.hand?.id;
    if(fresh&&next.server_time-h.started_at>5||h.phase==='showdown'&&next.server_time-h.finished_at>5){clearMotion();return;}
    if(state&&(state.room!==next.id||state.hand!==h.id))cancel();
    if(!state)state={room:next.id,hand:h.id,jobs:new Map(),queue:[],running:false,wheel:false,wheelPlayed:false};
    const p=plan(previous,next,uid);
    for(const job of p.jobs)if(!state.jobs.has(job.key)){state.jobs.set(job.key,job);state.queue.push(job);}
    if(p.wheel&&!state.wheelPlayed)state.wheel=true;
  }
  function target(job){return document.querySelector(job.seat?`[data-deal-seat="${job.seat}"]`:`[data-card-key="${job.key}"]`);}
  function visible(el,box){
    if(!el||!box.width||!box.height||box.bottom<0||box.top>innerHeight||box.right<0||box.left>innerWidth)return false;
    const scroller=el.closest('.hand-scroll,.split-hands');if(!scroller)return true;
    const clip=scroller.getBoundingClientRect();return box.right>clip.left&&box.left<clip.right;
  }
  function reveal(job){const el=target(job);el?.classList.remove('arcade-card-pending');if(state?.jobs.get(job.key)===job)state.jobs.delete(job.key);}
  // CSP (style-src 'self') blocks the template's style attribute and patchNode's setAttribute('style'),
  // so the resting rotor angle is written through CSSOM. The un-filled spin animation then ends on it.
  const rest=new WeakMap();
  function settle(){
    for(const rotor of document.querySelectorAll('.roulette-wheel>.roulette-rotor')){
      const value=rotor.parentElement.dataset.winningNumber,index=value===''?0:order.indexOf(Number(value)),angle=index>0?-index*360/37:0,last=rest.get(rotor);
      rest.set(rotor,{angle,from:last?last.angle:0});
      rotor.style.transform=`rotate(${angle}deg)`;
    }
  }
  function play(){
    settle();
    if(!state)return;
    // Reapply pending state after an SSE DOM patch; never hide controls or totals.
    for(const job of state.jobs.values())if(job.kind!=='back')target(job)?.classList.add('arcade-card-pending');
    if(state.wheel&&!state.wheelPlayed){state.wheel=false;state.wheelPlayed=true;spin();}
    if(state.running||!state.queue.length)return;state.running=true;const token=epoch;
    // Read all geometry before creating animation layers (no layout writes in the loop).
    const deck=document.querySelector('.arcade-deck'),origin=deck?.getBoundingClientRect();
    const jobs=state.queue.splice(0).map(job=>{const el=target(job),box=el?.getBoundingClientRect();return {job,box,show:el&&visible(el,box)};});
    const safety=later(()=>{if(epoch===token)cancel();},1800);
    let index=0;
    function step(){
      if(epoch!==token||!state)return;
      const item=jobs[index++];
      if(!item){state.running=false;if(!effects.size){clearTimeout(safety);timers.delete(safety);}if(state.queue.length)play();return;}
      const {job,box,show}=item;
      if(!show||!origin||!visible(deck,origin)){reveal(job);step();return;}
      // A throttled/stalled browser must not accumulate dozens of GPU layers.
      if(effects.size>=6){reveal(job);later(step,28);return;}
      if(job.kind==='flip'){
        reveal(job);const el=target(job);if(el)watch(el,[{transform:'rotateY(90deg)',opacity:.3},{transform:'rotateY(0)',opacity:1}],{duration:160,easing:'ease-out'});
      }else{
        const ghost=document.createElement('span');ghost.className='playing-card covered arcade-card-flight';ghost.innerHTML='<span>♠</span>';
        const w=job.kind==='back'?28:box.width,h=job.kind==='back'?40:box.height;
        ghost.style.width=w+'px';ghost.style.height=h+'px';layer.append(ghost);
        const x=origin.left+origin.width/2-w/2,y=origin.top;
        watch(ghost,[{transform:`translate(${x}px,${y}px) rotate(-14deg) scale(.65)`,opacity:0},{offset:.12,transform:`translate(${x}px,${y}px) rotate(-14deg) scale(.8)`,opacity:1},{transform:`translate(${box.left}px,${box.top}px) rotate(0deg) scale(1)`,opacity:1}],{duration:150,easing:'cubic-bezier(.2,.65,.2,1)'},()=>{ghost.remove();if(epoch===token)reveal(job);});
      }
      later(step,Math.min(55,Math.max(28,1100/jobs.length)));
    }
    step();
  }
  function spin(){
    let wheel=document.querySelector('.roulette-wheel');if(!wheel)return;
    let popover=null;const from=rest.get(wheel.querySelector('.roulette-rotor'))?.from||0;
    const originalBox=wheel.getBoundingClientRect();
    if(!visible(wheel,originalBox)||originalBox.top<56||originalBox.bottom>innerHeight-8){
      removeResult();popover=document.createElement('aside');popover.className='roulette-result-popover';
      popover.setAttribute('role','region');popover.setAttribute('aria-label','本局輪盤結果');
      const copy=wheel.cloneNode(true),caption=document.createElement('p');caption.textContent=`開出 ${wheel.dataset.winningNumber} · 已結算`;
      const dismiss=document.createElement('button');dismiss.className='button ghost';dismiss.type='button';dismiss.textContent='收起轉盤';dismiss.setAttribute('aria-label','收起輪盤結果');dismiss.onclick=removeResult;
      popover.append(copy,caption,dismiss);document.body.append(popover);resultPanel={node:popover,room:state.room,hand:state.hand};wheel=copy;
    }
    const rotor=wheel.querySelector('.roulette-rotor'),orbit=wheel.querySelector('.roulette-ball-orbit'),ball=wheel.querySelector('.roulette-ball');
    if(!rotor||!orbit||!ball){removeResult();return;}
    const box=wheel.getBoundingClientRect();
    const token=epoch,number=Number(wheel.dataset.winningNumber),angle=-order.indexOf(number)*360/37;
    wheel.classList.add('is-spinning');
    watch(rotor,[{transform:`rotate(${from}deg)`},{transform:`rotate(${1440+angle}deg)`}],{duration:2350,easing:'cubic-bezier(.12,.4,.18,1)'});
    watch(orbit,[{transform:'rotate(0deg)'},{transform:'rotate(-1440deg)'}],{duration:2350,easing:'cubic-bezier(.1,.38,.2,1)'});
    watch(ball,[{transform:`translateY(${-box.width*.09}px)`,offset:0},{transform:`translateY(${-box.width*.09}px)`,offset:.65},{transform:'translateY(3px)',offset:.84},{transform:'translateY(-2px)',offset:.9},{transform:'translateY(0)',offset:1}],{duration:2350,easing:'ease-out'},()=>{if(token===epoch)wheel.classList.remove('is-spinning');});
    later(()=>{if(token===epoch){for(const a of effects)a.cancel();effects.clear();wheel.classList.remove('is-spinning');}},2600);
  }
  function wheel(number){
    const result=Number.isInteger(number),angle=result?-order.indexOf(number)*360/37:0;
    const point=(r,deg)=>[100+r*Math.sin(deg*Math.PI/180),100-r*Math.cos(deg*Math.PI/180)];
    const segments=order.map((v,i)=>{const deg=i*360/37,a=point(96,deg-180/37),b=point(96,deg+180/37),c=point(64,deg+180/37),d=point(64,deg-180/37),label=point(83,deg);return `<path d="M${a} A96 96 0 0 1 ${b} L${c} A64 64 0 0 0 ${d}Z" fill="${v===0?'#287655':reds.has(v)?'#92334a':'#20292b'}" stroke="#b99a6355" stroke-width=".65"/><text x="${label[0]}" y="${label[1]}" dy="3" transform="rotate(${deg} ${label.join(' ')})">${v}</text>`;}).join('');
    return `<div class="roulette-wheel" data-winning-number="${result?number:''}" aria-hidden="true"><div class="roulette-rotor" style="transform:rotate(${angle}deg)"><svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="99" fill="#413425"/>${segments}<circle cx="100" cy="100" r="62" fill="#25483a" stroke="#b99a63" stroke-width="2"/><path d="M100 42v116M42 100h116" stroke="#b99a63" stroke-width="3"/></svg></div><div class="wheel-hub">${result?number:'♠'}</div><div class="roulette-ball-orbit"><span class="roulette-ball"></span></div></div>`;
  }
  window.addEventListener('resize',clearMotion,{passive:true});window.addEventListener('pagehide',cancel,{passive:true});
  window.addEventListener('scroll',()=>{if(!state?.wheelPlayed)clearMotion();},{passive:true});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='visible')clearMotion();});
  reduced.addEventListener?.('change',clearMotion);
  return {plan,prepare,play,cancel,wheel,order,pending:key=>!!state?.jobs.has(key)};
})();
