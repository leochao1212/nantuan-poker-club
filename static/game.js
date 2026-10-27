'use strict';
const $=(s,e=document)=>e.querySelector(s), $$=(s,e=document)=>[...e.querySelectorAll(s)];
const app=$('#app'),modal=$('#modal');
let memberQuery='',memberId=null,credentialsChanging=false;
let roomFilter='all',roomsExpanded=false,rankMode='assets',ranksExpanded=false,profileTab='settings';
let recoveredUntil=0;
let reminderPaused=false;
document.addEventListener('change',event=>{if(event.target.id==='play-reminder-pause')reminderPaused=event.target.checked;});
function playReminder(){const text='小玩怡情莫貪心，適時收手最安心；輸贏看淡不追金，休息一下好心情。';return `<aside class="play-reminder" aria-label="理性遊戲提醒"><strong>適度娛樂</strong><div class="reminder-window"><p class="reminder-readable">${text}</p><div class="reminder-track" aria-hidden="true"><span>${text}<i>◆</i></span><span>${text}<i>◆</i></span></div></div><label class="reminder-pause" title="暫停跑馬燈"><input id="play-reminder-pause" type="checkbox" ${reminderPaused?'checked':''}><span class="reminder-readable">暫停跑馬燈</span><svg class="reminder-pause-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12M16 6v12"/></svg><svg class="reminder-play-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 9 6-9 6Z"/></svg></label></aside>`;}
let lobby=null,room=null,memberCount=0,requiresInvite=false,authMode='login',view='lobby',roomId=null;
let live=null,liveRoomId=null,streamClientId=null,liveReady=false,lastPush=0,pendingOperation=null,actionFeedback=null;
let presencePending=false,hourlyPending=false,hourlyClaimId=null;
let clockSampleAt=0,clockSampleRtt=Infinity,lastFallback=0,liveInterrupted=false;
let snapshotRead=null,presenceRead=null,connectionMode='syncing',recoveryAttempt=null,liveEpoch=0,heartbeatProbe=false,lastResumeAt=0;
let streamRetryTimer=null,streamRetryCount=0;
const telemetryAt=new Map();
function observeServerClock(result,sent,received){const server=result?.state?.server_time??result?.server_time;if(!Number.isFinite(server))return;const rtt=received-sent;if(!clockSampleAt||received-clockSampleAt>60000||rtt<=clockSampleRtt){clockOffset=server-(sent+received)/2000;clockSampleRtt=rtt;clockSampleAt=received;}}
function connectionReport(kind,details={}){
  const now=Date.now(),fields={...(recoveryAttempt?{attempt_id:recoveryAttempt.id,reason:recoveryAttempt.reason,duration_ms:Math.max(0,now-recoveryAttempt.startedAt)}:{}),visibility:document.visibilityState,online:navigator.onLine,...details};
  window.ClubFeatures?.event(kind,fields);
  if(!lobby||!streamClientId)return;
  const key=kind+':'+(fields.attempt_id||''),previous=telemetryAt.get(key);
  if(previous!==undefined&&now-previous<1000)return;
  telemetryAt.set(key,now);if(telemetryAt.size>64)telemetryAt.delete(telemetryAt.keys().next().value);
  // Diagnostics are best effort: never occupy the browser's connection pool
  // while a player's action or recovery snapshot is waiting for the network.
  if(telemetryTransport.queue.length>=6)telemetryTransport.queue.shift();
  telemetryTransport.queue.push({at:now,uid:me()?.id,body:JSON.stringify({kind,client:streamClientId,room_id:roomId,revision:room?.revision,last_event_age_ms:lastPush?Math.max(0,now-lastPush):0,...fields})});
  sendConnectionReport();
}
const telemetryTransport={active:null,queue:[]};
function sendConnectionReport(){
  if(telemetryTransport.active)return;
  let entry;
  while(telemetryTransport.queue.length){
    entry=telemetryTransport.queue.shift();
    if(lobby&&entry.uid===me()?.id&&Date.now()-entry.at<=5000)break;
    entry=null;
  }
  if(!entry)return;
  const controller=new AbortController();telemetryTransport.active=controller;
  const timer=setTimeout(()=>controller.abort(),1500);
  void fetch('/api/online/client-event',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'PokerClub'},body:entry.body,signal:controller.signal}).catch(()=>{}).finally(()=>{
    clearTimeout(timer);
    if(telemetryTransport.active===controller){telemetryTransport.active=null;sendConnectionReport();}
  });
}
function retireSnapshotRead(){const read=snapshotRead;snapshotRead=null;polling=false;resync=false;if(read){read.retired=true;read.controller.abort();}}
function retirePresenceRead(){const read=presenceRead;presenceRead=null;presencePending=false;if(read){read.retired=true;read.controller.abort();}}
function recoverSnapshot(fresh=false){
  if(!lobby||credentialsChanging||document.visibilityState!=='visible'||navigator.onLine===false)return;
  if(fresh){retireSnapshotRead();lastFallback=0;}
  if(Date.now()-lastFallback<2500)return;lastFallback=Date.now();void sync(true);
}
function beginRecovery(reason){
  const context=generation+':'+roomId;
  if(!recoveryAttempt||recoveryAttempt.context!==context){
    if(recoveryAttempt)connectionReport('recovery_cancelled',{reason:'channel'});
    recoveryAttempt={id:operationId(),reason,context,startedAt:Date.now(),synced:false};
    streamClientId??=operationId();connectionReport('recovery_started');
  }
  liveReady=false;setConnection(navigator.onLine===false?'offline':'syncing');
}
function markSynchronized(delivery){
  if(document.visibilityState!=='visible')return;
  const currentPush=liveReady&&Date.now()-lastPush<=4000;
  setConnection(currentPush?'live':'fallback');
  if(recoveryAttempt&&!recoveryAttempt.synced){recoveryAttempt.synced=true;connectionReport('recovery_synced',{delivery});}
  if(recoveryAttempt&&currentPush){connectionReport('stream_recovered',{delivery});recoveryAttempt=null;liveInterrupted=false;}
}
function resumeConnections(reason){
  if(!lobby||credentialsChanging||document.visibilityState!=='visible')return;
  if(live&&liveRoomId===roomId&&Date.now()-lastResumeAt<750){recoverSnapshot();return;}
  lastResumeAt=Date.now();beginRecovery(reason);retirePresenceRead();startLive(true);recoverSnapshot(true);
}
function retryLive(){
  if(streamRetryTimer!==null||!window.EventSource||!lobby||credentialsChanging||document.visibilityState!=='visible'||navigator.onLine===false)return;
  const uid=me().id,target=roomId,delay=Math.min(4000,500*2**Math.min(streamRetryCount++,3));
  streamRetryTimer=setTimeout(()=>{
    streamRetryTimer=null;
    if(me()?.id===uid&&roomId===target&&document.visibilityState==='visible')startLive(true);
  },delay);
}
function checkConnection(){
  if(!lobby||credentialsChanging||document.visibilityState!=='visible'||navigator.onLine===false)return;
  const age=Date.now()-lastPush;
  // A slow first response needs more time than two missed 3-second pings.
  // Keep independently reading snapshots while the current stream can recover.
  const stale=live&&(live.clubHasState?age>12000:Date.now()-(live.clubStartedAt??lastPush)>20000);
  if(live&&(live.readyState===2||stale)){
    liveInterrupted=true;beginRecovery('stream_stale');connectionReport('stream_stale');
    live.close();live=null;liveRoomId=null;retryLive();recoverSnapshot();
  }else if(live&&age>4000){
    if(!heartbeatProbe){heartbeatProbe=true;connectionReport('heartbeat_probe',{reason:'heartbeat_probe'});}
    recoverSnapshot();
  }else if(!liveReady){if(!live)retryLive();recoverSnapshot();}
}
function pauseConnections(reason){
  if(!lobby)return;
  if(recoveryAttempt)connectionReport('recovery_cancelled',{reason});
  recoveryAttempt=null;liveInterrupted=true;
  connectionReport(reason==='offline'?'network_offline':'page_hidden',{reason});stopLive();
  setConnection(reason==='offline'?'offline':'paused');
}
let busy=false,polling=false,resync=false,connected=true,signature='',generation=0,clockOffset=0,toastTimer,lastTurn=null;
const suit={s:'♠',h:'♥',d:'♦',c:'♣'},rank={T:'10',J:'J',Q:'Q',K:'K',A:'A'};
const phaseNames={preflop:'翻牌前',flop:'翻牌',turn:'轉牌',river:'河牌',showdown:'本手結算'};
const symbols={
  clubhouse:'<path d="m3 10 9-7 9 7M5 9v12h14V9M9 21v-7h6v7M9 9h6"/>',
  wallet:'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 8h18m-5 5h5m-5 0v3h5M5 5V3h12"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  headphones:'<path d="M3 14v-3a9 9 0 0 1 18 0v3"/><rect x="2" y="12" width="4" height="8" rx="2"/><rect x="18" y="12" width="4" height="8" rx="2"/>',
  mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/><path class="mic-slash" d="m3 3 18 18"/>',
  chat:'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 0 1-1-5 9 9 0 0 1 18 0Z"/><path d="M8 10h8m-8 4h5"/>',
  spade:'<path d="M12 2C9 7 3 9 3 14a5 5 0 0 0 8 4l-2 4h6l-2-4a5 5 0 0 0 8-4c0-5-6-7-9-12Z"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',back:'<path d="m14 5-7 7 7 7"/>',arrow:'<path d="m9 5 7 7-7 7"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  people:'<circle cx="9" cy="7" r="4"/><path d="M2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2M16 3a4 4 0 0 1 0 8m6 10v-2a4 4 0 0 0-3-3.87"/>',
  trophy:'<path d="M8 3h8v6a4 4 0 0 1-8 0V3Zm0 2H4v3a4 4 0 0 0 4 4m8-7h4v3a4 4 0 0 1-4 4m-4 1v6m-4 2h8"/>',
  history:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logout:'<path d="M9 4H4v16h5m6-12 4 4-4 4m-7-4h11"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',
  gift:'<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v9h14v-9M12 8v13M12 8C5 8 5 2 8 3c3 0 4 5 4 5Zm0 0c7 0 7-6 4-5-3 0-4 5-4 5Z"/>',
  settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
  check:'<path d="m5 12 4 4L19 6"/>',cards:'<rect x="7" y="3" width="13" height="17" rx="2"/><path d="m6 6-3 1 3 15 10-2"/>',
  shield:'<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/><path d="m8 12 3 3 5-6"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/>',
};
function icon(name){return `<svg class="icon ${name==='spade'?'spade-icon':''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbols[name]||symbols.spade}</svg>`;}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function num(n){return Number(n||0).toLocaleString('zh-TW');}
function delta(n){return (n>0?'+':n<0?'−':'')+num(Math.abs(n));}
function tone(n){return n>0?'win':n<0?'loss':'muted';}
function me(){return lobby?.me;}
function seated(){return room?.seats.find(s=>s.user_id===me()?.id);}
function notice(text){clearTimeout(toastTimer);$('#toast').textContent=text;$('#toast').classList.add('visible');toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4200);}
function avatar(u,large=false){return window.ClubIdentity.avatar(u,large);}
function card(c,small=false,key=''){const motion=key?` data-card-key="${key}"`:'';const pending=(key&&window.ClubDealer?.pending(key)?'deal-pending ':'')+(key&&window.ClubArcadeMotion?.pending(key)?'arcade-card-pending ':'');if(!c)return `<span class="playing-card ${pending}covered ${small?'small':''}" aria-label="未公開底牌"${motion}><span>♠</span></span>`;const red=c[1]==='h'||c[1]==='d';const faceState=window.ClubArt.cardState(c);return `<span class="playing-card ${pending}${red?'red':'black'} ${small?'small':''}" aria-label="${esc((rank[c[0]]||c[0])+suit[c[1]])}" data-rank="${esc(c[0])}" data-suit="${esc(c[1])}" data-photo-card="${esc(c)}" data-face-state="${faceState}"${motion}><b>${rank[c[0]]||c[0]}<i aria-hidden="true"></i></b><b class="card-bottom">${rank[c[0]]||c[0]}<i aria-hidden="true"></i></b></span>`;}
function brand(){return `<span class="brand-symbol">${icon('spade')}</span><span><strong>楠團牌室</strong><small>私人牌室</small></span>`;}
function operationId(){return Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');}
async function api(path,data,options={}){
  let responseStatus=0,timedOut=false;const sent=Date.now(),sentPerf=performance.now(),controller=options.controller||new AbortController(),timer=setTimeout(()=>{timedOut=true;controller.abort();},options.timeoutMs??8000);
  try{
    options.trace?.({phase:'send',at:sentPerf});
    const r=await fetch(path,{...(data===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'PokerClub'},body:JSON.stringify(data)}),signal:controller.signal});
    responseStatus=r.status;const headersAt=performance.now(),raw=await r.text(),bodyAt=performance.now(),result=JSON.parse(raw),parsedAt=performance.now();observeServerClock(result,sent,Date.now());
    if(options.trace){const server={};for(const part of (r.headers.get('Server-Timing')||'').split(',')){const m=part.trim().match(/^([a-z_]+);dur=([\d.]+)$/);if(m&&['receive','queue','db_wait','process','commit','snapshot','encode','server'].includes(m[1]))server[m[1]]=Number(m[2]);}options.trace({phase:'response',request_id:r.headers.get('X-Request-ID')||null,headers_ms:headersAt-sentPerf,download_ms:bodyAt-headersAt,parse_ms:parsedAt-bodyAt,server});} 
    if(!r.ok){const e=new Error(result.error||'連線失敗，請重試。');e.status=r.status;e.reason=result.reason;e.requestId=result.request_id;e.retryable=r.status>=500||r.status===408;throw e;}
    return result;
  }catch(e){
    if(e.name==='AbortError'||e instanceof TypeError||e instanceof SyntaxError){const error=new Error('連線較慢，尚未確認操作結果。');error.retryable=true;throw error;}
    throw e;
  }finally{clearTimeout(timer);window.ClubFeatures?.sample(path,Date.now()-sent,responseStatus,controller.signal.aborted&&!timedOut);}
}
function formError(form,message){const box=$('.form-error',form);box.hidden=false;box.textContent=message;box.focus();}
function pending(form,on){form.setAttribute('aria-busy',String(on));$$('button[type="submit"]',form).forEach(b=>{b.disabled=on;if(on){b.dataset.idleLabel=b.innerHTML;b.textContent='處理中…';}else if(b.dataset.idleLabel){b.innerHTML=b.dataset.idleLabel;delete b.dataset.idleLabel;}});}
function dialog(html){modal.innerHTML=html;modal.showModal();const close=$('[data-close]',modal);if(close)close.onclick=()=>modal.close();}
function xButton(){return `<button class="icon-button" type="button" data-close aria-label="關閉">${icon('close')}</button>`;}
function confirmDialog(title,text,label='確認',cancelLabel='取消'){return new Promise(resolve=>{let accepted=false;dialog(`<section class="confirm-dialog"><div class="modal-head"><h2 id="modal-title">${esc(title)}</h2>${xButton()}</div><p>${esc(text)}</p><div class="dialog-actions"><button class="button ghost" id="confirm-no">${esc(cancelLabel)}</button><button class="button primary" id="confirm-yes">${esc(label)}</button></div></section>`);modal.addEventListener('close',()=>resolve(accepted),{once:true});$('#confirm-no').focus({preventScroll:true});$('#confirm-no').onclick=()=>modal.close();$('#confirm-yes').onclick=()=>{accepted=true;modal.close();};});}

