'use strict';
// One visual round lifecycle. Financial state and operation receipts stay in game.js/server.
window.ClubRoundPresentation=(()=>{
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),names=new Set(['roulette','slot']);
 let current=null,panel=null,seen=null,fast=false,retired=null,redrawOnReturn=false;
 try{fast=localStorage.getItem('club.fastReveal')==='1';}catch{}
 const instant=()=>fast||reduced.matches;
 const active=r=>!!current&&current.room===r.id;
 const masked=r=>active(r)&&!instant();
 const stage=r=>active(r)?current.paused?'confirming':current.phase:'idle';
 const emit=()=>document.dispatchEvent(new Event('club:presentation-change'));
 function stopTracks(s){for(const record of s?.tracks.values()||[])record.animation?.cancel();s?.tracks.clear();}
 function clearTimers(s){for(const key of ['stopTimer','finishTimer','waitTimer'])clearTimeout(s?.[key]);}
 function removePanel(){panel?.node.remove();panel=null;}
 function cancel(redraw=false){const had=!!current;clearTimers(current);stopTracks(current);current=null;removePanel();if(had&&redraw)emit();}
 function finish(){
  const s=current;if(!s?.result)return;
  clearTimers(s);stopTracks(s);current=null;
  if(panel){const w=panel.node.querySelector('.roulette-wheel');w.dataset.winningNumber=String(s.result.number);w.classList.remove('is-spinning');w.querySelector('.wheel-hub').textContent=s.result.number;w.querySelector('.roulette-rotor').style.transform=`rotate(${-window.ClubArcadeMotion.order.indexOf(s.result.number)*360/37}deg)`;w.querySelector('.roulette-ball-orbit').style.transform='rotate(0deg)';w.querySelector('.roulette-ball').style.transform='translateY(0)';panel.node.querySelector('p').textContent=s.result.summary;const button=panel.node.querySelector('button');button.disabled=false;button.textContent='收起轉盤';button.onclick=removePanel;}
  emit();
 }
 function fresh(r,operation=null){return {room:r.id,kind:r.game_type,phase:'waiting',operation,started:performance.now(),tracks:new Map(),result:null};}
 function begin(r,action,payload){
  if(!names.has(r.game_type)||!(action==='start'||r.game_type==='roulette'&&action==='action'&&payload.action==='bet'))return;
  if(current?.operation===payload.operation_id)return;
  cancel();retired=null;if(instant())return;
  current=fresh(r,payload.operation_id);window.ClubArt.prepare(r.game_type);
  const s=current;s.waitTimer=setTimeout(()=>{if(current!==s||s.result)return;s.paused=true;stopTracks(s);emit();},8000);
  // Dispatch the request before the heavier visual DOM update.
  queueMicrotask(()=>{if(current===s)emit();});
 }
 function prepare(previous,next,animate=true){
  if(!names.has(next.game_type)||next.status==='closed'||document.visibilityState!=='visible'||instant()){cancel();return;}
  const h=next.hand,s=current;
  if(retired?.room===next.id&&next.accepted_operations?.includes(retired.operation)){if(h?.phase==='showdown')seen=next.id+':'+h.id;retired=null;cancel();return;}
  if(s&&s.room!==next.id)cancel();
  if(panel&&(panel.room!==next.id||(!current||current.result)&&panel.hand!==h?.id))removePanel();
  // A verification snapshot may acknowledge the click before push or POST.
  const owned=!!current?.operation&&next.accepted_operations?.includes(current.operation);
  if(current?.result&&h?.id===current.hand)return;
  if(current?.result&&h?.id!==current.hand)cancel();
  if(owned&&h?.phase!=='showdown'){cancel();return;}
  const isNew=h?.phase==='showdown'&&previous?.id===next.id&&(h.id!==previous.hand?.id||previous.hand?.phase!=='showdown');
  const age=Number.isFinite(h?.finished_at)?next.server_time-h.finished_at:0;
  if(!isNew||!(animate||owned)||(!owned&&age>10)||seen===next.id+':'+h.id)return;
  if(!current||current.room!==next.id){cancel();current=fresh(next);}
  const run=current;seen=next.id+':'+h.id;clearTimeout(run.waitTimer);run.hand=h.id;run.result={number:h.number,reels:h.reels,summary:h.summary};run.phase='spinning';run.paused=false;
  run.stopAt=Math.max(performance.now(),run.started+(run.kind==='slot'?1700:1500));run.finishAt=run.stopAt+(run.kind==='slot'?1600:3000);
  run.stopTimer=setTimeout(()=>{if(current===run){run.phase='stopping';play();}},Math.max(0,run.stopAt-performance.now()));
  run.finishTimer=setTimeout(()=>{if(current===run)finish();},Math.max(0,run.finishAt-performance.now())+60);
 }
 function fail(operation){if(current?.operation===operation)cancel(true);}
 function caption(r){if(!masked(r))return '';return current.paused?'仍在確認本局結果…':current.phase==='waiting'?'正在送出，轉動中…':current.phase==='stopping'?'慢慢停下，準備揭曉…':'轉動中，準備揭曉…';}
 function options(r){if(!names.has(r.game_type))return '';const reveal=active(r)&&!!current.result;return `<div class="round-presentation-options"><label><input type="checkbox" data-fast-reveal ${fast?'checked':''}>快速演出</label><button class="button ghost" type="button" data-skip-reveal ${reveal?'':'disabled'}>略過動畫</button></div>`;}
 function animate(el,frames,options){try{const a=el.animate(frames,options);a.finished.catch(()=>{});return a;}catch{return null;}}
 function angle(el){try{const m=new DOMMatrixReadOnly(getComputedStyle(el).transform);return Math.atan2(m.b,m.a)*180/Math.PI;}catch{return 0;}}
 function wheelFor(s){
  if(panel)return panel.node.querySelector('.roulette-wheel');
  const w=document.querySelector('.arcade-roulette .roulette-wheel');if(!w)return null;
  const b=w.getBoundingClientRect();if(b.top>=56&&b.bottom<=innerHeight-8&&b.width)return w;
  const node=document.createElement('aside'),copy=w.cloneNode(true),p=document.createElement('p'),button=document.createElement('button');node.className='roulette-result-popover';node.setAttribute('role','region');node.setAttribute('aria-label','輪盤開獎演出');button.type='button';button.className='button ghost';button.textContent=s.result?'略過動畫':'確認中…';button.disabled=!s.result;button.onclick=finish;node.append(copy,p,button);document.body.append(node);panel={node,room:s.room,hand:s.hand};return copy;
 }
 function slotTrack(s,el,index){
  let record=s.tracks.get(el),height=el.parentElement.clientHeight;
  if(!record){record={phase:'waiting',animation:animate(el,[{transform:'translateY(0)'},{transform:`translateY(${-6*height}px)`}],{duration:420+index*40,iterations:Infinity,easing:'linear'})};s.tracks.set(el,record);}
  if(s.phase!=='stopping'||record.phase==='stopping')return;
  let from=0;try{from=new DOMMatrixReadOnly(getComputedStyle(el).transform).m42;}catch{}
  record.animation?.cancel();record.phase='stopping';record.animation=animate(el,[{transform:`translateY(${from}px)`},{transform:`translateY(${-(6+s.result.reels[index])*height}px)`}],{duration:Math.max(80,s.finishAt-performance.now()-(2-index)*250),easing:'cubic-bezier(.12,.45,.22,1)',fill:'forwards'});
 }
 function wheelTrack(s,el,kind,width){
  let record=s.tracks.get(el);
  if(!record){const frames=kind==='ball'?[{transform:`translateY(${-width*.09}px)`},{transform:`translateY(${-width*.09}px)`}]:[{transform:'rotate(0deg)'},{transform:`rotate(${kind==='rotor'?360:-720}deg)`}];record={phase:'waiting',animation:animate(el,frames,{duration:kind==='rotor'?1800:1500,iterations:Infinity,easing:'linear'})};s.tracks.set(el,record);}
  if(s.phase!=='stopping'||record.phase==='stopping')return;
  const from=angle(el);record.animation?.cancel();record.phase='stopping';const duration=Math.max(80,s.finishAt-performance.now());
  const target=-window.ClubArcadeMotion.order.indexOf(s.result.number)*360/37;
  const end=kind==='rotor'?from+1440+((target-from)%360+360)%360:from-1800-((from%360+360)%360);
  const frames=kind==='ball'?[{transform:`translateY(${-width*.09}px)`,offset:0},{transform:`translateY(${-width*.09}px)`,offset:.6},{transform:'translateY(3px)',offset:.84},{transform:'translateY(-2px)',offset:.92},{transform:'translateY(0)',offset:1}]:[{transform:`rotate(${from}deg)`},{transform:`rotate(${end}deg)`}];
  record.animation=animate(el,frames,{duration,easing:kind==='ball'?'ease-out':'cubic-bezier(.12,.38,.2,1)',fill:'forwards'});
 }
 function play(){
  document.querySelectorAll('[data-fast-reveal]').forEach(el=>el.onchange=()=>{fast=el.checked;try{localStorage.setItem('club.fastReveal',fast?'1':'0');}catch{}if(fast){if(current?.result)finish();else cancel(true);}else emit();});
  document.querySelectorAll('[data-skip-reveal]').forEach(el=>el.onclick=finish);
  const s=current;if(!s||s.paused)return;
  for(const [el,record] of s.tracks)if(!el.isConnected){record.animation?.cancel();s.tracks.delete(el);}
  if(s.kind==='slot')document.querySelectorAll('.arcade-slot .slot-track').forEach((el,i)=>slotTrack(s,el,i));
  else{const w=wheelFor(s);if(!w)return;w.classList.add('is-spinning');w.querySelector('.wheel-hub').textContent='♠';if(panel){panel.hand=s.hand;panel.node.querySelector('p').textContent=caption({id:s.room});const b=panel.node.querySelector('button');b.disabled=!s.result;b.textContent=s.result?'略過動畫':'確認中…';}const width=w.clientWidth;wheelTrack(s,w.querySelector('.roulette-rotor'),'rotor',width);wheelTrack(s,w.querySelector('.roulette-ball-orbit'),'orbit',width);wheelTrack(s,w.querySelector('.roulette-ball'),'ball',width);}
 }
 document.addEventListener('visibilitychange',()=>{if(document.hidden){redrawOnReturn=!!current;if(current?.operation)retired={room:current.room,operation:current.operation};cancel();}else if(redrawOnReturn){redrawOnReturn=false;emit();}});window.addEventListener('pagehide',()=>cancel());
 reduced.addEventListener?.('change',()=>cancel(true));
 return {begin,prepare,play,cancel,fail,masked,stage,caption,options,skip:finish,running:()=>!!current};
})();
