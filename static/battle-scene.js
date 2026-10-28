import * as T from './three.module.js?v=0-186-1';

const TAU=Math.PI*2,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const approach=(a,b,t)=>a+(b-a)*(1-Math.exp(-t));
const weaponNames={pistol:'9mm 手槍',smg:'疾風衝鋒槍',rifle:'獵鷹步槍',sniper:'山隼狙擊槍'};
const lootColors={pistol:0xe7c57a,rifle:0xe7c57a,smg:0xe7c57a,sniper:0xd197e5,ammo:0xecce7c,medkit:0xf3f1da,armor:0x77c3d4,helmet:0x77c3d4,grenade:0xf08b61};

export class IslandScene {
  constructor(root,callbacks){
    this.root=root;this.canvas=root.querySelector('.battle-world');this.callbacks=callbacks;
    this.touch=matchMedia('(pointer:coarse)').matches;this.reduced=matchMedia('(prefers-reduced-motion:reduce)').matches;
    this.abort=new AbortController();this.signal=this.abort.signal;this.active=false;this.paused=false;this.weapons={};
    this.actors=new Map();this.items=new Map();this.effects=[];this.grenadeModels=[];this.state=null;this.lastSnapshot=0;this.lastFrame=0;this.elapsed=0;this.frames=0;this.frameAt=performance.now();this.miniAt=0;
    this.keys=new Set();this.control={forward:0,strafe:0,yaw:0,pitch:0,fire:false,aim:false,sprint:false,crouch:false,jump:false};
    this.yaw=0;this.pitch=0;this.stick={x:0,y:0};this.toggles={aim:false,sprint:false,crouch:false};this.holds={};this.drag=null;this.ownPosition=null;this.inputReady=false;this.sound=false;this.audio=null;
    this.renderer=new T.WebGLRenderer({canvas:this.canvas,antialias:!this.touch,alpha:false,powerPreference:'high-performance'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,this.touch?1.25:1.75));this.renderer.outputColorSpace=T.SRGBColorSpace;
    this.renderer.toneMapping=T.ACESFilmicToneMapping;this.renderer.toneMappingExposure=.98;
    this.renderer.shadowMap.enabled=!this.touch;this.renderer.shadowMap.type=T.PCFSoftShadowMap;
    this.scene=new T.Scene();this.scene.background=new T.Color(0xaac3c2);this.scene.fog=new T.Fog(0xaac3c2,100,510);
    this.camera=new T.PerspectiveCamera(65,1,.12,1500);this.camera.position.set(90,66,145);
    this.hemi=new T.HemisphereLight(0xdbf1fa,0x526542,1.8);this.scene.add(this.hemi);
    this.sun=new T.DirectionalLight(0xffe6ac,2.7);this.sun.position.set(-70,110,45);this.sun.castShadow=true;this.sun.shadow.mapSize.set(1024,1024);this.sun.shadow.camera.left=-65;this.sun.shadow.camera.right=65;this.sun.shadow.camera.top=65;this.sun.shadow.camera.bottom=-65;this.sun.shadow.camera.far=260;this.sun.shadow.normalBias=.06;this.scene.add(this.sun,this.sun.target);
    this.geo={box:new T.BoxGeometry(1,1,1),sphere:new T.SphereGeometry(1,10,7),ico:new T.IcosahedronGeometry(1,0),cylinder:new T.CylinderGeometry(1,1,1,7),cone:new T.ConeGeometry(1,1,7)};this.materials=new Map();this.world=new T.Group();this.scene.add(this.world);
    this.effectsGroup=new T.Group();this.scene.add(this.effectsGroup);this.temp=new T.Object3D();this.ray=new T.Raycaster();
    this.zoneMaterial=new T.MeshBasicMaterial({color:0x5dd4ed,transparent:true,opacity:.14,side:T.DoubleSide,depthWrite:false});
    this.zoneWall=new T.Mesh(new T.CylinderGeometry(1,1,65,96,1,true),this.zoneMaterial);this.zoneWall.position.y=29;this.scene.add(this.zoneWall);
    this.zoneRing=new T.Mesh(new T.TorusGeometry(1,.006,3,96),new T.MeshBasicMaterial({color:0x82e7f1,transparent:true,opacity:.8}));this.zoneRing.rotation.x=Math.PI/2;this.zoneRing.position.y=.12;this.scene.add(this.zoneRing);this.zoneWall.visible=false;this.zoneRing.visible=false;
    this.minimap=root.querySelector('.battle-minimap');this.minictx=this.minimap.getContext('2d');
    this.toast=document.createElement('div');this.toast.className='battle-scene-note';this.toast.setAttribute('role','status');root.querySelector('[data-battle-stage]').append(this.toast);
    this.bindInput();this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.canvas);this.resize();
    this.setMap(this.previewMap());this.renderer.setAnimationLoop(time=>this.frame(time));
  }
  material(color,extra={}){const key=color+JSON.stringify(extra);if(!this.materials.has(key))this.materials.set(key,new T.MeshStandardMaterial({color,roughness:.9,metalness:.02,...extra}));return this.materials.get(key);}
  mesh(geometry,color,x,y,z,sx=1,sy=1,sz=1,parent=this.world){const m=new T.Mesh(geometry,this.material(color));m.position.set(x,y,z);m.scale.set(sx,sy,sz);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
  boxes(boxes,color,parent=this.world){if(!boxes.length)return null;const m=new T.InstancedMesh(this.geo.box,this.material(color),boxes.length);boxes.forEach((b,i)=>{this.temp.position.set(b.x,b.y,b.z);this.temp.scale.set(b.w,b.h,b.d);this.temp.rotation.set(0,b.rotation||0,0);this.temp.updateMatrix();m.setMatrixAt(i,this.temp.matrix);});m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
  previewMap(){const structures=[{x:-65,z:-65,w:14,d:12,color:0},{x:-40,z:-65,w:12,d:16,color:1},{x:-65,z:-37,w:16,d:11,color:2},{x:70,z:20,w:13,d:15,color:1},{x:94,z:20,w:13,d:15,color:2},{x:82,z:49,w:20,d:12,color:0},{x:-145,z:105,w:18,d:12,color:2},{x:128,z:-133,w:20,d:13,color:1}];return {seed:41,radius:355,structures,cover:structures.flatMap(b=>[{x:b.x,y:1.6,z:b.z,w:b.w,h:3.2,d:b.d,kind:'preview'}])};}
  random(seed){let n=seed|0;return ()=>{n=(Math.imul(n,1664525)+1013904223)|0;return (n>>>0)/4294967296;};}
  setMap(map){
    this.map=map;this.ownPosition=null;this.inputReady=false;this.state=null;this.lastSnapshot=0;
    for(const g of this.grenadeModels)this.scene.remove(g);this.grenadeModels=[];
    this.clearGroup(this.world);for(const a of this.actors.values())this.scene.remove(a.group);this.actors.clear();for(const item of this.items.values()){item.beam.geometry.dispose();item.beam.material.dispose();this.scene.remove(item.group);}this.items.clear();for(const effect of this.effects)this.removeEffect(effect);this.effects=[];
    const rng=this.random(map.seed),r=map.radius;
    this.mesh(new T.CylinderGeometry(r+30,r+38,4,96),0xc5b37b,0,-2.1,0,1,1,1).receiveShadow=true;
    this.mesh(new T.CylinderGeometry(r,r+6,2,96),0x6e824f,0,-1,0);
    const terrain=new T.RingGeometry(0,r,96,24),colors=[],points=terrain.attributes.position;
    for(let i=0;i<points.count;i++){const x=points.getX(i),z=points.getY(i),tone=Math.sin(x*.025)*Math.cos(z*.019)*.055+Math.sin((x+z)*.09)*.015;const color=new T.Color().setHSL(.24+tone*.3,.23,.33+tone);colors.push(color.r,color.g,color.b);}
    terrain.setAttribute('color',new T.Float32BufferAttribute(colors,3));const grass=new T.Mesh(terrain,this.material(0xffffff,{vertexColors:true}));grass.rotation.x=-Math.PI/2;grass.position.y=.025;grass.receiveShadow=true;this.world.add(grass);
    const water=new T.Mesh(new T.PlaneGeometry(4500,4500),this.material(0x367e95,{metalness:.28,roughness:.36}));water.rotation.x=-Math.PI/2;water.position.y=-2;water.receiveShadow=true;this.world.add(water);
    // Long shore highlights, clustered vegetation and roads establish depth without image downloads.
    const road=[{x:0,y:.015,z:0,w:390,h:.03,d:8},{x:15,y:.018,z:-20,w:8,h:.03,d:380}];this.boxes(road,0x9a9277);
    const marks=[];for(let i=-180;i<=180;i+=16){marks.push({x:i,y:.04,z:0,w:5,h:.012,d:.16});marks.push({x:15,y:.04,z:i,w:.16,h:.012,d:5});}this.boxes(marks,0xd9c99a);
    const grounds=[],roofColors=[0x5b7775,0x9d6550,0x556578],roofs=[[],[],[]],windows=[],frames=[];
    for(const b of map.structures){
      grounds.push({x:b.x,y:.02,z:b.z,w:b.w,h:.05,d:b.d});roofs[b.color%3].push({x:b.x,y:3.65,z:b.z,w:b.w+1.2,h:.65,d:b.d+1.2});
      for(const side of [-1,1])for(const dx of [-b.w*.3,b.w*.3]){windows.push({x:b.x+dx,y:1.9,z:b.z+side*(b.d/2+.23),w:1.25,h:1.1,d:.05});frames.push({x:b.x+dx,y:1.25,z:b.z+side*(b.d/2+.27),w:1.5,h:.1,d:.14});}
      for(const side of [-1,1])windows.push({x:b.x+side*(b.w/2+.23),y:1.9,z:b.z,w:.05,h:1.1,d:1.25});
      frames.push({x:b.x,y:.13,z:b.z+b.d/2+1.1,w:3.4,h:.25,d:2.5});
    }
    this.boxes(grounds,0xb4aa8c);this.boxes(windows,0x31515e);this.boxes(frames,0xe3d3af);
    for(let i=0;i<3;i++)if(roofs[i].length){const roof=new T.InstancedMesh(new T.ConeGeometry(1,1,4),this.material(roofColors[i]),roofs[i].length);roofs[i].forEach((b,index)=>{this.temp.position.set(b.x,4,b.z);this.temp.rotation.set(0,Math.PI/4,0);this.temp.scale.set(b.w/Math.SQRT2,1.6,b.d/Math.SQRT2);this.temp.updateMatrix();roof.setMatrixAt(index,this.temp.matrix);});roof.castShadow=true;roof.receiveShadow=true;this.world.add(roof);}
    this.boxes(map.cover.filter(b=>['wall','preview'].includes(b.kind)),0xc8bd9e);
    this.boxes(map.cover.filter(b=>b.kind==='crate'),0xa27848);
    const rocks=map.cover.filter(b=>b.kind==='rock');if(rocks.length){const mesh=new T.InstancedMesh(this.geo.ico,this.material(0x969c8d),rocks.length);rocks.forEach((b,i)=>{this.temp.position.set(b.x,b.y,b.z);this.temp.rotation.set(rng(),rng()*TAU,rng());this.temp.scale.set(b.w*.7,b.h*.85,b.d*.7);this.temp.updateMatrix();mesh.setMatrixAt(i,this.temp.matrix);});mesh.castShadow=true;mesh.receiveShadow=true;this.world.add(mesh);}
    const trees=map.cover.filter(b=>b.kind==='tree').map(b=>({x:b.x,z:b.z,h:7+rng()*5}));
    // Non-colliding vegetation stays beyond the physical shoreline during matches.
    for(let i=0;i<90;i++){const a=rng()*TAU,rad=map.cover[0]?.kind==='preview'?40+rng()*260:r+10+rng()*10;trees.push({x:Math.sin(a)*rad,z:Math.cos(a)*rad,h:6+rng()*6});}
    if(trees.length){const trunks=new T.InstancedMesh(this.geo.cylinder,this.material(0x79674b),trees.length),foliage=new T.InstancedMesh(this.geo.cone,this.material(0x355d47),trees.length*2);trees.forEach((b,i)=>{this.temp.position.set(b.x,b.h*.3,b.z);this.temp.rotation.set(0,0,0);this.temp.scale.set(.35,b.h*.6,.35);this.temp.updateMatrix();trunks.setMatrixAt(i,this.temp.matrix);for(let k=0;k<2;k++){this.temp.position.set(b.x,b.h*(.57+k*.2),b.z);this.temp.scale.set(b.h*(.33-k*.08),b.h*.55,b.h*(.33-k*.08));this.temp.updateMatrix();foliage.setMatrixAt(i*2+k,this.temp.matrix);}});trunks.castShadow=true;foliage.castShadow=true;this.world.add(trunks,foliage);}
    // Coastline rocks and an offshore signal tower are original, code-made scenery.
    for(let i=0;i<7;i++){const a=i*1.17,rad=r+17;this.mesh(this.geo.ico,0x9caa99,Math.sin(a)*rad,1,Math.cos(a)*rad,12,5,10);}
    for(const [x,z,h] of [[-430,-260,36],[430,-180,51],[-420,270,31],[180,-430,64]]){this.mesh(this.geo.ico,0x6c897c,x,h*.3-3,z,60,h,45);}
    this.mesh(this.geo.cylinder,0xd5cdb5,-225,7,202,3,14,3);this.mesh(this.geo.cone,0xb26843,-225,15,202,4,3,4);
    this.world.traverse(o=>{if(o.isMesh)o.frustumCulled=true;});this.zoneWall.visible=false;this.zoneRing.visible=false;
  }
  actor(id,name){
    const group=new T.Group(),body=new T.Group(),skin=[0xc59b75,0x9a7358,0xd6b38d][Math.abs(id)%3],jacket=[0xc08b44,0x5c8178,0x8d6560,0x708599][Math.abs(id)%4];group.add(body);
    this.mesh(this.geo.box,jacket,0,1.04,0,.6,.65,.32,body);this.mesh(this.geo.box,0x333f40,0,1.08,.19,.44,.5,.22,body);this.mesh(this.geo.box,0x343a3b,0,.69,0,.5,.22,.31,body);
    this.mesh(this.geo.sphere,skin,0,1.65,0,.205,.25,.2,body);const helmet=this.mesh(this.geo.sphere,0x3c4d4c,0,1.78,0,.24,.15,.23,body);this.mesh(this.geo.box,0x273a42,0,1.68,-.18,.32,.085,.05,body);
    const limbs=[];for(const side of [-1,1]){const leg=new T.Group();leg.position.set(side*.17,.65,0);this.mesh(this.geo.box,0x3b4e52,0,-.25,0,.22,.52,.24,leg);this.mesh(this.geo.box,0x293539,0,-.55,-.04,.24,.12,.32,leg);body.add(leg);limbs.push(leg);}
    const arm=new T.Group();arm.position.set(.34,1.25,0);this.mesh(this.geo.box,jacket,0,-.15,-.13,.17,.36,.21,arm);this.mesh(this.geo.box,skin,0,-.32,-.29,.14,.14,.36,arm);body.add(arm);
    const left=this.mesh(this.geo.box,jacket,-.3,1.11,-.24,.17,.21,.5,body);
    const weapon=new T.Group();weapon.position.set(.29,.98,-.51);this.mesh(this.geo.box,0x27343a,0,0,0,.13,.14,.55,weapon);this.mesh(this.geo.cylinder,0x101c23,0,.01,-.36,.045,.4,.045,weapon).rotation.x=Math.PI/2;this.mesh(this.geo.box,0x343c3b,0,-.14,.08,.09,.25,.13,weapon);body.add(weapon);
    const flash=this.mesh(this.geo.cone,0xffe1a3,0,0,-.62,.2,.4,.2,weapon);flash.rotation.x=-Math.PI/2;flash.visible=false;
    this.scene.add(group);return {group,body,limbs,arm,left,weapon,helmet,flash,id,name,target:null,shotAt:-10};
  }
  update(state){
    const now=performance.now();this.state=state;this.lastSnapshot=now;
    const own=state.players.find(p=>p.id===state.self.id);if(own&&!this.inputReady){this.yaw=own.yaw;this.pitch=own.pitch;this.ownPosition=new T.Vector3(own.x,own.y,own.z);this.inputReady=true;}
    const visible=new Set();for(const p of state.players){visible.add(p.id);let a=this.actors.get(p.id);if(!a){a=this.actor(p.id,p.name);a.group.position.set(p.x,p.y,p.z);this.actors.set(p.id,a);}a.target=p;a.group.visible=p.hp>0;a.helmet.visible=p.helmet;a.weapon.visible=!!p.slot;a.weapon.scale.z=p.slot==='pistol'?.63:p.slot==='sniper'?1.35:1;}
    for(const [id,a] of this.actors){if(!visible.has(id))a.group.visible=false;}
    const items=new Set();for(const item of state.loot){items.add(item.id);let art=this.items.get(item.id);if(!art){const group=new T.Group(),color=lootColors[item.kind]||0xe7c57a;const box=new T.Mesh(this.geo.box,this.material(color,{emissive:color,emissiveIntensity:.12}));box.scale.set(item.kind in weaponNames?.75:.5,.2,item.kind in weaponNames?.25:.5);group.add(box);const beam=new T.Mesh(new T.CylinderGeometry(.13,.13,1.4,5),new T.MeshBasicMaterial({color,transparent:true,opacity:.28,depthWrite:false}));beam.position.y=.65;group.add(beam);group.position.set(item.x,.25,item.z);this.scene.add(group);art={group,box,beam};this.items.set(item.id,art);} }
    for(const [id,a] of this.items){if(!items.has(id)){a.beam.geometry.dispose();a.beam.material.dispose();this.scene.remove(a.group);this.items.delete(id);}}
    const grenades=state.grenades.slice(0,32);for(let i=0;i<grenades.length;i++){if(!this.grenadeModels[i]){this.grenadeModels[i]=new T.Mesh(this.geo.sphere,this.material(0x3b4d32));this.grenadeModels[i].scale.setScalar(.18);this.scene.add(this.grenadeModels[i]);}const g=grenades[i];this.grenadeModels[i].position.set(g.x,g.y,g.z);this.grenadeModels[i].visible=true;}
    for(let i=grenades.length;i<this.grenadeModels.length;i++)this.grenadeModels[i].visible=false;
    this.zoneWall.visible=['playing','drop'].includes(state.phase);this.zoneRing.visible=this.zoneWall.visible;this.zoneWall.position.set(state.zone.x,29,state.zone.z);this.zoneWall.scale.set(Math.max(.01,state.zone.r),1,Math.max(.01,state.zone.r));this.zoneRing.position.set(state.zone.x,.12,state.zone.z);this.zoneRing.scale.setScalar(Math.max(.01,state.zone.r));
    if(state.phase==='waiting'){this.clearInput();this.inputReady=false;}
  }
  effect(e){
    if(e.kind==='shot'){
      const a=this.actors.get(e.player);if(a)a.shotAt=this.elapsed;
      if(this.effects.length<45){let origin=new T.Vector3(...e.start);if(a?.group.visible){a.weapon.updateWorldMatrix(true,false);origin=a.weapon.localToWorld(new T.Vector3(0,0,-.62));}const geometry=new T.BufferGeometry().setFromPoints([origin,new T.Vector3(...e.end)]),material=new T.LineBasicMaterial({color:0xffd48a,transparent:true,opacity:.85});const mesh=new T.Line(geometry,material);this.effectsGroup.add(mesh);this.effects.push({mesh,at:this.elapsed,life:.085});}
      if(e.player===this.state?.self.id){this.playShot(this.state.self.slot);if(!this.reduced)this.pitch=clamp(this.pitch+.012,-1.2,1.2);}
    }else if(e.kind==='explosion'){
      const mesh=new T.Mesh(this.geo.sphere,new T.MeshBasicMaterial({color:0xffba66,transparent:true,opacity:.8,depthWrite:false}));mesh.position.set(e.x,e.y+1,e.z);this.effectsGroup.add(mesh);this.effects.push({mesh,at:this.elapsed,life:.6,explosion:true});this.playShot('explosion');
    }else if(e.kind==='hit'&&e.player===this.state?.self.id){this.root.classList.remove('battle-damaged');void this.root.offsetWidth;this.root.classList.add('battle-damaged');}
  }
  input(){
    const blocked=this.paused||!this.active||document.hidden;
    const input={forward:blocked?0:clamp(Number(this.keys.has('KeyW'))-Number(this.keys.has('KeyS'))-this.stick.y,-1,1),strafe:blocked?0:clamp(Number(this.keys.has('KeyD'))-Number(this.keys.has('KeyA'))+this.stick.x,-1,1),yaw:this.yaw,pitch:this.pitch,fire:!blocked&&(!!this.holds.fire||this.keys.has('KeyF')),aim:!blocked&&(!!this.holds.aim||this.toggles.aim),sprint:!blocked&&(this.keys.has('ShiftLeft')||this.keys.has('ShiftRight')||this.toggles.sprint),crouch:!blocked&&(this.keys.has('KeyC')||this.toggles.crouch),jump:!blocked&&this.control.jump};this.control.jump=false;this.control={...input,jump:false};return input;
  }
  clearInput(){this.keys.clear();this.stick={x:0,y:0};this.holds={};this.toggles={aim:false,sprint:false,crouch:false};this.control={...this.control,forward:0,strafe:0,fire:false,aim:false,sprint:false,crouch:false,jump:false};this.drag=null;for(const b of this.root.querySelectorAll('[data-battle-toggle]'))b.setAttribute('aria-pressed','false');const stick=this.root.querySelector('[data-battle-stick] span');if(stick)stick.style.transform='translate(-50%,-50%)';}
  pause(value){this.paused=value;if(value){this.clearInput();if(document.pointerLockElement===this.canvas)document.exitPointerLock();}}
  reset(){this.clearInput();this.active=false;this.paused=false;this.state=null;this.inputReady=false;this.zoneWall.visible=false;this.zoneRing.visible=false;for(const a of this.actors.values())a.group.visible=false;for(const item of this.items.values())item.group.visible=false;this.camera.position.set(90,66,145);}
  bindInput(){
    const on=(target,name,fn,extra={})=>target.addEventListener(name,fn,{signal:this.signal,...extra});
    on(window,'keydown',e=>{if(!this.root.isConnected||e.target.closest('input,select,textarea,dialog')||!this.state||this.state.phase==='waiting')return;if(e.code==='Escape'){this.callbacks.pause();return;}if(this.paused||!this.active)return;if(['Space','KeyW','KeyA','KeyS','KeyD','ShiftLeft','ShiftRight','KeyC','KeyE','KeyR','KeyH','KeyG','KeyF','Digit1','Digit2'].includes(e.code))e.preventDefault();this.keys.add(e.code);if(e.repeat)return;if(e.code==='Space')this.control.jump=true;const actions={KeyE:'pickup',KeyR:'reload',KeyH:'heal',KeyG:'grenade'};if(actions[e.code])this.callbacks.action(actions[e.code]);if(e.code==='Digit1'||e.code==='Digit2'){const slot=Object.keys(this.state.self.weapons)[e.code==='Digit1'?0:1];if(slot)this.callbacks.action('slot',slot);}});
    on(window,'keyup',e=>this.keys.delete(e.code));on(window,'blur',()=>this.clearInput());
    on(this.canvas,'contextmenu',e=>e.preventDefault());
    on(this.canvas,'pointerdown',e=>{if(!this.active||this.paused)return;if(this.touch||e.pointerType==='touch'){this.canvas.setPointerCapture(e.pointerId);this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};return;}if(document.pointerLockElement!==this.canvas){try{this.canvas.requestPointerLock()?.catch(()=>this.notify('按住畫面拖曳，也能轉動視角。'));}catch{}this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};this.canvas.setPointerCapture(e.pointerId);this.canvas.focus();}else if(e.button===0)this.holds.fire=true;else if(e.button===2)this.holds.aim=true;});
    on(window,'pointermove',e=>{if(this.paused||!this.active)return;if(document.pointerLockElement===this.canvas){this.yaw+=e.movementX*.0025;this.pitch=clamp(this.pitch-e.movementY*.0022,-1.2,1.2);}else if(this.drag?.id===e.pointerId){this.yaw+=(e.clientX-this.drag.x)*.006;this.pitch=clamp(this.pitch-(e.clientY-this.drag.y)*.005,-1.2,1.2);this.drag.x=e.clientX;this.drag.y=e.clientY;}this.yaw=((this.yaw+Math.PI)%TAU+TAU)%TAU-Math.PI;});
    on(window,'pointerup',e=>{if(this.drag?.id===e.pointerId)this.drag=null;if(e.pointerType==='mouse'){if(e.button===0)this.holds.fire=false;if(e.button===2)this.holds.aim=false;}});on(this.canvas,'pointercancel',()=>this.clearInput());
    on(document,'pointerlockchange',()=>{if(!document.pointerLockElement&&this.active&&!this.paused)this.callbacks.pause();});
    const stick=this.root.querySelector('[data-battle-stick]');let stickId=null;const move=e=>{const box=stick.getBoundingClientRect(),dx=e.clientX-box.x-box.width/2,dy=e.clientY-box.y-box.height/2,r=box.width*.38,length=Math.hypot(dx,dy),scale=Math.max(1,length/r);this.stick={x:dx/scale/r,y:dy/scale/r};stick.querySelector('span').style.transform=`translate(calc(-50% + ${dx/scale}px),calc(-50% + ${dy/scale}px))`;};
    on(stick,'pointerdown',e=>{e.preventDefault();stickId=e.pointerId;stick.setPointerCapture(e.pointerId);move(e);});on(stick,'pointermove',e=>{if(e.pointerId===stickId)move(e);});for(const event of ['pointerup','pointercancel','lostpointercapture'])on(stick,event,()=>{stickId=null;this.stick={x:0,y:0};stick.querySelector('span').style.transform='translate(-50%,-50%)';});
    for(const b of this.root.querySelectorAll('[data-battle-hold]')){on(b,'pointerdown',e=>{e.preventDefault();b.setPointerCapture(e.pointerId);this.holds[b.dataset.battleHold]=true;b.classList.add('pressed');});for(const event of ['pointerup','pointercancel','lostpointercapture'])on(b,event,()=>{this.holds[b.dataset.battleHold]=false;b.classList.remove('pressed');});}
    for(const b of this.root.querySelectorAll('[data-battle-toggle]'))on(b,'click',()=>{const key=b.dataset.battleToggle;this.toggles[key]=!this.toggles[key];b.setAttribute('aria-pressed',String(this.toggles[key]));});
    on(this.root.querySelector('[data-battle-jump]'),'click',()=>this.control.jump=true);
  }
  safe(x,z,y){if(Math.hypot(x,z)>this.map.radius-.5)return false;return !this.map.cover.some(b=>y+1.8>b.y-b.h/2&&y<b.y+b.h/2&&Math.abs(x-b.x)<b.w/2+.45&&Math.abs(z-b.z)<b.d/2+.45);}
  frame(time){
    if(document.hidden)return;const cap=this.touch||this.reduced?30:60;if(time-this.lastFrame<1000/cap-1)return;const dt=Math.min(.06,(time-this.lastFrame)/1000||.016);this.lastFrame=time;this.elapsed+=dt;this.frames++;
    if(!this.state||this.state.phase==='waiting'){
      this.camera.position.set(90+(this.reduced?0:Math.sin(this.elapsed*.035)*12),66,145);this.camera.lookAt(-15,0,-60);
    }else{
      const s=this.state,own=s.players.find(p=>p.id===s.self.id),age=Math.min(.18,(performance.now()-this.lastSnapshot)/1000);
      for(const a of this.actors.values()){const p=a.target;if(!p||!a.group.visible)continue;
        if(p.id===s.self.id&&own&&s.self.hp>0){
          if(!this.ownPosition)this.ownPosition=new T.Vector3(p.x,p.y,p.z);
          if(s.phase==='playing'&&this.active&&!this.paused){const c=this.control,speed=(c.sprint&&!c.aim&&!c.crouch&&s.self.stamina>0?7.5:c.crouch?2.2:4.5)*(s.self.heal?.35:1),n=Math.max(1,Math.hypot(c.forward,c.strafe));const dx=(Math.sin(this.yaw)*c.forward+Math.cos(this.yaw)*c.strafe)*speed/n*dt,dz=(-Math.cos(this.yaw)*c.forward+Math.sin(this.yaw)*c.strafe)*speed/n*dt;if(this.safe(this.ownPosition.x+dx,this.ownPosition.z,p.y))this.ownPosition.x+=dx;if(this.safe(this.ownPosition.x,this.ownPosition.z+dz,p.y))this.ownPosition.z+=dz;}
          const error=Math.hypot(this.ownPosition.x-(p.x+p.vx*age),this.ownPosition.z-(p.z+p.vz*age));const speed=error>3?40:10;
          this.ownPosition.x=approach(this.ownPosition.x,p.x+p.vx*age,dt*speed);this.ownPosition.z=approach(this.ownPosition.z,p.z+p.vz*age,dt*speed);this.ownPosition.y=approach(this.ownPosition.y,p.y,dt*20);a.group.position.copy(this.ownPosition);
        }else{a.group.position.x=approach(a.group.position.x,p.x+p.vx*age,dt*15);a.group.position.z=approach(a.group.position.z,p.z+p.vz*age,dt*15);a.group.position.y=approach(a.group.position.y,p.y,dt*15);}
        const turn=-p.yaw-a.body.rotation.y;a.body.rotation.y=p.id===s.self.id?-this.yaw:a.body.rotation.y+Math.atan2(Math.sin(turn),Math.cos(turn))*(1-Math.exp(-dt*12));const moving=p.animation==='run',crouch=p.animation==='crouch';a.body.position.y=crouch?-.48:0;a.limbs.forEach((leg,i)=>{leg.position.y=crouch?.8:.65;leg.rotation.x=crouch?-1.1:moving?Math.sin(this.elapsed*11+i*Math.PI+p.id)*.65:0;});a.arm.rotation.x=-p.pitch*.7;a.weapon.rotation.x=-p.pitch;a.flash.visible=this.elapsed-a.shotAt<.055;a.weapon.position.z=-.51+(this.elapsed-a.shotAt<.09?.055:0);
        if(p.animation==='drop'){a.body.position.y=0;a.arm.rotation.x=-2;a.left.rotation.x=-2;if(!a.chute){a.chute=this.mesh(this.geo.sphere,0xcdab67,0,4.7,0,2.9,.7,2.3,a.group);for(const side of [-1,1]){const line=this.mesh(this.geo.cylinder,0xe9dfbd,side*1.2,3,0,.015,3.6,.015,a.group);line.rotation.z=side*.25;a.chute.userData.lines??=[];a.chute.userData.lines.push(line);}}a.chute.visible=true;for(const l of a.chute.userData.lines)l.visible=true;}else if(a.chute){a.chute.visible=false;for(const l of a.chute.userData.lines)l.visible=false;a.left.rotation.x=0;}
      }
      const follow=s.self.hp>0?this.actors.get(s.self.id):[...this.actors.values()].find(a=>a.target?.hp>0&&a.group.visible);
      if(follow){const pos=follow.group.position,yaw=s.self.hp>0?this.yaw:follow.target.yaw,pitch=s.self.hp>0?this.pitch:0,aim=this.control.aim&&s.self.hp>0;
        const portrait=this.canvas.clientWidth<this.canvas.clientHeight;
        const distance=aim ? 1.15 : 4.7,side=aim ? .32 : (portrait ? .42 : 1.7);
        const desired=new T.Vector3(pos.x-Math.sin(yaw)*distance+Math.cos(yaw)*side,pos.y+2.5-pitch*1.5,pos.z+Math.cos(yaw)*distance+Math.sin(yaw)*side);
        const target=new T.Vector3(pos.x,pos.y+1.65,pos.z);const difference=desired.clone().sub(target),length=difference.length();this.ray.set(target,difference.normalize());
        // Camera collision uses cheap server-box intersections, avoiding a huge mesh raycast.
        let hit=length;for(const b of this.map.cover){const d=this.boxRay(target,this.ray.ray.direction,b,hit);if(d!==null)hit=Math.max(.3,d-.25);}if(hit<length)desired.copy(target).addScaledVector(this.ray.ray.direction,hit);
        this.camera.position.lerp(desired,1-Math.exp(-dt*18));this.camera.lookAt(pos.x+Math.sin(yaw)*Math.cos(pitch)*30,pos.y+1.55+Math.sin(pitch)*30,pos.z-Math.cos(yaw)*Math.cos(pitch)*30);this.camera.fov=approach(this.camera.fov,aim?44:65,dt*12);this.camera.updateProjectionMatrix();
        this.sun.position.set(pos.x-70,pos.y+110,pos.z+45);this.sun.target.position.set(pos.x,0,pos.z);
        const outside=Math.hypot(pos.x-s.zone.x,pos.z-s.zone.z)>s.zone.r;this.root.classList.toggle('battle-outside-zone',outside);const compass=this.root.querySelector('[data-battle-compass]');compass.textContent=['北','東北','東','東南','南','西南','西','西北'][Math.round(((yaw/TAU*8)%8+8)%8)%8]+' '+Math.round(((yaw/TAU*360)%360+360)%360)+'°';
        if(time-this.miniAt>150){this.minimapDraw(pos,yaw);this.miniAt=time;}
      }
    }
    for(const e of this.effects.slice()){const age=this.elapsed-e.at;if(age>e.life){this.removeEffect(e);this.effects.splice(this.effects.indexOf(e),1);continue;}e.mesh.material.opacity=(1-age/e.life)*.8;if(e.explosion)e.mesh.scale.setScalar(1+age*13);}
    if(this.elapsed>this.toastUntil)this.toast.classList.remove('show');
    this.renderer.render(this.scene,this.camera);
    if(time-this.frameAt>=1000){this.root.dataset.battleFps=String(Math.round(this.frames*1000/(time-this.frameAt)));this.root.dataset.battleDrawCalls=String(this.renderer.info.render.calls);this.root.dataset.battleTriangles=String(this.renderer.info.render.triangles);this.frames=0;this.frameAt=time;}
  }
  boxRay(origin,direction,b,max){let low=0,high=max;for(const [key,size] of [['x','w'],['y','h'],['z','d']]){const a=b[key]-b[size]/2,c=b[key]+b[size]/2;if(Math.abs(direction[key])<1e-8){if(origin[key]<a||origin[key]>c)return null;}else{const u=(a-origin[key])/direction[key],v=(c-origin[key])/direction[key];low=Math.max(low,Math.min(u,v));high=Math.min(high,Math.max(u,v));if(high<low)return null;}}return low;}
  minimapDraw(pos,yaw){const c=this.minictx,s=this.state;if(!c||!s)return;const n=168,scale=n/800;c.clearRect(0,0,n,n);c.fillStyle='#123740';c.fillRect(0,0,n,n);c.save();c.translate(n/2,n/2);c.scale(scale,scale);c.fillStyle='#496451';c.beginPath();c.arc(0,0,this.map.radius,0,TAU);c.fill();c.fillStyle='#b0b396';for(const b of this.map.structures)c.fillRect(b.x-b.w/2,b.z-b.d/2,b.w,b.d);c.strokeStyle='#a5e9ee';c.lineWidth=2/scale;c.beginPath();c.arc(s.zone.x,s.zone.z,s.zone.r,0,TAU);c.stroke();c.strokeStyle='#fff3b4';c.lineWidth=1/scale;c.setLineDash([6/scale,5/scale]);c.beginPath();c.arc(s.zone.next_x,s.zone.next_z,s.zone.next_r,0,TAU);c.stroke();c.setLineDash([]);c.translate(pos.x,pos.z);c.rotate(yaw);c.fillStyle='#fff3b4';c.beginPath();c.moveTo(0,-11/scale);c.lineTo(-5/scale,5/scale);c.lineTo(5/scale,5/scale);c.closePath();c.fill();c.restore();c.fillStyle='#e8f3ef';c.font='bold 11px sans-serif';c.fillText('北',78,14);}
  resize(){const width=this.canvas.clientWidth,height=this.canvas.clientHeight;if(!width||!height)return;this.renderer.setSize(width,height,false);this.camera.aspect=width/height;this.camera.updateProjectionMatrix();}
  notify(message){this.toast.textContent=message;this.toast.classList.add('show');this.toastUntil=this.elapsed+3;}
  async toggleSound(){if(!this.sound){this.audio??=new(window.AudioContext||window.webkitAudioContext)();await this.audio.resume();this.sound=true;}else this.sound=false;return this.sound;}
  playShot(kind){if(!this.sound||!this.audio||this.audio.state!=='running')return;const audio=this.audio,now=audio.currentTime,osc=audio.createOscillator(),gain=audio.createGain();osc.type='sawtooth';osc.frequency.setValueAtTime(kind==='explosion'?65:kind==='sniper'?170:260,now);osc.frequency.exponentialRampToValueAtTime(35,now+.11);gain.gain.setValueAtTime(.045,now);gain.gain.exponentialRampToValueAtTime(.0001,now+.13);osc.connect(gain).connect(audio.destination);osc.start();osc.stop(now+.14);osc.onended=()=>{osc.disconnect();gain.disconnect();};}
  removeEffect(e){this.effectsGroup.remove(e.mesh);if(e.mesh.geometry!==this.geo.sphere)e.mesh.geometry.dispose();e.mesh.material.dispose();}
  clearGroup(group){for(const child of [...group.children]){child.traverse(o=>{if(o.geometry&&!Object.values(this.geo).includes(o.geometry))o.geometry.dispose();if(o.isInstancedMesh)o.dispose();});group.remove(child);}}
  destroy(){this.abort.abort();this.observer.disconnect();if(document.pointerLockElement===this.canvas)document.exitPointerLock();this.renderer.setAnimationLoop(null);for(const e of this.effects)this.removeEffect(e);this.effects=[];this.scene.traverse(o=>{o.geometry?.dispose();if(Array.isArray(o.material))o.material.forEach(m=>m.dispose());else o.material?.dispose();});for(const m of this.materials.values())m.dispose();Object.values(this.geo).forEach(g=>g.dispose());this.renderer.dispose();this.renderer.forceContextLoss();void this.audio?.close().catch(()=>{});this.toast.remove();}
}