function tableHeading(r,user,subtitle){
  const own=r.seats.find(s=>s.user_id===user.id),waiting=!!(busy||pendingOperation);
  return `<div class="room-heading"><div class="room-heading-left"><a class="button ghost table-back" id="back-lobby" href="#lobby" title="${own?(own.leaving?'回到大廳，等待本局結算':'回到大廳，保留目前座位'):'回到遊戲大廳'}">${icon('back')}回大廳</a><div><h1>${esc(r.name)}</h1><p>${subtitle}</p></div></div><div class="table-tools"><button class="button ghost" type="button" data-social-toggle aria-label="聊天與語音">${icon('chat')}<span class="table-secondary-label">聊天／語音</span></button><button class="button ghost" type="button" id="show-history" aria-label="牌局紀錄與重播">${icon('history')}<span class="table-secondary-label">紀錄</span></button>${own?`<button class="button ghost table-leave" type="button" id="leave-table" data-leave-table ${own.leaving||waiting?'disabled':''}>${icon('logout')}<span>${own.leaving?'結算後離桌':'離開牌桌'}</span></button>`:''}${r.owner_id===user.id&&r.status==='waiting'?`<details class="table-manage" data-preserve-open><summary aria-label="房主管理">${icon('settings')}</summary><div><button class="text-button danger" type="button" id="close-table" ${waiting?'disabled':''}>結束牌桌</button></div></details>`:''}</div></div>`;
}
function currentTableNotice(){
  if(view==='table'||!lobby.current_room_id)return '';
  const current=lobby.rooms.find(r=>r.id===lobby.current_room_id),own=current?.seats.find(s=>s.user_id===me().id);
  return `<aside class="current-table-notice" aria-label="目前的牌桌"><span><strong>${own?.leaving?'已安排結算後離桌':'你仍在牌桌'}</strong>${current?`<span>${esc(current.name)}</span>`:''}</span><a class="button ghost" href="#table/${lobby.current_room_id}">${own?.leaving?'查看結算':'回到牌桌'}${icon('arrow')}</a></aside>`;
}
function navigationBlocked(){
  if(view!=='table'||!room||!busy&&!pendingOperation)return false;
  feedback(pendingOperation&&!busy?'結果尚未確認，請先按「確認原操作」。':'操作確認中，請稍候再離開。',true);notice('請先確認目前這筆操作，再切換頁面。');return true;
}
// Keep uncertain receipts attached to their table, including browser Back.
document.addEventListener('click',event=>{const link=event.target.closest('a[href^="#"]');if(link&&link.hash!=='#main'&&link.hash!==location.hash&&navigationBlocked())event.preventDefault();},true);
function finishDeparture(op){
  if(!op||!['leave','close'].includes(op.action)||view!=='table'||room?.id!==op.target||busy||pendingOperation)return;
  notice(op.action==='close'?'牌桌已結束。':seated()?.leaving?'已安排結算後離桌；結算完成會退回錢包。':'已離開牌桌，籌碼已退回錢包。');go('lobby');
}
function leaveDescription(r,user){
  const player=r.hand?.players.find(p=>p.user_id===user.id);
  if(r.status!=='playing'||!player)return '本桌籌碼會退回錢包，並回到大廳。';
  const ending=' 確認後回到大廳，結算完成才釋放座位。';
  const text={holdem:player.stack===0&&!player.folded?'你已 All-in，會保留本手結果，結算後離桌。':'本手會棄牌，結算後離桌。',big2:'離桌視為放棄本局，仍依剩餘手牌計算輸贏。',blackjack:'本局手牌會自動停牌，輸贏照常結算。',mahjong:'本局由系統自動摸打，輸贏照常計算；不額外罰點。',mines:'已翻格按目前金額收手；尚未翻格退回本金。',tower:'已通過樓層按目前金額收手；尚未翻格退回本金。',inbetween:'本局門柱會略過；已完成的押注仍依結果結算。'};
  return (text[r.game_type||'holdem']||'已確認的押注仍會結算；尚未確認的押注不會送出。')+ending;
}

function renderAuth(){
  window.ClubSocial?.roomChanged(null,null);stopLive();window.ClubAdmin?.unmount();window.ClubProfile?.unmount();window.ClubMember?.unmount();window.ClubStaff?.unmount();window.ClubFishing?.unmount();window.ClubBank?.unmount();window.ClubDealer?.cancel();window.ClubArcadeMotion?.cancel();window.ClubBonus?.cancel();window.ClubRoundPresentation?.cancel();
  const reg=authMode==='register';
  app.innerHTML=`${playReminder()}<main class="auth-layout"><section class="auth-scene"><a class="brand" href="#">${brand()}</a><div class="auth-pitch"><span class="neon-label"><i></i>私人的局，隨時開桌</span><h1>門關上。<br>好戲<span>才開始。</span></h1><p>自己的帳號，隨時同桌。<br>電腦發牌、即時對局，今晚不用等齊一個房間。</p><div class="auth-perks"><span>${icon('cards')}電腦莊家</span><span>${icon('people')}${Object.keys(window.ClubArcade.catalog).length} 種遊戲</span><span>${icon('shield')}專屬邀請碼</span></div></div><div class="auth-art" aria-hidden="true"><div class="art-orbit"></div><div class="art-card art-back">K<span>♠</span></div><div class="art-card art-front">A<span>♠</span><small>THE SIX</small></div><div class="art-chip chip-a"></div><div class="art-chip chip-b"></div><div class="art-chip chip-c"></div></div><div class="auth-scene-foot"><span>私人線上牌室</span><span>虛擬籌碼・不涉及金流</span></div></section>
  <section class="auth-side"><div class="auth-form-wrap"><span class="small-label">兄弟的位子，留好了</span><h2>${reg?'加入楠團，準備上桌。':'歡迎回來，今晚玩幾手？'}</h2><p class="muted">${reg?'每個人建立自己的帳號，用邀請碼入座。':'登入你的帳號，直接回到線上牌桌。'}</p><div class="auth-tabs" role="tablist" aria-label="登入或註冊"><button role="tab" aria-selected="${!reg}" data-auth="login">登入帳號</button><button role="tab" aria-selected="${reg}" data-auth="register">建立帳號</button></div>
  <form id="auth-form"><div class="form-error" hidden role="alert" tabindex="-1"></div>${reg?'<label>你的暱稱<input name="nickname" autocomplete="nickname" maxlength="16" placeholder="兄弟們怎麼叫你" required></label>':''}<label>帳號<input name="username" autocomplete="username" minlength="3" maxlength="24" pattern="[A-Za-z0-9_]{3,24}" placeholder="英文字母、數字或底線" autocapitalize="none" spellcheck="false" required></label><label>密碼<span class="password-field"><input id="auth-password" aria-label="密碼" name="password" type="password" autocomplete="${reg?'new-password':'current-password'}" minlength="8" maxlength="128" placeholder="至少 8 個字元" required><button class="password-toggle" type="button" id="toggle-password" aria-pressed="false" aria-controls="auth-password">顯示</button></span></label>${reg&&(requiresInvite||memberCount>0)?'<label>牌桌邀請碼<input name="invite_code" maxlength="8" placeholder="輸入 8 位專屬邀請碼" autocapitalize="characters" spellcheck="false" required></label>':''}<button class="button primary full" type="submit">${reg?'建立帳號，加入牌室':'登入，進入牌室'} ${icon('arrow')}</button></form><div class="auth-fine">${icon('shield')}使用邀請碼加入，每桌最多六人，帳號數量不限。</div></div><div class="auth-side-foot">${Object.keys(window.ClubArcade.catalog).length} 款遊戲 · 任務與收藏 <span>電腦莊家 · 即時對局</span></div></section></main>`;
  $$('[data-auth]').forEach(b=>b.onclick=()=>{authMode=b.dataset.auth;renderAuth();});
  $('#toggle-password').onclick=()=>{const field=$('#auth-password'),button=$('#toggle-password'),show=field.type==='password';field.type=show?'text':'password';button.textContent=show?'隱藏':'顯示';button.setAttribute('aria-pressed',String(show));};
  $('#auth-form').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;pending(f,true);try{await api(reg?'/api/register':'/api/login',Object.fromEntries(new FormData(f)));await enter();}catch(error){formError(f,error.message);}finally{pending(f,false);}};
}

