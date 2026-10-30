'use strict';
window.ClubMarketReview=(()=>{
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={resume:'核對後恢復報價',settle:'撤單、按停牌前價結清後恢復'};
 let host=null,ctx=null,uid=null,epoch=0,timer=0,pending=null,sending=false,reading=false;
 const key=()=>`nantuan-market-halt-review:${uid}`;
 function say(text){const e=host?.querySelector('[data-halt-message]');if(e)e.textContent=text;}
 function lock(){if(!host)return;host.querySelectorAll('fieldset').forEach(e=>e.disabled=sending||!!pending||e.closest('form').dataset.ready!=='true');host.querySelectorAll('[type=submit]').forEach(e=>e.disabled=sending||!!pending||e.closest('form').dataset.ready!=='true');host.querySelector('[data-halt-retry]').hidden=!pending;host.querySelector('[data-halt-retry]').disabled=sending;host.querySelector('[data-halt-refresh]').disabled=sending||!!pending;}
 function clear(){pending=null;try{sessionStorage.removeItem(key());}catch{}}
 function paint(data){
  if(!host)return;
  host.querySelector('[data-halt-cases]').innerHTML=data.cases.map(c=>`<article class="panel"><h3>${esc(c.symbol)}</h3><p>停牌前可信價格：${esc(c.base_price)} · 最新候選價格：${esc(c.candidate_price??'等待來源')}<br>${c.candidate_at?new Date(c.candidate_at*1000).toLocaleString('zh-TW'):''} · ${c.ready?'有效候選報價':'行情缺少、過期或休市，暫不能處理'}</p><p>現貨 ${c.exposure.spot} 筆、做空 ${c.exposure.shorts} 筆、合約 ${c.exposure.contracts} 筆、待成交 ${c.exposure.orders} 筆</p><form class="bank-admin-form" data-halt-case="${esc(c.case_id||'')}" data-ready="${c.ready}"><fieldset ${!c.ready?'disabled':''}><label>處理方式<select name="action"><option value="resume">核對後恢復報價（不調整部位）</option><option value="settle">撤單、按停牌前價結清後恢復</option></select></label><label>審核備註<input name="note" maxlength="200" required placeholder="請說明已核對的價格與原因"></label><label><input type="checkbox" name="confirm" required> 我已核對行情來源與處理方式</label></fieldset><p>有舊部位且價格仍偏離超過 35% 時，須維持停牌或選結清。結清會退回委託保留點數、依停牌前可信價結束所有該標的部位，再啟用候選價；本版不提供拆股換股。</p><button type="submit" class="button primary" ${!c.ready?'disabled':''}>確認處理 ${esc(c.symbol)}</button></form></article>`).join('')||'<p>目前沒有待處理的異常停牌。</p>';
  for(const form of host.querySelectorAll('[data-halt-case]')){
   const item=data.cases.find(c=>c.case_id===form.dataset.haltCase);
   form.oninput=()=>form.dataset.dirty='true';
   form.onsubmit=async e=>{e.preventDefault();if(sending||pending||!item?.ready)return;const fields=new FormData(form),action=fields.get('action');
    if(!confirm((action==='settle'?`確定撤回 ${item.symbol} 的委託，並按停牌前可信價格 ${item.base_price} 結清既有部位後恢復？`:`確定已核對 ${item.symbol} 的候選價格 ${item.candidate_price}，恢復報價？`)))return;
    const value={symbol:item.symbol,case_id:item.case_id,quote_key:item.quote_key,action,note:fields.get('note'),operation_id:crypto.randomUUID()};
    try{sessionStorage.setItem(key(),JSON.stringify(value));pending=value;}catch{say('無法保存操作收據，尚未送出處理。');return;}
    await perform();
   };
  }
  host.querySelector('[data-halt-history]').innerHTML=data.history.map(h=>`<li><strong>${esc(h.symbol)} · ${esc(labels[h.action])}</strong><p>${esc(h.note)} · ${new Date(h.created_at*1000).toLocaleString('zh-TW')}</p></li>`).join('')||'<li>尚無停牌處理紀錄</li>';
  lock();
 }
 async function read(force=false){
  if(!host||reading||sending||!force&&(host.hidden||host.querySelector('[data-dirty]')))return;
  reading=true;const token=epoch;
  try{const data=await ctx.api('/api/admin/market-halts');if(token!==epoch||!host)return;paint(data);}catch(e){if(token===epoch)say(e.message);}finally{if(token===epoch)reading=false;}
 }
 async function perform(){
  if(!pending||sending||!host)return;const owner=uid,request=pending;epoch++;reading=false;sending=true;lock();say('正在確認停牌處理…');
  try{const result=await ctx.api('/api/admin/market-halts',request);if(uid!==owner)return;clear();say(result.message+(result.replayed?'（原操作已確認）':''));}
  catch(e){if(uid!==owner)return;if(!e.retryable)clear();say(e.retryable?'結果未確認，請按「確認原處理結果」，不會再次結清或派點。':e.message);}
  finally{if(uid===owner){sending=false;lock();if(!pending)void read(true);}}
 }
 function unmount(){clearInterval(timer);timer=0;host=null;epoch++;reading=false;}
 function mount(element,context){
  if(!element)return;unmount();host=element;ctx=context;
  if(uid!==context.user.id){uid=context.user.id;sending=false;pending=null;}
  try{const saved=JSON.parse(sessionStorage.getItem(key())||'null');if(saved&&labels[saved.action]&&typeof saved.operation_id==='string')pending=saved;}catch{}
  host.innerHTML='<h2>行情異常審核</h2><p>異常價格先隔離，經管理員核對後恢復；處理保留完整紀錄。</p><button type="button" class="button ghost" data-halt-refresh>重新載入候選行情</button><button type="button" class="button primary" data-halt-retry hidden>確認原處理結果</button><p role="status" data-halt-message></p><div data-halt-cases></div><details><summary>停牌處理紀錄</summary><ul data-halt-history></ul></details>';
  host.querySelector('[data-halt-refresh]').onclick=()=>read(true);host.querySelector('[data-halt-retry]').onclick=perform;lock();void read(true);timer=setInterval(()=>{if(!document.hidden)void read();},10000);
 }
 return {mount,unmount};
})();
