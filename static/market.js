/* Paper trading: fixed-point quantities, receipt recovery and bounded visible reads. */
'use strict';
window.ClubMarket=(()=>{
 const num=x=>Number(x||0).toLocaleString('zh-TW',{maximumFractionDigits:2}),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const when=x=>x?new Date(x*1000).toLocaleString('zh-TW',{hour12:false}):'尚無報價',names={TW:'台股',US:'美股',CC:'加密貨幣'},statuses={pending:'等待新報價',filled:'已成交',cancelled:'已取消',expired:'已到期'};
 let host=null,ctx=null,uid=null,state=null,selected='TW:2330',group='TW',side='buy',reading=false,sending=false,epoch=0,timer=0,operation=null,review=false;
 const q=s=>host?.querySelector(s),key=()=>`nantuan-market:${uid}`;
 function message(s,bad=false){const e=q('[data-market-message]');if(e){e.textContent=s;e.classList.toggle('error',bad);e.setAttribute('role',bad?'alert':'status');}}
 function clear(){operation=null;try{sessionStorage.removeItem(key());}catch{}}
 function item(){return state?.instruments.find(i=>i.symbol===selected);}
 function status(){if(!host)return;const locked=sending||!!operation;
  q('fieldset').disabled=locked||!state;
  q('[data-market-submit]').disabled=sending||!state||!operation&&(!item()?.available||side==='sell'&&!Number(state.positions.find(p=>p.symbol===selected)?.available_quantity));
  q('[data-market-submit]').textContent=sending?'確認委託中…':operation?'確認原委託':review?'確認'+(side==='buy'?'買入':'賣出')+'委託':'預覽'+(side==='buy'?'買入':'賣出');
  q('[data-market-back]').hidden=!review||!!operation;q('[data-market-review]').hidden=!review;
  host.querySelectorAll('[data-market-symbol],[data-market-side],[data-market-group],[data-market-cancel]').forEach(b=>b.disabled=locked);
 }
 function paint(){if(!host||!state)return;
  const text=(s,v)=>{const e=q(s);if(e&&e.textContent!==v)e.textContent=v;};
  text('[data-market-cash]',num(ctx.wallet.balance));text('[data-market-assets]',num(state.value));
  text('[data-market-profit]',num(state.positions.reduce((n,p)=>n+p.profit,0)));
  for(const i of state.instruments){const button=q(`[data-market-symbol="${i.symbol}"]`);if(!button)continue;button.hidden=i.market!==group;button.setAttribute('aria-pressed',String(i.symbol===selected));button.querySelector('[data-price]').textContent=i.quote?num(i.quote.price)+' 點':'尚未取得';button.querySelector('[data-feed]').textContent=i.available?i.mode:i.quote?.halted?'公司行動待確認':i.market==='US'&&state.providers.some(p=>p.name==='US'&&p.status==='missing_key')?'待設定免費 API Key':'行情暫停';}
  host.querySelectorAll('[data-market-group]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.marketGroup===group)));
  host.querySelectorAll('[data-market-side]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.marketSide===side)));
  const i=item(),p=state.positions.find(p=>p.symbol===selected);
  text('[data-market-title]',i?.name||'選擇標的');text('[data-market-symbol-label]',selected);
  text('[data-market-price]',i?.quote?num(i.quote.price)+' 點':'—');
  text('[data-market-source]',i?.quote?`${i.quote.source} · ${when(i.quote.asof)}${i.available?'':' · 暫停接受新委託'}`:'等待行情來源，不會使用模擬價格成交。');
  text('[data-market-native]',i?.quote&&i.currency==='USD'?`原幣 ${num(i.quote.native)} USD · 換算匯率 ${Number(i.quote.fx).toFixed(4)}（${when(i.quote.fx_at)}）`:'1 點＝1 元台幣');
  text('[data-market-timing]',i?.market==='CC'?'約每 10 秒取得公開報價；下一次有效買賣價成交。':'每日收盤行情；委託後等待下一次新收盤資料成交，可隨時取消。');
  text('[data-market-amount-label]',side==='buy'?'買入預算（點）':'賣出份額');
  text('[data-market-available]',side==='buy'?`可用 ${num(ctx.wallet.balance)} 點；先保留預算，依成交價換算份額。`:`可賣 ${p?.available_quantity||'0'} 份；已掛單份額會保留。`);
  host.querySelectorAll('[data-market-preset]').forEach(b=>b.hidden=side==='sell');
  const field=q('[name=market_amount]');field.step=side==='buy'?'1':'0.00000001';field.min=side==='buy'?'1':'0.00000001';field.max=side==='buy'?String(Math.min(1000000,ctx.wallet.balance)):(p?.available_quantity||'0');
  text('[data-market-all]',side==='buy'?'全部預算':'全部份額');
  const history=i?.history||[],chart=q('[data-market-chart]'),signature=JSON.stringify([selected,history]);
  if(chart.dataset.signature!==signature){chart.dataset.signature=signature;if(history.length<2){chart.textContent='累積報價後顯示走勢';}else{const ys=history.map(p=>Number(p.price)),min=Math.min(...ys),max=Math.max(...ys),range=max-min||1,points=ys.map((v,n)=>`${8+n*284/(ys.length-1)},${82-(v-min)*68/range}`).join(' ');chart.innerHTML=`<svg viewBox="0 0 300 90" role="img" aria-label="最近 ${history.length} 筆真實報價，最低 ${num(min)}，最高 ${num(max)} 點"><polyline points="${points}"/></svg>`;}}
  const positions=q('[data-market-positions]'),ps=JSON.stringify(state.positions);
  if(positions.dataset.signature!==ps){positions.dataset.signature=ps;positions.innerHTML=state.positions.length?state.positions.map(p=>`<li><div><strong>${esc(state.instruments.find(i=>i.symbol===p.symbol)?.name)}</strong><small>${esc(p.quantity)} 份${p.stale?' · 舊報價估值':''}</small></div><div><b>${num(p.value)} 點</b><small>${p.profit>=0?'+':''}${num(p.profit)} 點</small></div></li>`).join(''):'<li>成交後會在這裡顯示持倉。</li>';}
  const orders=q('[data-market-orders]'),os=JSON.stringify(state.orders);
  if(orders.dataset.signature!==os){orders.dataset.signature=os;orders.innerHTML=state.orders.length?state.orders.map(o=>`<li><div><strong>#${o.id} · ${esc(o.symbol)} · ${o.side==='buy'?'買入':'賣出'} · ${statuses[o.status]}</strong><small>${o.status==='filled'?`${esc(o.quantity)} 份 · ${num(o.points)} 點 · 成交報價 ${when(o.fill_asof)}`:o.side==='buy'?`保留 ${num(o.budget)} 點`:`保留 ${esc(o.quantity)} 份`}</small><small>${esc(o.reason)||when(o.submitted_at)}</small></div>${o.status==='pending'?`<button type="button" class="button ghost" data-market-cancel="${o.id}">取消委託</button>`:''}</li>`).join(''):'<li>尚無委託。</li>';}
  status();
 }
 async function read(){if(!host||reading||sending||document.hidden)return;reading=true;const token=epoch,owner=uid;
  try{const r=await ctx.api('/api/market');if(token!==epoch||uid!==owner||!host)return;if(state&&r.market.server_time<state.server_time)return;state=r.market;ctx.wallet=r.wallet;paint();ctx.updated?.(r,owner);}
  catch(e){if(token===epoch)message(e.message,true);}finally{if(token===epoch)reading=false;}
 }
 async function perform(action,data){if(sending||!host)return;
  if(!operation){operation={action,data:{...data,operation_id:crypto.randomUUID()}};try{sessionStorage.setItem(key(),JSON.stringify(operation));}catch{operation=null;message('請允許網站保存回執後再下單。',true);return;}}
  const request=operation,owner=uid;epoch++;reading=false;sending=true;status();message('正在確認委託…');
  try{const r=await ctx.api('/api/market/'+request.action,request.data);if(uid!==owner)return;clear();review=false;state=r.market;ctx.wallet=r.wallet;paint();const order=state.orders.find(o=>o.id===r.order_id);message(request.action==='cancel'?'委託已取消，保留資產已解除。':order?.status==='filled'?`委託 #${r.order_id} 已成交，請查看成交紀錄。`:`委託 #${r.order_id} 已受理，等待下一次新報價。`);ctx.updated?.(r,owner);}
  catch(e){if(uid!==owner)return;if(!e.retryable){clear();review=false;}message(e.retryable?'結果尚未確認。請按「確認原委託」，不會再次保留點數。':e.message,true);}
  finally{if(uid===owner){sending=false;status();}}
 }
 function reset(){review=false;q('[data-market-review]').hidden=true;status();}
 function unmount(){clearInterval(timer);timer=0;host=null;epoch++;reading=false;}
 function mount(context){const element=document.querySelector('#market-console');if(!element)return;
  if(uid!==context.user.id){uid=context.user.id;state=null;operation=null;sending=false;review=false;epoch++;try{const saved=JSON.parse(sessionStorage.getItem(key())||'null');if(saved&&['order','cancel'].includes(saved.action)&&typeof saved.data?.operation_id==='string'){operation=saved;if(saved.action==='order'){selected=saved.data.symbol;group=selected.split(':')[0];side=saved.data.side;}}}catch{}}
  ctx=context;host=element;if(host.dataset.owner===String(uid)){paint();return;}
  host.dataset.owner=String(uid);epoch++;reading=false;
  host.innerHTML=`<div class="market-banner"><div><span class="small-label">點數現貨 · 三個市場</span><h2>你的下一筆投資。</h2><p>1 點＝1 元台幣，只使用遊戲內點數。</p></div><a class="button gold-button" href="#bank">銀行存提／借款 →</a></div><div class="market-overview"><article class="panel"><span>錢包可用</span><strong data-market-cash>—</strong></article><article class="panel"><span>持倉與委託資產</span><strong data-market-assets>—</strong></article><article class="panel"><span>持倉損益（點）</span><strong data-market-profit>—</strong></article></div><div class="market-layout"><section class="panel market-watch"><h2>選擇市場</h2><div class="market-tabs" role="group" aria-label="市場">${Object.entries(names).map(([id,label])=>`<button class="button ghost" data-market-group="${id}" aria-pressed="${group===id}">${label}</button>`).join('')}</div><div class="market-instruments">${[['TW:2330','台積電'],['TW:2317','鴻海'],['TW:2454','聯發科'],['TW:0050','元大台灣50'],['TW:0056','元大高股息'],['US:AAPL','Apple'],['US:MSFT','Microsoft'],['US:NVDA','NVIDIA'],['CC:BTC','Bitcoin'],['CC:ETH','Ethereum'],['CC:SOL','Solana']].map(([id,name])=>`<button type="button" class="market-instrument" data-market-symbol="${id}" aria-pressed="false"><span><strong>${name}</strong><small>${id}</small></span><span><b data-price>—</b><small data-feed>等待行情</small></span></button>`).join('')}</div></section><section class="panel market-compose"><span class="small-label" data-market-symbol-label></span><h2 data-market-title>選擇標的</h2><strong class="market-quote" data-market-price>—</strong><p class="market-source" data-market-source></p><p class="market-source" data-market-native></p><div class="market-chart" data-market-chart></div><p data-market-timing></p><div class="market-tabs" role="group" aria-label="買賣方向"><button class="button ghost" data-market-side="buy" aria-pressed="true">買入</button><button class="button ghost" data-market-side="sell" aria-pressed="false">賣出</button></div><form data-market-form><fieldset disabled><legend class="sr-only">現貨委託</legend><label for="market-amount" data-market-amount-label>買入預算（點）</label><input id="market-amount" name="market_amount" type="number" inputmode="decimal" value="1000" required><div class="market-presets"><button class="button ghost" type="button" data-market-preset="100">100 點</button><button class="button ghost" type="button" data-market-preset="1000">1,000 點</button><button class="button ghost" type="button" data-market-all>全部預算</button></div><p data-market-available></p></fieldset><p class="bank-review" data-market-review tabindex="-1" hidden></p><div class="market-submit"><button type="submit" class="button primary" data-market-submit disabled>預覽買入</button><button type="button" class="button ghost" data-market-back hidden>返回修改</button></div><p class="bank-message" role="status" data-market-message></p></form><details><summary>成交與點數規則</summary><p>買入先保留預算，依下一筆有效報價換算八位小數份額。賣出只可使用持有份額，不提供放空或槓桿。買入扣點向上取整、賣出回點向下取整，各不到 1 點；無額外手續費。股票等新收盤資料更新，最長等待七天；加密貨幣委託最長兩分鐘。未成交可取消；行情中斷會暫停成交，到期解除保留。第一版不派股息；疑似分割等異常價差會暫停交易，待核對公司行動。</p></details></section></div><div class="market-bottom"><section class="panel"><h2>我的持倉</h2><ul class="market-records" data-market-positions></ul></section><section class="panel"><h2>委託與成交</h2><button class="button ghost" type="button" data-market-refresh>更新紀錄</button><ul class="market-records" data-market-orders></ul></section></div><p class="market-attribution">台股：<a href="https://openapi.twse.com.tw/" target="_blank" rel="noopener">TWSE 開放資料</a> · 美股：<a href="https://marketstack.com/" target="_blank" rel="noopener">Marketstack</a> · 加密貨幣：<a href="https://www.kraken.com/" target="_blank" rel="noopener">Kraken</a> · <a href="https://www.exchangerate-api.com" target="_blank" rel="noopener">Rates By Exchange Rate API</a>。報價僅用於點數模擬交易。</p>`;
  host.onclick=e=>{const b=e.target.closest('button');if(!b||sending)return;
   if(b.hasAttribute('data-market-refresh'))return void read();
   if(b.hasAttribute('data-market-cancel'))return void perform('cancel',{order_id:Number(b.dataset.marketCancel)});
   if(operation)return;
   if(b.dataset.marketGroup){group=b.dataset.marketGroup;selected=state?.instruments.find(i=>i.market===group)?.symbol||({'TW':'TW:2330','US':'US:AAPL','CC':'CC:BTC'}[group]);reset();paint();}
   if(b.dataset.marketSymbol){selected=b.dataset.marketSymbol;reset();paint();if(innerWidth<=760)q('.market-compose').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
   if(b.dataset.marketSide){side=b.dataset.marketSide;q('[name=market_amount]').value=side==='buy'?'1000':state?.positions.find(p=>p.symbol===selected)?.available_quantity||'';reset();paint();}
   if(b.dataset.marketPreset){if(side==='buy')q('[name=market_amount]').value=b.dataset.marketPreset;reset();}
   if(b.hasAttribute('data-market-all')){q('[name=market_amount]').value=side==='buy'?Math.min(1000000,ctx.wallet.balance):state?.positions.find(p=>p.symbol===selected)?.available_quantity||'';reset();}
   if(b.hasAttribute('data-market-back'))reset();
  };
  q('[data-market-form]').oninput=reset;
  q('[data-market-form]').onsubmit=e=>{e.preventDefault();if(operation)return void perform(operation.action,operation.data);if(!state||sending||!item()?.available)return;
   const input=q('[name=market_amount]');if(!input.checkValidity())return input.reportValidity();
   const amount=input.value;if(side==='buy'&&!Number.isSafeInteger(Number(amount)))return message('買入預算請填整數點數。',true);
   if(!review){review=true;const panel=q('[data-market-review]');panel.hidden=false;panel.textContent=`${side==='buy'?'保留 '+num(amount)+' 點買入':'保留 '+amount+' 份賣出'} ${item().name}。${q('[data-market-timing]').textContent} 成交價會與目前顯示價格不同。`;panel.focus();status();return;}
   void perform('order',{symbol:selected,side,...(side==='buy'?{amount:Number(amount)}:{quantity:amount})});
  };
  paint();void read();clearInterval(timer);timer=setInterval(()=>void read(),10000);
 }
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)void read();});window.addEventListener('online',()=>void read());
 return{view:()=>'<div id="market-console" class="market-console" aria-label="點數交易所"></div>',mount,unmount};
})();