async function route(){if(view==='table'&&room&&location.hash!=='#table/'+room.id&&navigationBlocked()){history.replaceState(null,'','#table/'+room.id);return;}window.ClubAdmin?.unmount();window.ClubProfile?.unmount();window.ClubMember?.unmount();window.ClubStaff?.unmount();window.ClubFishing?.unmount();window.ClubBank?.unmount();window.ClubDealer?.cancel();window.ClubArcadeMotion?.cancel();window.ClubBonus?.cancel();window.ClubRoundPresentation?.cancel();const match=location.hash.match(/^#table\/(\d+)(?:\?invite=([A-Za-z0-9_-]{20,80}))?$/);roomId=match?Number(match[1]):null;memberId=Number(location.hash.match(/^#member\/(\d+)$/)?.[1])||null;view=memberId?'member':roomId?'table':['stats','members','collection','rewards','admin','wallet','bank','profile','clubhouse','fishing'].includes(location.hash.slice(1))?location.hash.slice(1):'lobby';room=null;signature='';generation++;window.ClubSocial?.roomChanged(roomId,lobby?.me);if(lobby&&match?.[2]){const token=generation;try{await api('/api/online/rooms/'+roomId+'/invite',{code:match[2],operation_id:operationId()});if(token!==generation)return;history.replaceState(null,'','#table/'+roomId);}catch(error){notice(error.message);if(token===generation)go('lobby');return;}}if(lobby){if(!roomId){signature=stateSignature(lobby);render();}startLive();}window.scrollTo({top:0,behavior:'instant'});}
function go(where){const hash=typeof where==='number'?'#table/'+where:'#'+where;if(hash!==location.hash&&navigationBlocked())return;if(location.hash===hash){route();}else location.hash=hash;}
function shell(content){const nav=[['lobby','grid','遊戲大廳'],['stats','trophy','籌碼排行'],['members','people','楠團成員'],['bank','wallet','楠團銀行'],['clubhouse','clubhouse','我的會所'],['rewards','gift','補給任務']];if(me()?.is_admin)nav.push(['admin','shield','管理後台']);return `<a class="skip-link" href="#main">跳至主要內容</a><div class="club-app night-edition"><aside class="sidebar"><a class="brand" href="#lobby">${brand()}</a><div class="private-badge">${icon('shield')}只限自己人</div><nav aria-label="主選單">${nav.map(([id,ic,name])=>`<a href="#${id}" class="nav-item ${(view===id||id==='rewards'&&view==='collection')?'active':''}" ${(view===id||id==='rewards'&&view==='collection')?'aria-current="page"':''}>${icon(ic)}<span>${name}</span>${id==='members'?`<b>${num(lobby.total_members??lobby.users.length)} 人</b>`:id==='rewards'?`<b class="reward-count" data-reward-count ${rewardCount()?'':'hidden'}>${rewardCount()} 可領</b>`:''}</a>`).join('')}</nav><div class="sidebar-rule"><p>朋友的聚會場</p></div><div class="sidebar-foot"><a class="archive-link" href="/ledger">${icon('history')}原有記帳紀錄</a><div class="account"><button class="profile-account-button" data-open-profile aria-label="管理我的帳號">${avatar(me())}<span class="profile-user-text"><strong>${esc(me().nickname)}</strong>${window.ClubIdentity.badge(me())}<small>@${esc(me().username)}</small></span></button><button class="icon-button" id="logout" aria-label="登出帳號">${icon('logout')}</button></div></div></aside><div class="club-main">${playReminder()}<header class="topbar"><a class="mobile-brand" href="#lobby" aria-label="楠團牌室，回到大廳">${icon('spade')}<span class="brand-mobile-long">楠團牌室</span><span class="brand-mobile-short">楠團</span></a><span class="header-word">${({lobby:"遊戲大廳",stats:"籌碼排行",members:"楠團成員",clubhouse:"我的會所",fishing:"楠團漁港",collection:"外觀收藏",rewards:"補給任務",wallet:"點數轉帳",bank:"楠團銀行",profile:"我的帳號",admin:"管理後台",table:"遊戲牌桌"})[view]||"楠團牌室"}</span><div class="header-right">${lobby.wallet?.enabled?`<button class="header-balance" data-open-bank aria-label="帳號總籌碼 ${num(lobby.wallet.total)} 點，開啟銀行"><strong>${num(lobby.wallet.total)}</strong><small> 點</small></button>`:''}<button type="button" class="connection ${connected?'':'offline'}" id="connection" data-mode="${connectionMode}" aria-live="polite" aria-atomic="true" aria-label="連線狀態：${connectionLabel()}，查看連線診斷"><i></i>${connectionLabel()}</button><button class="icon-button" id="open-bank" aria-label="銀行存提款與轉帳" title="楠團銀行">${icon('wallet')}</button><button class="button global-voice-button" data-global-voice aria-label="加入語音" title="加入語音">${icon('headphones')}<span data-voice-label>語音</span><i aria-hidden="true"></i></button><button class="icon-button global-voice-mute" data-global-mute hidden aria-label="關閉麥克風" title="關閉麥克風">${icon('mic')}</button><button class="profile-account-button top-profile" data-open-profile aria-label="管理我的帳號">${avatar(me())}<span class="profile-user-text"><strong>${esc(me().nickname)}</strong>${window.ClubIdentity.badge(me())}</span></button><button class="icon-button mobile-logout" id="mobile-logout" aria-label="登出帳號">${icon('logout')}</button></div></header>${recoveryNotice()}<main id="main" tabindex="-1">${currentTableNotice()}${view==='table'&&room?window.ClubFeatures.party(room,me()):''}${content}</main><footer class="page-foot"><span>楠團私人牌室</span><span>電腦莊家・虛擬籌碼・無金流</span></footer></div></div>`;}
function bindFeatures(){window.ClubFeatures.bind({api,dialog,close:xButton,card,room,user:me(),command,notice,context:()=>({mode:connectionLabel(),room_id:roomId,revision:room?.revision,view,pending_since:pendingOperation?.sentAt})});}
function bindShell(){bindExperience();$$('[data-rewards-jump]').forEach(b=>b.onclick=()=>{const target=$('.club-missions');if(target){target.setAttribute('tabindex','-1');target.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});target.focus({preventScroll:true});}});$$('[data-global-voice]').forEach(b=>b.onclick=()=>window.ClubSocial?.quickJoin());$$('[data-global-mute]').forEach(b=>b.onclick=()=>window.ClubSocial?.toggleMute());window.ClubSocial?.refreshUI();window.ClubIncome.bind({user:me(),wallet:lobby.wallet,now:Date.now()/1000+clockOffset,clock:()=>Date.now()/1000+clockOffset,api,operationId,notice,confirm:confirmDialog,refresh:()=>sync(true),update:result=>{lobby.wallet=result.wallet;signature='';render();void sync(true);}});bindFeatures();const partyButton=$('#create-party');if(partyButton)partyButton.onclick=createParty;$$('[data-open-profile]').forEach(b=>b.onclick=()=>{profileTab='settings';go('profile');});window.ClubRewards?.bind({club:lobby.club,user:me(),api,operationId,notice,refresh:response=>{lobby.club=response.club;lobby.wallet=response.wallet;lobby.me.cosmetics=response.club.equipped;const own=lobby.users.find(u=>u.id===me().id);if(own)own.cosmetics=response.club.equipped;signature='';render();}});const skip=$('.skip-link');if(skip)skip.onclick=e=>{e.preventDefault();$('#main').focus();};$$('[data-open-transfers],#open-transfers').forEach(b=>b.onclick=()=>go('wallet'));$$('[data-open-bank],#open-bank').forEach(b=>b.onclick=()=>go('bank'));$$('[data-transfer-user]').forEach(b=>b.onclick=()=>{const person=lobby.users.find(u=>u.id===Number(b.dataset.transferUser));if(person){window.ClubTransfers.setPrefill(person);go('wallet');}});const claim=$('#daily-claim');if(claim)claim.onclick=claimDaily;const hourly=$('#hourly-claim');if(hourly)hourly.onclick=claimHourly;updateSupplyClock();for(const id of ['logout','mobile-logout']){const b=$('#'+id);if(b)b.onclick=async()=>{try{await api('/api/logout',{});window.ClubSocial?.roomChanged(null,null);lobby=null;room=null;pendingOperation=null;actionFeedback=null;generation++;const info=await api('/api/bootstrap');memberCount=info.member_count;requiresInvite=info.requires_invite;renderAuth();}catch(e){notice(e.message);}};}$$('[data-create]').forEach(b=>b.onclick=()=>createRoom(b.dataset.game||'holdem'));$$('[data-configure]').forEach(b=>b.onclick=()=>createRoom(b.dataset.configure,true));$$('[data-room]').forEach(b=>b.onclick=()=>go(Number(b.dataset.room)));}
function patchNode(current,next){
  if(current.isEqualNode(next)&&!(current.nodeType===Node.ELEMENT_NODE&&(current instanceof HTMLInputElement||current.querySelector('input'))))return;
  if(current.nodeType!==next.nodeType||current.nodeName!==next.nodeName){current.replaceWith(next.cloneNode(true));return;}
  if(current.nodeType===Node.TEXT_NODE){if(current.nodeValue!==next.nodeValue)current.nodeValue=next.nodeValue;return;}
  if(current.nodeType!==Node.ELEMENT_NODE)return;
  for(const key of ['id','data-seat','data-player','data-room','data-action','data-card-key','data-big2-card','data-risk-cell','data-floor','href']){if(current.getAttribute(key)!==next.getAttribute(key)){current.replaceWith(next.cloneNode(true));return;}}
  if(['bank-console','admin-console','transfer-console','profile-console','member-console','staff-console','fishing-page'].includes(current.id))return;
  if(current instanceof HTMLImageElement&&current.matches('.current-art')&&current.getAttribute('src')===next.getAttribute('src'))for(const flag of ['data-art-loading','data-art-failed'])next.toggleAttribute(flag,current.hasAttribute(flag));
  if(current instanceof HTMLDetailsElement&&current.hasAttribute('data-preserve-open')&&current.open)next.setAttribute('open','');
  for(const attr of [...current.attributes])if(!next.hasAttribute(attr.name))current.removeAttribute(attr.name);
  for(const attr of [...next.attributes])if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
  const children=[...next.childNodes];
  children.forEach((child,index)=>{if(current.childNodes[index])patchNode(current.childNodes[index],child);else current.appendChild(child.cloneNode(true));});
  while(current.childNodes.length>children.length)current.lastChild.remove();
  if(current instanceof HTMLInputElement)current.value=next.value;
}
function patchApp(html){
  const template=document.createElement('template');template.innerHTML=html;
  const children=[...template.content.childNodes];
  children.forEach((node,index)=>{if(app.childNodes[index])patchNode(app.childNodes[index],node);else app.appendChild(node.cloneNode(true));});
  while(app.childNodes.length>children.length)app.lastChild.remove();
}
function render(){if(!lobby)return renderAuth();const back=lobby.club?.equipped?.back?.style||'';if(document.documentElement.dataset.cardBack!==back)document.documentElement.dataset.cardBack=back;patchApp(shell(view==='fishing'?window.ClubFishing.page():view==='clubhouse'?window.ClubIncome.page(lobby.wallet,me()):view==='member'?window.ClubMember.view():view==='profile'?profileView():view==='admin'?adminView():view==='bank'?heading('楠團銀行','')+window.ClubBank.view():view==='wallet'?heading('點數轉帳','帳號間移轉虛擬點數，先確認收款人，再確認金額。','<a class="button ghost" href="#bank">銀行存款／借款</a>')+window.ClubTransfers.view():view==='table'&&room?tableView():view==='rewards'?rewardsView():view==='collection'?window.ClubRewards.view(lobby.club,lobby.wallet,me()):view==='stats'?statsView():view==='members'?membersView():lobbyView()));bindShell();if(view==='fishing')window.ClubFishing.mount({user:me(),wallet:lobby.wallet,serverTime:lobby.server_time,api,operationId,onWallet:w=>{lobby.wallet=w;const b=$('.header-balance strong');if(b)b.textContent=num(w.total);}});if(view==='clubhouse')window.ClubStaff.mount({user:me(),wallet:lobby.wallet,api,operationId,notice,confirm:confirmDialog,clock:()=>Date.now()/1000+clockOffset,update:result=>{lobby.wallet=result.wallet;signature='';render();void sync(true);}});if(view==='profile'||view==='member')window.ClubMember.mount({id:view==='profile'?me().id:memberId,version:JSON.stringify([lobby.users.find(u=>u.id===(view==='profile'?me().id:memberId)),view==='profile'?lobby.wallet.total:null]),user:me(),api,transfer:person=>{window.ClubTransfers.setPrefill(person);go('wallet');}});if(view==='profile')window.ClubProfile.mount({user:me(),club:lobby.club,user:me(),api,operationId,saved:profile=>{lobby.me={...lobby.me,...profile};const own=lobby.users.find(u=>u.id===me().id);if(own)Object.assign(own,profile);signature='';render();void sync(true);},equipped:result=>{lobby.club=result.club;lobby.wallet=result.wallet;lobby.me.cosmetics=result.club.equipped;signature='';render();}});if(view==='bank')window.ClubBank.mount({user:me(),wallet:lobby.wallet,api,updated:(result,uid)=>{if(me()?.id!==uid)return;lobby.wallet=result.wallet;const b=$('.header-balance strong');if(b)b.textContent=num(result.wallet.total);if(result.ok){signature='';void sync(true);}}});if(view==='wallet')window.ClubTransfers.mount({user:me(),wallet:lobby.wallet,api,refresh:(result,uid)=>{if(me()?.id!==uid)return;lobby.wallet=result.wallet;signature='';void sync(true);}});if(view==='admin')window.ClubAdmin?.mount(me());if(view==='table'&&room){bindTable();window.ClubSocial?.update(room);window.ClubDealer?.play();window.ClubArcadeMotion?.play();window.ClubBonus?.play();window.ClubRoundPresentation?.play();}window.ClubIdentity.observe();if(view==='members'){bindMemberSearch();const c=$('#copy-invite');if(c)c.onclick=async()=>{try{await navigator.clipboard.writeText(`楠團牌室 ${location.origin}\n邀請碼：${lobby.invite_code}`);notice('網址與邀請碼已複製，分享給兄弟即可。');}catch{notice('邀請碼：'+lobby.invite_code+'，可直接選取複製。');}};}}
// A turn update only changes the table. Keep the mobile header and sidebar
// intact instead of rebuilding and walking their repeated SVG/effect markup.
function renderTableUpdate(){
 const template=document.createElement('template');template.innerHTML=`<main id="main" tabindex="-1">${window.ClubFeatures.party(room,me())}${tableView()}</main>`;
 patchNode($('#main'),template.content.firstChild);bindTable();window.ClubSocial?.update(room);window.ClubDealer?.play();window.ClubArcadeMotion?.play();window.ClubBonus?.play();window.ClubRoundPresentation?.play();window.ClubIdentity.observe();
}
function heading(title,text,action=''){return `<div class="page-heading"><div><h1>${title}</h1><p>${text}</p></div>${action}</div>`;}
function createParty(){dialog(`<section><div class="modal-head"><h2 id="modal-title">包廂玩什麼？</h2>${xButton()}</div><div class="feature-actions">${['holdem','big2','blackjack','roulette','baccarat','dice','mahjong'].map(k=>`<button class="button ghost" data-party-game="${k}">${window.ClubArcade.catalog[k].name}</button>`).join('')}</div></section>`);$$('[data-party-game]').forEach(b=>b.onclick=()=>createRoom(b.dataset.partyGame,true,true));}
function createButton(){return `<button class="button primary" data-create>${icon('plus')}開一張新桌</button>`;}
function lobbyView(){
  const rooms=lobby.rooms.filter(r=>roomFilter==='mine'?r.seats.some(s=>s.user_id===me().id):roomFilter==='all'||r.game_type===roomFilter||roomFilter==='holdem'&&!r.game_type);
  const shown=roomsExpanded?rooms:rooms.slice(0,6);
  return `<div class="night-lobby">${heading('遊戲大廳','',`<a class="button ghost rewards-shortcut" href="#rewards">${icon('gift')}補給任務</a>`)}<section class="night-feature"><div class="night-main-art"><div class="night-hero-copy"><h2>${lobby.current_room_id?'回桌，繼續這一局。':'今晚，開一桌。'}</h2><p>${lobby.current_room_id?'你的座位與籌碼都還在。':'選個遊戲，和朋友打兩手。'}</p><div class="night-hero-actions"><button class="button night-primary" ${lobby.current_room_id?'data-room="'+lobby.current_room_id+'"':'data-lobby-jump="games"'}>${lobby.current_room_id?'回到牌桌':'選擇遊戲'}</button><button class="button ghost" id="create-party">建立好友包廂</button></div></div></div><div class="night-feature-picks"><button type="button" data-create data-game="big2"><span aria-hidden="true">2</span>大老二</button><a href="#clubhouse"><span aria-hidden="true">♜</span>我的會所</a><a href="#collection"><span aria-hidden="true">♣</span>外觀收藏</a></div></section>
  <section id="lobby-rooms" class="tables-section night-tables lobby-room-strip"><div class="section-title"><h2>開放牌桌 <span>${rooms.length}</span></h2><p>${num(lobby.online_count??0)} 位在線</p></div><label class="room-filter">篩選牌桌<select id="room-filter"><option value="all">全部遊戲</option><option value="mine" ${roomFilter==='mine'?'selected':''}>我的牌桌</option>${Object.entries(window.ClubArcade.catalog).map(([key,g])=>`<option value="${key}" ${roomFilter===key?'selected':''}>${g.name}</option>`).join('')}</select></label>${rooms.length?`<div class="room-grid">${shown.map(roomCard).join('')}</div>${rooms.length>6?`<button class="button ghost" id="expand-rooms">${roomsExpanded?'收起牌桌':'顯示全部 '+rooms.length+' 桌'}</button>`:''}`:`<div class="empty-tables"><h3>目前沒有符合的牌桌</h3><button class="button primary" data-lobby-jump="games">選遊戲開桌</button></div>`}</section>
  <section id="lobby-games"><div class="night-catalog-heading"><h2>選擇遊戲</h2><span>開桌或設定底注</span></div>${window.ClubFishing.card()}${window.ClubArcade.choices(icon)}</section>
  </div>`;
}

