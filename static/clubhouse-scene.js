'use strict';
window.ClubhouseScene=(()=>{
 const names=['私人包廂','暖燈小館','尊爵會館','曜金行宮','翡翠御苑','星河城堡','雲頂王庭','天際皇宮','星耀帝城','楠團天宮'];
 // Every scene keeps the same street foreground for these employee paths.
 const routes=names.map(()=>[[400,812,0],[860,852,1],[1130,832,2]]);
 const employeeKeys=['concierge','host','steward'];let owned=new Set(['concierge']);
 const observed=new Map();let scheduled=false;
 const observer=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
  for(const entry of entries){observed.set(entry.target,entry.isIntersecting);entry.target.toggleAttribute('data-estate-paused',!entry.isIntersecting);}
 }):null;
 function sync(){scheduled=false;for(const node of observed.keys())if(!node.isConnected){observer?.unobserve(node);observed.delete(node);}
  document.querySelectorAll('.clubhouse-scene').forEach(node=>{if(!observed.has(node)){observed.set(node,true);observer?.observe(node);}node.toggleAttribute('data-estate-paused',!observed.get(node));node.querySelectorAll('[data-estate-employee]').forEach(person=>person.setAttribute('data-estate-owned',String(owned.has(person.dataset.estateEmployee))));});
 }
 // 員工走路貼圖（共用 static/assets/staff 的去背 WebP）。尺寸比例：高 190、寬依各圖比例。
 const sprites=[['concierge',94],['host',96],['steward',88]];
 const spriteData={concierge:window.ClubArt.url('staff/concierge.webp'),host:window.ClubArt.url('staff/host.webp'),steward:window.ClubArt.url('staff/steward.webp')};
 function employee(x,y,index){const [key,w]=sprites[index];return `<g transform="translate(${x} ${y})"><g class="estate-walker estate-route-${index}"><g class="estate-person-scale"><ellipse cy="3" rx="${Math.round(w/2.6)}" ry="7" fill="#020a10" opacity=".38"/><g class="estate-flip"><image class="estate-sprite" href="${spriteData[key]}" x="${-w/2}" y="-190" width="${w}" height="190"/></g></g></g></g>`;}
 function render(income){const raw=Number(income?.decor_level),level=Number.isInteger(raw)&&raw>=0&&raw<names.length?raw:0,tier=level+1;
  if(!scheduled){scheduled=true;queueMicrotask(sync);}
  return `<div class="clubhouse-scene estate-tier-${level}" data-estate-level="${level}" role="img" aria-label="裝潢 Lv.${tier} ${names[level]}建築外觀"><picture><source media="(max-width: 760px)" srcset="${window.ClubArt.url('clubhouse/tier-'+tier+'-small.webp')}"><img class="estate-render" src="${window.ClubArt.url('clubhouse/tier-'+tier+'.webp')}" width="1536" height="1024" alt="" decoding="async" draggable="false"></picture><svg class="estate-people" viewBox="0 0 1536 1024" aria-hidden="true">${routes[level].map(([x,y,index])=>`<g data-estate-employee="${employeeKeys[index]}" data-estate-owned="${owned.has(employeeKeys[index])}">${employee(x,y,index)}</g>`).join('')}</svg></div>`;
 }
 document.addEventListener('visibilitychange',()=>document.documentElement.toggleAttribute('data-club-hidden',document.hidden));
 document.documentElement.toggleAttribute('data-club-hidden',document.hidden);
 function staff(employees){owned=new Set((employees||[]).filter(p=>p.owned).map(p=>p.key));sync();}
 return {render,names,staff,sprite:key=>Object.prototype.hasOwnProperty.call(spriteData,key)?spriteData[key]:null};
})();
