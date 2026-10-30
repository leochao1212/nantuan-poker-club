'use strict';
window.ClubLottery=(()=>{
 let host,ctx,state,pending,selected=new Set(),busy=false,reading=false,epoch=0,timer,offset=0;
 const num=n=>Number(n||0).toLocaleString('zh-TW'),q=s=>host?.querySelector(s),key=uid=>'nantuan-lottery:'+uid;
 const balls=ns=>ns.map(n=>`<span class="lottery-ball">${String(n).padStart(2,'0')}</span>`).join('');
 function message(t){const e=q('[data-lottery-message]');if(e)e.textContent=t;}
 function unmount(){epoch++;clearInterval(timer);host=null;ctx=null;state=null;pending=null;busy=false;reading=false;selected=new Set();}
 function view(){return '<section id="lottery-console" aria-label="朋友樂透"></section>';}
 function paint(){
  if(!host||!state)return;
  const d=state.current,now=Date.now()/1000+offset,open=d&&now<d.cutoff;
  q('[data-lottery-pool]').textContent=num(state.jackpot);
  q('[data-lottery-date]').textContent=d?`${d.id} 期 · 台灣時間 21:00 開獎`:'正在準備下一期';
  q('[data-lottery-clock]').textContent=open?`距 20:55 截止還有 ${Math.floor((d.cutoff-now)/3600)} 小時 ${Math.floor((d.cutoff-now)%3600/60)} 分 ${Math.floor((d.cutoff-now)%60)} 秒`:d&&now<d.draw_at?'本期已截止，21:00 自動開獎':'正在等候結算，稍後自動更新';
  q('[data-lottery-budget]').textContent=`錢包 ${num(ctx.wallet.balance)} 點 · 本期已買 ${state.bought} / ${state.limit} 注`;
  q('[data-lottery-selection]').textContent=selected.size?[...selected].sort((a,b)=>a-b).map(n=>String(n).padStart(2,'0')).join(' · '):'選出你的 5 個號碼';
  host.querySelectorAll('[data-lottery-number]').forEach(b=>{b.setAttribute('aria-pressed',String(selected.has(Number(b.dataset.lotteryNumber))));b.disabled=busy||!!pending||!open;});
  q('[data-lottery-quick]').disabled=busy||!!pending||!open;
  const buy=q('[data-lottery-buy]');buy.disabled=busy||(!pending&&(!open||selected.size!==5||state.bought>=state.limit||ctx.wallet.balance<state.price));buy.textContent=busy?'確認購票中…':pending?'確認原購票結果':'確認購買 1 注 · 100 點';
  const signature=JSON.stringify([state.tickets,state.results,state.current?.commitment]);
  if(host.dataset.records===signature)return;host.dataset.records=signature;
  q('[data-lottery-tickets]').innerHTML=state.tickets.map(t=>`<li><div><strong>${t.draw_id} · 票號 #${t.id}</strong><div class="lottery-balls">${balls(t.numbers)}</div></div><b>${t.prize===null?'等待開獎':t.prize?`${t.tier} +${num(t.prize)} 點（已入帳）`:'未中獎'}</b></li>`).join('')||'<li>還沒有彩券。選好號碼後，這裡會留下購票紀錄。</li>';
  q('[data-lottery-results]').innerHTML=state.results.map(r=>`<article><h3>${r.id} 期</h3><div class="lottery-balls">${balls(r.result.slice(0,5).sort((a,b)=>a-b))}<span class="lottery-special">特別號 ${balls([r.result[5]])}</span></div><p>當期頭獎池 ${num(r.jackpot)} 點 · 全部獎項已發 ${num(r.paid)} 點</p><details><summary>開獎驗證資料</summary><p>承諾 SHA-256：<code>${r.commitment}</code></p><p>公開種子：<code>${r.seed}</code></p><p>抽取順序：${r.result.join(', ')}。前五個為主號，第六個為特別號。</p></details></article>`).join('')||'<p>第一期開獎後，這裡會顯示結果。</p>';
  q('[data-lottery-commitment]').textContent=d?.commitment||'準備中';
  q('[data-lottery-tiers]').innerHTML=state.tiers.map(t=>`<tr><th scope="row">${t.label}</th><td>${t.match} 個主號${t.special?'＋特別號':''}</td><td>${t.prize===null?'均分累積頭獎':num(t.prize)+' 點'}</td><td>${(t.outcomes/t.total*100).toFixed(4)}%</td></tr>`).join('');
 }
 async function read(){
  if(!host||busy||reading)return;reading=true;const token=epoch,context=ctx;
  try{const r=await context.api('/api/lottery');if(token!==epoch)return;state=r.lottery;context.wallet=r.wallet;offset=state.server_time-Date.now()/1000;paint();context.updated?.(r,context.user.id);}catch(e){if(token===epoch)message(e.message);}finally{if(token===epoch)reading=false;}
 }
 async function buy(){
  if(busy||!state)return;const context=ctx,token=++epoch,owner=context.user.id;reading=false;
  if(!pending){
   if(selected.size!==5)return;
   pending={operation_id:crypto.randomUUID(),draw_id:state.current.id,numbers:[...selected].sort((a,b)=>a-b)};
   try{sessionStorage.setItem(key(owner),JSON.stringify(pending));}catch{pending=null;message('無法保存購票回執，請允許網站儲存資料後再試。');return;}
  }
  busy=true;paint();message('正在確認購票…');
  try{const r=await context.api('/api/lottery/buy',pending);sessionStorage.removeItem(key(owner));if(token!==epoch)return;pending=null;state=r.lottery;context.wallet=r.wallet;message(`${r.replayed?'原購票已確認':'購票成功'} · 票號 #${r.ticket_id}，不會重複扣點。`);context.updated?.(r,owner);}
  catch(e){if(token!==epoch)return;if(!e.retryable){pending=null;sessionStorage.removeItem(key(owner));}message(e.retryable?'結果尚未確認，請按「確認原購票結果」核對，不會重複扣款。':e.message);}
  finally{if(token===epoch){busy=false;paint();}}
 }
 function mount(context){
  const element=document.querySelector('#lottery-console');if(!element)return;
  if(host===element&&ctx?.user.id===context.user.id){ctx=context;return;}
  unmount();host=element;ctx=context;
  try{pending=JSON.parse(sessionStorage.getItem(key(ctx.user.id))||'null');if(pending)selected=new Set(pending.numbers);}catch{pending=null;}
  host.innerHTML=`<div class="lottery-hero panel"><div><span class="small-label">朋友限定 · 20 選 5</span><h2>今晚的好消息，<br>留一份給自己。</h2><p data-lottery-date>載入期別…</p><p data-lottery-clock></p></div><div class="lottery-jackpot"><span>本期累積頭獎</span><strong data-lottery-pool>—</strong><span>遊戲點數 · 多注中獎均分</span></div></div><div class="lottery-layout"><section class="panel lottery-picker"><h2>挑 5 個幸運號碼</h2><p>每注 100 點，每人每期最多 10 注。20:55 截止。</p><p data-lottery-budget></p><div class="lottery-grid" role="group" aria-label="從 1 到 20 選 5 個號碼">${Array.from({length:20},(_,i)=>`<button type="button" data-lottery-number="${i+1}" aria-pressed="false" disabled>${String(i+1).padStart(2,'0')}</button>`).join('')}</div><button class="button ghost" type="button" data-lottery-quick disabled>電腦選號</button><p class="lottery-selection" data-lottery-selection>選出你的 5 個號碼</p><button type="button" class="button primary full" data-lottery-buy disabled>確認購買 1 注 · 100 點</button><p data-lottery-message role="status" aria-live="polite"></p><p>購買即扣點，不能取消。開獎後自動派獎，不用手動領取。</p></section><section class="panel lottery-rules"><h2>朋友版，玩得懂的運氣</h2><p>從 1–20 選 5 個號碼；開出 5 個主號與 1 個特別號，號碼不重複、不計順序。特別號不用另外選。每注只領符合的最高獎項。</p><div class="lottery-table"><table><thead><tr><th>獎項</th><th>命中</th><th>獎金</th><th>單注機率</th></tr></thead><tbody data-lottery-tiers></tbody></table></div><p>頭獎機率 1 / 15,504；任一獎約 36.61%，包含低於票價的 50 點小獎。固定小獎期望回饋約 72.76 點／注，另有 20 點／注進入頭獎池。</p><details><summary>獎池、驗證與遊戲規則</summary><p>頭獎初始 10,000 點，每注投入 20 點；沒人中就累積。多張頭獎票均分，整除餘點留到下期；開出頭獎後，系統再補 10,000 點。小獎另由系統支付，空期不增加獎池。</p><p>稱號不改變中獎機率，也不額外提高本遊戲獎金。本遊戲不計入牌桌局數或任務。僅限站內虛擬點數，沒有現金兌換。</p><p>售票前公開種子雜湊，開獎後公開種子。SHA-256 使用種子 hex 解碼後的位元組；依 HMAC-SHA256（key＝種子，訊息＝friends-lottery-v1:0 起的計數）逐位元組抽號。捨棄大於等於 240 的值，其餘取餘數 20 加 1，跳過重複，取前 6 個號碼。此機制可核對事後是否更換種子，並非第三方公證。</p><p>本期承諾：<code data-lottery-commitment></code></p><p>這是獨立設計的朋友版，號碼池、獎金、開獎頻率與機率皆不同於台灣彩券。<a href="https://www.taiwanlottery.com/lotto/info/lotto649/" target="_blank" rel="noopener">台彩官方大樂透玩法 ↗</a></p></details></section></div><section class="panel lottery-history"><h2>我的彩券</h2><p>最近 100 注 · 中獎金額為實際入帳點數</p><ul data-lottery-tickets></ul></section><section class="panel lottery-history"><h2>最近 14 期開獎</h2><div data-lottery-results></div></section>`;
  host.querySelectorAll('[data-lottery-number]').forEach(b=>b.onclick=()=>{const n=Number(b.dataset.lotteryNumber);if(selected.has(n))selected.delete(n);else if(selected.size<5)selected.add(n);else message('已選滿 5 個號碼，先取消一個再換號。');paint();});
  q('[data-lottery-quick]').onclick=()=>{selected=new Set();while(selected.size<5){const bytes=crypto.getRandomValues(new Uint8Array(16));for(const b of bytes)if(b<240&&selected.size<5)selected.add(b%20+1);}paint();};
  q('[data-lottery-buy]').onclick=buy;
  if(pending)message('有一筆購票尚待確認，請核對原購票結果。');
  let ticks=0;timer=setInterval(()=>{if(!document.hidden){paint();if(++ticks%10===0)void read();}},1000);void read();
 }
 return {view,mount,unmount};
})();