function rewardCount(state=lobby){
  const w=state?.wallet;if(!w?.enabled)return 0;
  const hourly=Math.max(0,(w.hourly_next_at||0)-(Date.now()/1000+clockOffset))===0;
  return Number(!w.daily_claimed)+Number(hourly)+(state.club?.missions||[]).filter(m=>!m.claimed&&m.progress>=m.target).length;
}
function rewardsView(){return `<section class="rewards-hub">${heading('補給與今日任務','每日補給、每小時補給和任務獎勵，都在這裡。',`<div class="rewards-links"><button class="button ghost" data-rewards-jump>${icon('check')}今日任務</button><a class="button ghost" href="#collection">${icon('cards')}外觀收藏</a></div>`)}${walletPanel()}${window.ClubRewards.missions(lobby.club)}</section>`;}
function roomCard(r){if(r.game_type&&r.game_type!=='holdem')return window.ClubArcade.roomCard(r,{avatar,icon,me:me()});const mine=r.seats.some(s=>s.user_id===me().id);return `<article class="room-card"><div class="room-card-top"><span class="table-status ${r.status==='playing'?'playing':''}"><i></i>${r.status==='playing'?'對局進行中':'等待發牌'}</span><span class="room-code">桌 #${String(r.id).padStart(3,'0')}</span></div><h3>${esc(r.name)}</h3><div class="room-specs"><span>盲注 <b>${r.small_blind}/${r.big_blind}</b></span><span>入桌 <b>金額自訂</b></span></div><div class="room-card-bottom"><div class="mini-avatars">${r.seats.slice(0,4).map(p=>avatar(p)).join('')}<span>${r.seats.length}/6 入座</span></div><button class="button ${mine?'primary':'ghost'}" data-room="${r.id}">${mine?'回到牌桌':r.seats.length===6?'觀戰':'進入牌桌'}${icon('arrow')}</button></div></article>`;}
function statsView(){
  const users=lobby.users.slice().sort((a,b)=>rankMode==='profit'?b.profit-a.profit||b.total_chips-a.total_chips:(a.rank||999)-(b.rank||999)||b.total_chips-a.total_chips);
  const own=users.find(u=>u.id===me().id),position=own?users.indexOf(own)+1:null,shown=ranksExpanded?users:users.slice(0,10);
  return `${heading('籌碼排行榜','補給與遊戲淨輸贏分開計算。')}<div class="view-switch" role="group" aria-label="排行方式"><button class="button ghost" data-rank-mode="assets" aria-pressed="${rankMode==='assets'}">總資產</button><button class="button ghost" data-rank-mode="profit" aria-pressed="${rankMode==='profit'}">遊戲淨贏</button></div><div class="own-rank"><span>我的${rankMode==='assets'?'總資產':'遊戲淨贏'}排名</span><strong>${position?'#'+(rankMode==='assets'?(own.rank||position):position):'—'}</strong><b>${rankMode==='assets'?num(own?.total_chips):delta(own?.profit||0)} 點</b></div><section class="panel ranking-panel"><div class="rank-header"><span>成員</span><span>手數</span><span>淨輸贏</span><span>總籌碼</span></div>${shown.map((u,i)=>`<div class="rank-row ${u.id===me().id?'is-own':''}"><div class="rank-identity"><span class="rank-number">${String(rankMode==='assets'?(u.rank||i+1):i+1).padStart(2,'0')}</span>${avatar(u)}<span class="identity-stack"><strong><a class="member-name-link" href="#member/${u.id}">${esc(u.nickname)}</a>${u.id===me().id?'<em class="me-tag">我</em>':''}</strong>${window.ClubIdentity.badge(u)}</span></div><span class="rank-stat"><small>手數</small>${num(u.hands)}</span><span class="rank-stat"><small>淨輸贏</small>${delta(u.profit)}</span><strong class="wallet-total">${num(u.total_chips)}</strong></div>`).join('')}${users.length>10?`<button class="button ghost" id="expand-ranks">${ranksExpanded?'只看前十名':'顯示全部 '+users.length+' 人'}</button>`:''}<p class="panel-note">${rankMode==='profit'?'遊戲淨贏依目前名單排序；帳號名單為總資產前 100 名及自己。':'總資產含錢包、桌上與底池、銀行存款，並扣除貸款與應付利息。'}補給不列入遊戲淨輸贏。</p></section><details class="night-supply" data-preserve-open><summary>我的籌碼與補給</summary>${walletPanel()}</details><details class="night-supply" data-preserve-open><summary>收藏與獲利榜</summary>${window.ClubRewards.leaderboards(lobby.club)}</details>`;
}

