'use strict';
window.ClubBlocade=(()=>{
 let host,ctx,state,pending=null,busy=false,reading=false,epoch=0,timer,controller,selected=null,mode='move',viewed=null,stamp='',offset=0,lastRead=0,error='';
 const n=v=>Number(v||0).toLocaleString('zh-TW'),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const q=s=>host?.querySelector(s),key=uid=>'nantuan-blocade:'+uid,coord=pos=>String.fromCharCode(65+pos[1])+(pos[0]+1);
 const goals=['上方','右方','下方','左方'];
 function unmount(){epoch++;clearInterval(timer);controller?.abort();host=null;ctx=null;state=null;pending=null;busy=false;reading=false;stamp='';viewed=null;selected=null;error='';}
 function view(){return '<section id="blocade-console" class="blocade" aria-label="步步為營"></section>';}
 function mine(){return state?.room?.game?.players.find(p=>p.uid===ctx.user.id);}
 function myTurn(){const r=state?.room;return r?.status==='playing'&&r.game.players[r.game.turn].uid===ctx.user.id&&!mine()?.out;}
 function usable(){return myTurn()&&!state.room.paused&&!pending&&!busy&&Date.now()-lastRead<8000&&Date.now()/1000+offset<state.room.deadline;}
 function status(message){error=message;const e=q('[data-bc-message]');if(e)e.textContent=message;}
 function pawn(p,index){return `<span class="bc-pawn bc-color-${index}" aria-hidden="true">${index+1}</span>`;}
 function drawWall(w,preview=false){const [a,r,c]=w;return `<span class="bc-wall bc-r${r} bc-c${c} ${a==='h'?'bc-horizontal':'bc-vertical'} ${preview?'bc-preview':''}" aria-hidden="true"></span>`;}
 function board(){
  const room=state.room,game=room.game,players=game?.players||room.players.map((p,i)=>({...p,pos:(room.capacity===2?[[8,4],[0,4]]:[[8,4],[4,0],[0,4],[4,8]])[i]}));
  const legal=room.legal_moves||[],moveMode=mode==='move',can=usable();
  return `<div class="bc-board-scroll"><div class="bc-board" role="group" aria-label="9 乘 9 棋盤，欄 A 到 I，列 1 到 9">
   ${Array.from({length:81},(_,i)=>{const r=Math.floor(i/9),c=i%9,p=players.find(p=>!p.out&&p.pos[0]===r&&p.pos[1]===c),pi=players.indexOf(p),valid=legal.some(pos=>pos[0]===r&&pos[1]===c),chosen=selected?.kind==='move'&&selected.pos[0]===r&&selected.pos[1]===c;
    return `<button type="button" class="bc-cell bc-r${r} bc-c${c} ${r===0?'bc-goal-top':''} ${r===8?'bc-goal-bottom':''} ${room.capacity===4&&c===0?'bc-goal-left':''} ${room.capacity===4&&c===8?'bc-goal-right':''} ${valid&&moveMode&&can?'bc-legal':''} ${chosen?'bc-chosen':''}" data-bc-cell="${r},${c}" aria-label="${coord([r,c])}${p?'，'+esc(p.name):''}" ${!can||!moveMode||!valid?'disabled':''}>${p?pawn(p,pi):valid&&moveMode&&can?'<span class="bc-dot"></span>':''}${r===8?`<small>${String.fromCharCode(65+c)}</small>`:c===0?`<small>${r+1}</small>`:''}</button>`;
   }).join('')}${(game?.walls||[]).map(w=>drawWall(w)).join('')}
   ${!moveMode&&can?Array.from({length:64},(_,i)=>{const r=Math.floor(i/8),c=i%8;return `<button type="button" class="bc-anchor bc-r${r} bc-c${c}" data-bc-anchor="${r},${c}" aria-label="預覽${mode==='h'?'橫':'直'}牆 ${coord([r,c])}"><span></span></button>`;}).join(''):''}
   ${selected?.kind==='wall'?drawWall(selected.wall,true):''}
  </div></div>`;
 }
 function rules(){return `<details class="bc-rules"><summary>玩法、點數與斷線規則</summary><p>每回合走一步或放一道牆，先到對面任一格獲勝。雙人各 10 道牆，四人各 5 道牆；牆不能交叉、重疊或完全堵死任何人的路。遇到相鄰棋子可跳過，後方被阻擋時可側跳；所有落點暫被棋子佔住時可跳過回合。</p><p>加入即保留同額入場籌碼。冠軍拿整桌獎池，不抽水、自動入帳。機器人由系統出同額籌碼，贏得的獎池由系統收回；機器人不讀取你的預覽操作，稱號不改變棋局與獎金。</p><p>開局前退桌全退；開局後退出即認輸，棋子移除、已放的牆保留。每回合 45 秒，逾時先代走最短路，連續 3 次逾時視為認輸。重新整理可接回同一局；伺服器部署時暫停計時。等候 15 分鐘取消退費；對局達 30 分鐘或 400 回合則和局全退。僅限站內虛擬點數，無現金兌換。</p></details>`;}
 function lobby(){return `<div class="bc-lobby"><section class="bc-create"><h2>開一桌，等朋友。</h2><p>走出自己的路，也給朋友一點阻礙。</p><form data-bc-create><fieldset><legend>這桌幾個人？</legend><label><input type="radio" name="capacity" value="2" checked>雙人對決</label><label><input type="radio" name="capacity" value="4">四人混戰</label></fieldset><label class="bc-field">每人入場點數<input name="stake" type="number" min="0" max="10000" step="1" value="100" inputmode="numeric" required aria-describedby="bc-stake-help"></label><div class="bc-presets">${[0,100,500,1000,5000].map(v=>`<button type="button" data-bc-stake="${v}">${v?n(v):'免費'}</button>`).join('')}</div><p id="bc-stake-help">可用 ${n(ctx.wallet.balance)} 點。0–10,000 點，所有人同額加入。</p><label class="bc-bots"><input name="bots" type="checkbox" checked><span>允許機器人補位<small>桌主按開始時補滿空位，系統出同額籌碼。</small></span></label><button class="bc-primary" type="submit" ${busy||pending||state.current_id?'disabled':''}>確認開桌並保留入場點數</button></form></section><section class="bc-tables"><h2>朋友的棋桌</h2><div data-bc-tables>${tables()}</div></section></div>`;}
 function tables(){return state.tables.length?state.tables.map(t=>`<article class="bc-table-row"><div><strong>#${t.id} · ${t.capacity} 人桌</strong><p>${t.players.length}/${t.capacity} 人 · 每人 ${n(t.stake)} 點</p><small>${esc(t.players.map(p=>p.name).join('、'))} · ${t.bots?'可由機器人補位':'只限真人'}</small></div><button type="button" data-bc-open="${t.id}">${t.status==='waiting'?'查看棋桌':'觀戰'}</button></article>`).join(''):'<div class="bc-empty"><svg viewBox="0 0 120 100" aria-hidden="true"><path d="M20 18h80v64H20zM20 50h80M60 18v64" fill="none" stroke="currentColor" stroke-width="4"/><circle cx="40" cy="34" r="9" fill="currentColor"/><path d="M78 57v19" stroke="currentColor" stroke-width="7"/></svg><p>還沒有棋桌</p><small>開桌後朋友就能加入，一個人也能和機器人玩。</small></div>';}
 function roomView(){
  const r=state.room,g=r.game,member=r.players.some(p=>p.uid===ctx.user.id),owner=r.owner===ctx.user.id,ended=['finished','cancelled'].includes(r.status);
  const players=g?.players||r.players;
  return `<div class="bc-room-heading"><div><h2>#${r.id} · ${r.capacity===2?'雙人對決':'四人混戰'}</h2><p>每人 ${n(r.stake)} 點 · ${r.bots?'允許機器人補位':'只限真人'}</p></div><div class="bc-pot"><span>${r.status==='waiting'?'滿桌獎池':'本局獎池'}</span><strong>${n(r.target_pot)} <small>點</small></strong></div></div>
   <div class="bc-match"><section class="bc-play"><div class="bc-turnline"><strong data-bc-turn></strong><span data-bc-clock></span></div><div class="bc-board-caption">${mine()?`你的 ${g.players.indexOf(mine())+1} 號棋子，目標是${goals[mine().side]}`:'先走到自己對面的一邊獲勝'}<button type="button" data-bc-zoom aria-pressed="false">放大棋盤</button></div><div data-bc-board>${board()}</div><div data-bc-controls>${controls()}</div></section><aside class="bc-sidebar"><div class="bc-player-list">${Array.from({length:r.capacity},(_,i)=>{const p=players[i];return p?`<div class="bc-player ${g?.turn===i&&r.status==='playing'?'bc-playing':''} ${p.out?'bc-out':''}">${pawn(p,i)}<div><strong>${esc(p.name)}${p.uid===ctx.user.id?'（你）':''}</strong><small>${p.bot?'機器人 · 系統出資':r.owner===p.uid?'桌主':'真人玩家'}${p.out?' · 已認輸':''}</small></div><b>${g?p.walls:r.capacity===2?10:5}<small>道牆</small></b></div>`:`<div class="bc-player bc-seat-empty"><span class="bc-empty-seat">${i+1}</span><span>等朋友入座${r.bots?'<small>開始時由機器人補位</small>':''}</span></div>`;}).join('')}</div>
   ${ended?`<div class="bc-result" role="status"><h3>${r.status==='cancelled'?'本局已取消／和局':esc(r.winner.name)+' 獲勝'}</h3><p>${r.status==='cancelled'?esc(r.reason):`${r.winner.bot?'機器人贏得獎池，系統收回':'獎池已自動入帳'} ${n(r.pot)} 點。`}</p><button type="button" data-bc-back>回棋桌大廳</button></div>`:r.status==='waiting'?`<div class="bc-waiting"><h3>${r.players.length} / ${r.capacity} 人已入座</h3><p>${r.bots?'等朋友加入，或由桌主按開始，機器人補滿剩餘空位。':'等真人到齊後，由桌主開始。'}</p>${owner?`<button type="button" class="bc-primary" data-bc-start ${!r.bots&&r.players.length<r.capacity?'disabled':''}>${r.players.length<r.capacity?'補上機器人並開始':'開始對局'}</button>`:!member?`<button type="button" class="bc-primary" data-bc-join ${state.current_id||r.players.length>=r.capacity?'disabled':''}>加入並保留 ${n(r.stake)} 點</button>`:'<p>等桌主開始即可。</p>'}</div>`:''}
   <div class="bc-room-actions"><button type="button" data-bc-share>複製邀請連結</button>${member&&!ended&&!mine()?.out?`<button type="button" data-bc-leave>${r.status==='waiting'?'退桌並全額退還':'認輸離桌'}</button>`:''}${!ended?'<button type="button" data-bc-back>查看其他棋桌</button>':''}</div><p class="bc-small">重新整理可接回對局。開局後入場點數不退還，離開頁面仍會計時。</p></aside></div>`;
 }
 function controls(){
  if(!myTurn())return '';
  if(!state.room.legal_moves.length)return '<p>落點暫時被棋子佔住，可跳過這回合。</p><button type="button" class="bc-primary" data-bc-pass>跳過本回合</button>';
  return `<div class="bc-modes" role="group" aria-label="回合動作">${[['move','走棋'],['h','橫牆'],['v','直牆']].map(([v,t])=>`<button type="button" data-bc-mode="${v}" aria-pressed="${mode===v}" ${v!=='move'&&!mine().walls?'disabled':''}>${t}</button>`).join('')}</div><p class="bc-help">${mode==='move'?'點亮起的格子預覽，再確認走棋。':'點棋盤交界預覽牆壁，再確認放置。'}</p>${mode==='move'?`<div class="bc-move-options" aria-label="可走的位置">${state.room.legal_moves.map(pos=>`<button type="button" data-bc-move="${pos}" aria-pressed="${selected?.kind==='move'&&String(selected.pos)===String(pos)}">走到 ${coord(pos)}</button>`).join('')}</div>`:`<div class="bc-wall-inputs"><label>起點欄<select data-bc-col>${Array.from({length:8},(_,i)=>`<option value="${i}" ${selected?.wall?.[2]===i?'selected':''}>${String.fromCharCode(65+i)}</option>`).join('')}</select></label><label>起點列<select data-bc-row>${Array.from({length:8},(_,i)=>`<option value="${i}" ${selected?.wall?.[1]===i?'selected':''}>${i+1}</option>`).join('')}</select></label><button type="button" data-bc-preview>預覽牆壁</button></div>`}<button type="button" class="bc-primary bc-confirm" data-bc-confirm ${!selected||!usable()?'disabled':''}>${selected?selected.kind==='move'?`確認走到 ${coord(selected.pos)}`:`確認放${mode==='h'?'橫':'直'}牆 ${coord(selected.wall.slice(1))}`:'先選擇位置'}</button>`;
 }
 function history(){return `<details class="bc-history"><summary>我的最近 20 桌紀錄</summary>${state.history.map(r=>`<button type="button" data-bc-open="${r.id}"><span>#${r.id} · 入場 ${n(r.stake)} 點</span><strong>${r.payout===null?'進行中':`已入帳 ${n(r.payout)} 點`}</strong></button>`).join('')||'<p>完成第一局後，這裡會留下結果。</p>'}</details>`;}
 function paint(force=false){
  if(!host||!state)return;
  const r=state.room,sig=JSON.stringify([r?.id,r?.revision,r?null:state.tables,state.current_id,state.history,!!pending]);
  if(force||stamp!==sig){
   const old=host.querySelector('form'),form=old?Object.fromEntries(new FormData(old)):null;
   const focused=document.activeElement,focusKey=focused?.dataset?.bcCell||focused?.dataset?.bcAnchor;
   const zoom=q('.bc-board-scroll')?.classList.contains('bc-zoomed');
   stamp=sig;
   host.innerHTML=`<header class="bc-heading"><div><h1>步步為營</h1><p>走一步，或讓朋友多走幾步。</p></div><a href="#lobby">回遊戲大廳</a></header><div class="bc-feedback"><p data-bc-message role="status">${esc(error)}</p><button type="button" data-bc-retry ${!pending?'hidden':''}>確認原操作結果</button></div>${!r&&state.current_id?'<button type="button" class="bc-return" data-bc-current>返回正在進行的棋桌</button>':''}${r?roomView():lobby()}${history()}${rules()}`;
   if(form){const f=q('form');if(f){f.elements.stake.value=form.stake;f.elements.capacity.value=form.capacity;f.elements.bots.checked=!!form.bots;}}
   if(zoom)q('.bc-board-scroll')?.classList.add('bc-zoomed');
   if(form&&focused?.name){const field=q('form')?.elements[focused.name];(field?.focus?field:field?.value&&q('form')?.querySelector(`[name="${focused.name}"][value="${field.value}"]`))?.focus?.({preventScroll:true});}
   if(focusKey)host.querySelector(`[data-bc-cell="${focusKey}"],[data-bc-anchor="${focusKey}"]`)?.focus({preventScroll:true});
   bind();
  }
  tick();
 }
 function tick(){
  if(!host)return;
  const r=state?.room,turn=q('[data-bc-turn]'),clock=q('[data-bc-clock]');
  if(turn&&r){turn.textContent=r.paused?'更新中，棋局暫停計時':r.status==='waiting'?'等待開局':r.status==='playing'?myTurn()?'輪到你了':`輪到 ${r.game.players[r.game.turn].name}`:'本局已結束';
   const left=Math.max(0,Math.ceil(r.deadline-(Date.now()/1000+offset)));
   clock.textContent=r.paused?'更新後自動繼續':r.status==='playing'?`${left} 秒`:'冠軍全拿 · 不抽水';}
  const stale=state&&Date.now()-lastRead>=8000;
  if(stale&&!error)status('連線更新中，確認最新棋盤後才能操作。');
  host.querySelectorAll('[data-bc-pass],[data-bc-confirm],[data-bc-cell],[data-bc-anchor],[data-bc-move],[data-bc-mode],[data-bc-preview]').forEach(b=>{
   if(b.matches('[data-bc-confirm]'))b.disabled=!selected||!usable();
   else if(!usable())b.disabled=true;
  });
  host.querySelectorAll('[data-bc-start],[data-bc-join],[data-bc-leave],form button[type="submit"]').forEach(b=>{
   if(pending||busy||stale)b.disabled=true;
  });
  const retry=q('[data-bc-retry]');if(retry)retry.disabled=busy;
 }
 function selection(action){selected=action;paint(true);}
 async function openRoom(id){controller?.abort();epoch++;reading=false;viewed=id;selected=null;stamp='';await read();}
 function bind(){
  const form=q('form');if(form)form.onsubmit=async e=>{e.preventDefault();const data=new FormData(form),stake=Number(data.get('stake'));if(!Number.isInteger(stake)||stake<0||stake>state.max_stake){status('請填 0–10,000 點整數。');return;}await send('create',{capacity:Number(data.get('capacity')),stake,bots:!!data.get('bots')});};
  host.querySelectorAll('[data-bc-stake]').forEach(b=>b.onclick=()=>{form.elements.stake.value=b.dataset.bcStake;});
  host.querySelectorAll('[data-bc-open]').forEach(b=>b.onclick=()=>void openRoom(Number(b.dataset.bcOpen)));
  host.querySelectorAll('[data-bc-back]').forEach(b=>b.onclick=()=>{controller?.abort();epoch++;reading=false;viewed=0;state.room=null;selected=null;stamp='';paint();void read();});
  if(q('[data-bc-current]'))q('[data-bc-current]').onclick=()=>void openRoom(state.current_id);
  if(q('[data-bc-start]'))q('[data-bc-start]').onclick=()=>void send('start',{room_id:state.room.id});
  if(q('[data-bc-join]'))q('[data-bc-join]').onclick=()=>void send('join',{room_id:state.room.id});
  if(q('[data-bc-leave]'))q('[data-bc-leave]').onclick=async()=>{const r=state.room,token=epoch;if(!await ctx.confirm(r.status==='playing'?'認輸離桌':'退桌退款',r.status==='playing'?'確定認輸？入場點數不退還。':'退桌並全額退還入場點數？')||token!==epoch||state?.room?.id!==r.id)return;await send('leave',{room_id:r.id});};
  if(q('[data-bc-share]'))q('[data-bc-share]').onclick=async()=>{const link=location.origin+location.pathname+'#blocade?room='+state.room.id;try{await navigator.clipboard.writeText(link);status('邀請連結已複製，傳給朋友就能加入。');}catch{status('邀請連結：'+link);}};
  if(q('[data-bc-zoom]'))q('[data-bc-zoom]').onclick=e=>{const on=q('.bc-board-scroll').classList.toggle('bc-zoomed');e.currentTarget.setAttribute('aria-pressed',String(on));e.currentTarget.textContent=on?'縮回棋盤':'放大棋盤';};
  host.querySelectorAll('[data-bc-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.bcMode;selected=null;paint(true);});
  host.querySelectorAll('[data-bc-cell],[data-bc-move]').forEach(b=>b.onclick=()=>{if(usable())selection({kind:'move',pos:(b.dataset.bcCell||b.dataset.bcMove).split(',').map(Number)});});
  host.querySelectorAll('[data-bc-anchor]').forEach(b=>b.onclick=()=>selection({kind:'wall',wall:[mode,...b.dataset.bcAnchor.split(',').map(Number)]}));
  if(q('[data-bc-preview]'))q('[data-bc-preview]').onclick=()=>selection({kind:'wall',wall:[mode,Number(q('[data-bc-row]').value),Number(q('[data-bc-col]').value)]});
  if(q('[data-bc-pass]'))q('[data-bc-pass]').onclick=()=>{if(usable())void send('act',{room_id:state.room.id,ply:state.room.game.ply,action:{kind:'wait'}});};
  if(q('[data-bc-confirm]'))q('[data-bc-confirm]').onclick=()=>{if(usable()&&selected)void send('act',{room_id:state.room.id,ply:state.room.game.ply,action:selected});};
  q('[data-bc-retry]').onclick=()=>void send();
 }
 async function read(){
  if(!host||reading||busy)return;reading=true;const token=epoch,context=ctx;controller=new AbortController();
  try{const result=await context.api('/api/blocade'+(viewed?'?room='+viewed:''),undefined,{controller});if(token!==epoch)return;
   const wasStale=Date.now()-lastRead>=8000;const old=state?.room;state=result.blocade;if(viewed===0)state.room=null;
   if(old?.id!==state.room?.id||old?.game?.ply!==state.room?.game?.ply)selected=null;
   context.wallet=result.wallet;offset=state.server_time-Date.now()/1000;lastRead=Date.now();
   if(error.startsWith('連線')){error='';stamp='';}
   context.updated?.(result,context.user.id);paint(wasStale);
  }catch(e){if(token===epoch){status(e.retryable?'連線暫停，正在重連。原對局與點數會保留。':e.message);tick();}}
  finally{if(token===epoch)reading=false;}
 }
 async function send(verb,data){
  if(busy||!ctx)return;const context=ctx,owner=context.user.id;
  if(!pending){if(!verb)return;pending={verb,data:{...data,operation_id:crypto.randomUUID()}};try{sessionStorage.setItem(key(owner),JSON.stringify(pending));}catch{pending=null;status('無法保存操作回執，請允許網站儲存資料後再試。');return;}}
  controller?.abort();const token=++epoch;reading=false;busy=true;paint(true);status('正在確認操作…');
  try{const result=await context.api('/api/blocade/'+pending.verb,pending.data);sessionStorage.removeItem(key(owner));if(token!==epoch)return;
   pending=null;state=result.blocade;viewed=result.room_id;context.wallet=result.wallet;offset=state.server_time-Date.now()/1000;lastRead=Date.now();selected=null;
   error=result.replayed?'原操作已確認，不會重複扣點。':'操作已確認。';context.updated?.(result,owner);
  }catch(e){if(token!==epoch)return;if(!e.retryable){sessionStorage.removeItem(key(owner));pending=null;}error=e.retryable?'結果尚未確認，請確認原操作結果，不會重複扣點。':e.message;}
  finally{if(token===epoch){busy=false;paint(true);if(!pending)void read();}}
 }
 function mount(context){
  const element=document.querySelector('#blocade-console');if(!element)return;
  if(host===element&&ctx?.user.id===context.user.id){ctx=context;return;}
  unmount();host=element;ctx=context;
  const match=location.hash.match(/^#blocade\?room=(\d+)$/);viewed=match?Number(match[1]):null;
  try{pending=JSON.parse(sessionStorage.getItem(key(ctx.user.id))||'null');}catch{pending=null;}
  if(pending)error='有一筆操作尚待確認，請核對原操作結果。';
  host.innerHTML='<p data-bc-message role="status">正在載入棋桌…</p><button type="button" data-bc-load>重試載入</button><button type="button" data-bc-home>回棋桌大廳</button>';q('[data-bc-load]').onclick=()=>void read();q('[data-bc-home]').onclick=()=>void openRoom(0);void read();
  let ticks=0;timer=setInterval(()=>{tick();if(!document.hidden&&++ticks%(state?.room?.status==='playing'?2:5)===0)void read();},1000);
 }
 return {view,mount,unmount};
})();
