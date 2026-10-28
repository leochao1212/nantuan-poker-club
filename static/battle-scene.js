import * as T from './three.module.js?v=0-186-1';

const RAY_AXES=[['x','w'],['y','h'],['z','d']];
const TAU=Math.PI*2,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const approach=(a,b,t)=>a+(b-a)*(1-Math.exp(-t));
const weaponNames={pistol:'9mm 手槍',smg:'疾風衝鋒槍',rifle:'獵鷹步槍',sniper:'山隼狙擊槍'};
const lootColors={pistol:0xe7c57a,rifle:0xe7c57a,smg:0xe7c57a,sniper:0xd197e5,ammo:0xecce7c,medkit:0xf3f1da,armor:0x77c3d4,helmet:0x77c3d4,grenade:0xf08b61};

export class IslandScene {
  constructor(root,callbacks){
    this.root=root;this.canvas=root.querySelector('.battle-world');this.callbacks=callbacks;
    this.touch=matchMedia('(pointer:coarse)').matches;this.reduced=matchMedia('(prefers-reduced-motion:reduce)').matches;
    this.abort=new AbortController();this.signal=this.abort.signal;this.active=false;this.paused=false;this.weapons={};
    this.actors=new Map();this.items=new Map();this.grenadeModels=[];this.state=null;this.lastSnapshot=0;this.lastFrame=0;this.elapsed=0;this.frames=0;this.frameAt=performance.now();this.miniAt=0;
    this.keys=new Set();this.control={forward:0,strafe:0,yaw:0,pitch:0,fire:false,aim:false,sprint:false,crouch:false,jump:false};
    this.yaw=0;this.pitch=0;this.stick={x:0,y:0};this.toggles={aim:false,sprint:false,crouch:false};this.holds={};this.fireQueued=false;this.drag=null;this.ownPosition=null;this.inputReady=false;this.sound=false;this.audio=null;
    this.targetFps=this.reduced?30:60;this.pixelRatio=Math.min(devicePixelRatio,this.touch?1:1.25);this.qualityAt=0;this.frameGaps=[];
    this.renderer=new T.WebGLRenderer({canvas:this.canvas,antialias:false,alpha:false,powerPreference:'high-performance'});
    this.renderer.setPixelRatio(this.pixelRatio);this.renderer.outputColorSpace=T.SRGBColorSpace;
    this.renderer.toneMapping=T.ACESFilmicToneMapping;this.renderer.toneMappingExposure=.98;
    this.renderer.shadowMap.enabled=false;
    this.scene=new T.Scene();this.scene.background=new T.Color(0xaac3c2);this.scene.fog=new T.Fog(0xaac3c2,100,510);
    this.camera=new T.PerspectiveCamera(65,1,.12,1500);this.camera.position.set(90,66,145);
    this.hemi=new T.HemisphereLight(0xdbf1fa,0x526542,1.8);this.scene.add(this.hemi);
    this.sun=new T.DirectionalLight(0xffe6ac,2.7);this.sun.position.set(-70,110,45);this.scene.add(this.sun,this.sun.target);
    this.geo={box:new T.BoxGeometry(1,1,1),sphere:new T.SphereGeometry(1,10,7),ico:new T.IcosahedronGeometry(1,0),cylinder:new T.CylinderGeometry(1,1,1,7),cone:new T.ConeGeometry(1,1,7)};this.materials=new Map();this.world=new T.Group();this.scene.add(this.world);
    this.effectsGroup=new T.Group();this.scene.add(this.effectsGroup);this.temp=new T.Object3D();this.ray=new T.Raycaster();
    this.actorBatches=new Map();for(const key of ['box','sphere','cylinder','cone']){const mesh=new T.InstancedMesh(this.geo[key],this.material(0xffffff),512);mesh.instanceMatrix.setUsage(T.DynamicDrawUsage);mesh.count=0;mesh.frustumCulled=false;this.actorBatches.set(key,mesh);this.scene.add(mesh);}
    this.actorShadows=new T.InstancedMesh(new T.CircleGeometry(.7,12),new T.MeshBasicMaterial({color:0x122823,transparent:true,opacity:.18,depthWrite:false}),16);this.actorShadows.count=0;this.actorShadows.frustumCulled=false;this.actorShadows.instanceMatrix.setUsage(T.DynamicDrawUsage);this.scene.add(this.actorShadows);this.batchWhite=new T.Color(0xffffff);
    this.lootBoxes=new T.InstancedMesh(this.geo.box,this.material(0xffffff),256);this.lootBeams=new T.InstancedMesh(this.geo.cylinder,new T.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:.22,depthWrite:false}),256);
    for(const mesh of [this.lootBoxes,this.lootBeams]){mesh.count=0;mesh.frustumCulled=false;mesh.instanceMatrix.setUsage(T.DynamicDrawUsage);this.scene.add(mesh);}
    this.traceSlots=Array.from({length:48},()=>({start:new T.Vector3(),end:new T.Vector3(),at:-10,life:.13}));this.traceCursor=0;
    this.traceGeometry=new T.BufferGeometry();this.tracePositions=new T.BufferAttribute(new Float32Array(48*6),3).setUsage(T.DynamicDrawUsage);this.traceColors=new T.BufferAttribute(new Float32Array(48*6),3).setUsage(T.DynamicDrawUsage);this.traceGeometry.setAttribute('position',this.tracePositions);this.traceGeometry.setAttribute('color',this.traceColors);this.traceGeometry.setDrawRange(0,0);this.traces=new T.LineSegments(this.traceGeometry,new T.LineBasicMaterial({vertexColors:true,transparent:true,opacity:.9,depthWrite:false}));this.traces.frustumCulled=false;this.effectsGroup.add(this.traces);
    this.explosions=Array.from({length:6},()=>{const mesh=new T.Mesh(this.geo.sphere,new T.MeshBasicMaterial({color:0xffba66,transparent:true,opacity:.8,depthWrite:false}));mesh.visible=false;this.effectsGroup.add(mesh);return {mesh,at:-10,life:.6};});
    this.actorFrustum=new T.Frustum();this.frustumMatrix=new T.Matrix4();this.actorBounds=new T.Sphere(new T.Vector3(),5);this.previewDirection=new T.Vector3();this.correction=new T.Vector3();this.cameraTarget=new T.Vector3();this.cameraDesired=new T.Vector3();this.cameraDelta=new T.Vector3();this.localAmmo=0;this.lastServerAmmo=0;this.localSlot='';this.localNextShot=0;this.localVisuals=[];
    this.zoneMaterial=new T.MeshBasicMaterial({color:0x5dd4ed,transparent:true,opacity:.14,side:T.DoubleSide,depthWrite:false});
    this.zoneWall=new T.Mesh(new T.CylinderGeometry(1,1,65,96,1,true),this.zoneMaterial);this.zoneWall.position.y=29;this.scene.add(this.zoneWall);
    this.zoneRing=new T.Mesh(new T.TorusGeometry(1,.006,3,96),new T.MeshBasicMaterial({color:0x82e7f1,transparent:true,opacity:.8}));this.zoneRing.rotation.x=Math.PI/2;this.zoneRing.position.y=.12;this.scene.add(this.zoneRing);this.zoneWall.visible=false;this.zoneRing.visible=false;
    this.minimap=root.querySelector('.battle-minimap');this.minictx=this.minimap.getContext('2d');
    this.toast=document.createElement('div');this.toast.className='battle-scene-note';this.toast.setAttribute('role','status');root.querySelector('[data-battle-stage]').append(this.toast);
    this.damage=document.createElement('div');this.damage.className='battle-damage';this.damage.setAttribute('aria-hidden','true');root.querySelector('[data-battle-stage]').append(this.damage);this.compass=root.querySelector('[data-battle-compass]');this.stickKnob=root.querySelector('[data-battle-stick] span');this.bindInput();this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.canvas);this.resize();
    this.setMap(this.previewMap());this.animate=time=>this.frame(time);this.renderer.setAnimationLoop(this.animate);
  }
  material(color,extra={}){const key=color+JSON.stringify(extra);if(!this.materials.has(key)){this.materials.set(key,new T.MeshLambertMaterial({color,...extra}));}return this.materials.get(key);}
  mesh(geometry,color,x,y,z,sx=1,sy=1,sz=1,parent=this.world){const m=new T.Mesh(geometry,this.material(color));m.position.set(x,y,z);m.scale.set(sx,sy,sz);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
  boxes(boxes,color,parent=this.world){if(!boxes.length)return null;const m=new T.InstancedMesh(this.geo.box,this.material(color),boxes.length);boxes.forEach((b,i)=>{this.temp.position.set(b.x,b.y,b.z);this.temp.scale.set(b.w,b.h,b.d);this.temp.rotation.set(0,b.rotation||0,0);this.temp.updateMatrix();m.setMatrixAt(i,this.temp.matrix);});m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
  previewMap(){const structures=[{x:-65,z:-65,w:14,d:12,color:0},{x:-40,z:-65,w:12,d:16,color:1},{x:-65,z:-37,w:16,d:11,color:2},{x:70,z:20,w:13,d:15,color:1},{x:94,z:20,w:13,d:15,color:2},{x:82,z:49,w:20,d:12,color:0},{x:-145,z:105,w:18,d:12,color:2},{x:128,z:-133,w:20,d:13,color:1}];return {seed:-1,radius:355,structures,cover:structures.flatMap(b=>[{x:b.x,y:1.6,z:b.z,w:b.w,h:3.2,d:b.d,kind:'preview'}])};}
  random(seed){let n=seed|0;return ()=>{n=(Math.imul(n,1664525)+1013904223)|0;return (n>>>0)/4294967296;};}
  setMap(map){
    // Rejoining the same round must not rebuild GPU resources or reset the view.
    if(this.map?.seed===map.seed)return false;
    this.map=map;this.coverGrid=new Map();for(const box of map.cover)for(let x=Math.floor((box.x-box.w/2-8)/24);x<=Math.floor((box.x+box.w/2+8)/24);x++)for(let z=Math.floor((box.z-box.d/2-8)/24);z<=Math.floor((box.z+box.d/2+8)/24);z++){const key=x+':'+z;if(!this.coverGrid.has(key))this.coverGrid.set(key,[]);this.coverGrid.get(key).push(box);}this.ownPosition=null;this.inputReady=false;this.state=null;this.lastSnapshot=0;
    this.mapBuilds=(this.mapBuilds||0)+1;this.root.dataset.battleMapBuilds=String(this.mapBuilds);this.clearInput();this.correction.set(0,0,0);this.localSlot='';this.localNextShot=0;this.clearTransient();for(const mesh of this.actorBatches.values())mesh.count=0;this.actorShadows.count=this.lootBoxes.count=this.lootBeams.count=0;
    for(const g of this.grenadeModels)this.scene.remove(g);this.grenadeModels=[];
    this.clearGroup(this.world);this.actors.clear();this.items.clear();
    const rng=this.random(map.seed),r=map.radius;
    this.mesh(new T.CylinderGeometry(r+30,r+38,4,96),0xc5b37b,0,-2.1,0,1,1,1).receiveShadow=true;
    this.mesh(new T.CylinderGeometry(r,r+6,2,96),0x6e824f,0,-1,0);
    const terrain=new T.RingGeometry(0,r,96,24),colors=[],points=terrain.attributes.position;
    for(let i=0;i<points.count;i++){const x=points.getX(i),z=points.getY(i),tone=Math.sin(x*.025)*Math.cos(z*.019)*.055+Math.sin((x+z)*.09)*.015;const color=new T.Color().setHSL(.24+tone*.3,.23,.33+tone);colors.push(color.r,color.g,color.b);}
    terrain.setAttribute('color',new T.Float32BufferAttribute(colors,3));const grass=new T.Mesh(terrain,this.material(0xffffff,{vertexColors:true}));grass.rotation.x=-Math.PI/2;grass.position.y=.025;grass.receiveShadow=true;this.world.add(grass);
    const water=new T.Mesh(new T.PlaneGeometry(4500,4500),this.material(0x367e95));water.rotation.x=-Math.PI/2;water.position.y=-2;water.receiveShadow=true;this.world.add(water);
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
    const parts=[],part=(...args)=>this.actorPart(parts,...args),group=new T.Group(),body=new T.Group(),skin=[0xc59b75,0x9a7358,0xd6b38d][Math.abs(id)%3],jacket=[0xc08b44,0x5c8178,0x8d6560,0x708599][Math.abs(id)%4];group.add(body);
    part(this.geo.box,jacket,0,1.04,0,.6,.65,.32,body);part(this.geo.box,0x333f40,0,1.08,.19,.44,.5,.22,body);part(this.geo.box,0x343a3b,0,.69,0,.5,.22,.31,body);
    part(this.geo.sphere,skin,0,1.65,0,.205,.25,.2,body);const helmet=part(this.geo.sphere,0x3c4d4c,0,1.78,0,.24,.15,.23,body);part(this.geo.box,0x273a42,0,1.68,-.18,.32,.085,.05,body);
    const limbs=[];for(const side of [-1,1]){const leg=new T.Group();leg.position.set(side*.17,.65,0);part(this.geo.box,0x3b4e52,0,-.25,0,.22,.52,.24,leg);part(this.geo.box,0x293539,0,-.55,-.04,.24,.12,.32,leg);body.add(leg);limbs.push(leg);}
    const arm=new T.Group();arm.position.set(.34,1.25,0);part(this.geo.box,jacket,0,-.15,-.13,.17,.36,.21,arm);part(this.geo.box,skin,0,-.32,-.29,.14,.14,.36,arm);body.add(arm);
    const left=part(this.geo.box,jacket,-.3,1.11,-.24,.17,.21,.5,body);
    const weapon=new T.Group();weapon.position.set(.29,.98,-.51);part(this.geo.box,0x27343a,0,0,0,.13,.14,.55,weapon);part(this.geo.cylinder,0x101c23,0,.01,-.36,.045,.4,.045,weapon).rotation.x=Math.PI/2;part(this.geo.box,0x343c3b,0,-.14,.08,.09,.25,.13,weapon);body.add(weapon);
    const flash=part(this.geo.cone,0xffe1a3,0,0,-.62,.2,.4,.2,weapon);flash.rotation.x=-Math.PI/2;flash.visible=false;
    const chute=part(this.geo.sphere,0xcdab67,0,4.7,0,2.9,.7,2.3,group);chute.visible=false;chute.userData.lines=[];for(const side of [-1,1]){const line=part(this.geo.cylinder,0xe9dfbd,side*1.2,3,0,.015,3.6,.015,group);line.rotation.z=side*.25;line.visible=false;chute.userData.lines.push(line);}
    // Detached skeletons supply matrices; only the four shared batches enter the renderer.
    return {group,body,limbs,arm,left,weapon,helmet,flash,chute,parts,id,name,target:null,from:new T.Vector3(),receivedAt:0,shotAt:-10,flashFrames:0};
  }
  actorPart(parts,geometry,color,x,y,z,sx=1,sy=1,sz=1,parent){const node=new T.Object3D();node.position.set(x,y,z);node.scale.set(sx,sy,sz);node.userData.part={key:Object.keys(this.geo).find(key=>this.geo[key]===geometry),color:new T.Color(color)};parent.add(node);parts.push(node);return node;}
  updateActorBatches(){
    const counts={box:0,sphere:0,cylinder:0,cone:0};
    this.camera.updateMatrixWorld(true);this.actorFrustum.setFromProjectionMatrix(this.frustumMatrix.multiplyMatrices(this.camera.projectionMatrix,this.camera.matrixWorldInverse));
    for(const actor of this.actors.values()){this.actorBounds.center.copy(actor.group.position);this.actorBounds.center.y+=2.5;actor.inFrustum=actor.group.visible&&(actor.id===this.state.self.id||this.actorFrustum.intersectsSphere(this.actorBounds));if(!actor.inFrustum)continue;actor.group.updateMatrixWorld(true);for(const part of actor.parts){let shown=true;for(let node=part;node&&node!==actor.group;node=node.parent)if(!node.visible){shown=false;break;}if(!shown)continue;const {key,color}=part.userData.part,mesh=this.actorBatches.get(key),i=counts[key]++;if(i>=512)continue;mesh.setMatrixAt(i,part.matrixWorld);mesh.setColorAt(i,color);}}
    for(const [key,mesh] of this.actorBatches){mesh.count=Math.min(512,counts[key]);if(!mesh.count){this.temp.position.set(0,-10000,0);this.temp.rotation.set(0,0,0);this.temp.scale.set(1,1,1);this.temp.updateMatrix();mesh.setMatrixAt(0,this.temp.matrix);mesh.setColorAt(0,this.batchWhite);mesh.count=1;}mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor){mesh.instanceColor.setUsage(T.DynamicDrawUsage);mesh.instanceColor.needsUpdate=true;}}
    let shadows=0;for(const actor of this.actors.values()){if(!actor.inFrustum||shadows>=16)continue;const pos=actor.group.position,scale=.9/(1+Math.max(0,pos.y)*.02);this.temp.position.set(pos.x,.07,pos.z);this.temp.rotation.set(-Math.PI/2,0,0);this.temp.scale.set(scale,scale,1);this.temp.updateMatrix();this.actorShadows.setMatrixAt(shadows++,this.temp.matrix);}this.actorShadows.count=shadows;this.actorShadows.instanceMatrix.needsUpdate=true;
  }
  updateLoot(items){
    this.items.clear();this.lootColorCache??=new Map();let i=0;
    for(const item of items){if(i>=256)break;this.items.set(item.id,item);if(!this.lootColorCache.has(item.kind))this.lootColorCache.set(item.kind,new T.Color(lootColors[item.kind]||0xe7c57a));const color=this.lootColorCache.get(item.kind);this.temp.rotation.set(0,0,0);this.temp.position.set(item.x,.25,item.z);this.temp.scale.set(item.kind in weaponNames?.75:.5,.2,item.kind in weaponNames?.25:.5);this.temp.updateMatrix();this.lootBoxes.setMatrixAt(i,this.temp.matrix);this.lootBoxes.setColorAt(i,color);this.temp.position.y=.9;this.temp.scale.set(.13,1.4,.13);this.temp.updateMatrix();this.lootBeams.setMatrixAt(i,this.temp.matrix);this.lootBeams.setColorAt(i,color);i++;}
    for(const mesh of [this.lootBoxes,this.lootBeams]){mesh.count=i;mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;}
  }
  update(state){
    const now=performance.now();this.state=state;this.lastSnapshot=now;
    const own=state.players.find(p=>p.id===state.self.id);if(own&&!this.inputReady){this.yaw=own.yaw;this.pitch=own.pitch;this.ownPosition=new T.Vector3(own.x,own.y,own.z);this.inputReady=true;}else if(own&&state.phase==='playing'){const lag=Math.min(.12,(this.networkLag||0)/2000),dx=own.x+own.vx*lag-this.ownPosition.x,dz=own.z+own.vz*lag-this.ownPosition.z,distance=Math.hypot(dx,dz);if(distance>4){this.ownPosition.set(own.x,own.y,own.z);this.correction.set(0,0,0);}else if(distance>.35)this.correction.set(dx,0,dz);}
    while(this.localVisuals.length&&now-this.localVisuals[0]>1500)this.localVisuals.shift();const ammo=state.self.weapons[state.self.slot]||0;if(state.self.slot!==this.localSlot||ammo>this.lastServerAmmo)this.localAmmo=ammo;else this.localAmmo=Math.min(this.localAmmo,ammo);if(!this.localVisuals.length&&!this.holds.fire&&!this.fireQueued&&!this.keys.has('KeyF'))this.localAmmo=ammo;this.lastServerAmmo=ammo;this.localSlot=state.self.slot;
    const visible=new Set();for(const p of state.players){visible.add(p.id);let a=this.actors.get(p.id);if(!a){a=this.actor(p.id,p.name);a.group.position.set(p.x,p.y,p.z);this.actors.set(p.id,a);}a.from.copy(a.group.position);a.target=p;a.receivedAt=now;a.group.visible=p.hp>0;a.helmet.visible=p.helmet;a.weapon.visible=!!p.slot;a.weapon.scale.z=p.slot==='pistol'?.63:p.slot==='sniper'?1.35:1;}
    for(const [id,a] of this.actors){if(!visible.has(id))a.group.visible=false;}
    this.updateLoot(state.loot);
    const grenades=state.grenades.slice(0,32);for(let i=0;i<grenades.length;i++){if(!this.grenadeModels[i]){this.grenadeModels[i]=new T.Mesh(this.geo.sphere,this.material(0x3b4d32));this.grenadeModels[i].scale.setScalar(.18);this.scene.add(this.grenadeModels[i]);}const g=grenades[i];this.grenadeModels[i].position.set(g.x,g.y,g.z);this.grenadeModels[i].visible=true;}
    for(let i=grenades.length;i<this.grenadeModels.length;i++)this.grenadeModels[i].visible=false;
    this.zoneWall.visible=['playing','drop'].includes(state.phase);this.zoneRing.visible=this.zoneWall.visible;this.zoneWall.position.set(state.zone.x,29,state.zone.z);this.zoneWall.scale.set(Math.max(.01,state.zone.r),1,Math.max(.01,state.zone.r));this.zoneRing.position.set(state.zone.x,.12,state.zone.z);this.zoneRing.scale.setScalar(Math.max(.01,state.zone.r));
    if(state.phase==='waiting'){this.clearInput();this.inputReady=false;}
  }
  flash(actor,local=false,streak=false){if(actor){actor.shotAt=this.elapsed;actor.flashFrames=2;}if(local){this.playShot(this.state.self.slot);if(!this.reduced)this.recoil=.014;if(actor&&streak){const trace=this.traceSlots[this.traceCursor++%this.traceSlots.length];actor.weapon.updateWorldMatrix(true,false);trace.start.set(0,0,-.62);actor.weapon.localToWorld(trace.start);const direction=this.previewDirection.set(Math.sin(this.yaw)*Math.cos(this.pitch),Math.sin(this.pitch),-Math.cos(this.yaw)*Math.cos(this.pitch));let distance=1.8;for(const box of this.nearCover(trace.start.x,trace.start.z)){const hit=this.boxRay(trace.start,direction,box,distance);if(hit!==null)distance=hit;}trace.end.copy(trace.start).addScaledVector(direction,distance);trace.at=this.elapsed;trace.seen=false;}}}
  previewShot(){
    // Visual prediction only: never modify state.self ammunition or decide hits.
    const state=this.state,now=performance.now(),weapon=this.weapons[state?.self.slot];
    if(!this.active||this.paused||document.hidden||state?.phase!=='playing'||!weapon||state.self.reload||state.self.heal||this.localAmmo<=0||now-this.lastSnapshot>600||now<this.localNextShot)return;
    this.localNextShot=now+weapon.interval*1000;this.localAmmo--;this.localVisuals.push(now);if(this.localVisuals.length>16)this.localVisuals.shift();this.flash(this.actors.get(state.self.id),true,true);
  }
  effect(e){
    if(e.kind==='shot'){
      const actor=this.actors.get(e.player),own=e.player===this.state?.self.id,now=performance.now();while(this.localVisuals.length&&now-this.localVisuals[0]>1500)this.localVisuals.shift();const predicted=own&&this.localVisuals.length>0;if(predicted)this.localVisuals.shift();else this.flash(actor,own);
      if(predicted)return;const trace=this.traceSlots[this.traceCursor++%this.traceSlots.length];trace.start.set(...e.start);if(actor?.group.visible){actor.weapon.updateWorldMatrix(true,false);trace.start.set(0,0,-.62);actor.weapon.localToWorld(trace.start);}trace.end.set(...e.end);trace.at=this.elapsed;trace.seen=false;
    }else if(e.kind==='explosion'){
      const effect=this.explosions[(this.explosionCursor=(this.explosionCursor||0)+1)%this.explosions.length];effect.mesh.position.set(e.x,e.y+1,e.z);effect.at=this.elapsed;effect.seen=false;this.playShot('explosion');
    }else if(e.kind==='hit'&&e.player===this.state?.self.id&&!this.reduced){this.damageAnimation?.cancel();this.damageAnimation=this.damage.animate([{opacity:1},{opacity:0}],{duration:280,easing:'ease-out'});}
  }
  updateEffects(){
    let count=0;for(const trace of this.traceSlots){const age=this.elapsed-trace.at;if(trace.at<0||age>trace.life&&trace.seen)continue;const fade=Math.max(.15,1-age/trace.life),i=count++*2;this.tracePositions.setXYZ(i,trace.start.x,trace.start.y,trace.start.z);this.tracePositions.setXYZ(i+1,trace.end.x,trace.end.y,trace.end.z);this.traceColors.setXYZ(i,fade,.66*fade,.3*fade);this.traceColors.setXYZ(i+1,fade,.66*fade,.3*fade);trace.seen=true;}
    if(!count){this.tracePositions.setXYZ(0,0,0,0);this.tracePositions.setXYZ(1,0,0,0);}this.traceGeometry.setDrawRange(0,Math.max(2,count*2));this.tracePositions.needsUpdate=true;this.traceColors.needsUpdate=true;
    for(const effect of this.explosions){const age=this.elapsed-effect.at,shown=effect.at>=0&&(!effect.seen||age<effect.life);effect.mesh.visible=shown;if(shown){effect.mesh.material.opacity=Math.max(.05,1-age/effect.life)*.8;effect.mesh.scale.setScalar(1+age*13);effect.seen=true;}}
  }
  clearTransient(){this.localVisuals=[];this.damageAnimation?.cancel();this.damageAnimation=null;for(const trace of this.traceSlots)trace.at=-10;for(const effect of this.explosions){effect.at=-10;effect.mesh.visible=false;}for(const actor of this.actors.values()){actor.flashFrames=0;actor.shotAt=-10;actor.flash.visible=false;}}
  input(consume=true){
    const blocked=this.paused||!this.active||document.hidden;
    const input={forward:blocked?0:clamp(Number(this.keys.has('KeyW'))-Number(this.keys.has('KeyS'))-this.stick.y,-1,1),strafe:blocked?0:clamp(Number(this.keys.has('KeyD'))-Number(this.keys.has('KeyA'))+this.stick.x,-1,1),yaw:this.yaw,pitch:this.pitch,fire:!blocked&&(this.fireQueued||!!this.holds.fire||this.keys.has('KeyF')),aim:!blocked&&(!!this.holds.aim||this.toggles.aim),sprint:!blocked&&(this.keys.has('ShiftLeft')||this.keys.has('ShiftRight')||this.toggles.sprint),crouch:!blocked&&(this.keys.has('KeyC')||this.toggles.crouch),jump:!blocked&&this.control.jump};if(consume){this.fireQueued=false;this.control.jump=false;}this.control={...input,jump:consume?false:input.jump};return input;
  }
  clearInput(){this.keys.clear();this.stick={x:0,y:0};this.holds={};this.fireQueued=false;this.localVisuals=[];this.localNextShot=0;for(const b of this.root.querySelectorAll('[data-battle-hold]'))b.classList.remove('pressed');this.toggles={aim:false,sprint:false,crouch:false};this.control={...this.control,forward:0,strafe:0,fire:false,aim:false,sprint:false,crouch:false,jump:false};this.drag=null;for(const b of this.root.querySelectorAll('[data-battle-toggle]'))b.setAttribute('aria-pressed','false');const stick=this.root.querySelector('[data-battle-stick] span');if(stick)stick.style.transform='translate(-50%,-50%)';}
  pause(value){this.paused=value;if(value){this.clearInput();if(document.pointerLockElement===this.canvas)document.exitPointerLock();}}
  reset(){this.clearInput();this.clearTransient();this.root.classList.remove('battle-outside-zone');this.outside=false;this.active=false;this.paused=false;this.state=null;this.inputReady=false;this.zoneWall.visible=false;this.zoneRing.visible=false;for(const mesh of this.actorBatches.values())mesh.count=0;this.actorShadows.count=this.lootBoxes.count=this.lootBeams.count=0;for(const a of this.actors.values())a.group.visible=false;this.camera.position.set(90,66,145);}
  bindInput(){
    const on=(target,name,fn,extra={})=>target.addEventListener(name,fn,{signal:this.signal,...extra});
    on(window,'keydown',e=>{if(!this.root.isConnected||e.target.closest('input,select,textarea,dialog')||!this.state||this.state.phase==='waiting')return;if(e.code==='Escape'){this.callbacks.pause();return;}if(this.paused||!this.active)return;if(['Space','KeyW','KeyA','KeyS','KeyD','ShiftLeft','ShiftRight','KeyC','KeyE','KeyR','KeyH','KeyG','KeyF','Digit1','Digit2'].includes(e.code))e.preventDefault();this.keys.add(e.code);if(e.repeat)return;if(e.code==='Space')this.control.jump=true;const actions={KeyE:'pickup',KeyR:'reload',KeyH:'heal',KeyG:'grenade'};if(actions[e.code])this.callbacks.action(actions[e.code]);if(e.code==='Digit1'||e.code==='Digit2'){const slot=Object.keys(this.state.self.weapons)[e.code==='Digit1'?0:1];if(slot)this.callbacks.action('slot',slot);}});
    on(window,'keyup',e=>this.keys.delete(e.code));on(window,'blur',()=>this.clearInput());on(document,'visibilitychange',()=>{this.clearInput();if(document.hidden){this.clearTransient();this.renderer.setAnimationLoop(null);}else{this.renderedAt=0;this.lastFrame=performance.now();this.renderer.setAnimationLoop(this.animate);}});
    on(this.canvas,'contextmenu',e=>e.preventDefault());
    on(this.canvas,'pointerdown',e=>{if(!this.active||this.paused)return;if(this.touch||e.pointerType==='touch'){if(this.drag&&this.drag.id!==e.pointerId)return;e.preventDefault();this.canvas.setPointerCapture(e.pointerId);this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};return;}if(document.pointerLockElement!==this.canvas){try{this.canvas.requestPointerLock()?.catch(()=>this.notify('按住畫面拖曳，也能轉動視角。'));}catch{}this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};this.canvas.setPointerCapture(e.pointerId);this.canvas.focus();}else if(e.button===0)this.holds.fire=true;else if(e.button===2)this.holds.aim=true;});
    on(window,'pointermove',e=>{if(this.paused||!this.active)return;if(document.pointerLockElement===this.canvas){this.yaw+=e.movementX*.0025;this.pitch=clamp(this.pitch-e.movementY*.0022,-1.2,1.2);}else if(this.drag?.id===e.pointerId){this.yaw+=(e.clientX-this.drag.x)*.006;this.pitch=clamp(this.pitch-(e.clientY-this.drag.y)*.005,-1.2,1.2);this.drag.x=e.clientX;this.drag.y=e.clientY;}this.yaw=((this.yaw+Math.PI)%TAU+TAU)%TAU-Math.PI;});
    on(window,'pointerup',e=>{if(this.drag?.id===e.pointerId)this.drag=null;if(e.pointerType==='mouse'){if(e.button===0)this.holds.fire=false;if(e.button===2)this.holds.aim=false;}});on(this.canvas,'pointercancel',e=>{if(this.drag?.id===e.pointerId)this.drag=null;});
    on(document,'pointerlockchange',()=>{if(!document.pointerLockElement&&this.active&&!this.paused)this.callbacks.pause();});
    const stick=this.root.querySelector('[data-battle-stick]');let stickId=null;const move=e=>{const box=stick.getBoundingClientRect(),dx=e.clientX-box.x-box.width/2,dy=e.clientY-box.y-box.height/2,r=box.width*.38,length=Math.hypot(dx,dy),scale=Math.max(1,length/r);this.stick={x:dx/scale/r,y:dy/scale/r};stick.querySelector('span').style.transform=`translate(calc(-50% + ${dx/scale}px),calc(-50% + ${dy/scale}px))`;};
    on(stick,'pointerdown',e=>{e.preventDefault();stickId=e.pointerId;stick.setPointerCapture(e.pointerId);move(e);});on(stick,'pointermove',e=>{if(e.pointerId===stickId)move(e);});for(const event of ['pointerup','pointercancel','lostpointercapture'])on(stick,event,()=>{stickId=null;this.stick={x:0,y:0};stick.querySelector('span').style.transform='translate(-50%,-50%)';});
    for(const b of this.root.querySelectorAll('[data-battle-hold]')){on(b,'pointerdown',e=>{e.preventDefault();if(!this.active||this.paused||document.hidden)return;if(b.dataset.battleHold==='fire'&&!this.state?.self.slot){this.notify('先靠近補給，按「拾取」取得武器。');return;}b.setPointerCapture(e.pointerId);this.holds[b.dataset.battleHold]=true;if(b.dataset.battleHold==='fire'){this.fireQueued=true;this.previewShot();}b.classList.add('pressed');});for(const event of ['pointerup','pointercancel','lostpointercapture'])on(b,event,()=>{this.holds[b.dataset.battleHold]=false;b.classList.remove('pressed');});}
    for(const b of this.root.querySelectorAll('[data-battle-toggle]'))on(b,'click',()=>{const key=b.dataset.battleToggle;this.toggles[key]=!this.toggles[key];b.setAttribute('aria-pressed',String(this.toggles[key]));});
    on(this.root.querySelector('[data-battle-jump]'),'click',()=>this.control.jump=true);
  }
  nearCover(x,z){return this.coverGrid.get(Math.floor(x/24)+':'+Math.floor(z/24))||[];}
  safe(x,z,y){if(Math.hypot(x,z)>this.map.radius-.5)return false;return !this.nearCover(x,z).some(b=>y+1.8>b.y-b.h/2&&y<b.y+b.h/2&&Math.abs(x-b.x)<b.w/2+.45&&Math.abs(z-b.z)<b.d/2+.45);}
  frame(time){
    if(document.hidden)return;const interval=1000/this.targetFps,delta=time-this.lastFrame;if(delta<interval-.5)return;
    const gap=this.renderedAt?time-this.renderedAt:interval,dt=Math.min(.1,Math.max(0,gap)/1000);this.renderedAt=time;this.lastFrame=time-delta%interval;this.elapsed+=Math.max(0,gap)/1000;this.frames++;
    const started=performance.now();this.recoil=(this.recoil||0)*Math.exp(-dt*18);
    if(!this.state||this.state.phase==='waiting'){this.camera.position.set(90+(this.reduced?0:Math.sin(this.elapsed*.035)*12),66,145);this.camera.lookAt(-15,0,-60);}
    else{
      const s=this.state,now=performance.now(),snapshotAge=(now-this.lastSnapshot)/1000,age=Math.min(.25,snapshotAge),controls=this.input(false);if(controls.fire)this.previewShot();
      for(const actor of this.actors.values()){
        const p=actor.target;if(!p||!actor.group.visible)continue;
        if(p.id===s.self.id&&s.self.hp>0){
          if(s.phase==='playing'&&this.active&&!this.paused&&snapshotAge<.6){const speed=(controls.sprint&&!controls.aim&&!controls.crouch&&s.self.stamina>0?7.5:controls.crouch?2.2:4.5)*(s.self.heal?.35:1),n=Math.max(1,Math.hypot(controls.forward,controls.strafe)),dx=(Math.sin(this.yaw)*controls.forward+Math.cos(this.yaw)*controls.strafe)*speed/n*dt,dz=(-Math.cos(this.yaw)*controls.forward+Math.sin(this.yaw)*controls.strafe)*speed/n*dt;if(this.safe(this.ownPosition.x+dx,this.ownPosition.z,p.y))this.ownPosition.x+=dx;if(this.safe(this.ownPosition.x,this.ownPosition.z+dz,p.y))this.ownPosition.z+=dz;}
          // Apply only a correction received with a new snapshot, not the old position every frame.
          const fraction=1-Math.exp(-dt*8);this.ownPosition.x+=this.correction.x*fraction;this.ownPosition.z+=this.correction.z*fraction;this.correction.multiplyScalar(1-fraction);
          this.ownPosition.y=approach(this.ownPosition.y,s.phase==='drop'?Math.max(0,p.y-age*34/7):p.y,dt*14);actor.group.position.copy(this.ownPosition);
        }else{
          const mix=clamp((now-actor.receivedAt)/140,0,1),extra=Math.max(0,Math.min(.1,(now-actor.receivedAt-140)/1000));actor.group.position.set(actor.from.x+(p.x-actor.from.x)*mix+p.vx*extra,actor.from.y+(p.y-actor.from.y)*mix,actor.from.z+(p.z-actor.from.z)*mix+p.vz*extra);
        }
        const local=p.id===s.self.id,turn=-p.yaw-actor.body.rotation.y;actor.body.rotation.y=local?-this.yaw:actor.body.rotation.y+Math.atan2(Math.sin(turn),Math.cos(turn))*(1-Math.exp(-dt*14));const moving=local?s.phase==='playing'&&Math.hypot(controls.forward,controls.strafe)>.1:p.animation==='run',crouch=local?controls.crouch:p.animation==='crouch';actor.body.position.y=crouch?-.48:0;actor.limbs.forEach((leg,i)=>{leg.position.y=crouch?.8:.65;leg.rotation.x=crouch?-1.1:moving?Math.sin(this.elapsed*11+i*Math.PI+p.id)*.65:0;});actor.arm.rotation.x=-p.pitch*.7;actor.weapon.rotation.x=local?-this.pitch:-p.pitch;actor.flash.visible=actor.flashFrames>0||this.elapsed-actor.shotAt<.08;if(actor.flashFrames>0)actor.flashFrames--;actor.weapon.position.z=-.51+(this.elapsed-actor.shotAt<.12?.055:0);
        const dropping=p.animation==='drop';actor.chute.visible=dropping;for(const line of actor.chute.userData.lines)line.visible=dropping;actor.left.rotation.x=dropping?-2:0;if(dropping){actor.body.position.y=0;actor.arm.rotation.x=-2;}
      }
      const follow=s.self.hp>0?this.actors.get(s.self.id):[...this.actors.values()].find(a=>a.target?.hp>0&&a.group.visible);
      if(follow){
        const pos=follow.group.position,yaw=s.self.hp>0?this.yaw:follow.target.yaw,pitch=s.self.hp>0?this.pitch+this.recoil:0,aim=controls.aim&&s.self.hp>0,distance=aim?1.15:4.7,side=aim?.32:this.portrait?.42:1.7;
        const desired=this.cameraDesired.set(pos.x-Math.sin(yaw)*distance+Math.cos(yaw)*side,pos.y+2.5-pitch*1.5,pos.z+Math.cos(yaw)*distance+Math.sin(yaw)*side),target=this.cameraTarget.set(pos.x,pos.y+1.65,pos.z),difference=this.cameraDelta.copy(desired).sub(target),length=difference.length();this.ray.set(target,difference.normalize());let hit=length;
        for(const box of this.nearCover(pos.x,pos.z)){const d=this.boxRay(target,this.ray.ray.direction,box,hit);if(d!==null)hit=Math.max(.3,d-.25);}if(hit<length)desired.copy(target).addScaledVector(this.ray.ray.direction,hit);
        this.camera.position.copy(desired);this.camera.lookAt(pos.x+Math.sin(yaw)*Math.cos(pitch)*30,pos.y+1.55+Math.sin(pitch)*30,pos.z-Math.cos(yaw)*Math.cos(pitch)*30);const fov=approach(this.camera.fov,aim?44:65,dt*14);if(Math.abs(fov-this.camera.fov)>.005){this.camera.fov=fov;this.camera.updateProjectionMatrix();}
        if(time-this.miniAt>200){const outside=Math.hypot(pos.x-s.zone.x,pos.z-s.zone.z)>s.zone.r;if(outside!==this.outside){this.root.classList.toggle('battle-outside-zone',outside);this.outside=outside;}const text=['北','東北','東','東南','南','西南','西','西北'][Math.round(((yaw/TAU*8)%8+8)%8)%8]+' '+Math.round(((yaw/TAU*360)%360+360)%360)+'°';if(this.compass.textContent!==text)this.compass.textContent=text;this.minimapDraw(pos,yaw);this.miniAt=time;}
      }
      this.updateActorBatches();
    }
    this.updateEffects();if(this.elapsed>this.toastUntil)this.toast.classList.remove('show');this.renderer.render(this.scene,this.camera);
    this.renderMs=performance.now()-started;if(gap<250)this.frameGaps.push(gap);if(this.frameGaps.length>90)this.frameGaps.shift();
    if(time-this.frameAt>=1000){this.root.dataset.battleFps=String(Math.round(this.frames*1000/(time-this.frameAt)));this.root.dataset.battleDrawCalls=String(this.renderer.info.render.calls);this.root.dataset.battleTriangles=String(this.renderer.info.render.triangles);this.root.dataset.battleRenderMs=this.renderMs.toFixed(2);this.root.dataset.battlePixelRatio=this.pixelRatio.toFixed(2);this.frames=0;this.frameAt=time;this.adaptQuality(time);}
  }
  adaptQuality(time){if(this.frameGaps.length<60||time-this.qualityAt<5000||!this.active||this.paused||!document.hasFocus())return;const values=[...this.frameGaps].sort((a,b)=>a-b),p75=values[Math.floor(values.length*.75)];if(p75>27&&this.pixelRatio>.76){this.pixelRatio=Math.max(.75,this.pixelRatio-.15);this.renderer.setPixelRatio(this.pixelRatio);this.qualityAt=time;this.frameGaps=[];}else if(p75>38&&this.targetFps>30){this.targetFps=30;this.qualityAt=time;this.frameGaps=[];}}
  boxRay(origin,direction,b,max){let low=0,high=max;for(const [key,size] of RAY_AXES){const a=b[key]-b[size]/2,c=b[key]+b[size]/2;if(Math.abs(direction[key])<1e-8){if(origin[key]<a||origin[key]>c)return null;}else{const u=(a-origin[key])/direction[key],v=(c-origin[key])/direction[key];low=Math.max(low,Math.min(u,v));high=Math.min(high,Math.max(u,v));if(high<low)return null;}}return low;}
  minimapDraw(pos,yaw){const c=this.minictx,s=this.state;if(!c||!s)return;const n=168,scale=n/800;c.clearRect(0,0,n,n);c.fillStyle='#123740';c.fillRect(0,0,n,n);c.save();c.translate(n/2,n/2);c.scale(scale,scale);c.fillStyle='#496451';c.beginPath();c.arc(0,0,this.map.radius,0,TAU);c.fill();c.fillStyle='#b0b396';for(const b of this.map.structures)c.fillRect(b.x-b.w/2,b.z-b.d/2,b.w,b.d);c.strokeStyle='#a5e9ee';c.lineWidth=2/scale;c.beginPath();c.arc(s.zone.x,s.zone.z,s.zone.r,0,TAU);c.stroke();c.strokeStyle='#fff3b4';c.lineWidth=1/scale;c.setLineDash([6/scale,5/scale]);c.beginPath();c.arc(s.zone.next_x,s.zone.next_z,s.zone.next_r,0,TAU);c.stroke();c.setLineDash([]);c.translate(pos.x,pos.z);c.rotate(yaw);c.fillStyle='#fff3b4';c.beginPath();c.moveTo(0,-11/scale);c.lineTo(-5/scale,5/scale);c.lineTo(5/scale,5/scale);c.closePath();c.fill();c.restore();c.fillStyle='#e8f3ef';c.font='bold 11px sans-serif';c.fillText('北',78,14);}
  resize(){const width=this.canvas.clientWidth,height=this.canvas.clientHeight;if(!width||!height||width===this.viewWidth&&height===this.viewHeight)return;this.viewWidth=width;this.viewHeight=height;this.renderer.setSize(width,height,false);this.portrait=width<height;this.camera.aspect=width/height;this.camera.updateProjectionMatrix();}
  notify(message){this.toast.textContent=message;this.toast.classList.add('show');this.toastUntil=this.elapsed+3;}
  async toggleSound(){if(!this.sound){this.audio??=new(window.AudioContext||window.webkitAudioContext)();await this.audio.resume();this.sound=true;}else this.sound=false;return this.sound;}
  playShot(kind){if(!this.sound||!this.audio||this.audio.state!=='running')return;const audio=this.audio,now=audio.currentTime,osc=audio.createOscillator(),gain=audio.createGain();osc.type='sawtooth';osc.frequency.setValueAtTime(kind==='explosion'?65:kind==='sniper'?170:260,now);osc.frequency.exponentialRampToValueAtTime(35,now+.11);gain.gain.setValueAtTime(.045,now);gain.gain.exponentialRampToValueAtTime(.0001,now+.13);osc.connect(gain).connect(audio.destination);osc.start();osc.stop(now+.14);osc.onended=()=>{osc.disconnect();gain.disconnect();};}
  clearGroup(group){for(const child of [...group.children]){child.traverse(o=>{if(o.geometry&&!Object.values(this.geo).includes(o.geometry))o.geometry.dispose();if(o.isInstancedMesh)o.dispose();});group.remove(child);}}
  destroy(){this.abort.abort();this.observer.disconnect();if(document.pointerLockElement===this.canvas)document.exitPointerLock();this.renderer.setAnimationLoop(null);const geometries=new Set(Object.values(this.geo)),materials=new Set(this.materials.values());this.scene.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(Array.isArray(o.material))o.material.forEach(m=>materials.add(m));else if(o.material)materials.add(o.material);if(o.isInstancedMesh)o.dispose();});for(const geometry of geometries)geometry.dispose();for(const material of materials)material.dispose();this.renderer.dispose();this.renderer.forceContextLoss();void this.audio?.close().catch(()=>{});this.toast.remove();this.damageAnimation?.cancel();this.damage.remove();}
}