function adminView(){return me()?.is_admin?`${heading('管理後台','查看帳號狀態與籌碼，所有增減都會留下紀錄。')}<section id="admin-console"></section>`:heading('管理員專用','請使用獨立管理員帳號登入。');}
function membersView(){return `${heading('楠團成員','帳號數量不限，各遊戲提供 1–6 個座位。找朋友一起上桌。')}<details class="member-invite" data-preserve-open><summary>邀請朋友加入</summary><section class="invite-panel"><div><span class="small-label">邀朋友入局</span><h2>同一個牌室，各自的帳號。</h2><p>把網址和邀請碼傳給朋友，註冊後就能加入牌桌。</p></div><div class="invite-value"><span>牌室邀請碼</span><strong>${esc(lobby.invite_code)}</strong><button class="button ghost" id="copy-invite">複製網址與邀請碼</button></div></section></details><div class="member-toolbar"><label class="member-search"><span class="sr-only">搜尋成員暱稱或帳號</span>${icon('search')}<input id="member-search" type="search" placeholder="搜尋暱稱或帳號" value="${esc(memberQuery)}" autocomplete="off"></label><span class="member-count" id="member-count" role="status"></span></div><div class="members-grid">${lobby.users.slice().sort((a,b)=>a.id-b.id).map(u=>`<article class="panel member-panel" data-member-search="${esc((u.nickname+' '+u.username).toLocaleLowerCase())}"><div class="member-top">${avatar(u,true)}<span class="presence ${lobby.server_time-u.last_seen<16?'online':''}"><i></i>${lobby.server_time-u.last_seen<16?'在線':'離線'}</span></div><h2>${`<a class="member-name-link" href="#member/${u.id}">${esc(u.nickname)}</a>`}${u.id===me().id?'<em class="me-tag">我</em>':''}</h2>${window.ClubIdentity.badge(u)}<p>@${esc(u.username)}</p><div class="member-stats"><div><span>總籌碼</span><strong class="wallet-total">${num(u.total_chips)}</strong></div><div><span>完成手數</span><strong>${num(u.hands)}</strong></div></div>${u.id!==me().id?`<button class="button ghost member-transfer" data-transfer-user="${u.id}">轉點數給 @${esc(u.username)}</button>`:''}</article>`).join('')}</div><p class="member-empty" id="member-empty" hidden>找不到符合的成員，試試其他暱稱或帳號。</p>`;}
function bindMemberSearch(){const input=$('#member-search');const filter=()=>{memberQuery=input.value;const query=memberQuery.trim().toLocaleLowerCase();let count=0;$$('[data-member-search]').forEach(card=>{card.hidden=!card.dataset.memberSearch.includes(query);if(!card.hidden)count++;});$('#member-count').textContent=`顯示 ${count} 位 · 已註冊 ${num(lobby.total_members)} 位${lobby.total_members>lobby.users.length?'（名單為排行前 100 名與自己）':''}`;$('#member-empty').hidden=count>0;};input.oninput=filter;filter();}
function fundingField(balance,initial){return `<label for="funding-amount">這次帶入籌碼</label><div class="funding-entry"><input id="funding-amount" name="buy_in" type="number" inputmode="numeric" min="1" max="${balance}" step="1" value="${Math.min(initial,balance)}" required aria-describedby="funding-help"><button class="button ghost" type="button" id="funding-all">全部帶入</button></div><p class="funding-help" id="funding-help">可帶入 1–${num(balance)} 點，其他籌碼留在錢包。</p>`;}
function bindFundingAll(){const input=$('#funding-amount');$('#funding-all').onclick=()=>{const balance=room?.wallet?.balance??lobby.wallet.balance;input.max=balance;input.value=balance;$('#funding-help').textContent=`可帶入 1–${num(balance)} 點，其他籌碼留在錢包。`;input.dispatchEvent(new Event('input',{bubbles:true}));};}
async function createRoom(kind='holdem',configure=false,privateParty=false){
  const games=window.ClubArcade.catalog;if(!games[kind])kind='holdem';
  if(lobby.current_room_id){go(lobby.current_room_id);notice('你已經入座，先回到原本的牌桌。');return;}
  const balance=lobby.wallet.balance;if(balance<1){notice('錢包目前沒有籌碼，請先領取每日補給。');return;}
  if(kind==='mahjong'){window.ClubMahjong.create({balance,user:me(),dialog,close:xButton,api,operationId,go,formError,pending,fundingField,bindFundingAll});return;}
  if(!configure&&!['holdem','big2'].includes(kind)){
    const button=document.querySelector('[data-create][data-game="'+kind+'"]');if(button?.disabled)return;if(button)button.disabled=true;
    try{const response=await api('/api/online/rooms',{operation_id:operationId(),name:games[kind].name+' · '+me().nickname,game_type:kind,stake:kind==='baccarat'?20:10,buy_in:Math.min(1000,balance)});go(response.id);}catch(error){notice(error.message);if(button)button.disabled=false;}return;
  }
  dialog(`<form id="create-form"><div class="modal-head"><div><span class="small-label">今晚，由你開場</span><h2 id="modal-title">開一張新桌</h2></div>${xButton()}</div><p class="funding-note">可用錢包 ${num(balance)} 點；每人自行決定帶入金額。</p><div class="form-error" hidden role="alert" tabindex="-1"></div><input id="game-choice" name="game_type" type="hidden" value="${kind}"><p class="selected-game">${games[kind].name} · ${games[kind].people}</p><label>牌桌名稱<input name="name" value="${esc(games[kind].name)} · 今晚不睡局" maxlength="32" required></label><label id="holdem-options">盲注<select id="blind-choice" name="blind"><option value="10">5 / 10</option><option value="20">10 / 20</option><option value="50">25 / 50</option><option value="100">50 / 100</option></select></label><label id="arcade-options"><span id="stake-label">基本點數</span><input id="game-stake" name="stake" type="number" inputmode="numeric" value="10" min="1" max="${lobby.betting_limits?.params.max_bet??10000}" step="1"></label><fieldset id="big2-options"><legend>大老二規則</legend><label>單打三條<select name="big2_triples"><option value="on">開啟</option><option value="off">關閉</option></select></label><label>手留 2 額外加倍<select name="big2_twos" id="big2-twos"><option value="off">關閉</option><option value="on">開啟：每張 2 再 ×2</option></select></label><p id="big2-reserve-note" class="funding-note" role="status"></p></fieldset>${['holdem','big2','blackjack','roulette','baccarat','dice'].includes(kind)?`<fieldset class="party-create-options"><legend>邀朋友一起玩</legend><label><input type="checkbox" name="private_party" ${privateParty?'checked':''}>私人包廂，只限邀請連結加入</label></fieldset>`:''}${fundingField(balance,1000)}<div class="rules-note" id="game-create-note"></div><button class="button primary full" type="submit">${icon('cards')}開桌並入座</button></form>`);
  bindFundingAll();const creationId=operationId();$('#game-stake').setAttribute('aria-describedby','big2-reserve-note');$('#big2-twos').setAttribute('aria-describedby','big2-reserve-note');
  function choice(){const key=$('#game-choice').value;$('#holdem-options').hidden=key!=='holdem';$('#big2-options').hidden=key!=='big2';$('#arcade-options').hidden=key==='holdem';const stake=$('#game-stake'),step=key==='baccarat'?20:key==='blackjack'?2:1;stake.required=key!=='holdem';stake.min=String(step);stake.step=String(step);stake.value=Math.max(step,Math.ceil(Number(stake.value)/step)*step);$('#stake-label').textContent=key==='roulette'?'每次點選增加的籌碼（每局上限 '+num(lobby.betting_limits?.params.max_bet??10000)+'）':key==='big2'?'每張牌點數':'每局下注點數';$('#game-create-note').textContent=key==='holdem'?'德州 2–6 人；逾時能過牌就過牌，否則棄牌。':window.ClubArcade.rules(key);}
  function reserveNote(){const required=Number($('#game-stake').value)*($('#big2-twos').value==='on'?832:52);$('#big2-reserve-note').textContent='每人開局須預留 '+num(required)+' 點，未用預留於結算退回。'+($('#big2-twos').value==='on'?'已計入最多 4 張 2 的加倍。':'');}$('#game-choice').onchange=choice;$('#game-stake').addEventListener('input',reserveNote);$('#big2-twos').onchange=reserveNote;choice();reserveNote();
  $('#create-form').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget;pending(f,true);const values=Object.fromEntries(new FormData(f)),bb=Number(values.blind);try{const response=await api('/api/online/rooms',{operation_id:creationId,name:values.name,game_type:values.game_type,private:values.private_party==='on',stake:Number(values.stake),...(values.game_type==='big2'?{big2_rules:{triples:values.big2_triples==='on',twos_double:values.big2_twos==='on'}}:{}),small_blind:bb/2,big_blind:bb,buy_in:Number(values.buy_in)});modal.close();go(response.id);}catch(error){formError(f,error.message);}finally{pending(f,false);}};
}
function openFunding(action,seat=null){
  if(!room||busy||pendingOperation)return;const target=room.id,balance=room.wallet.balance,rebuy=action==='rebuy';
  if(balance<1){notice('錢包目前沒有籌碼，請回大廳領取每日補給。');return;}
  dialog(`<form id="funding-form"><div class="modal-head"><h2 id="modal-title">${rebuy?'從錢包帶入籌碼':seat===null?'自動入座':`入座第 ${seat+1} 號位`}</h2>${xButton()}</div><p class="dialog-subtitle">${esc(room.name)} · ${room.game_type&&room.game_type!=='holdem'?window.ClubArcade.catalog[room.game_type].name+' · 基本 '+num(room.stake)+' 點':'盲注 '+room.small_blind+'/'+room.big_blind}</p><p class="funding-note">可用錢包 ${num(balance)} 點${rebuy?` · 桌上 ${num(seated().stack)} 點`:''}</p><div class="form-error" hidden role="alert" tabindex="-1"></div>${fundingField(balance,room.buy_in)}<p class="funding-help">${rebuy?'補碼會增加桌上籌碼，不會改變本次入桌的淨輸贏。':'帶入金額由你決定，至少 1 點；中途入座從下一手參與。'}</p><button class="button primary full" type="submit">${rebuy?'確認帶入籌碼':'確認入座'}</button></form>`);
  bindFundingAll();$('#funding-form').onsubmit=e=>{e.preventDefault();const amount=Number($('#funding-amount').value);if(room?.id!==target){formError(e.currentTarget,'牌桌已變更，請關閉後重新選擇。');return;}if(!Number.isSafeInteger(amount)||amount<1||amount>room.wallet.balance){formError(e.currentTarget,`請填寫 1–${num(room.wallet.balance)} 點。`);return;}modal.close();command(action,{[rebuy?'amount':'buy_in']:amount,...(seat===null?{}:{seat})},`已${rebuy?'補入':'帶入'} ${num(amount)} 點籌碼。`);};
}

function tableView(){window.ClubArt.prepare(room.game_type||'holdem');if(room.game_type&&room.game_type!=='holdem')return window.ClubArcade.table(room,me(),{card,icon,heading:tableHeading,feedback:feedbackHTML()});const own=seated(),h=room.hand,playing=room.status==='playing',players=h?.players||[],myResult=h?.results.find(p=>p.user_id===me().id),reference=own?.seat??0;const occupied=new Map(room.seats.map(s=>[s.seat,s]));return `<section class="live-room holdem-room">${tableHeading(room,me(),`盲注 ${room.small_blind}/${room.big_blind} · 第 ${room.hand_no} 手${own?' · '+(own.seat+1)+' 號座位':''}`)}
  ${room.status==='closed'?'<div class="room-ended">這張牌桌已結束，戰績已保存。<a href="#lobby">回大廳開新桌</a></div>':''}
  <div class="holdem-layout"><div class="table-arena"><div class="table-light"></div><div class="poker-felt"><div class="felt-inner"></div><span class="felt-wordmark" aria-hidden="true">楠團牌室<span>私人牌室</span></span></div><div class="board-area"><div class="pot-total"><span>${playing?'目前底池':h?'本手底池':'準備入局'}</span><strong>${h?num(h.players.reduce((s,p)=>s+p.contribution,0)):'—'}</strong><small>虛擬籌碼</small></div><div class="community-cards" aria-label="公共牌">${Array.from({length:5},(_,i)=>h?.board[i]?card(h.board[i],false,`board-${i}`):'<span class="board-placeholder" aria-label="尚未發出的公共牌">♠</span>').join('')}</div><div class="street-label">${h?phaseNames[h.phase]:'找位子坐下，電腦準備發牌'}</div>${h&&h.phase==='showdown'?`<div class="winner-line">${h.results.filter(r=>r.profit>0).map(r=>`${esc(r.nickname)} <b>+${num(r.profit)}</b>`).join(' <i>／</i> ')||'本手平分底池'}</div>`:''}</div>
  ${Array.from({length:6},(_,visual)=>{const seatIndex=(reference+visual)%6,seat=occupied.get(seatIndex),p=seat?players.find(x=>x.user_id===seat.user_id):null,turn=playing&&h.actor===seat?.user_id;return seat?`<div class="table-seat spot-${visual} ${seat.user_id===me().id?'is-me':''} ${turn?'on-turn':''} ${p?.folded?'folded':''}" data-player="${seat.user_id}"><div class="seat-cards">${p?(p.hole.length?p.hole.map((c,ci)=>card(c,seat.user_id!==me().id,`hole-${seat.user_id}-${ci}`)).join(''):card(null,true,`hole-${seat.user_id}-0`)+card(null,true,`hole-${seat.user_id}-1`)):''}</div><div class="seat-box">${room.dealer_seat===seatIndex&&h?'<span class="dealer-disc" title="莊家位">D</span>':''}${avatar(seat)}<div class="seat-details"><strong>${esc(seat.nickname)}${seat.user_id===me().id?'<em>你</em>':''}</strong><b>${num(seat.stack)}</b>${window.ClubIdentity.badge(seat)}</div><span class="seat-online ${seat.online?'online':''}" aria-label="${seat.online?'在線':'離線'}"></span></div><div class="seat-caption"><span class="seat-number">${seatIndex+1} 號 · </span>${seat.leaving?'本手後離桌':seat.away?'逾時代打':p?.folded?'已棄牌':p?.last_action?esc(p.last_action):p?'等待行動':'等待下一手'}</div>${p?.street_bet&&playing?`<div class="seat-bet"><i></i>${num(p.street_bet)}</div>`:''}${turn?'<progress class="seat-clock" max="30" value="30" aria-label="行動剩餘時間"></progress>':''}</div>`:`<button class="table-seat vacant spot-${visual}" data-seat="${seatIndex}" ${own||room.status==='closed'?'disabled':''} aria-label="入座第 ${seatIndex+1} 號座位"><span>${icon('plus')}</span><strong>${seatIndex+1} 號空位</strong><small>${own?'等兄弟加入':'點擊入座'}</small></button>`;}).join('')}</div>
  <aside class="holdem-decision"><div class="table-control-area" id="table-controls">${actionControls(own,h,playing,myResult)}${feedbackHTML()}</div>${window.ClubArcade.fundingPanel(room,me(),icon)}</aside></div><div class="table-bottom"><div class="dealer-log"><span>${icon('spade')}莊家</span><p>${esc(room.log.at(-1)?.text||'等待玩家入座。')}</p></div></div></section>`;}

