'use strict';
window.ClubAdmin=(()=>{
  let root=null,user=null,data=null,search='',page=1,section='accounts',loading=false,again=false,searchTimer=null,token=0,signature='';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=n=>Number(n||0).toLocaleString('zh-TW');
  const dialog=document.createElement('dialog');dialog.id='admin-modal';dialog.setAttribute('aria-label','調整虛擬籌碼');document.body.append(dialog);
  const q=s=>root?.querySelector(s),d=s=>dialog.querySelector(s);
  async function api(path,payload){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{const response=await fetch(path,{signal:controller.signal,cache:'no-store',...(payload?{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'PokerClub'},body:JSON.stringify(payload)}:{})});const result=await response.json();if(!response.ok){const error=new Error(result.error||'管理功能暫時無法使用。');error.retryable=response.status>=500;throw error;}return result;
    }catch(error){if(error.name==='AbortError'||error instanceof TypeError||error instanceof SyntaxError){const e=new Error('連線結果未確認，請再確認同一筆操作。');e.retryable=true;throw e;}throw error;}finally{clearTimeout(timeout);}
  }
  function passwordForm(){
    root.innerHTML=`<section class="panel admin-password"><h2>${user.password_change_required?'首次登入，請設定你的密碼。':'更換管理員密碼'}</h2><p>管理員密碼至少 12 個字元。更換後，其他分頁的登入會失效。</p><form id="admin-password-form"><label>目前密碼<input name="current_password" type="password" autocomplete="current-password" required maxlength="128"></label><label>新密碼<input name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><label>再次輸入新密碼<input name="confirm_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><p class="form-error" role="alert" hidden></p><button class="button primary" type="submit">儲存新密碼</button>${!user.password_change_required?'<button class="button ghost" type="button" id="cancel-password">取消</button>':''}</form></section>`;
    q('#cancel-password')?.addEventListener('click',renderShell);
    q('form').onsubmit=async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget)),error=q('.form-error'),button=q('[type="submit"]');error.hidden=true;
      if(values.new_password!==values.confirm_password){error.textContent='兩次新密碼不一致，請重新確認。';error.hidden=false;return;}button.disabled=true;button.textContent='正在儲存…';
      window.dispatchEvent(new Event('club:credentials-changing'));
      try{await api('/api/admin/password',values);if(!root)return;user={...user,password_change_required:false};renderShell();}
      catch(e){if(error.isConnected){error.textContent=e.message+(e.retryable?' 若已變更成功，請以新密碼重新登入。':'');error.hidden=false;}}
      finally{window.dispatchEvent(new Event('club:credentials-changed'));button.disabled=false;button.textContent='儲存新密碼';}
    };
  }
  function renderShell(){
    if(!root)return;if(user.password_change_required)return passwordForm();
    root.innerHTML=`<div class="view-switch" role="group" aria-label="後台分區">${[['accounts','帳號管理'],['settings','遊戲設定'],['history','管理紀錄']].map(([key,label])=>`<button class="button ghost" data-admin-section="${key}" aria-pressed="${section===key}">${label}</button>`).join('')}</div><div class="admin-summary" id="admin-summary"></div><section class="panel game-settings-panel" id="game-settings-console" data-admin-panel="settings"></section><section class="panel" data-admin-panel="accounts"><div class="admin-toolbar"><label><span class="sr-only">搜尋全部帳號</span><input id="admin-search" type="search" maxlength="80" placeholder="搜尋暱稱或帳號" value="${esc(search)}"></label><button class="button ghost" id="admin-refresh">重新整理</button><button class="button ghost" id="admin-change-password">更換密碼</button></div><p class="admin-status" id="admin-status" role="status">讀取帳號狀態中…</p><div class="admin-accounts" id="admin-accounts"></div><div class="admin-pages"><button class="button ghost" id="admin-prev">上一頁</button><span id="admin-page"></span><button class="button ghost" id="admin-next">下一頁</button></div></section><section class="panel admin-ledger" data-admin-panel="history"><div class="panel-title"><h2>籌碼調整紀錄</h2><span>最近 50 筆 · 每筆保留管理員與備註</span></div><div id="admin-history"></div></section>`;
    root.querySelectorAll('[data-admin-section]').forEach(b=>b.onclick=()=>{section=b.dataset.adminSection;showSection();});showSection();
    q('#admin-search').oninput=e=>{search=e.target.value;page=1;clearTimeout(searchTimer);searchTimer=setTimeout(refresh,250);};q('#admin-refresh').onclick=refresh;q('#admin-change-password').onclick=passwordForm;
    q('#admin-prev').onclick=()=>{if(page>1){page--;refresh();}};q('#admin-next').onclick=()=>{if(page*50<data?.total_matches){page++;refresh();}};
    root.onclick=e=>{const action=e.target.closest('[data-account-action]');if(action){const account=data?.accounts.find(p=>p.id===Number(action.dataset.accountId));if(account)accountForm(account,action.dataset.accountAction);return;}const button=e.target.closest('[data-admin-grant]');if(button){const account=data?.accounts.find(p=>p.id===Number(button.dataset.adminGrant));if(account)grantForm(account);}};signature='';refresh();window.ClubGameSettings?.mount(q('#game-settings-console'));
  }
  async function refresh(){
    if(!root||user.password_change_required||!q('#admin-accounts'))return;if(loading){again=true;return;}loading=true;const generation=token,requested=search,requestedPage=page;
    try{const next=await api(`/api/admin/accounts?search=${encodeURIComponent(search)}&page=${page}`);if(generation!==token||!root||requested!==search||requestedPage!==page)return;data=next;paint();}
    catch(error){const status=q('#admin-status');if(status)status.textContent=error.message;}
    finally{loading=false;if(again){again=false;refresh();}}
  }
  function paint(){
    if(!q('#admin-accounts'))return;const nextSignature=JSON.stringify([data.accounts.map(a=>({...a,last_seen:0})),data.history,data.account_history,data.total_matches,page]);
    q('#admin-summary').innerHTML=`<div><span>註冊帳號</span><strong>${num(data.total_accounts)}</strong></div><div><span>目前在線</span><strong>${num(data.online_accounts)}</strong></div><div><span>全站總籌碼</span><strong>${num(data.total_chips)}</strong></div>`;
    q('#admin-status').textContent=`符合 ${num(data.total_matches)} 個帳號 · 狀態即時同步`;q('#admin-page').textContent=`第 ${page} / ${Math.max(1,Math.ceil(data.total_matches/50))} 頁`;q('#admin-prev').disabled=page===1;q('#admin-next').disabled=page*50>=data.total_matches;
    if(nextSignature===signature)return;signature=nextSignature;
    q('#admin-accounts').innerHTML=data.accounts.length?data.accounts.map(a=>`<article class="admin-account"><header><div><h3>${esc(a.nickname)}${a.is_admin?'<span class="me-tag">管理員</span>':''}</h3><p>@${esc(a.username)}</p></div><span class="status-chip status-${esc(a.status)}">${({active:'正常',blocked:'已封鎖',deleted:'已刪除'})[a.status]||'正常'}${a.status==='active'&&a.online?' · 在線':''}</span></header><dl><div><dt>錢包</dt><dd>${num(a.balance)}</dd></div><div><dt>桌上與底池</dt><dd>${num(a.in_play)}</dd></div><div><dt>總籌碼</dt><dd class="wallet-total">${num(a.total)}</dd></div></dl><p class="admin-room">${a.room?`<a href="#table/${a.room.id}">${esc(a.room.name)} · ${a.room.seat} 號位</a> · ${a.room.leaving?'本手後離桌':a.room.away?'暫離':a.room.status==='playing'?'對局中':'等待發牌'}`:'目前未入座'}</p>${a.status_reason?`<p class="admin-account-reason">處理原因：${esc(a.status_reason)}</p>`:''}<footer><span>註冊 ${new Date(a.created_at).toLocaleDateString('zh-TW')}</span><div class="admin-account-actions">${a.status!=='deleted'?`<button class="button gold-button" data-admin-grant="${a.id}">調整籌碼</button>`:''}${!a.is_admin&&a.status!=='deleted'?`<button class="button ghost" data-account-action="${a.status==='blocked'?'unblock':'block'}" data-account-id="${a.id}">${a.status==='blocked'?'解除封鎖':'封鎖帳號'}</button><button class="button ghost account-delete" data-account-action="delete" data-account-id="${a.id}">刪除帳號</button>`:''}</div></footer></article>`).join(''):'<p class="admin-empty">找不到符合的帳號，試試其他暱稱或帳號。</p>';
    q('#admin-history').innerHTML=data.history.length?data.history.map(g=>`<article class="admin-grant-row"><div><strong>${esc(g.target)}</strong><span>@${esc(g.target_username)}</span><p>${esc(g.note)}</p><small>${esc(g.actor)} ${g.amount<0?'扣除':'增加'} · ${new Date(g.created_at*1000).toLocaleString('zh-TW')}</small></div><b class="${g.amount<0?'loss':'win'}">${g.amount<0?'−':'+'}${num(Math.abs(g.amount))}</b></article>`).join(''):'<p class="admin-empty">目前沒有管理員調整紀錄。</p>';
    let log=q('#admin-account-history');if(!log){log=document.createElement('section');log.id='admin-account-history';log.className='panel admin-account-log';log.dataset.adminPanel='history';root.append(log);}
    showSection();log.innerHTML='<h2>帳號管理紀錄</h2>'+((data.account_history||[]).map(e=>`<article><strong>${({block:'封鎖',unblock:'解除封鎖',delete:'刪除'})[e.action]} @${esc(e.username_snapshot)}</strong><p>${esc(e.reason)}</p><small>@${esc(e.actor_username)} · ${new Date(e.created_at*1000).toLocaleString('zh-TW')}</small></article>`).join('')||'<p>目前沒有帳號管理紀錄。</p>');
  }
  function showSection(){if(!root)return;root.querySelectorAll('[data-admin-panel]').forEach(p=>p.hidden=p.dataset.adminPanel!==section);root.querySelectorAll('[data-admin-section]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.adminSection===section)));}
  function accountForm(account,action){
    const title=({block:'封鎖帳號',unblock:'解除封鎖',delete:'刪除帳號'})[action],operation=crypto.randomUUID().replaceAll('-','');let pending=null,sending=false;
    dialog.setAttribute('aria-label',title);dialog.innerHTML=`<form id="admin-account-form"><div class="modal-head"><h2>${title}</h2><button class="icon-button" type="button" data-cancel-account aria-label="關閉視窗">×</button></div><p class="dialog-subtitle">${esc(account.nickname)} · @${esc(account.username)}</p><p class="profile-help">${action==='delete'?'刪除會永久停用帳號、清除暱稱與照片；交易、籌碼和戰績保留供稽核。':action==='block'?'會登出此帳號的所有裝置，並安排牌局結算離桌。':'解除後此帳號可以重新登入，牌局與籌碼保留。'}</p><div class="form-error" role="alert" tabindex="-1" hidden></div><label>處理原因<input name="reason" maxlength="200" required autocomplete="off"></label>${action==='delete'?`<label>輸入帳號 ${esc(account.username)} 確認刪除<input name="confirm_username" autocomplete="off" required autocapitalize="none" spellcheck="false" aria-describedby="delete-account-note"></label><p id="delete-account-note" class="profile-help">此操作無法由解除封鎖還原。</p>`:''}<div class="dialog-actions"><button class="button ghost" type="button" data-cancel-account>取消</button><button class="button primary ${action==='delete'?'account-delete':''}" type="submit">確認${title}</button></div></form>`;
    dialog.querySelectorAll('[data-cancel-account]').forEach(b=>b.onclick=()=>{if(!sending)dialog.close();});dialog.showModal();d('[name="reason"]').focus();
    d('form').onsubmit=async e=>{e.preventDefault();if(sending)return;const form=e.currentTarget,values=Object.fromEntries(new FormData(form)),error=d('[role="alert"]'),button=d('[type="submit"]');error.hidden=true;
      if(!pending&&action==='delete'&&values.confirm_username!==account.username){error.textContent='請輸入完全相同的帳號。';error.hidden=false;error.focus();return;}
      pending||={user_id:account.id,action,reason:values.reason,confirm_username:values.confirm_username,state_revision:account.state_revision,operation_id:operation};sending=true;button.disabled=true;button.textContent='正在處理…';form.querySelectorAll('input').forEach(el=>el.readOnly=true);
      try{await api('/api/admin/account-action',pending);dialog.close();refresh();}
      catch(e){error.textContent=e.message;error.hidden=false;error.focus();if(!e.retryable)pending=null;}
      finally{sending=false;button.disabled=false;button.textContent=pending?'確認處理結果':'確認'+title;form.querySelectorAll('input').forEach(el=>el.readOnly=!!pending);}
    };
  }
  function grantForm(account){
    const operation=Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');let pending=null;
    dialog.innerHTML=`<form id="admin-grant-form"><div class="modal-head"><h2>調整虛擬籌碼</h2><button class="icon-button" type="button" id="close-admin-grant" aria-label="關閉調整視窗"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button></div><p class="dialog-subtitle">對象：${esc(account.nickname)}（@${esc(account.username)}）<br>錢包 ${num(account.balance)} 點 · 桌上與底池 ${num(account.in_play)} 點</p><label>調整方式<select name="direction"><option value="1">增加籌碼</option><option value="-1">扣除籌碼</option></select></label><label>調整點數<input name="amount" type="number" inputmode="numeric" min="1" max="1000000" step="1" value="1000" required aria-describedby="admin-adjust-preview"></label><p id="admin-adjust-preview" class="dialog-subtitle" role="status"></p><label>調整備註<input name="note" type="text" maxlength="200" placeholder="例如：活動獎勵、點數修正" required></label><p class="form-error" role="alert" hidden></p><div class="dialog-actions"><button class="button ghost" type="button" id="cancel-admin-grant">取消</button><button class="button primary" type="submit">確認增加</button></div></form>`;
    dialog.showModal();d('#close-admin-grant').onclick=d('#cancel-admin-grant').onclick=()=>dialog.close();
    const direction=d('[name="direction"]'),amount=d('[name="amount"]'),note=d('[name="note"]'),submit=d('[type="submit"]');let sending=false;
    function preview(){
      const deduct=direction.value==='-1',value=Number(amount.value),limit=deduct?Math.min(account.balance,1000000):1000000,valid=Number.isInteger(value)&&value>0&&value<=limit;
      amount.max=String(Math.max(0,limit));submit.classList.toggle('admin-deduct',deduct);submit.textContent=pending?'確認這筆調整':`確認${deduct?'扣除':'增加'}${valid?' '+num(value)+' 點':''}`;submit.disabled=sending||(!pending&&!valid);
      d('#admin-adjust-preview').textContent=deduct&&value>account.balance?`錢包最多可扣 ${num(account.balance)} 點；桌上與底池籌碼需先離桌取回。`:valid?`預估調整後錢包：${num(account.balance+Number(direction.value)*value)} 點。${deduct?'只扣錢包，不動用桌上與底池籌碼。':''}`:'每次請輸入 1–1,000,000 點整數。';
    }
    direction.onchange=()=>{if(direction.value==='-1'&&Number(amount.value)>account.balance)amount.value=account.balance>0?Math.min(account.balance,1000000):'';preview();};amount.oninput=preview;preview();
    d('form').onsubmit=async e=>{e.preventDefault();if(sending)return;const values=Object.fromEntries(new FormData(e.currentTarget)),error=d('.form-error'),button=d('[type="submit"]');error.hidden=true;const payload=pending||{user_id:account.id,amount:Number(values.amount),note:values.note,operation_id:operation};button.disabled=true;
      if(!pending)payload.amount*=Number(values.direction);sending=true;direction.disabled=true;amount.readOnly=true;note.readOnly=true;button.textContent=pending?'確認調整結果…':'調整中…';
      try{await api('/api/admin/adjustments',payload);dialog.close();refresh();}
      catch(e){error.textContent=e.message;error.hidden=false;if(e.retryable)pending=payload;}
      finally{sending=false;direction.disabled=!!pending;amount.readOnly=!!pending;note.readOnly=!!pending;preview();}
    };
  }
  function unmount(){window.ClubGameSettings?.unmount();token++;root=null;user=null;data=null;signature='';clearTimeout(searchTimer);if(dialog.open)dialog.close();}
  function mount(identity){const element=document.querySelector('#admin-console');if(!element||!identity?.is_admin)return;if(root===element)return;unmount();root=element;user=identity;renderShell();}
  return {mount,refresh,unmount};
})();
