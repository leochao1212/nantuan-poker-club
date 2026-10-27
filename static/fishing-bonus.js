/* Durable treasure settlement; the board only reveals server-confirmed prizes. */
'use strict';
window.ClubFishingBonus=(()=>{
 const num=n=>Number(n||0).toLocaleString('zh-TW'),pool=[2,3,5,8,10,20,50,100],cells=[];
 for(let x=0;x<5;x++)cells.push([x,0]);for(let y=1;y<5;y++)cells.push([4,y]);for(let x=3;x>=0;x--)cells.push([x,4]);for(let y=3;y>0;y--)cells.push([0,y]);
 function create({command,pause}){
  const dialog=document.createElement('dialog');dialog.className='fish-bonus-modal';dialog.setAttribute('aria-label','海底寶藏');document.body.append(dialog);
  let state=null,event=null,active=false,busy=false,token=0,timer=0,resolveWait=null,seen=new Set();
  function stop(){token++;clearTimeout(timer);if(resolveWait){resolveWait();resolveWait=null;}}
  function wait(ms){return new Promise(r=>{resolveWait=r;timer=setTimeout(()=>{resolveWait=null;r();},ms);});}
  function close(){stop();active=false;dialog.close();}
  function final(){stop();if(!event?.draws)return;draw(true);}
  function draw(done=false){
   if(!event)return;const settled=event.status==='settled',show=done&&settled;
   dialog.innerHTML=`<header><h2>海底寶藏</h2><button data-bonus-close aria-label="關閉寶箱">×</button></header><p>以捕獲時每發 ${num(event.stake)} 點計算 · ${event.rounds} 次獎勵</p><div class="fish-bonus-board">${cells.map(([x,y],i)=>`<div data-bonus-cell="${i}" style="grid-column:${x+1};grid-row:${y+1}"><strong>${pool[i%8]}×</strong></div>`).join('')}<div class="fish-bonus-center"><div class="fish-bonus-chest">${window.ClubFishingScene.portrait('chest')}</div><b data-bonus-progress>${show?event.rounds+'／'+event.rounds:'準備開箱'}</b><strong data-bonus-total>${show?'＋'+num(event.gross):'寶藏獎勵'}</strong><small data-bonus-item>${show?(event.item==='laser'?'雷射':'冰凍')+' 道具 ＋1':''}</small></div></div><p class="fish-bonus-draws" data-bonus-draws>${show?event.draws.map(m=>m+'×').join(' ＋ '):'獎勵會存檔，離頁也能回來領取'}</p><button class="fish-bonus-primary" data-bonus-start ${busy?'disabled':''}>${show?'已入帳，繼續捕魚':busy?'確認開獎中…':'開啟寶藏'}</button><button class="fish-bonus-skip" data-bonus-skip hidden>略過動畫，查看結果</button><small class="fish-bonus-note">本站獎勵池 · 2–100 倍 · 規則可在玩法中查看</small>`;
   dialog.querySelector('[data-bonus-close]').onclick=close;dialog.querySelector('[data-bonus-start]').onclick=show?close:claim;dialog.querySelector('[data-bonus-skip]').onclick=final;
  }
  async function reveal(){
   const current=++token;draw();dialog.querySelector('[data-bonus-start]').hidden=true;dialog.querySelector('[data-bonus-skip]').hidden=false;
   if(matchMedia('(prefers-reduced-motion: reduce)').matches){final();return;}
   let index=0,total=0;
   for(let round=0;round<event.draws.length;round++){
    const target=pool.indexOf(event.draws[round])+(round%2)*8,steps=16+(target-index+16)%16;
    for(let step=0;step<steps;step++){
     if(current!==token||!active)return;
     dialog.querySelector('[data-bonus-cell="'+index+'"]').classList.remove('is-lit');index=(index+1)%16;dialog.querySelector('[data-bonus-cell="'+index+'"]').classList.add('is-lit');
     await wait(step>steps-5?90+(step-(steps-5))*30:35);
    }
    if(current!==token||!active)return;total+=event.stake*event.draws[round];dialog.querySelector('[data-bonus-progress]').textContent=(round+1)+'／'+event.rounds;dialog.querySelector('[data-bonus-total]').textContent='＋'+num(total);dialog.querySelector('[data-bonus-draws]').textContent=event.draws.slice(0,round+1).map(m=>m+'×').join(' ＋ ');await wait(300);
   }
   if(current===token&&active)final();
  }
  async function claim(){
   if(busy||!event)return;busy=true;draw();const id=event.id;
   const reply=await command('bonus',{bonus_id:id});busy=false;
   if(reply?.result?.bonus){if(event?.id!==id){if(active)draw(event?.status==='settled');return;}event=reply.result.bonus;if(active)void reveal();}
   else if(active){draw();const b=dialog.querySelector('[data-bonus-start]');b.textContent='確認原次開箱';b.onclick=claim;}
  }
  function open(next){pause();stop();event=next||state?.bonuses?.[0]||state?.last_bonus;if(!event)return;active=true;seen.add(event.id);draw(event.status==='settled');if(!dialog.open)dialog.showModal();}
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  return {open,update(next,auto=false){state=next;const pending=next?.bonuses?.[0];if(auto&&pending&&!seen.has(pending.id)&&!active&&!busy)open(pending);},destroy(){stop();active=false;dialog.remove();}};
 }
 return {create};
})();