function actionControls(own,h,playing,myResult){if(room.game_type&&room.game_type!=='holdem')return window.ClubArcade.controls(room,me());if(room.status==='closed')return `<div class="between-hands"><div><h2>今晚先到這，戰績已記住。</h2><p>回大廳隨時可以再開一桌。</p></div><button class="button primary" id="new-after-close">${icon('plus')}再開新桌</button></div>`;if(!own)return `<div class="between-hands"><div><h2>${room.seats.length===6?'六個位置都坐滿了。':'看好位置，就坐下。'}</h2><p>${lobby.current_room_id?'你在其他桌已有座位，請先回原桌離座。':`自訂帶入金額，或把錢包全部帶入；現在加入可參與${playing?'下一手':'發牌'}。`}</p></div><button class="button primary" id="join-table" ${room.seats.length>=6||lobby.current_room_id?'disabled':''}>${icon('plus')}選擇籌碼入座</button></div>`;
  if(own.leaving)return `<div class="waiting-turn"><span class="small-chip"></span><div><strong>已安排離桌，這手仍會正確結算。</strong><p>All-in 的牌會保留到攤牌，結算完自動釋放座位。</p></div></div>`;
  if(!playing){const eligible=room.seats.filter(s=>s.stack>0&&!s.away&&!s.leaving).length;return `<div class="between-hands"><div><span class="small-label">${h?'本手已結算':'電腦莊家就位'}</span><h2>${myResult?`本手 <span class="${tone(myResult.profit)}">${delta(myResult.profit)}</span> <small>${esc(myResult.rank)}</small>`:eligible>=2?'人到齊，準備發牌。':'等另一位兄弟入座。'}</h2><p>${own.away?'上一回合逾時已自動處理，正在恢復你的座位。':own.stack===0?'籌碼用完了，補充後再上桌。':'任何入座成員都可以發下一手，莊家位會自動輪轉。'}</p></div><div class="between-buttons">${own.away?'<button class="button ghost" id="return-table">回到牌桌</button>':''}<button class="button primary" id="deal-hand" ${eligible<2||own.away||own.stack===0?'disabled':''}>${icon('cards')}${h?'發下一手':'發牌開局'}</button></div></div>`;}
  if(!room.legal){const actor=h.players.find(p=>p.user_id===h.actor),myHand=h.players.find(p=>p.user_id===me().id);return `<div class="waiting-turn"><span class="waiting-pulse"></span><div><strong>${myHand?.folded?(own.away?'你因逾時已自動棄牌。':'你已棄牌，等下一手。'):!myHand?'下一手就輪到你。':own.away?'逾時已由系統自動處理。':`等待 ${esc(actor?.nickname||'其他玩家')} 行動`}</strong><p>${own.away?'回到此頁會自動恢復；已完成的行動與結算保留。':myHand?.stack===0&&!myHand?.folded?'你已 All-in，等待其他玩家完成行動。':'每位玩家有 30 秒，牌局會自動同步。'}</p></div><span class="turn-time" id="turn-time"></span>${own.away?'<button class="button ghost" id="return-table">回到牌桌</button>':''}</div>`;}
  const legal=room.legal,call=legal.actions.includes('check')?'過牌':`跟注 ${num(legal.to_call)}`;
  return `<div class="your-turn-heading"><strong><span class="pulse-dot"></span>輪到你了</strong><span>剩餘 <b id="turn-time">30</b> 秒</span><span>可用籌碼 <b>${num(own.stack)}</b></span></div><div class="betting-controls"><div class="quick-actions"><button class="button fold-button" data-action="fold">棄牌</button><button class="button call-button" data-action="${legal.actions.includes('check')?'check':'call'}">${call}</button>${legal.actions.includes('allin')?'<button class="button allin-button" data-action="allin">All-in</button>':''}</div>${legal.can_full_raise?`<form id="raise-form"><label for="raise-amount">加注至</label><div class="raise-entry"><div class="raise-stepper"><button class="raise-step" type="button" data-raise-step="-1" aria-label="減少下注金額" aria-controls="raise-amount">−</button><input id="raise-amount" aria-label="加注至籌碼，點擊輸入" aria-haspopup="dialog" type="text" inputmode="none" readonly data-min="${legal.min_raise_to}" data-max="${legal.max_raise_to}" value="${legal.min_raise_to}" required><button class="raise-step" type="button" data-raise-step="1" aria-label="增加下注金額" aria-controls="raise-amount">+</button></div><button class="button primary" type="submit">加注</button></div><div class="raise-presets"><button type="button" data-preset="min">最小</button><button type="button" data-preset="half">半池</button><button type="button" data-preset="pot">底池</button><span>每次 ±${num(room.big_blind)}</span></div></form>`:`<p class="raise-hint">${legal.actions.includes('raise')?'籌碼未達最低加注額，可選擇 All-in。':'本輪加注權未重新開放，或對手已全部 All-in。'}</p>`}</div>`;
}

function walletPanel(){const w=lobby?.wallet;if(!w)return '';if(!w.enabled)return '<section class="wallet-panel"><strong>總籌碼制度準備中</strong><p>目前手牌結束後，所有帳號會統一以 3,000 點重新開始；舊戰績保留。</p></section>';return `<section class="wallet-panel" aria-label="我的帳號籌碼"><div class="wallet-main"><span class="wallet-mark" aria-hidden="true">${icon('wallet')}</span><div><span class="wallet-title">我的總資產</span><strong>${num(w.total)}<small>點</small></strong><div class="wallet-breakdown"><span>錢包<b>${num(w.balance)}</b></span><span>桌上與底池<b>${num(w.in_play)}</b></span></div></div></div><div><button class="button gold-button wallet-transfer-link" data-open-bank>銀行存款／借款</button><button class="button ghost wallet-transfer-link" data-open-transfers>${icon('wallet')}點數轉帳／紀錄</button></div><div class="supply-boxes"><div class="daily-box"><span>每日補給 1,000 點 · 台灣時間換日</span><button class="button gold-button" id="daily-claim" ${w.daily_claimed?'disabled':''}>${w.daily_claimed?icon('check')+'今日已領取':'領取今日 1,000 點'}</button></div><div class="daily-box hourly-box"><span>每小時補給 200 點 · 領取後等 60 分鐘</span><button class="button gold-button" id="hourly-claim" ${!w.hourly_available||hourlyPending?'disabled':''}>${hourlyPending?'領取中…':w.hourly_available?'領取每小時 200 點':'補給冷卻中'}</button><small id="hourly-ready-time" role="timer" aria-live="off"></small></div></div></section>`;}
async function claimHourly(){
  if(hourlyPending)return;const uid=me()?.id;hourlyPending=true;hourlyClaimId??=operationId();updateSupplyClock();
  try{const result=await api('/api/wallet/hourly',{operation_id:hourlyClaimId});hourlyClaimId=null;if(me()?.id!==uid)return;lobby.wallet=result.wallet;notice(result.message);await sync(true);}
  catch(error){notice(error.message);}
  finally{hourlyPending=false;updateSupplyClock();}
}
function updateSupplyClock(){
  const count=rewardCount();$$('[data-reward-count]').forEach(b=>{b.hidden=!count;if(b.textContent!==count+' 可領')b.textContent=count+' 可領';});
  const w=lobby?.wallet,button=$('#hourly-claim'),label=$('#hourly-ready-time');if(!w||!button)return;
  const remaining=Math.max(0,Math.ceil((w.hourly_next_at||0)-(Date.now()/1000+clockOffset))),ready=remaining===0;
  button.disabled=hourlyPending||!w.enabled||!ready;const text=hourlyPending?'領取中…':ready?'領取每小時 200 點':'補給冷卻中';if(button.textContent!==text)button.textContent=text;
  const status=ready?'現在可領取；未領不累積':String(Math.floor(remaining/60)).padStart(2,'0')+':'+String(remaining%60).padStart(2,'0')+' 後可再領';if(label&&label.textContent!==status)label.textContent=status;
}
async function claimDaily(){const button=$('#daily-claim');if(button)button.disabled=true;try{const result=await api('/api/wallet/claim',{});lobby.wallet=result.wallet;notice(result.message);await sync(true);}catch(error){notice(error.message);if(button)button.disabled=false;}}
function animateTable(previous,next){
  if(next.game_type&&next.game_type!=='holdem')return;
  if(!previous?.hand||!next.hand||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  for(const p of next.hand.players){const old=previous.hand.players.find(v=>v.user_id===p.user_id);if(!old||old.last_action===p.last_action||!p.last_action)continue;const el=$(`[data-player="${p.user_id}"] .seat-caption`);if(el)el.animate([{transform:'scale(.92)',opacity:.3},{transform:'scale(1.06)',opacity:1},{transform:'scale(1)',opacity:1}],{duration:300,easing:'ease-out'});}
  const pot=$('.pot-total strong');if(pot&&previous.hand.players.reduce((s,p)=>s+p.contribution,0)!==next.hand.players.reduce((s,p)=>s+p.contribution,0))pot.animate([{transform:'scale(1.18)',color:'#fff'},{transform:'scale(1)',color:'#e6bd78'}],{duration:260});
}
function updateRaiseButtons(){const input=$('#raise-amount');if(!input||!room?.legal)return;const value=Number(input.value);$$('[data-raise-step]').forEach(button=>button.disabled=busy||!!pendingOperation||(Number(button.dataset.raiseStep)<0?value<=room.legal.min_raise_to:value>=room.legal.max_raise_to));}
function setRaiseAmount(value){if(!room?.legal||busy||pendingOperation)return;const input=$('#raise-amount');if(!input)return;input.value=Math.max(room.legal.min_raise_to,Math.min(room.legal.max_raise_to,value));updateRaiseButtons();}
function stepRaise(direction){const input=$('#raise-amount');if(input&&room?.legal)setRaiseAmount((Number(input.value)||room.legal.min_raise_to)+direction*room.big_blind);}
function openBetKeypad(){
  if(!room?.legal||busy)return;const turn=room.hand.turn_id,legal={...room.legal};let draft=$('#raise-amount').value;
  dialog(`<section class="bet-keypad"><div class="modal-head"><div><h2 id="modal-title">加注至多少？</h2><p>本回合 ${num(legal.min_raise_to)}–${num(legal.max_raise_to)} 點</p></div>${xButton()}</div><output id="bet-draft" aria-live="polite">${esc(draft)}</output><div class="bet-pad">${['1','2','3','4','5','6','7','8','9','清除','0','刪除'].map(key=>`<button type="button" data-digit="${key}">${key}</button>`).join('')}</div><div class="bet-pad-presets"><button type="button" data-pad-amount="${legal.min_raise_to}">最小</button><button type="button" data-pad-amount="${legal.max_raise_to}">全部籌碼</button></div><p id="bet-pad-error" role="alert"></p><button class="button primary full" id="bet-pad-done">套用金額</button><p class="keypad-note">套用後再按牌桌上的「加注」，才會送出。</p></section>`);
  const update=()=>{$('#bet-draft').textContent=draft||'0';};
  const keys=e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;const key=/^[0-9]$/.test(e.key)?e.key:e.key==='Backspace'?'刪除':e.key==='Delete'?'清除':null;if(key){e.preventDefault();modal.querySelector(`[data-digit="${key}"]`).click();}else if(e.key==='Enter'){e.preventDefault();$('#bet-pad-done').click();}};modal.addEventListener('keydown',keys);modal.addEventListener('close',()=>modal.removeEventListener('keydown',keys),{once:true});
  $$('[data-digit]',modal).forEach(button=>button.onclick=()=>{const key=button.dataset.digit;draft=key==='清除'?'':key==='刪除'?draft.slice(0,-1):(draft==='0'?'':draft)+key;draft=draft.slice(0,10);update();});
  $$('[data-pad-amount]',modal).forEach(button=>button.onclick=()=>{draft=button.dataset.padAmount;update();});
  $('#bet-pad-done').onclick=()=>{if(room?.hand?.turn_id!==turn){$('#bet-pad-error').textContent='回合已更新，請關閉後重新輸入。';return;}const amount=Number(draft);if(!Number.isInteger(amount)||amount<legal.min_raise_to||amount>legal.max_raise_to){$('#bet-pad-error').textContent=`請填寫 ${num(legal.min_raise_to)}–${num(legal.max_raise_to)} 點。`;return;}setRaiseAmount(amount);modal.close();};
}
function feedbackHTML(){
  const f=actionFeedback?.roomId===room?.id?actionFeedback:null;
  return `<div id="action-feedback" class="action-feedback ${f?.error?'error':''}" data-pending="${!!pendingOperation}" role="${f?.error?'alert':'status'}" aria-live="polite" ${['slot','dice','roulette'].includes(room?.game_type)?`data-empty="${!f}" ${room.game_type==='slot'?'data-slot-status="true"':'data-dock-status="true"'}`:f?'':'hidden'}>${f?`<span>${esc(f.text)}</span>${pendingOperation&&!busy?'<button class="button ghost" id="retry-operation">確認原操作</button>':''}`:''}</div>`;
}
function feedback(text,error=false){
  actionFeedback={roomId:room?.id,text,error};
  const el=$('#action-feedback');if(el){el.outerHTML=feedbackHTML();const retry=$('#retry-operation');if(retry)retry.onclick=()=>{if(pendingOperation)command(pendingOperation.action,{},null,pendingOperation);};}
}
function refreshControls(){
  if(!room||!$('#table-controls'))return;
  const funding=$('.playing-funding')||$('.table-funding');if(funding){const fragment=document.createElement('template');fragment.innerHTML=window.ClubArcade.fundingPanel(room,me(),icon);patchNode(funding,fragment.content.firstElementChild);}
  $('#table-controls').innerHTML=actionControls(seated(),room.hand,room.status==='playing',room.hand?.results.find(p=>p.user_id===me().id))+feedbackHTML();
  bindTable();
}
async function command(action,extra={},message,retry=null){
  if(!room)return;
  if(busy){feedback('上一筆操作仍在確認，請稍候。');return;}
  if(pendingOperation&&!retry){feedback('上一筆操作尚未確認，請先按「確認原操作」。',true);return;}
  const op=retry||{action,target:room.id,payload:{revision:room.revision,operation_id:operationId(),...(action==='start'&&room.next_game_settings?{expected_settings_revision:room.next_game_settings.revision,expected_bet_limit_revision:room.next_game_settings.bet_limit_revision}:{}),...extra},message};
  if(action==='action'&&!retry){op.payload.hand_id=extra.hand_id??room.hand.id;op.payload.turn_id=extra.turn_id??room.hand.turn_id;}
  op.sentAt??=Date.now();op.trace=window.ClubFeatures?.beginOperation(action,room.game_type);pendingOperation=op;busy=true;const token=generation;window.ClubRoundPresentation?.begin(room,action,op.payload);
  $$('button',$('#table-controls')||document).forEach(b=>b.disabled=true);
  $$('[data-leave-table],#close-table').forEach(b=>b.disabled=true);
  $$('[data-seat],[data-risk-cell],[data-dice-bet],[data-roulette],[data-big2-card]').forEach(b=>b.disabled=true);
  feedback(retry?'正在確認同一筆操作，不會重複扣籌碼…':'正在確認操作…');window.ClubFeatures?.operationFeedback(op.trace);
  const acknowledgement=new Promise(resolve=>op.resolve=resolve);
  const controllers=[];
  const send=(path,data)=>{const controller=new AbortController();controllers.push(controller);return api(path,data,{controller,trace:data?metric=>window.ClubFeatures?.operationRequest(op.trace,metric):undefined});};
  const verification=setTimeout(async()=>{
    if(pendingOperation!==op||token!==generation)return;
    try{
      const next=await send(`/api/online/rooms/${op.target}`);
      if(token===generation&&pendingOperation===op)applyState(next,false,false);
    }catch{/* Keep the original request and the same receipt on uncertain delivery. */}
  },1200);
  try{
    let result;
    for(let attempt=0;attempt<2;attempt++){
      try{result=await Promise.race([send(`/api/online/rooms/${op.target}/${op.action}`,op.payload),acknowledgement]);break;}
      catch(error){if(attempt===0&&error.retryable){feedback('連線較慢，正在確認同一筆操作…');continue;}throw error;}
    }
    if(token!==generation)return;
    op.completed=true;
    if(result.state)applyState(result.state,false,true,result.delivery||'http');else await sync(true);
    if(pendingOperation===op)pendingOperation=null;
    feedback(op.message||'操作已確認。');
  }catch(error){
    if(!error.retryable&&pendingOperation===op){pendingOperation=null;window.ClubRoundPresentation?.fail(op.payload.operation_id);}
    if(token!==generation)return;
    feedback(error.retryable?'結果尚未確認。請按「確認原操作」，不會重複執行。':error.message,true);
    notice(error.message);
    if(error.status===401){lobby=null;pendingOperation=null;renderAuth();}else await Promise.race([sync(true),acknowledgement]);
  }finally{
    clearTimeout(verification);controllers.forEach(controller=>controller.abort());
    busy=false;
    window.ClubFeatures?.operationFinished(op.trace,token!==generation?'cancelled':pendingOperation===op?'uncertain':'rejected');
    if(token===generation){refreshControls();if(op.completed)finishDeparture(op);}
  }
}
function bindTable(){
  const leave=$('[data-leave-table]');if(leave)leave.disabled=!!(busy||pendingOperation||seated()?.leaving);const close=$('#close-table');if(close)close.disabled=!!(busy||pendingOperation);
  const dock=$('.bet-submit-bar'),status=$('#action-feedback');if(dock&&status&&!dock.contains(status))dock.append(status);
  $('#show-history').onclick=()=>window.ClubFeatures.history();$$('[data-social-toggle]').forEach(b=>b.onclick=()=>window.ClubSocial?.open());
  $$('[data-funding-join]').forEach(b=>b.onclick=()=>openFunding('join'));
  $$('[data-seat]').forEach(b=>b.onclick=()=>openFunding('join',Number(b.dataset.seat)));
  const handlers={
    'join-table':()=>openFunding('join'),
    'deal-hand':()=>command('start',window.ClubBonus.startOptions(room)),
    'rebuy-table':()=>openFunding('rebuy'),
    'return-table':()=>command('return',{},'你已回到牌桌。'),
    'new-after-close':()=>{go('lobby');setTimeout(createRoom,100);},
    'leave-table':async()=>{if(busy||pendingOperation||!seated()||seated().leaving)return;const target=room.id;if(await confirmDialog('確定離開牌桌？',leaveDescription(room,me()),'離桌回大廳','繼續留桌')&&room?.id===target&&!busy&&!pendingOperation&&seated()&&!seated().leaving)await command('leave');},
    'close-table':async()=>{if(busy||pendingOperation)return;const target=room.id;if(await confirmDialog('結束這張牌桌？','所有玩家都會離桌，籌碼依既有規則退回錢包，已完成的紀錄會保留。','結束牌桌','保留牌桌')&&room?.id===target&&room.status==='waiting'&&!busy&&!pendingOperation)await command('close');},
  };
  for(const [id,fn] of Object.entries(handlers)){const b=$('#'+id);if(b)b.onclick=fn;}
  $$('[data-leave-table]').forEach(b=>b.onclick=handlers['leave-table']);
  $$('[data-table-help]').forEach(b=>b.onclick=()=>dialog(`<section class="table-help-dialog"><div class="modal-head"><h2 id="modal-title">${esc(b.getAttribute('aria-label'))}</h2>${xButton()}</div>${$$(`[data-help-source="${b.dataset.tableHelp}"]`).map(source=>source.innerHTML).join('')}</section>`));
  $$('[data-action]').forEach(b=>b.onclick=async()=>{const hand_id=room.hand.id,turn_id=room.hand.turn_id;if(b.dataset.action==='allin'&&!await confirmDialog('這手，全下？',`投入目前剩餘的 ${num(seated().stack)} 虛擬籌碼。`, '確認 All-in'))return;command('action',{action:b.dataset.action,hand_id,turn_id});});
  const form=$('#raise-form');if(form){form.onsubmit=e=>{e.preventDefault();const amount=Number($('#raise-amount').value);if(amount>=room.legal.min_raise_to&&amount<=room.legal.max_raise_to)command('action',{action:'raise',amount,hand_id:room.hand.id});else feedback('加注額超出本回合允許範圍。',true);};$('#raise-amount').onclick=openBetKeypad;$('#raise-amount').onkeydown=e=>{if(['ArrowUp','ArrowRight','ArrowDown','ArrowLeft'].includes(e.key)){e.preventDefault();stepRaise(['ArrowUp','ArrowRight'].includes(e.key)?1:-1);}else if(e.key==='Enter'||e.key===' '){e.preventDefault();openBetKeypad();}};}
  $$('[data-preset]').forEach(b=>b.onclick=()=>{const legal=room.legal,pot=room.hand.players.reduce((n,p)=>n+p.contribution,0),target=b.dataset.preset==='min'?legal.min_raise_to:legal.current_bet+legal.to_call+Math.floor((pot+legal.to_call)*(b.dataset.preset==='half'?.5:1));setRaiseAmount(target);});
  $$('[data-raise-step]').forEach(button=>button.onclick=()=>stepRaise(Number(button.dataset.raiseStep)));updateRaiseButtons();
  const retry=$('#retry-operation');if(retry)retry.onclick=()=>{if(pendingOperation)command(pendingOperation.action,{},null,pendingOperation);};
  if(busy||pendingOperation){$$('.table-funding button').forEach(b=>b.disabled=true);$$('button',$('#table-controls')).forEach(b=>{if(b.id!=='retry-operation')b.disabled=true;});$$('[data-seat]').forEach(b=>b.disabled=true);}
  window.ClubArcade?.bind(room,me(),{command,feedback,busy:busy||!!pendingOperation});
  updateClock();bindFeatures();
}
function showHistory(){if(room.game_type&&room.game_type!=='holdem')return dialog(window.ClubArcade.history(room,{card,close:xButton()}));dialog(`<section><div class="modal-head"><div><span class="small-label">${esc(room.name)}</span><h2 id="modal-title">最近 12 手牌局</h2></div>${xButton()}</div>${room.history.length?room.history.map(h=>`<article class="history-hand"><div class="history-hand-head"><strong>第 ${h.number} 手</strong><span>${new Date(h.finished_at*1000).toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})}</span></div><div class="history-board">${h.board.map(c=>card(c,true)).join('')||'<span class="muted">對手全棄，未發公共牌</span>'}</div>${h.results.map(r=>`<div class="history-result"><span>${esc(r.nickname)}</span><span class="history-holes">${r.hole.map(c=>card(c,true)).join('')}</span><span>${esc(r.rank)}</span><strong class="${tone(r.profit)}">${delta(r.profit)}</strong></div>`).join('')}<div class="side-pots">${h.pots.map((p,i)=>`<span>${p.refund?'退回未跟注':i===0?'主池':'邊池'} ${num(p.amount)} → ${p.winners.map(uid=>esc(h.results.find(r=>r.user_id===uid)?.nickname)).join('、')}</span>`).join('')}</div></article>`).join(''):'<div class="history-empty">第一手結算後，就會出現在這裡。</div>'}</section>`);}

