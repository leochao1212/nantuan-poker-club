'use strict';
window.ClubhouseScene=(()=>{
 const names=['私人包廂','霓虹酒廊','尊爵會館','曜金行宮'];
 const routes=[
  [[440,655,0],[850,790,1],[1080,775,2]],
  [[430,735,0],[970,720,1],[650,360,2]],
  [[490,724,0],[1050,740,1],[875,294,2]],
  [[370,693,0],[1010,846,1],[1155,460,2]]
 ];
 const employeeKeys=['concierge','host','steward'];let owned=new Set(['concierge']);
 const observed=new Map();let scheduled=false;
 const observer=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
  for(const entry of entries){observed.set(entry.target,entry.isIntersecting);entry.target.toggleAttribute('data-estate-paused',!entry.isIntersecting);}
 }):null;
 function sync(){scheduled=false;for(const node of observed.keys())if(!node.isConnected){observer?.unobserve(node);observed.delete(node);}
  document.querySelectorAll('.clubhouse-scene').forEach(node=>{if(!observed.has(node)){observed.set(node,true);observer?.observe(node);}node.toggleAttribute('data-estate-paused',!observed.get(node));node.querySelectorAll('[data-estate-employee]').forEach(person=>person.setAttribute('data-estate-owned',String(owned.has(person.dataset.estateEmployee))));});
 }
 function employee(x,y,index){return `<g transform="translate(${x} ${y})"><g class="estate-walker estate-route-${index}"><g class="estate-person-scale"><ellipse cy="2" rx="11" ry="4" fill="#020a10" opacity=".65"/><path class="estate-leg-a" d="M-3-16V-2" stroke="#c3b29e" stroke-width="5" stroke-linecap="round"/><path class="estate-leg-b" d="M3-16V-2" stroke="#c3b29e" stroke-width="5" stroke-linecap="round"/><path class="estate-uniform-${index}" d="M0-34V-16" stroke-width="16" stroke-linecap="round"/><path d="M-10-31L-12-20M10-31L12-20" stroke="#d4ab8b" stroke-width="4" stroke-linecap="round"/><circle cy="-44" r="8" fill="#d4ab8b"/><path d="M-8-46Q-8-57 4-53Q11-51 8-44L4-48Z" fill="#202b34"/><path d="M-3-36L0-30L3-36" fill="#ebdfce"/></g></g></g>`;}
 function render(income){const raw=Number(income?.decor_level),level=Number.isInteger(raw)&&raw>=0&&raw<names.length?raw:0,tier=level+1;
  if(!scheduled){scheduled=true;queueMicrotask(sync);}
  return `<div class="clubhouse-scene estate-tier-${level}" data-estate-level="${level}" role="img" aria-label="裝潢 Lv.${tier} ${names[level]}建築外觀"><picture><source media="(max-width: 760px)" srcset="/assets/clubhouse/tier-${tier}-small.webp"><img class="estate-render" src="/assets/clubhouse/tier-${tier}.webp" width="1536" height="1024" alt="" decoding="async" draggable="false"></picture><svg class="estate-people" viewBox="0 0 1536 1024" aria-hidden="true">${routes[level].map(([x,y,index])=>`<g data-estate-employee="${employeeKeys[index]}" data-estate-owned="${owned.has(employeeKeys[index])}">${employee(x,y,index)}</g>`).join('')}</svg></div>`;
 }
 document.addEventListener('visibilitychange',()=>document.documentElement.toggleAttribute('data-club-hidden',document.hidden));
 document.documentElement.toggleAttribute('data-club-hidden',document.hidden);
 function staff(employees){owned=new Set((employees||[]).filter(p=>p.owned).map(p=>p.key));sync();}
 return {render,names,staff};
})();
