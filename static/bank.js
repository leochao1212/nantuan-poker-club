'use strict';
window.ClubBank=(()=>{
 const num=v=>Number(v||0).toLocaleString('zh-TW'),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={deposit:'存入',withdraw:'提款',collect:'領取利息',borrow:'借款',repay:'還款'};
 const percent=bps=>(bps/100).toLocaleString('zh-TW',{maximumFractionDigits:2})+'%';
 let host=null,ctx=null,uid=null,state=null,operation=null,sending=false,reading=false,epoch=0,timer=0,action='deposit',reviewing=false,repayAll=false,loanQuote=null,lastBalance=null;
 const q=s=>host?.querySelector(s),key=()=>`nantuan-bank:${uid}`;
 function view(){return '<section id="bank-console" aria-label="楠團銀行"></section>';}
 function message(text,bad=false){const e=q('[data-bank-message]');if(e){e.textContent=text;e.classList.toggle('error',bad);e.setAttribute('role',bad?'alert':'status');}}
 function clear(){operation=null;try{sessionStorage.removeItem(key());}catch{}}
 function save(){sessionStorage.setItem(key(),JSON.stringify(operation));}
 function status(){
  if(!host)return;const pending=sending||!!operation;
  q('fieldset').disabled=pending||!state;
  const unavailable=state&&(action==='deposit'&&ctx.wallet.balance<1||action==='withdraw'&&state.savings<1||action==='borrow'&&(!!state.loan||state.settings.loan_limit<1)||action==='repay'&&!state.loan);
  q('[data-bank-submit]').disabled=sending||!state||!operation&&!!unavailable;
  q('[data-bank-submit]').textContent=sending?'正在確認…':operation?'確認原操作':reviewing?'確認借入 '+num(q('[name=amount]').value)+' 點':labels[action];
  q('[data-bank-collect]').disabled=pending||!state||state.interest<1;
  q('[data-bank-cancel]').hidden=!reviewing||!!operation;
  q('[data-bank-review]').hidden=!reviewing;
  q('[data-bank-amount-label]').textContent=labels[action]+'點數';
  host.querySelectorAll('[data-bank-action]').forEach(b=>{b.disabled=pending;b.setAttribute('aria-pressed',String(b.dataset.bankAction===action));});
 }
 function paint(){
  if(!host||!state)return;
  const text=(s,v)=>{const e=q(s);if(e&&e.textContent!==v)e.textContent=v;},loan=state.loan,p=state.settings;
  text('[data-bank-cash]',num(ctx.wallet.balance));text('[data-bank-savings]',num(state.savings));text('[data-bank-interest]',num(state.interest));
  text('[data-bank-saving-rate]',percent(p.deposit_bps)+'／日');text('[data-bank-loan-rate]',percent(p.loan_bps)+'／日');
  text('[data-bank-debt]',num(loan?.total_due));text('[data-bank-net]',num(ctx.wallet.total));
  text('[data-bank-loan-info]',loan?`本金 ${num(loan.principal)} ＋ 利息 ${num(loan.interest)} 點 · 日息 ${percent(loan.rate_bps)} · ${new Date(loan.due_at*1000).toLocaleDateString('zh-TW')} 到期${loan.overdue?' · 已逾期，請還款':''}`:`可借上限 ${num(p.loan_limit)} 點 · ${p.loan_days} 天到期 · 同時一筆貸款`);
  q('[data-bank-loan-info]').classList.toggle('loss',!!loan?.overdue);
  const available=action==='deposit'?ctx.wallet.balance:action==='withdraw'?state.savings:action==='borrow'?(loan?0:p.loan_limit):Math.min(ctx.wallet.balance,loan?.total_due||0);
  const cap=action==='repay'?2_000_000:1_000_000;q('[name=amount]').max=Math.max(1,Math.min(cap,available));
  text('[data-bank-available]',repayAll?'全部還清：依伺服器收到還款時的欠款結清':action==='borrow'&&loan?'請先還清現有貸款':`本次最多可${labels[action]} ${num(Math.min(cap,available))} 點`);
  const history=q('[data-bank-history]'),signature=JSON.stringify(state.history);
  if(history.dataset.signature!==signature){history.dataset.signature=signature;history.innerHTML=state.history.length?state.history.map(r=>`<li><span><strong>${labels[r.kind]||esc(r.kind)}</strong><small>${new Date(r.created_at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})} · #${r.id}</small></span><b>${num(r.amount)} 點</b></li>`).join(''):'<li>尚無銀行交易</li>';}
  q('[data-bank-more]').hidden=!state.next_before;status();
 }
 async function read(more=false){
  if(!host||reading)return;reading=true;const token=epoch,owner=uid;
  try{const r=await ctx.api('/api/bank'+(more&&state?.next_before?'?before='+state.next_before:''));if(token!==epoch||uid!==owner||!host)return;
   if(state&&r.bank.server_time<state.server_time)return;
   if(more)r.bank.history=[...state.history,...r.bank.history.filter(n=>!state.history.some(o=>o.id===n.id))];
   state=r.bank;ctx.wallet=r.wallet;lastBalance=r.wallet.balance;paint();ctx.updated?.(r,owner);
  }catch(e){if(token===epoch)message(e.message,true);}finally{if(token===epoch)reading=false;}
 }
 async function perform(kind,payload){
  if(sending||!host||!state)return;
  if(!operation){operation={action:kind,data:{...payload,operation_id:crypto.randomUUID()}};try{save();}catch{operation=null;message('無法保存操作回執，請允許網站儲存資料後再試。',true);return;}}
  const request=operation,owner=uid;sending=true;status();message('正在確認'+labels[request.action]+'…');
  try{const result=await ctx.api('/api/bank/'+request.action,request.data);if(uid!==owner)return;clear();reviewing=false;repayAll=false;state=result.bank;ctx.wallet=result.wallet;lastBalance=result.wallet.balance;paint();message((result.replayed?'原操作已確認：':'已完成：')+labels[result.action]+' '+num(result.amount)+' 點');ctx.updated?.(result,owner);
  }catch(e){if(uid!==owner)return;if(!e.retryable){clear();reviewing=false;}message(e.retryable?'結果尚未確認。請按「確認原操作」，不會重複扣點或重複借款。':e.message,true);
  }finally{if(uid===owner){sending=false;status();}}
 }
 function submit(e){
  e.preventDefault();if(operation)return void perform(operation.action,operation.data);if(!state||sending)return;
  const amount=Number(q('[name=amount]').value),max=Number(q('[name=amount]').max);
  if(!Number.isSafeInteger(amount)||amount<1||amount>max){message('請填寫可用額度內的整數點數。',true);return;}
  if(action==='borrow'&&!reviewing){reviewing=true;const p=state.settings,totalInterest=Math.ceil(amount*p.loan_bps*p.loan_days/10000);
   loanQuote={amount,revision:p.revision};
   q('[data-bank-review]').textContent=`借入 ${num(amount)} 點，日息 ${percent(p.loan_bps)}、${p.loan_days} 天到期。若到期一次還清，約需還 ${num(amount+totalInterest)} 點；可提前還款，依未還本金計息。`;status();q('[data-bank-review]').focus();return;
  }
  void perform(action,{amount,...(action==='repay'?{loan_id:state.loan?.id,...(repayAll?{pay_all:true}:{})}:{}),...(action==='borrow'?{expected_revision:loanQuote.revision}:{})});
 }
 function unmount(){clearInterval(timer);timer=0;host=null;epoch++;reading=false;}
 function mount(context){
  const element=document.querySelector('#bank-console');if(!element)return;
  if(uid!==context.user.id){uid=context.user.id;clearInterval(timer);state=null;operation=null;sending=false;reviewing=false;repayAll=false;loanQuote=null;action='deposit';epoch++;
   try{const saved=JSON.parse(sessionStorage.getItem(key())||'null');if(saved&&labels[saved.action]&&typeof saved.data?.operation_id==='string'){operation=saved;action=saved.action==='collect'?'deposit':saved.action;}}catch{}
  }
  ctx=context;host=element;
  if(host.dataset.owner===String(uid)){if(lastBalance!==ctx.wallet.balance&&!sending&&!operation)void read();paint();return;}
  host.dataset.owner=String(uid);epoch++;reading=false;
  host.innerHTML=`<div class="bank-hero"><div><span class="small-label">楠團銀行 · 虛擬點數</span><h2>存款生息，隨時存提。</h2><p>存款日息 <b data-bank-saving-rate>—</b>，隨時存提。</p></div><a href="#wallet" class="button ghost">玩家轉帳與紀錄 →</a></div><div class="bank-overview"><article class="panel"><span>錢包可用</span><strong><b data-bank-cash>—</b><small>點</small></strong></article><article class="panel bank-vault"><span>銀行存款</span><strong><b data-bank-savings>—</b><small>點</small></strong><span>待領利息 <b data-bank-interest>0</b> 點</span><button class="button gold-button" data-bank-collect disabled>領取利息</button></article><article class="panel"><span>貸款待還</span><strong><b data-bank-debt>—</b><small>點</small></strong><p data-bank-loan-info></p></article></div><div class="bank-layout"><section class="panel bank-compose"><h2>點數櫃台</h2><div class="bank-tabs" role="group" aria-label="銀行操作">${['deposit','withdraw','borrow','repay'].map(k=>`<button class="button ghost" type="button" data-bank-action="${k}" aria-pressed="${action===k}">${labels[k]}</button>`).join('')}</div><form data-bank-form><fieldset disabled><legend class="sr-only">銀行交易點數</legend><label for="bank-amount" data-bank-amount-label>存入點數</label><div class="bank-stepper"><button class="button ghost" type="button" data-bank-step="-100" aria-label="減少 100 點">−</button><input id="bank-amount" name="amount" type="number" inputmode="numeric" min="1" max="1000000" step="1" value="1000" required><button class="button ghost" type="button" data-bank-step="100" aria-label="增加 100 點">＋</button></div><div class="bank-presets">${[100,1000,3000].map(v=>`<button class="button ghost" type="button" data-bank-preset="${v}">${num(v)}</button>`).join('')}<button class="button ghost" type="button" data-bank-all>全部</button></div><p data-bank-available></p></fieldset><p class="bank-review" data-bank-review tabindex="-1" hidden></p><div class="bank-submit"><button class="button primary" data-bank-submit type="submit" disabled>存入</button><button class="button ghost" data-bank-cancel type="button" hidden>返回修改</button></div><p class="bank-message" data-bank-message role="status"></p></form><details class="bank-rules"><summary>利息與還款規則</summary><p>存款按本金與持有秒數計算單利，未領利息不複利，未滿 1 點繼續累積。領息後進入錢包。</p><p>新貸款日息 <b data-bank-loan-rate>—</b>；提前還款先還利息、再還本金。還款時不足 1 點的貸款利息以 1 點計。貸款總利息上限為原借本金，逾期不能再借，不會自動扣錢包或桌上籌碼。</p><p>總資產＝錢包＋桌上與底池＋存款－貸款本金與應付利息。借款不算獲利；利率調整後舊貸款保留原條件，存款從調整時間起套用新利率。</p></details><p class="bank-net">目前總資產 <strong data-bank-net>—</strong> 點</p></section><section class="panel bank-records"><div class="panel-title"><h2>我的銀行明細</h2><button class="text-button" data-bank-refresh type="button">重新整理</button></div><ul data-bank-history><li>讀取中…</li></ul><button class="button ghost full" data-bank-more type="button" hidden>更早紀錄</button></section></div>`;
  host.querySelectorAll('[data-bank-action]').forEach(b=>b.onclick=()=>{if(sending||operation)return;action=b.dataset.bankAction;reviewing=false;repayAll=false;message('');paint();});
  const amount=q('[name=amount]'),set=v=>{amount.value=Math.max(1,Math.min(Number(amount.max),Math.trunc(Number(v)||1)));reviewing=false;repayAll=false;paint();};
  host.querySelectorAll('[data-bank-step]').forEach(b=>b.onclick=()=>set(Number(amount.value)+Number(b.dataset.bankStep)));
  host.querySelectorAll('[data-bank-preset]').forEach(b=>b.onclick=()=>set(b.dataset.bankPreset));q('[data-bank-all]').onclick=()=>{set(amount.max);repayAll=action==='repay';paint();};
  amount.oninput=()=>{reviewing=false;repayAll=false;status();};q('form').onsubmit=submit;q('[data-bank-cancel]').onclick=()=>{reviewing=false;status();};
  q('[data-bank-collect]').onclick=()=>perform('collect',{});q('[data-bank-refresh]').onclick=()=>read();q('[data-bank-more]').onclick=()=>read(true);
  if(operation){if(operation.data.amount)amount.value=operation.data.amount;message('上次操作尚待確認，請使用原回執核對。');}
  clearInterval(timer);timer=setInterval(()=>{if(!document.hidden&&!sending&&!operation)void read();},30000);paint();void read();
 }

 let adminHost=null,adminEpoch=0;
 function unmountAdmin(){adminHost=null;adminEpoch++;}
 function mountAdmin(element,context){
  if(!element)return;adminHost=element;const token=++adminEpoch;let policy=null,busy=false,pending=null;
  const storageKey='nantuan-bank-settings:'+context.user.id,find=s=>element.querySelector(s),say=t=>{if(element.isConnected)find('[data-bank-admin-status]').textContent=t;};
  try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{}
  element.innerHTML=`<h2>銀行設定</h2><p>利率以「每日百分比」計算，已借出的貸款維持原條件。</p><form class="bank-admin-form"><fieldset><label>存款日息（%）<input name="deposit_bps" type="number" inputmode="decimal" min="0" max="5" step="0.01" required></label><label>貸款日息（%）<input name="loan_bps" type="number" inputmode="decimal" min="0" max="10" step="0.01" required></label><label>每人貸款上限（點）<input name="loan_limit" type="number" inputmode="numeric" min="0" max="1000000" step="1" required></label><label>新貸款期限（天）<input name="loan_days" type="number" inputmode="numeric" min="1" max="30" step="1" required></label><label class="bank-admin-note">修改備註<input name="note" maxlength="200" required></label></fieldset><p>上限設 0 可暫停新借款。存款利率不可高於貸款利率；修改時先結清舊存款利率的累積，再套用新利率。</p><button class="button primary" type="submit">儲存銀行設定</button><button class="button ghost" type="button" data-bank-admin-reload>重新載入</button><p class="bank-message" data-bank-admin-status role="status"></p></form><details><summary>銀行設定修改紀錄</summary><ul class="bank-settings-history"></ul></details>`;
  function fields(values){for(const name of ['deposit_bps','loan_bps','loan_limit','loan_days','note'])if(values[name]!==undefined)find('[name='+name+']').value=name.endsWith('_bps')?values[name]/100:values[name];}
  function lock(){find('fieldset').disabled=busy||!!pending||!policy;find('[type=submit]').disabled=busy||!policy;find('[type=submit]').textContent=busy?'正在確認…':pending?'確認原設定結果':'儲存銀行設定';find('[data-bank-admin-reload]').disabled=busy||!!pending;}
  async function load(){try{const result=await context.api('/api/admin/bank-settings');if(token!==adminEpoch||!element.isConnected)return;policy=result.settings;fields(pending||policy);lock();element.querySelector('.bank-settings-history').innerHTML=result.history.map(h=>`<li><strong>${esc(h.note)}</strong><span>管理員 #${h.actor_id} · ${new Date(h.created_at*1000).toLocaleString('zh-TW')}</span></li>`).join('')||'<li>尚無修改紀錄</li>';if(pending)say('上次設定尚待確認，請核對原操作。');}catch(e){say(e.message);}}
  find('form').onsubmit=async e=>{e.preventDefault();if(busy||!policy)return;
   if(!pending){const d=Object.fromEntries(new FormData(e.currentTarget));pending={deposit_bps:Math.round(Number(d.deposit_bps)*100),loan_bps:Math.round(Number(d.loan_bps)*100),loan_limit:Number(d.loan_limit),loan_days:Number(d.loan_days),note:d.note,revision:policy.revision,operation_id:crypto.randomUUID()};try{sessionStorage.setItem(storageKey,JSON.stringify(pending));}catch{pending=null;say('無法保存操作回執，設定未送出。');return;}}
   busy=true;lock();try{const result=await context.api('/api/admin/bank-settings',pending);sessionStorage.removeItem(storageKey);pending=null;if(token!==adminEpoch||!element.isConnected)return;policy=result.settings;fields(policy);say(result.replayed?'原設定已確認，不會重複修改。':'銀行設定已儲存。');void load();}
   catch(e){if(!e.retryable){pending=null;sessionStorage.removeItem(storageKey);}say(e.retryable?'尚未確認，請核對原設定結果。':e.message);}finally{busy=false;if(token===adminEpoch&&element.isConnected)lock();}
  };find('[data-bank-admin-reload]').onclick=load;lock();void load();
 }
 return {view,mount,unmount,mountAdmin,unmountAdmin};
})();