function updateNextHand(){
  const button=$('#deal-hand');if(!button||!room||room.status!=='waiting')return;
  const holdem=room.game_type==='holdem'||!room.game_type,minimum=holdem?1:['big2','mahjong'].includes(room.game_type)?room.required_stack:['slot','mines','tower','dice','inbetween'].includes(room.game_type)?1:room.game_type==='blackjack'?2:room.stake,players=room.seats.filter(s=>!s.away&&!s.leaving&&s.stack>=minimum),own=seated();
  const wait=Math.max(0,Math.ceil((['roulette','slot','mines','tower','dice','inbetween'].includes(room.game_type)?0:room.next_hand_at||0)-(Date.now()/1000+clockOffset))),required=['big2','mahjong'].includes(room.game_type)?4:holdem?2:1;
  button.disabled=!!(busy||pendingOperation||!own||own.away||own.leaving||own.stack<minimum||players.length<required||wait||room.game_type==='blackjack'&&(!window.ClubBonus.validStake(room,me().id)||own.blackjack_ready&&!players.every(s=>s.blackjack_ready)));
  const text=room.game_type==='inbetween'?'發兩張門柱':room.game_type==='slot'?'轉動拉霸':room.game_type==='blackjack'?wait?wait+' 秒後可確認':own?.blackjack_ready&&!players.every(s=>s.blackjack_ready)?'已確認，等待同桌':'確認下注':wait?wait+' 秒後可開局':holdem?(room.hand?'發下一手':'發牌開局'):(room.hand?'開下一局':'開始遊戲');if(button.textContent!==text)button.textContent=text;
}
function updateClock(){updateRecoveryNotice();window.ClubStaff?.tick();window.ClubIncome?.tick(Date.now()/1000+clockOffset);window.ClubFeatures?.refreshDiagnostics();updateSupplyClock();updateNextHand();if(!room?.hand?.deadline||room.status!=='playing')return;const seconds=Math.max(0,Math.ceil(room.hand.deadline-(Date.now()/1000+clockOffset)));const label=$('#turn-time');const text=room.legal?String(seconds):seconds+' 秒';if(label&&label.textContent!==text)label.textContent=text;$$('.seat-clock').forEach(e=>{if(e.value!==seconds)e.value=seconds;e.classList.toggle('urgent',seconds<=8);});}
function connectionLabel(){return ({live:'即時連線',fallback:'備援同步',syncing:'同步中',offline:'網路中斷',paused:'暫停連線'})[connectionMode];}
function setConnection(mode){
  const prior=connectionMode;
  connectionMode=mode===true?(liveReady?'live':'fallback'):mode===false?(navigator.onLine===false?'offline':'syncing'):mode;
  connected=connectionMode==='live'||connectionMode==='fallback';
  if(connected&&['syncing','offline','paused'].includes(prior))recoveredUntil=Date.now()+3500;
  updateRecoveryNotice();
  const el=$('#connection');if(el){el.dataset.mode=connectionMode;el.classList.toggle('offline',!connected);const label=connectionLabel();el.setAttribute('aria-label','連線狀態：'+label+'，查看連線診斷');if(el.textContent!==label)el.innerHTML='<i></i>'+label;}
}
function stateSignature(next){
  const base=[view,next.me,next.total_members,next.betting_limits?.revision];
  const people=()=>next.users.map(u=>[u.id,u.username,u.nickname,u.avatar_key,u.avatar_url,u.profile_revision,u.profit,u.hands,u.total_chips,u.rank,u.cosmetics,view==='members'?next.server_time-u.last_seen<16:null]);
  if(view==='lobby'){const own=next.users.find(u=>u.id===next.me.id);return JSON.stringify([base,next.rooms,next.current_room_id,next.total_hands,next.online_count,next.wallet,next.club?.day,next.club?.missions,own?.profit,own?.hands]);}
  if(view==='clubhouse')return JSON.stringify([base,next.wallet]);
  if(view==='profile')return JSON.stringify([base,next.wallet]);
  if(view==='member')return JSON.stringify([base,next.users.find(u=>u.id===memberId)]);
  if(view==='wallet'||view==='bank')return JSON.stringify([base,next.wallet]);
  if(view==='fishing')return JSON.stringify([base,next.wallet.balance,next.wallet.total,next.wallet.day]);
  if(view==='rewards')return JSON.stringify([base,next.wallet,next.club?.day,next.club?.missions]);
  if(view==='collection')return JSON.stringify([base,next.wallet.balance,next.club]);
  if(view==='members')return JSON.stringify([base,people(),next.invite_code]);
  if(view==='stats')return JSON.stringify([base,people(),next.wallet,next.club?.leaders,next.club?.profit_leaders]);
  return JSON.stringify(base);
}
function applyState(next,force=false,animate=true,delivery='snapshot'){
  if(!lobby)return;const applying=performance.now(),accepted=pendingOperation&&next.accepted_operations?.includes(pendingOperation.payload.operation_id)?pendingOperation:null,trace=accepted?.trace;
  if(!clockSampleAt&&Number.isFinite(next.server_time))clockOffset=next.server_time-Date.now()/1000;
  if(pendingOperation&&next.accepted_operations?.includes(pendingOperation.payload.operation_id)){
    const op=pendingOperation;pendingOperation=null;op.resolve?.({state:next,delivery});
    feedback(op.message||'操作已確認。');
    if(!busy)refreshControls();
  }
  if(view==='table'&&roomId){
    if(next.id!==roomId||room&&room.id===next.id&&next.revision<room.revision)return;
    const changed=force||!room||next.revision!==room.revision||next.next_game_settings?.revision!==room.next_game_settings?.revision||next.next_game_settings?.bet_limit_revision!==room.next_game_settings?.bet_limit_revision||next.wallet?.balance!==room.wallet?.balance||next.wallet?.total!==room.wallet?.total||JSON.stringify(next.appearance_revision)!==JSON.stringify(room.appearance_revision)||JSON.stringify(next.party)!==JSON.stringify(room.party);
    const sameTurn=room?.hand?.id===next.hand?.id&&room?.hand?.actor===next.hand?.actor;
    const input=$('#raise-amount'),draft=sameTurn&&input?{value:input.value,focused:document.activeElement===input}:null;
    const stakeFocus=document.activeElement?.id==='round-stake';
    const previous=room;window.ClubRoundPresentation?.prepare(previous,next,animate);if(changed){window.ClubDealer?.prepare(next.game_type==='holdem'&&animate?previous:null,next);window.ClubArcadeMotion?.prepare(animate?previous:null,next,me().id);window.ClubBonus?.prepare(animate?previous:null,next);}room=next;lobby.current_room_id=next.current_room_id;lobby.wallet=next.wallet;window.ClubSocial?.update(next);
    if(changed){
      lastTurn=room.hand?.actor;if(previous&&$('#table-controls'))renderTableUpdate();else render();animateTable(previous,next);
      const replacement=$('#raise-amount');
      if(draft&&replacement&&Number(draft.value)>=Number(replacement.dataset.min)&&Number(draft.value)<=Number(replacement.dataset.max)){
        replacement.value=draft.value;updateRaiseButtons();if(draft.focused)replacement.focus({preventScroll:true});
      }
      if(stakeFocus&&$('#round-stake'))$('#round-stake').focus({preventScroll:true});
    }else{
      for(const seat of room.seats){const el=$(`[data-player="${seat.user_id}"] .seat-online`);if(el){el.classList.toggle('online',seat.online);el.setAttribute('aria-label',seat.online?'在線':'離線');}}
    }
  }else{
    if(!next.users)return;
    const nextSig=stateSignature(next);
    lobby=next;if(force||nextSig!==signature){signature=nextSig;render();}if(view==='admin')window.ClubAdmin?.refresh();
  }
  markSynchronized(delivery);updateClock();window.ClubFeatures?.operationApplied(trace,applying,delivery);finishDeparture(accepted);
}
function stopLive(retire=true){clearTimeout(streamRetryTimer);streamRetryTimer=null;if(live)live.close();live=null;liveRoomId=null;liveReady=false;if(retire){retireSnapshotRead();retirePresenceRead();}setConnection(document.visibilityState==='visible'?'syncing':'paused');}
async function sendPresence(){
  if(!lobby||credentialsChanging||presencePending||document.visibilityState!=='visible'||navigator.onLine===false)return;
  const read={controller:new AbortController(),retired:false};presenceRead=read;presencePending=true;const token=generation;
  try{const result=await api('/api/online/presence',{room_id:roomId},{controller:read.controller});if(!read.retired&&token===generation&&(result.resumed||Number.isInteger(result.room_revision)&&room&&result.room_revision>room.revision))await sync(true);}catch(error){if(!read.retired&&error.status===401&&token===generation){lobby=null;room=null;generation++;renderAuth();}}finally{if(presenceRead===read){presenceRead=null;presencePending=false;}}
}
function startLive(force=false){
  if(!lobby||credentialsChanging||document.visibilityState!=='visible'||navigator.onLine===false)return;
  if(!force&&live&&liveRoomId===roomId&&live.readyState!==2){void sendPresence();return;}
  stopLive(!force);
  beginRecovery(force?'reconnect':'channel');void sendPresence();
  if(!window.EventSource){recoverSnapshot(true);return;}
  streamClientId??=operationId();
  const uid=me().id,epoch=++liveEpoch,source=new EventSource('/api/online/events?presence=client&client='+streamClientId+(roomId?'&room='+roomId:''));
  source.clubStartedAt=Date.now();source.clubHasState=false;
  live=source;liveRoomId=roomId;lastPush=Date.now();heartbeatProbe=false;
  source.addEventListener('state',event=>{
    if(source!==live||me()?.id!==uid||epoch!==liveEpoch)return;
    try{const next=JSON.parse(event.data);if(roomId?next.id!==roomId:!next.users)return;const animate=liveReady;source.clubHasState=true;liveReady=true;streamRetryCount=0;clearTimeout(streamRetryTimer);streamRetryTimer=null;lastPush=Date.now();heartbeatProbe=false;window.ClubFeatures?.event('state');applyState(next,false,animate,'push');}catch(error){console.error('牌室畫面更新失敗',error);liveInterrupted=true;beginRecovery('state_error');connectionReport('state_error');recoverSnapshot(true);}
  });
  source.addEventListener('ping',()=>{if(source===live&&me()?.id===uid){lastPush=Date.now();heartbeatProbe=false;window.ClubFeatures?.event('ping');if(!liveReady||connectionMode==='fallback')recoverSnapshot();}});
  source.addEventListener('auth',()=>{if(source!==live)return;lobby=null;room=null;generation++;renderAuth();});
  source.onerror=()=>{if(source!==live)return;liveInterrupted=true;beginRecovery('stream_error');connectionReport('stream_error');source.close();live=null;liveRoomId=null;retryLive();recoverSnapshot();};
}
async function sync(force=false){
  if(!lobby||credentialsChanging||document.visibilityState!=='visible'||navigator.onLine===false||(busy&&!force))return;
  if(polling){resync=resync||force;return;}
  const read={controller:new AbortController(),retired:false};snapshotRead=read;polling=true;const token=generation;
  try{
    const next=await api(view==='table'&&roomId?'/api/online/rooms/'+roomId:'/api/online/lobby',undefined,{timeoutMs:5000,controller:read.controller});
    if(!read.retired&&snapshotRead===read&&token===generation)applyState(next,force,liveReady);
  }catch(error){
    if(read.retired||token!==generation)return;setConnection(false);
    if(error.status===401){lobby=null;room=null;renderAuth();}else if(error.status===400&&view==='table'&&!room){notice(error.message);go('lobby');}else if(force)notice(error.message);
  }finally{if(snapshotRead===read){snapshotRead=null;polling=false;if(resync){resync=false;queueMicrotask(()=>sync(true));}}}
}
async function enter(){lobby=await api('/api/online/lobby');if(lobby.me.is_admin&&(lobby.me.password_change_required||!location.hash||location.hash==='#lobby'))location.hash='#admin';else if(lobby.current_room_id&&(!location.hash||location.hash==='#lobby'))location.hash='#table/'+lobby.current_room_id;route();}
async function boot(){try{const info=await api('/api/bootstrap');memberCount=info.member_count;requiresInvite=info.requires_invite;authMode=memberCount===0?'register':'login';try{await enter();}catch(error){if(error.status!==401)throw error;renderAuth();}}catch(error){app.innerHTML=`<main class="connection-error"><h1>暫時連不上牌室</h1><p>${esc(error.message)}</p><button class="button primary" id="retry">重新連線</button></main>`;$('#retry').onclick=boot;}}
window.addEventListener('club:credentials-changing',()=>{credentialsChanging=true;generation++;stopLive();});
window.addEventListener('club:credentials-changed',()=>{credentialsChanging=false;if(lobby)startLive();});
window.addEventListener('hashchange',()=>{if(lobby)route();});
window.addEventListener('offline',()=>pauseConnections('offline'));
window.addEventListener('online',()=>resumeConnections('online'));
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resumeConnections('visible');else pauseConnections('hidden');});
document.addEventListener('freeze',()=>pauseConnections('freeze'));
document.addEventListener('resume',()=>resumeConnections('resume'));
window.addEventListener('pagehide',()=>pauseConnections('pagehide'));
window.addEventListener('pageshow',event=>{if(event.persisted)resumeConnections('pageshow');});
window.addEventListener('focus',()=>{if(!live||live.readyState===2)resumeConnections('focus');else if(!liveReady||Date.now()-lastPush>4000)recoverSnapshot();});
modal.addEventListener('click',e=>{if(e.target!==modal)return;const b=modal.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)modal.close();});
setInterval(checkConnection,1000);
setInterval(updateClock,250);
setInterval(sendPresence,8000);
boot();

