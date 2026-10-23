'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $('#app'), modal = $('#modal');
let state = null, authMode = 'login', memberCount = 0, tab = 'overview', currentGame = null, unit = '筹码';
let busy = false, toastTimer, requiresInvite = false;
const icons = {
  spade: '<path d="M12 2C9 7 3 9 3 14a5 5 0 0 0 8 4l-2 4h6l-2-4a5 5 0 0 0 8-4c0-5-6-7-9-12Z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  people: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3a4 4 0 0 1 0 8"/><circle cx="9" cy="7" r="4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  back: '<path d="m15 5-7 7 7 7"/>',
  logout: '<path d="M9 4H4v16h5m6-12 4 4-4 4m-7-4h11"/>',
  download: '<path d="M12 3v12m-4-4 4 4 4-4M4 15v6h16v-6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/>',
};
function icon(name, cls='') { return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.spade}</svg>`; }
function esc(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function amount(v, signed=false) { return (signed && v>0 ? '+' : v<0 ? '−' : '') + (Math.abs(v)/100).toLocaleString('zh-CN', {maximumFractionDigits:2}); }
function color(v) { return v>0 ? 'positive' : v<0 ? 'negative' : 'neutral'; }
function person(id) { return state.users.find(u=>u.id===id) || state.historical_users?.find(u=>u.id===id) || {id,username:'',nickname:'歷史成員'}; }
function avatar(u, small=false) { return `<span class="avatar tone-${(u.id-1)%6} ${small?'small':''}">${esc(u.nickname.slice(0,1))}</span>`; }
function dateToday() { const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function shortDate(d) { return esc(d.replaceAll('-', '.')); }
function notify(message) { clearTimeout(toastTimer); $('#toast').textContent=message; $('#toast').classList.add('visible'); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),3800); }
async function api(path, data) {
  const r=await fetch(path, data===undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'PokerClub'},body:JSON.stringify(data)});
  const body=await r.json();
  if(!r.ok) { const e=new Error(body.error || '请求失败，请重试。'); e.status=r.status; throw e; }
  return body;
}
async function load() {
  state=await api('/api/state');
  const units=[...new Set(state.games.map(g=>g.unit))];
  if(units.length && !units.includes(unit)) unit=units[0];
}
function errorBox(form, msg) { const el=$('.form-error',form); el.textContent=msg; el.hidden=false; el.focus(); }
function setPending(form, pending) { $$('button[type="submit"]', form).forEach(b=>{b.disabled=pending;}); }
function brand() { return `<div class="brand-mark">${icon('spade')}</div><div><strong>楠團牌室</strong><span>私人牌室</span></div>`; }

function renderAuth() {
  const register=authMode==='register';
  app.innerHTML=`<main class="auth-shell">
    <section class="welcome"><div class="brand light">${brand()}</div><div class="welcome-copy"><span class="eyebrow gold">A SEAT FOR EVERY BROTHER</span><h1>旧账本，<br>每一局都记得。</h1><p>今晚的好牌，明天的谈资。<br>每一次输赢，都记得清清楚楚。</p></div>
    <div class="table-art" aria-hidden="true"><div class="felt"><span class="table-label">THE SIX CLUB<span>EST. 2026 · PRIVATE TABLE</span></span><div class="cards"><b>A<span>♠</span></b><b>K<span>♠</span></b></div></div>${[1,2,3,4,5,6].map(i=>`<i class="seat seat-${i}">0${i}</i>`).join('')}<div class="chip chip-one"></div><div class="chip chip-two"></div></div>
    <div class="welcome-foot"><span>PRIVATE POKER LEDGER</span><span>好兄弟，好好记账。</span></div></section>
    <section class="auth-panel"><div class="auth-content"><span class="eyebrow">YOUR PRIVATE POKER LEDGER</span><h2>${register?'留个名字，准备上桌。':'欢迎回到牌桌。'}</h2><p class="muted">${register?(memberCount===0?(requiresInvite?'输入专属邀请码，创建你们的第一个账号。':'你是第一位成员，注册后即可邀请朋友加入。'):`已有 ${memberCount} 位成员入座，用邀请码加入你们的牌桌。`):'登录你的账号，看看今天手气怎么样。'}</p>
    <div class="auth-tabs" role="tablist" aria-label="账号操作"><button role="tab" aria-selected="${!register}" data-auth="login">登录账号</button><button role="tab" aria-selected="${register}" data-auth="register">创建账号</button></div>
    <form id="auth-form"><div class="form-error" role="alert" tabindex="-1" hidden></div>
    ${register?'<label>你的昵称<input name="nickname" autocomplete="nickname" maxlength="16" placeholder="兄弟们怎么叫你" required></label>':''}
    <label>账号<input name="username" autocomplete="username" minlength="3" maxlength="24" pattern="[A-Za-z0-9_]{3,24}" placeholder="英文字母、数字或底线" required autocapitalize="none" spellcheck="false"></label>
    <label>密码<input type="password" name="password" autocomplete="${register?'new-password':'current-password'}" minlength="8" maxlength="128" placeholder="至少 8 个字元" required></label>
    ${register&&(requiresInvite||memberCount>0)?'<label>室友邀请码<input name="invite_code" maxlength="8" placeholder="输入你们牌桌的 8 位专属邀请码" required autocapitalize="characters" spellcheck="false"></label>':''}
    <button class="button primary full" type="submit">${register?'创建账号，加入牌桌':'登录，回到牌桌'} ${icon('arrow')}</button>
    </form><div class="auth-note"><span class="tiny-spade">♠</span> 独立账号 · 共享牌局账本 · 历史记录保留</div></div>
    <div class="auth-foot">线下尽兴，线上记清。<span>仅记录牌局与筹码输赢</span></div></section></main>`;
  $$('[data-auth]').forEach(b=>b.onclick=()=>{authMode=b.dataset.auth;renderAuth();});
  $('#auth-form').onsubmit=async e=>{
    e.preventDefault(); const form=e.currentTarget; setPending(form,true);
    try { await api(register?'/api/register':'/api/login',Object.fromEntries(new FormData(form))); await load(); render(); }
    catch(ex) { errorBox(form,ex.message); } finally {setPending(form,false);}
  };
}

function stats() {
  const games=state.games.filter(g=>g.status==='settled'&&g.unit===unit);
  const rows=state.users.map(u=>{
    const entries=games.flatMap(g=>g.entries.filter(e=>e.user_id===u.id));
    return {...u, count:entries.length, wins:entries.filter(e=>e.cash_out>e.buy_in).length,
      profit:entries.reduce((s,e)=>s+e.cash_out-e.buy_in,0), buyIn:entries.reduce((s,e)=>s+e.buy_in,0)};
  }).sort((a,b)=>b.profit-a.profit||a.id-b.id);
  return {games,rows, me:rows.find(u=>u.id===state.me.id)};
}
function render() {
  if(!state) return renderAuth();
  const nav=[['overview','grid','牌桌总览'],['history','history','牌局记录'],['members','people','楠團成员']];
  app.innerHTML=`<div class="app-shell"><aside class="sidebar"><a class="brand" href="#" aria-label="楠團牌室首页">${brand()}</a><span class="sidebar-label">CLUBHOUSE</span><nav aria-label="主导航">${nav.map(([id,ic,label])=>`<button data-tab="${id}" class="nav-item ${tab===id&&!currentGame?'selected':''}" ${tab===id&&!currentGame?'aria-current="page"':''}>${icon(ic)}<span>${label}</span>${id==='members'?`<b>${state.users.length} 人</b>`:''}</button>`).join('')}</nav>
    <div class="sidebar-bottom"><div class="club-card"><div class="tiny-label">SIX SEATS. ONE TABLE.</div><div class="mini-suits" aria-hidden="true">♠ <span>♥</span> ♣ <span>♦</span></div><p>牌品见人品，账目要分明。</p></div><div class="account">${avatar(state.me,true)}<div><strong>${esc(state.me.nickname)}</strong><span>@${esc(state.me.username)}</span></div><button class="icon-button" id="logout" aria-label="退出登录" title="退出登录">${icon('logout')}</button></div></div></aside>
    <div class="workspace"><header class="topbar"><span class="breadcrumb"><a class="online-return" href="/">返回線上牌室</a> <i>/</i> ${currentGame?'牌局详情':nav.find(n=>n[0]===tab)[2]}</span><div class="topbar-right"><span class="status-dot"></span><span>${state.users.length} 位成员已入座</span><button class="icon-button" id="refresh" aria-label="刷新牌局" title="刷新">${icon('refresh')}</button><button class="icon-button mobile-logout" id="mobile-logout" aria-label="退出登录" title="退出登录">${icon('logout')}</button></div></header>
    <main id="main" tabindex="-1">${currentGame?gameView():tab==='overview'?overview():tab==='history'?history():members()}</main>
    <footer class="page-footer"><span>楠團牌室 · 每一局都有迹可循</span><span>PRIVATE POKER LEDGER</span></footer></div></div>`;
  $$('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;currentGame=null;render();});
  $('.brand').onclick=e=>{e.preventDefault();tab='overview';currentGame=null;render();};
  const logout=async()=>{
    try {await api('/api/logout',{});state=null;currentGame=null;const info=await api('/api/bootstrap');memberCount=info.member_count;requiresInvite=info.requires_invite;renderAuth();} catch(e){notify(e.message);}
  };
  $('#logout').onclick=logout;
  $('#mobile-logout').onclick=logout;
  $('#refresh').onclick=()=>refresh();
  $$('[data-new]').forEach(b=>b.onclick=newGame);
  $$('[data-game]').forEach(b=>b.onclick=()=>{currentGame=Number(b.dataset.game);render();window.scrollTo(0,0);});
  const selector=$('#unit'); if(selector) selector.onchange=()=>{unit=selector.value;render();};
  const copy=$('#copy-invite'); if(copy) copy.onclick=async()=>{
    try {await navigator.clipboard.writeText(state.invite_code);notify('邀请码已复制。');} catch {notify(`邀请码：${state.invite_code}，长按或选取即可复制。`);}
  };
  if(currentGame) bindGame();
}
function unitSelect() {
  const units=[...new Set(['筹码',...state.games.map(g=>g.unit)])];
  return `<label class="unit-picker">统计单位<select id="unit" aria-label="统计单位">${units.map(u=>`<option ${u===unit?'selected':''}>${esc(u)}</option>`).join('')}</select></label>`;
}
function heading(kicker,title,description,action='') {
  return `<div class="section-heading"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p class="muted">${description}</p></div>${action}</div>`;
}
function overview() {
  const s=stats(), active=state.games.filter(g=>g.status==='active');
  return `${heading('THE CLUB AT A GLANCE','好牌桌，好兄弟。','输赢一目了然，下次继续同桌。',`<button class="button primary" data-new>${icon('plus')} 开一场新牌局</button>`)}
    <section class="hero-card"><div><span class="eyebrow gold">YOUR POKER STORY</span><h2>每一场牌局，<br>都值得好好记。</h2><p>记录买入和带出，剩下的交给账本。</p><span class="hero-caption">历史记录独立保存，线上战绩请返回牌室查看。</span></div><div class="hero-graphic" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="hero-playing-card back-card">K<span>♠</span></div><div class="hero-playing-card front-card">A<span>♠</span><small>THE SIX CLUB</small></div><div class="hero-chip">6</div></div></section>
    <div class="stats-heading"><span class="eyebrow">累计战绩 · 仅计已结算牌局</span>${unitSelect()}</div>
    <section class="stat-grid" aria-label="战绩统计"><article class="stat"><span>我的累计输赢</span><strong class="${color(s.me.profit)}">${amount(s.me.profit,true)}<small>${esc(unit)}</small></strong><p>${s.me.count?`已参与 ${s.me.count} 场 · 赢了 ${s.me.wins} 场`:'你的第一场战绩，等你来写'}</p></article><article class="stat"><span>已结算牌局</span><strong>${s.games.length}<small>场</small></strong><p>每场收支均已核对平衡</p></article><article class="stat"><span>进行中的牌局</span><strong>${active.length.toString().padStart(2,'0')}<small>场</small></strong><p>记录买入，散场后填写带出</p></article></section>
    <div class="dashboard-grid"><section class="panel"><div class="panel-heading"><div><h2>楠團战绩榜</h2><p>手气有起伏，兄弟一直在。</p></div><span class="tag">${esc(unit)}</span></div>${leaderboard(s)}</section>
    <section class="panel"><div class="panel-heading"><div><h2>最近牌局</h2><p>这一桌的故事，接着写。</p></div><button class="text-button" data-tab="history">全部记录 ${icon('arrow')}</button></div>${state.games.length?state.games.slice(0,4).map(gameRow).join(''):empty('history','牌桌还在等你们','两位成员注册后，就能开启第一场牌局。','开第一场牌局')}</section></div>`;
}
function leaderboard(s) {
  const max=Math.max(1,...s.rows.map(r=>Math.abs(r.profit)));
  return `<div class="ranking">${s.rows.map((u,i)=>`<div class="rank-row"><span class="rank-num">${String(i+1).padStart(2,'0')}</span>${avatar(u,true)}<div class="rank-person"><strong>${esc(u.nickname)} ${u.id===state.me.id?'<span class="me-badge">我</span>':''}</strong><span>${u.count} 场 · ${u.count?Math.round(u.wins/u.count*100):0}% 胜率</span></div><div class="rank-score"><strong class="${color(u.profit)}">${amount(u.profit,true)}</strong><div class="bar-track"><svg class="${color(u.profit)}" viewBox="0 0 100 3" preserveAspectRatio="none" aria-hidden="true"><rect width="${Math.round(Math.abs(u.profit)/max*100)}" height="3" rx="1.5" fill="currentColor"/></svg></div></div></div>`).join('')}</div><p class="panel-footnote">不同单位分别统计 · 未结算牌局不计入战绩</p>`;
}
function gameRow(g) {
  const mine=g.entries.find(e=>e.user_id===state.me.id), profit=g.status==='settled'&&mine?mine.cash_out-mine.buy_in:null;
  return `<button class="game-row" data-game="${g.id}"><span class="game-date"><strong>${g.played_on.slice(8)}</strong><small>${g.played_on.slice(5,7)} 月</small></span><span class="game-info"><strong>${esc(g.title)}</strong><span>${g.entries.length} 人 · ${esc(g.unit)} <i>·</i> ${g.status==='active'?'进行中':'已结算'}</span></span><span class="game-result ${profit===null?'neutral':color(profit)}">${profit===null?(g.status==='active'?'<span class="live-badge">待结算</span>':'未参与'):amount(profit,true)}</span>${icon('arrow')}</button>`;
}
function empty(ic,title,desc,button) {return `<div class="empty"><span class="empty-icon">${icon(ic)}</span><h3>${title}</h3><p>${desc}</p>${button?`<button class="button secondary" data-new>${icon('plus')}${button}</button>`:''}</div>`;}
function history() {
  const active=state.games.filter(g=>g.status==='active'), settled=state.games.filter(g=>g.status==='settled');
  return `${heading('EVERY NIGHT, ON RECORD','牌局记录','买入、带出、净输赢，每一笔都查得到。',`<div class="button-group"><a class="button secondary" href="/api/export" download>${icon('download')}导出 CSV</a><button class="button primary" data-new>${icon('plus')}新牌局</button></div>`)}
    <section class="panel history-panel"><div class="panel-heading"><h2>进行中 <span class="count">${active.length}</span></h2><span class="muted">填写后由开局者结算</span></div>${active.length?active.map(gameRow).join(''):empty('spade','现在没有进行中的牌局','下一场好牌，随时开始。')}</section>
    <section class="panel history-panel"><div class="panel-heading"><h2>已结算 <span class="count">${settled.length}</span></h2><span class="muted">右侧显示你的净输赢</span></div>${settled.length?settled.map(gameRow).join(''):empty('history','还没有已结算的牌局','完整填写买入和带出，核对平衡后就会出现在这里。')}</section>`;
}
function members() {
  const s=stats();
  return `${heading('PRIVATE POKER LEDGER','楠團成员','各有账号，共用一本账。历史记录一起保存。',unitSelect())}
    <section class="invite-banner"><div><span class="eyebrow">INVITE YOUR BROTHERS</span><h2>邀请朋友，一起记清每一局。</h2><p>把这个牌桌的网址和邀请码发给室友，打开相同网址后，各自创建账号即可加入。</p></div><div class="invite-code"><span>室友邀请码</span><strong>${esc(state.invite_code)}</strong><button class="text-button" id="copy-invite">复制邀请码</button></div></section>
    <div class="member-grid">${s.rows.sort((a,b)=>a.id-b.id).map(u=>`<article class="panel member-card">${avatar(u)}<h2>${esc(u.nickname)} ${u.id===state.me.id?'<span class="me-badge">我</span>':''}</h2><p class="muted">@${esc(u.username)}</p><div class="member-stat"><div><span>累计输赢 · ${esc(unit)}</span><strong class="${color(u.profit)}">${amount(u.profit,true)}</strong></div><div><span>已玩牌局</span><strong>${u.count}<small> 场</small></strong></div></div></article>`).join('')}${Array.from({length:0},(_,i)=>`<div class="vacant-seat"><span>${String(state.users.length+i+1).padStart(2,'0')}</span><strong>留给下一位兄弟</strong><p>用邀请码注册，即可入座</p></div>`).join('')}</div>`;
}
function openModal(html) { modal.innerHTML=html; modal.showModal(); $('[data-close]',modal).onclick=()=>modal.close(); }
function closeButton(){return `<button type="button" class="icon-button" data-close aria-label="关闭">${icon('close')}</button>`;}
function confirmAction(title, message, actionLabel) {
  return new Promise(resolve=>{
    let accepted=false;
    openModal(`<section><div class="modal-heading"><h2 id="modal-title">${esc(title)}</h2>${closeButton()}</div><p class="muted confirmation-copy">${esc(message)}</p><div class="button-group confirmation-actions"><button type="button" class="button secondary" id="confirm-cancel">再检查一下</button><button type="button" class="button primary" id="confirm-accept">${esc(actionLabel)}</button></div></section>`);
    modal.addEventListener('close',()=>resolve(accepted),{once:true});
    $('#confirm-cancel').onclick=()=>modal.close();
    $('#confirm-accept').onclick=()=>{accepted=true;modal.close();};
  });
}
function newGame() {
  if(state.users.length<2){notify('至少两位成员注册后才能开局，去「楠團成员」取得邀请码。');tab='members';render();return;}
  openModal(`<form id="new-game-form"><div class="modal-heading"><div><span class="eyebrow">DEAL A NEW NIGHT</span><h2 id="modal-title">开一场新牌局</h2></div>${closeButton()}</div><p class="muted">选好兄弟，记下买入，准备发牌。</p><div class="form-error" role="alert" tabindex="-1" hidden></div>
    <label>牌局名称<input name="title" value="今晚的兄弟局" maxlength="60" required></label><div class="form-columns"><label>日期<input type="date" name="played_on" value="${dateToday()}" required></label><label>记账单位<select name="unit"><option>筹码</option><option>NTD</option><option>CNY</option><option>HKD</option><option>USD</option></select></label></div>
    <label>每人初始买入<input name="buy_in" type="number" min="0" max="100000000" step="0.01" inputmode="decimal" value="1000" required><span class="field-hint">统一初始值，后续可分别修改累计买入。</span></label>
    <fieldset><legend>今晚谁上桌？ <span>至少 2 人，包含你自己</span></legend><div class="player-picker">${state.users.map(u=>`<label class="player-option">${avatar(u,true)}<span>${esc(u.nickname)}</span><input type="checkbox" name="player" value="${u.id}" checked ${u.id===state.me.id?'disabled':''}></label>`).join('')}</div></fieldset>
    <label>牌局备注 <span class="optional">选填</span><textarea name="note" maxlength="300" rows="2" placeholder="例如：小盲 5 / 大盲 10，筹码与记账单位 1:1"></textarea></label><div class="modal-actions"><button class="button primary full" type="submit">${icon('plus')} 建立牌局</button></div></form>`);
  $('#new-game-form').onsubmit=async e=>{
    e.preventDefault();const f=e.currentTarget;setPending(f,true);
    const data=Object.fromEntries(new FormData(f));delete data.player;
    data.players=$$('input[name="player"]:checked',f).map(x=>Number(x.value));
    try {const r=await api('/api/games',data);await load();modal.close();currentGame=r.id;render();notify('牌局已建立，祝各位好牌！');}catch(ex){errorBox(f,ex.message);}finally{setPending(f,false);}
  };
}
function gameView() {
  const g=state.games.find(x=>x.id===currentGame);
  if(!g){currentGame=null;return history();}
  const owner=g.creator_id===state.me.id, active=g.status==='active', editable=owner&&active;
  return `<button class="text-button back-button" id="back">${icon('back')}回到牌局记录</button>${heading('AT THE TABLE',esc(g.title),`${shortDate(g.played_on)} <i>·</i> ${g.entries.length} 位玩家 <i>·</i> 开局者：${esc(person(g.creator_id).nickname)}`,`<span class="status-pill ${active?'active':''}">${active?'进行中':'已结算'}</span>`)}
    <section class="panel ledger-panel"><div class="panel-heading"><div><h2>本场记账 <span class="tag">${esc(g.unit)}</span></h2><p>${editable?'买入填写累计投入，带出填写离桌时剩下的金额。':'净输赢 = 带出 − 累计买入。'}</p></div>${!owner?'<span class="tag">由开局者管理</span>':''}</div>
    <form id="ledger-form"><div class="form-error" role="alert" tabindex="-1" hidden></div><div class="ledger-table"><div class="ledger-head"><span>上桌的兄弟</span><span>累计买入</span><span>带出金额</span><span>净输赢</span></div>
    ${g.entries.map(e=>{const u=person(e.user_id);return `<div class="ledger-row" data-user="${u.id}"><div class="ledger-person">${avatar(u,true)}<strong>${esc(u.nickname)}</strong>${u.id===state.me.id?'<span class="me-badge">我</span>':''}</div><div>${editable?`<input aria-label="${esc(u.nickname)}累计买入" class="money-input" name="buy-${u.id}" type="number" inputmode="decimal" step="0.01" min="0" max="100000000" value="${e.buy_in/100}" required>`:`<span>${amount(e.buy_in)}</span>`}</div><div>${editable?`<input aria-label="${esc(u.nickname)}带出金额" class="money-input" name="cash-${u.id}" type="number" inputmode="decimal" step="0.01" min="0" max="100000000" placeholder="待填写" value="${e.cash_out===null?'':e.cash_out/100}">`:`<span>${e.cash_out===null?'待填写':amount(e.cash_out)}</span>`}</div><strong class="row-profit ${e.cash_out===null?'neutral':color(e.cash_out-e.buy_in)}">${e.cash_out===null?'—':amount(e.cash_out-e.buy_in,true)}</strong></div>`;}).join('')}</div>
    <div id="balance" class="balance-box" role="status"></div>${g.note?`<div class="game-note"><strong>牌局备注</strong><p>${esc(g.note)}</p></div>`:''}
    ${editable?`<div class="ledger-actions"><button type="button" class="text-button danger" id="cancel-game">作废此牌局</button><div class="button-group"><button class="button secondary" id="save-game" type="submit">保存记录</button><button class="button primary" id="settle-game" type="button">${icon('check')}核对并结算</button></div></div><p class="panel-footnote">结算时会保存当前输入。总买入须等于总带出，战绩才会计入排行榜。</p>`:owner?'<div class="ledger-actions"><p class="muted">此牌局已计入累计战绩。</p><button type="button" class="button secondary" id="reopen-game">重新编辑</button></div>':'<p class="panel-footnote">所有成员均可查看，由本场开局者保存及结算。</p>'}</form></section>`;
}
function draft(g) {return g.entries.map(e=>({user_id:e.user_id,buy_in:$(`[name="buy-${e.user_id}"]`).value,cash_out:$(`[name="cash-${e.user_id}"]`).value===''?null:$(`[name="cash-${e.user_id}"]`).value}));}
// Convert user decimal input to integer cents before displaying totals.
function inputCents(v) {if(!/^\d+(\.\d{0,2})?$/.test(String(v)))return null;const [a,b='']=String(v).split('.');return Number(a)*100+Number((b+'00').slice(0,2));}
function updateBalance(g) {
  const editable=g.status==='active'&&g.creator_id===state.me.id;
  const values=editable?draft(g):g.entries.map(e=>({...e,buy_in:String(e.buy_in/100),cash_out:e.cash_out===null?null:String(e.cash_out/100)}));
  let totalBuy=0,totalCash=0,missing=0,invalid=false;
  values.forEach(e=>{
    const b=inputCents(e.buy_in),c=e.cash_out===null?null:inputCents(e.cash_out);
    if(b===null||(e.cash_out!==null&&c===null))invalid=true;
    totalBuy+=b||0;totalCash+=c||0;if(e.cash_out===null)missing++;
    const p=$(`[data-user="${e.user_id}"] .row-profit`);
    if(p){const delta=(c||0)-(b||0);p.textContent=c===null||b===null?'—':amount(delta,true);p.className=`row-profit ${c===null||b===null?'neutral':color(delta)}`;}
  });
  const diff=totalCash-totalBuy;
  $('#balance').className=`balance-box ${!invalid&&!missing&&diff===0?'balanced':''}`;
  $('#balance').innerHTML=`<div><span>总买入</span><strong>${amount(totalBuy)}</strong></div><div><span>总带出</span><strong>${amount(totalCash)}</strong></div><div class="balance-status"><span>收支核对</span><strong>${invalid?'请检查金额':missing?`还有 ${missing} 人未填写`:diff===0?`${icon('check')}收支平衡`:`差额 ${amount(diff,true)}`}</strong></div>`;
}
function bindGame() {
  const g=state.games.find(x=>x.id===currentGame);if(!g)return;
  $('#back').onclick=()=>{currentGame=null;tab='history';render();};
  updateBalance(g);$$('.money-input').forEach(i=>i.oninput=()=>updateBalance(g));
  const f=$('#ledger-form');
  async function save(settle=false) {
    if(busy||!f.reportValidity())return;
    if(settle && !await confirmAction('核对并结算','确认本场买入和带出都正确？结算后将计入累计战绩。','确认结算'))return;
    busy=true;$$('button',f).forEach(b=>b.disabled=true);
    let revision=g.revision;
    try {
      await api(`/api/games/${g.id}/entries`,{revision,entries:draft(g)});
      revision++;g.revision=revision;
      if(settle)await api(`/api/games/${g.id}/settle`,{revision});
      await load();render();notify(settle?'牌局已结算，战绩已更新。':'记录已保存。');
    }catch(ex){errorBox(f,ex.message);}finally{busy=false;$$('button',f).forEach(b=>b.disabled=false);}
  }
  f.onsubmit=e=>{e.preventDefault();save();};
  const settle=$('#settle-game');if(settle)settle.onclick=()=>save(true);
  for(const [id,action,message] of [['cancel-game','cancel','确认作废这场牌局？作废后会从牌局列表移除。'],['reopen-game','reopen','重新编辑期间，本场输赢会暂时从累计战绩移除。确认重新编辑？']]) {
    const b=$('#'+id);if(b)b.onclick=async()=>{
      if(busy||!await confirmAction(action==='cancel'?'作废此牌局':'重新编辑牌局',message,action==='cancel'?'确认作废':'重新编辑'))return;busy=true;b.disabled=true;
      try {await api(`/api/games/${g.id}/${action}`,{revision:g.revision});await load();if(action==='cancel'){currentGame=null;tab='history';}render();notify(action==='cancel'?'牌局已作废。':'已重新打开牌局，可修改后再结算。');}catch(e){errorBox(f,e.message);}finally{busy=false;b.disabled=false;}
    };
  }
}
async function refresh() {if(busy)return;try {await load();render();notify('牌局已更新。');}catch(e){notify(e.message);if(e.status===401){state=null;renderAuth();}}}
modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close();}});
async function boot() {
  try {const info=await api('/api/bootstrap');memberCount=info.member_count;requiresInvite=info.requires_invite;authMode=memberCount===0?'register':'login';try {await load();}catch(e){if(e.status!==401)throw e;}render();}
  catch(e){app.innerHTML=`<main class="connection-error"><h1>暂时连不上牌桌</h1><p>${esc(e.message)}</p><p>请确认服务仍在运行，然后刷新页面。</p><button class="button primary" id="retry">重新连接</button></main>`;$('#retry').onclick=boot;}
}
// Only refresh read-only views. Never replace an in-progress ledger or registration form.
setInterval(async()=>{if(state&&!currentGame&&!modal.open&&!busy&&document.visibilityState==='visible'&&document.hasFocus()){try{await load();render();}catch{}}},20000);
boot();