function profileView(){return `${heading('我的帳號','')}<div class="view-switch" role="group" aria-label="個人頁面"><button class="button ghost" data-profile-tab="settings" aria-pressed="${profileTab==='settings'}">帳號設定</button><button class="button ghost" data-profile-tab="card" aria-pressed="${profileTab==='card'}">公開名片</button><button class="button ghost" data-profile-tab="wealth" aria-pressed="${profileTab==='wealth'}">資金水位</button></div><div class="profile-edit-panel" ${profileTab!=='settings'?'hidden':''}>${window.ClubProfile.view()}</div><div class="profile-tabs-page" data-profile-panel="${profileTab}" ${profileTab==='settings'?'hidden':''}>${window.ClubMember.view()}</div>`;}
function bindExperience(){
  $$('[data-lobby-jump]').forEach(b=>b.onclick=()=>document.querySelector('#lobby-'+b.dataset.lobbyJump)?.scrollIntoView({block:'start',behavior:'instant'}));
  const filter=$('#room-filter');if(filter)filter.onchange=()=>{roomFilter=filter.value;roomsExpanded=false;render();};
  const more=$('#expand-rooms');if(more)more.onclick=()=>{roomsExpanded=!roomsExpanded;render();};
  $$('[data-rank-mode]').forEach(b=>b.onclick=()=>{rankMode=b.dataset.rankMode;render();});
  const ranks=$('#expand-ranks');if(ranks)ranks.onclick=()=>{ranksExpanded=!ranksExpanded;render();};
  $$('[data-profile-tab]').forEach(b=>b.onclick=()=>{profileTab=b.dataset.profileTab;render();});
  updateRecoveryNotice();
}
function recoveryNotice(){return `<aside id="recovery-notice" class="recovery-notice" role="status" aria-live="polite" aria-atomic="true" ${view!=='table'?'hidden':''}><span data-recovery-text></span><button class="text-button" type="button" data-resync hidden>重新同步</button></aside>`;}
function updateRecoveryNotice(){
  const el=$('#recovery-notice');if(!el)return;el.hidden=view!=='table';
  const pending=!!pendingOperation,slow=Date.now()-(recoveryAttempt?.startedAt||Date.now())>5000;
  const text=pending?'上一筆操作確認中，請稍候':connectionMode==='offline'?'網路中斷，連回網路後會自動同步':['syncing','paused'].includes(connectionMode)?'正在同步牌桌，請稍候':Date.now()<recoveredUntil?'已恢復，牌桌已更新':connectionMode==='fallback'?'備援同步中，牌桌仍會更新':'';
  el.classList.toggle('has-message',!!text);const label=el.querySelector('[data-recovery-text]');if(label.textContent!==text)label.textContent=text;
  const button=el.querySelector('[data-resync]');button.hidden=pending||!slow||connected||navigator.onLine===false;button.onclick=()=>{if(!pendingOperation)resumeConnections('manual_read');};
}

document.addEventListener("club:presentation-change",()=>{if(view==="table"&&room&&lobby)renderTableUpdate();});
