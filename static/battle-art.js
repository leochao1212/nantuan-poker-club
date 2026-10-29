/* Original coastal field-station art. Shared, baked geometry; no remote assets. */
import * as T from './three.module.js?v=0-186-1';

const TAU=Math.PI*2;
const C={ink:0x233a40,metal:0x354b50,edge:0x748b8d,cloth:0x66796b,sand:0xc3ae7b,brass:0xc9a557,white:0xe8e5d5,teal:0x56867e};
export const GUN_MUZZLES={pistol:-.24,smg:-.52,rifle:-.76,sniper:-.99};

function bevel(){
  const shape=new T.Shape(),r=.10;
  shape.moveTo(-.4,-.5);shape.lineTo(.4,-.5);shape.quadraticCurveTo(.5,-.5,.5,-.4);shape.lineTo(.5,.4);shape.quadraticCurveTo(.5,.5,.4,.5);shape.lineTo(-.4,.5);shape.quadraticCurveTo(-.5,.5,-.5,.4);shape.lineTo(-.5,-.4);shape.quadraticCurveTo(-.5,-.5,-.4,-.5);
  const g=new T.ExtrudeGeometry(shape,{depth:.8,bevelEnabled:true,bevelSegments:1,steps:1,bevelSize:r,bevelThickness:r,curveSegments:2});g.center();g.computeBoundingBox();const size=g.boundingBox.getSize(new T.Vector3());g.scale(1/size.x,1/size.y,1/size.z);return g;
}

/** Bake different primitives/material colours into one shareable geometry. */
export class ArtBuilder{
  constructor(base){this.base=base;this.positions=[];this.normals=[];this.colors=[];this.transform=new T.Object3D();}
  add(kind,color,position,scale,rotation=[0,0,0]){
    const source=typeof kind==='string'?this.base[kind]:kind,g=source.index?source.toNonIndexed():source.clone();this.transform.position.set(...position);this.transform.scale.set(...scale);this.transform.rotation.set(...rotation);this.transform.updateMatrix();g.applyMatrix4(this.transform.matrix);
    const p=g.attributes.position,n=g.attributes.normal,existing=g.attributes.color,tint=new T.Color(color);
    for(let i=0;i<p.count;i++){this.positions.push(p.getX(i),p.getY(i),p.getZ(i));this.normals.push(n.getX(i),n.getY(i),n.getZ(i));this.colors.push(tint.r*(existing?existing.getX(i):1),tint.g*(existing?existing.getY(i):1),tint.b*(existing?existing.getZ(i):1));}g.dispose();return this;
  }
  box(color,p,s,r){const thin=Math.min(...s),long=Math.max(...s);return this.add(thin<.055||long<.14||(thin<.12&&long>.7)?'box':'bevel',color,p,s,r);}
  cylinder(color,p,s,r){return this.add('cylinder',color,p,s,r);}
  beam(color,a,b,radius=.035){const from=new T.Vector3(...a),to=new T.Vector3(...b),direction=to.clone().sub(from),q=new T.Quaternion().setFromUnitVectors(new T.Vector3(0,1,0),direction.clone().normalize()),rot=new T.Euler().setFromQuaternion(q);return this.cylinder(color,from.add(to).multiplyScalar(.5).toArray(),[radius,direction.length(),radius],[rot.x,rot.y,rot.z]);}
  finish(){const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(this.positions,3));g.setAttribute('normal',new T.Float32BufferAttribute(this.normals,3));g.setAttribute('color',new T.Float32BufferAttribute(this.colors,3));g.computeBoundingSphere();g.computeBoundingBox();return g;}
}

function gun(base,kind){
  const b=new ArtBuilder(base),pistol=kind==='pistol',smg=kind==='smg',sniper=kind==='sniper';
  if(pistol){
    b.box(C.ink,[0,.035,-.025],[.105,.10,.29]);b.box(C.edge,[0,.09,-.02],[.085,.012,.25]);b.box(C.cloth,[0,-.045,.005],[.10,.08,.22]);b.box(C.ink,[0,-.145,.075],[.085,.19,.105],[-.22,0,0]);b.box(C.sand,[0,-.243,.055],[.095,.026,.12]);b.cylinder(0x152b32,[0,.035,-.19],[.018,.10,.018],[Math.PI/2,0,0]);
    b.box(C.ink,[0,.104,-.145],[.022,.027,.025]);for(const x of [-.036,.036])b.box(C.ink,[x,.102,.088],[.018,.022,.035]);
  }else{
    const length=sniper?.53:smg?.30:.38,finish=sniper?0x8d8060:smg?0x627b76:0xb4a179;
    b.box(C.ink,[0,0,0],[.12,.135,length]);b.box(finish,[0,-.016,.255],[.105,.16,.25]);b.box(C.ink,[0,-.018,.38],[.12,.18,.04]);
    b.box(C.ink,[0,-.14,.10],[.075,.21,.10],[-.20,0,0]);b.box(C.metal,[0,-.155,-.035],[.085,smg?.28:.24,.13],[smg?0:.16,0,0]);
    b.box(finish,[0,.012,sniper?-.35:smg?-.24:-.30],[.115,.115,sniper?.31:smg?.20:.29]);
    const barrel=sniper?.51:smg?.23:.38,z=sniper?-.70:smg?-.40:-.53;
    b.cylinder(0x20343c,[0,.025,z],[.021,barrel,.021],[Math.PI/2,0,0]);b.cylinder(C.ink,[0,.025,GUN_MUZZLES[kind]+.04],[.035,.08,.035],[Math.PI/2,0,0]);
    b.box(C.edge,[0,.085,-.06],[.055,.025,sniper?.44:.36]);for(let i=0;i<4;i++)b.box(C.ink,[0,.104,-.19+i*.075],[.06,.016,.025]);
    for(const side of [-1,1])for(let i=0;i<3;i++)b.box(C.ink,[side*.057,.018,-.38+i*.06],[.006,.043,.025]);
    b.box(C.brass,[.066,.015,.09],[.006,.035,.065]);b.add('sphere',C.ink,[.081,.05,.10],[.025,.025,.025]);
    if(sniper){b.cylinder(C.ink,[0,.17,-.07],[.045,.29,.045],[Math.PI/2,0,0]);for(const z of [-.225,.08])b.cylinder(0x5c9e9d,[0,.17,z],[.033,.012,.033],[Math.PI/2,0,0]);for(const side of [-1,1])b.beam(C.metal,[side*.035,-.035,-.45],[side*.13,-.24,-.47],.016);}
    else{b.box(C.ink,[0,.115,-.01],[.065,.052,.075]);b.box(0x71a6a4,[0,.124,-.051],[.04,.023,.008]);b.box(C.ink,[0,.10,smg?-.46:-.64],[.026,.075,.035]);}
  }
  return b.finish();
}

function bodyGear(base){
  const b=new ArtBuilder(base);
  b.box(0x3f554e,[0,1.13,-.145],[.47,.43,.15]);b.box(0x597064,[0,1.29,-.23],[.31,.08,.025]);
  for(let i=-1;i<=1;i++){b.box(0x738172,[i*.145,1.05,-.255],[.13,.18,.075]);b.box(0x9da68c,[i*.145,1.08,-.299],[.085,.018,.015]);}
  for(const side of [-1,1]){b.box(0x89957c,[side*.205,1.31,-.12],[.065,.24,.04],[side*-.10,0,0]);b.box(C.brass,[side*.205,1.26,-.15],[.045,.045,.012]);b.box(0x344b43,[side*.24,.86,0],[.08,.18,.16]);}
  b.box(C.ink,[0,.85,0],[.49,.085,.33]);b.box(C.brass,[0,.85,-.18],[.085,.055,.022]);
  b.box(0x576c5b,[0,1.15,.23],[.42,.47,.25]);b.box(0x71816a,[0,1.09,.377],[.33,.22,.08]);b.box(0x98a181,[0,1.205,.416],[.25,.014,.012]);
  for(const side of [-1,1]){b.box(0x435b4c,[side*.224,1.10,.23],[.08,.23,.19]);b.box(0xa0a687,[side*.125,1.16,.423],[.032,.38,.012]);b.box(C.brass,[side*.125,1.01,.435],[.045,.038,.014]);}
  b.cylinder(0x8a9879,[0,1.43,.26],[.070,.41,.070],[0,0,Math.PI/2]);for(const x of [-.14,.14])b.box(0x3c5547,[x,1.43,.26],[.027,.148,.148]);
  b.box(C.white,[.08,1.21,.432],[.09,.055,.008]);b.box(0xc6a45e,[.08,1.21,.439],[.055,.012,.005]);
  return b.finish();
}

function firstPersonArms(base,pistol=false){
  const b=new ArtBuilder(base),right=[.06,-.11,.08],left=pistol?[-.045,-.12,.02]:[-.06,-.055,-.23];
  for(const [hand,end] of [[right,[.32,-.74,.46]],[left,[-.34,-.72,.42]]]){b.beam(0x637b6c,hand,end,.075);b.add('sphere',0x283f3a,hand,[.07,.075,.08]);b.box(0x8b9a81,[hand[0],hand[1]-.07,hand[2]+.04],[.12,.04,.095]);}
  return b.finish();
}

function item(base,kind,weapons){
  const b=new ArtBuilder(base);
  if(weapons[kind]){b.add(weapons[kind],0xffffff,[0,.17,0],[.76,.76,.76],[0,0,Math.PI/2]);return b.finish();}
  if(kind==='medkit'){b.box(0x4b8f82,[0,.19,0],[.55,.35,.40]);b.box(C.white,[0,.20,-.212],[.35,.20,.018]);b.box(0x4b8f82,[0,.20,-.225],[.13,.15,.009]);b.box(C.white,[0,.20,-.232],[.035,.12,.009]);b.box(C.white,[0,.20,-.239],[.10,.035,.009]);b.box(C.ink,[0,.39,0],[.22,.055,.10]);}
  if(kind==='ammo'){b.box(0x58664d,[0,.14,0],[.42,.25,.31]);b.box(0xa1a380,[0,.28,0],[.44,.05,.33]);for(let i=-1;i<=1;i++){b.cylinder(C.brass,[i*.10,.36,0],[.035,.14,.035]);b.add('cone',0xdfc68a,[i*.10,.455,0],[.033,.05,.033]);}b.box(C.sand,[0,.15,-.162],[.24,.08,.012]);}
  if(kind==='armor'){b.box(0x597e8b,[0,.29,0],[.45,.46,.13]);b.box(0x32545f,[0,.27,-.09],[.35,.28,.09]);for(const x of [-.18,.18])b.box(C.sand,[x,.50,0],[.09,.18,.08]);for(const x of [-.12,0,.12])b.box(0x8babb1,[x,.23,-.15],[.10,.13,.04]);}
  if(kind==='helmet'){b.add('hair',0x536b56,[0,.12,0],[.28,.30,.28]);b.box(C.ink,[0,.16,-.25],[.38,.045,.13]);for(const x of [-.23,.23])b.box(C.sand,[x,.10,0],[.04,.18,.14]);}
  if(kind==='grenade'){b.add('sphere',0x5c7047,[0,.21,0],[.16,.20,.16]);for(const y of [.13,.24])b.cylinder(0x394d35,[0,y,0],[.164,.035,.164]);b.box(C.metal,[.06,.39,0],[.07,.24,.08],[0,0,.25]);b.box(C.brass,[-.045,.41,0],[.10,.035,.035]);}
  return b.finish();
}

function crate(base){const b=new ArtBuilder(base);b.box(0x687762,[0,0,0],[.98,.98,.98]);b.box(0x87937b,[0,.43,0],[.99,.10,.99]);for(const side of [-1,1]){b.box(C.ink,[side*.32,0,0],[.065,.97,.99]);b.box(C.edge,[0,0,side*.49],[.24,.07,.025]);for(const x of [-.45,.45])for(const y of [-.45,.45])b.box(C.metal,[x,y,side*.45],[.10,.10,.10]);}b.box(C.white,[0,.15,.50],[.34,.22,.012]);b.box(C.brass,[0,.15,.509],[.22,.035,.006]);return b.finish();}

function texture(kind){
  const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d'),colors={grass:'#c0c9ad',plaster:'#e1dfca',brick:'#bfa48a',road:'#b0b3a7',wood:'#b5ad91',roof:'#b1c4c1',water:'#98b8b8'};x.fillStyle=colors[kind]||'#ccd3b9';x.fillRect(0,0,256,256);let seed=6241;const rand=()=>{seed=(Math.imul(seed,1664525)+1013904223)|0;return(seed>>>0)/4294967296;};
  for(let i=0;i<5000;i++){x.fillStyle=rand()>.5?'rgba(255,255,255,.09)':'rgba(27,45,38,.07)';x.fillRect(rand()*256,rand()*256,kind==='grass'?1:2,kind==='grass'?3:1);}
  if(kind==='brick'){x.strokeStyle='rgba(70,60,48,.22)';x.lineWidth=2;for(let y=0;y<256;y+=24){x.beginPath();x.moveTo(0,y);x.lineTo(256,y);x.stroke();for(let a=(y/24%2)*28;a<256;a+=56){x.beginPath();x.moveTo(a,y);x.lineTo(a,y+24);x.stroke();}}}
  if(kind==='wood'||kind==='roof'){x.strokeStyle='rgba(30,53,49,.19)';for(let y=0;y<256;y+=kind==='wood'?24:16){x.fillStyle='rgba(255,255,255,.07)';x.fillRect(0,y+2,256,2);x.beginPath();x.moveTo(0,y);x.lineTo(256,y);x.stroke();}if(kind==='roof')for(let a=0;a<256;a+=64){x.beginPath();x.moveTo(a,0);x.lineTo(a,256);x.stroke();}}
  if(kind==='water'){x.strokeStyle='rgba(228,246,235,.21)';for(let y=0;y<256;y+=20){x.beginPath();for(let a=0;a<=256;a+=8){const h=y+Math.sin(a*.043+y)*3;a?x.lineTo(a,h):x.moveTo(a,h);}x.stroke();}}
  const t=new T.CanvasTexture(c);t.colorSpace=T.SRGBColorSpace;t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(...({grass:[100,100],road:[36,2],water:[75,75],plaster:[3,1],brick:[4,1],wood:[3,1],roof:[3,2]}[kind]||[1,1]));return t;
}

function radial(){const c=document.createElement('canvas');c.width=c.height=64;const x=c.getContext('2d'),g=x.createRadialGradient(32,32,4,32,32,32);g.addColorStop(0,'rgba(15,34,29,.8)');g.addColorStop(.5,'rgba(15,34,29,.37)');g.addColorStop(1,'rgba(15,34,29,0)');x.fillStyle=g;x.fillRect(0,0,64,64);return new T.CanvasTexture(c);}

export function createArtKit(){
  const base={box:new T.BoxGeometry(1,1,1),bevel:bevel(),sphere:new T.SphereGeometry(1,14,10),ico:new T.IcosahedronGeometry(1,1),cylinder:new T.CylinderGeometry(1,1,1,9),cone:new T.ConeGeometry(1,1,9),limb:new T.CapsuleGeometry(1,2,3,8).scale(1,.25,1),hair:new T.SphereGeometry(1,12,6,0,TAU,0,Math.PI*.53)};
  const colored=new Set(),guns={};for(const key of Object.keys(GUN_MUZZLES)){guns[key]=gun(base,key);base['gun-'+key]=guns[key];colored.add('gun-'+key);}
  base.gear=bodyGear(base);colored.add('gear');const boot=new ArtBuilder(base);boot.box(0x31463f,[0,.025,-.035],[.205,.15,.30]);boot.box(0x1d3333,[0,-.043,-.045],[.217,.035,.32]);boot.box(0x819184,[0,.065,-.075],[.15,.025,.12]);base.boot=boot.finish();colored.add('boot');
  for(const [key,pistol]of [['view-arms',false],['view-pistol-arms',true]]){base[key]=firstPersonArms(base,pistol);colored.add(key);}
  const items={};for(const kind of ['pistol','smg','rifle','sniper','ammo','medkit','armor','helmet','grenade'])items[kind]=item(base,kind,guns);
  const shrub=new ArtBuilder(base);for(const [x,y,z,s]of [[0,.40,0,.44],[-.24,.25,.12,.25],[.22,.24,-.11,.26],[.04,.15,.25,.22]])shrub.add('ico',y>.3?0x67825d:0x435f48,[x,y-.5,z],[s,s,s]);base.shrub=shrub.finish();base.shrub.center();base.shrub.computeBoundingBox();const shrubSize=base.shrub.boundingBox.getSize(new T.Vector3());base.shrub.scale(1/shrubSize.x,1/shrubSize.y,1/shrubSize.z);
  return {base,colored,items,crate:crate(base),textures:Object.fromEntries(['grass','plaster','brick','road','wood','roof','water'].map(k=>[k,texture(k)])),shadow:radial()};
}

export function buildSoldier(scene,id,name){
  const parts=[],part=(...a)=>scene.actorPart(parts,...a),g=scene.geo,group=new T.Group(),body=new T.Group(),skin=[0xc59b75,0x9a7358,0xd6b38d][Math.abs(id)%3],jacket=[0xa99460,0x678777,0x96726b,0x6b8598][Math.abs(id)%4];group.add(body);
  part(g.bevel,jacket,0,1.13,0,.58,.62,.32,body);part(g.gear,0xffffff,0,0,0,1,1,1,body);
  part(g.cylinder,skin,0,1.47,0,.09,.14,.09,body);part(g.sphere,skin,0,1.65,0,.185,.23,.18,body);part(g.bevel,skin,0,1.54,-.025,.265,.16,.23,body);part(g.hair,[0x343c36,0x5b4937,0x424a43][Math.abs(id)%3],0,1.67,.016,.194,.23,.191,body);
  for(const x of [-.185,.185])part(g.sphere,skin,x,1.64,.015,.037,.055,.042,body);
  part(g.bevel,0x263e46,0,1.69,-.165,.29,.073,.052,body);for(const x of [-.073,.073])part(g.bevel,0x85abae,x,1.70,-.195,.11,.036,.012,body);part(g.bevel,skin,0,1.62,-.182,.052,.067,.066,body);part(g.box,0x816653,0,1.535,-.147,.07,.013,.008,body);
  const helmet=new T.Group();body.add(helmet);part(g.hair,0x53664f,0,1.67,.02,.226,.246,.225,helmet);part(g.bevel,0x334c43,0,1.71,-.20,.34,.035,.10,helmet);for(const x of [-.21,.21])part(g.bevel,0x8a9678,x,1.63,.015,.035,.14,.13,helmet);
  const limbs=[],knees=[],feet=[];for(const side of [-1,1]){const leg=new T.Group(),knee=new T.Group();leg.position.set(side*.16,.88,0);knee.position.y=-.41;leg.add(knee);part(g.limb,0x536b5a,0,-.205,0,.115,.41,.12,leg);part(g.limb,0x475e51,0,-.205,0,.092,.41,.105,knee);part(g.bevel,0x708471,0,-.015,-.095,.17,.18,.07,knee);const foot=new T.Group();foot.position.y=-.41;knee.add(foot);part(g.boot,0xffffff,0,0,0,1,1,1,foot);body.add(leg);limbs.push(leg);knees.push(knee);feet.push(foot);}
  const arms=[],elbows=[];for(const side of [1,-1]){const arm=new T.Group(),elbow=new T.Group();arm.position.set(side*.30,1.37,0);elbow.position.y=-.29;arm.add(elbow);part(g.limb,jacket,0,-.14,0,.105,.28,.11,arm);part(g.bevel,0x536b59,side*.065,-.08,0,.09,.15,.18,arm);part(g.limb,skin,0,-.15,0,.073,.29,.078,elbow);part(g.bevel,0x334e43,0,-.29,0,.13,.12,.15,elbow);body.add(arm);arms.push(arm);elbows.push(elbow);}
  const weapon=new T.Group();weapon.position.set(.26,1.39,-.48);const variants={};for(const key of Object.keys(GUN_MUZZLES)){variants[key]=part(g['gun-'+key],0xffffff,0,0,0,1,1,1,weapon);variants[key].visible=false;}weapon.userData.muzzleZ=GUN_MUZZLES.rifle;body.add(weapon);
  const flash=part(g.cone,0xffe2a1,0,.025,-.82,.12,.25,.12,weapon);flash.rotation.x=-Math.PI/2;flash.visible=false;
  const chute=new T.Group();group.add(chute);part(g.sphere,0xb8c19d,0,4.7,0,2.9,.58,2.3,chute);part(g.bevel,0x557a70,0,4.92,0,.62,.23,4.15,chute);chute.visible=false;chute.userData.lines=[];for(const side of [-1,1])for(const front of [-1,1]){const line=part(g.cylinder,0xe9dfbd,side*.95,3,front*.72,.012,3.5,.012,chute);line.rotation.set(front*-.3,0,side*.45);chute.userData.lines.push(line);}
  return {group,body,limbs,knees,feet,arms,elbows,arm:arms[0],left:arms[1],weapon,variants,helmet,flash,chute,parts,id,name,target:null,from:new T.Vector3(),receivedAt:0,shotAt:-10,flashFrames:0,walk:0,crouch:0,chuteScale:0,gaitPhase:id,samples:[],renderAt:0};
}

export function buildViewModel(scene){
  const group=new T.Group(),parts=[],part=(...a)=>scene.actorPart(parts,...a),variants={};for(const key of Object.keys(GUN_MUZZLES)){variants[key]=part(scene.geo['gun-'+key],0xffffff,0,0,0,1,1,1,group);variants[key].visible=false;}
  const rifleArms=part(scene.geo['view-arms'],0xffffff,0,0,0,1,1,1,group),pistolArms=part(scene.geo['view-pistol-arms'],0xffffff,0,0,0,1,1,1,group),flash=part(scene.geo.cone,0xffe3a3,0,.025,-.82,.10,.24,.10,group);flash.rotation.x=-Math.PI/2;flash.visible=false;
  return {group,parts,variants,rifleArms,pistolArms,flash};
}

export function addSky(scene){
  const geometry=new T.SphereGeometry(1250,32,24),p=geometry.attributes.position,colors=[],high=new T.Color(0x759fab),low=new T.Color(0xd6dfd3);for(let i=0;i<p.count;i++){const mix=Math.max(0,Math.min(1,(p.getY(i)+250)/1250)),c=low.clone().lerp(high,mix);colors.push(c.r,c.g,c.b);}geometry.setAttribute('color',new T.Float32BufferAttribute(colors,3));const mesh=new T.Mesh(geometry,new T.MeshBasicMaterial({vertexColors:true,side:T.BackSide,depthWrite:false,fog:false}));mesh.renderOrder=-10;mesh.frustumCulled=false;scene.scene.add(mesh);
}

export function addWorldDetails(scene,map,rng){
  const b=new ArtBuilder(scene.geo),shadows=[],plates=[];
  for(const [index,h]of map.structures.entries()){
    const style=h.color%3,trim=[0x506e6b,0x796d5d,0x667c83][style];shadows.push({x:h.x,z:h.z,w:h.w+4,d:h.d+4});
    for(const side of [-1,1]){
      b.box(trim,[h.x,3.03,h.z+side*(h.d/2+.13)],[h.w+.45,.15,.18]);if(side<0)b.box(0x8b9386,[h.x,.18,h.z+side*(h.d/2+.21)],[h.w,.28,.045]);else{const piece=(h.w-2.8)/2;for(const sign of [-1,1])b.box(0x8b9386,[h.x+sign*(piece+2.8)/2,.18,h.z+h.d/2+.21],[piece,.28,.045]);}
      for(const dx of [-h.w*.3,h.w*.3]){const z=h.z+side*(h.d/2+.24);b.box(0x294951,[h.x+dx,1.90,z],[1.30,1.12,.04]);for(const x of [-.70,.70])b.box(0xd4d7bd,[h.x+dx+x,1.90,z+side*.04],[.095,1.30,.10]);b.box(0xd8d7bd,[h.x+dx,1.27,z+side*.06],[1.55,.10,.19]);b.box(0x8fa7a5,[h.x+dx,1.90,z+side*.07],[.045,1.10,.035]);b.box(0xc7d1c2,[h.x+dx,2.47,z+side*.05],[1.50,.09,.10]);if(style===2)for(const x of [-.94,.94])b.box(trim,[h.x+dx+x,1.90,z],[.34,1.16,.09],[0,x*side*.12,0]);}
      for(const x of [-h.w/2+.10,h.w/2-.10])b.cylinder(0x7d9087,[h.x+x,1.55,h.z+side*(h.d/2+.16)],[.045,3.05,.045]);
      b.box(0x526c67,[h.x+side*(h.w/2+.21),1.9,h.z],[.05,1.12,1.25]);for(const z of [-.68,.68])b.box(0xd4d7bd,[h.x+side*(h.w/2+.24),1.90,h.z+z],[.09,1.30,.09]);
      b.box(0xbcbfa8,[h.x+side*1.49,1.5,h.z+h.d/2+.20],[.16,3,.12]);
    }
    b.box(0xd8d4bc,[h.x,2.98,h.z+h.d/2+.20],[3.15,.16,.15]);b.box(0xa7a78d,[h.x,.07,h.z+h.d/2+.35],[3.1,.12,.65]);b.box(0x657973,[h.x,4.79,h.z],[.20,.14,h.d+.6]);
    plates.push({x:h.x,y:3.07,z:h.z+h.d/2+.30,index});
    for(let i=0;i<3;i++)b.box(0x596e69,[h.x-h.w*.32+i*.16,3.73,h.z+h.d/2+.33],[.08,.13,.03]);
  }
  for(const box of map.cover.filter(p=>p.kind==='crate'||p.kind==='rock'))shadows.push({x:box.x,z:box.z,w:box.w+1.2,d:box.d+1.2});
  if(b.positions.length){const mesh=new T.Mesh(b.finish(),scene.material(0xffffff,{vertexColors:true}));scene.world.add(mesh);}
  if(shadows.length){const mesh=new T.InstancedMesh(new T.PlaneGeometry(1,1),new T.MeshBasicMaterial({map:scene.art.shadow,color:0xffffff,transparent:true,opacity:.34,depthWrite:false}),shadows.length);shadows.forEach((s,i)=>{scene.temp.position.set(s.x,.035,s.z);scene.temp.rotation.set(-Math.PI/2,0,0);scene.temp.scale.set(s.w,s.d,1);scene.temp.updateMatrix();mesh.setMatrixAt(i,scene.temp.matrix);});scene.world.add(mesh);}
  if(plates.length){const atlas=document.createElement('canvas');atlas.width=512;atlas.height=256;const c=atlas.getContext('2d');c.font='bold 23px sans-serif';c.textAlign='center';c.textBaseline='middle';for(let i=0;i<16;i++){const x=i%4*128,y=Math.floor(i/4)*64;c.fillStyle='#304b4e';c.fillRect(x,y,128,64);c.strokeStyle='#b4be9a';c.strokeRect(x+5,y+6,118,52);c.fillStyle='#e3d4a3';c.fillText('NT '+String(i+1).padStart(2,'0'),x+64,y+32);}const texture=new T.CanvasTexture(atlas);texture.colorSpace=T.SRGBColorSpace;scene.mapTextures??=[];scene.mapTextures.push(texture);const pos=[],uv=[];for(const p of plates){const x=p.x,y=p.y,z=p.z,w=.9,h=.32,u=(p.index%4)/4,v=1-Math.floor(p.index/4)/4;pos.push(x-w/2,y-h/2,z,x+w/2,y-h/2,z,x+w/2,y+h/2,z,x-w/2,y-h/2,z,x+w/2,y+h/2,z,x-w/2,y+h/2,z);uv.push(u,v-.25,u+.25,v-.25,u+.25,v,u,v-.25,u+.25,v,u,v);}const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(pos,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.computeVertexNormals();scene.world.add(new T.Mesh(g,new T.MeshLambertMaterial({map:texture})));}
  const grass=new ArtBuilder(scene.geo);for(let i=0;i<220;i++){const x=(rng()-.5)*map.radius*1.75,z=(rng()-.5)*map.radius*1.75;if(Math.hypot(x,z)>map.radius-12||Math.abs(x)<6||Math.abs(z)<6||map.structures.some(h=>Math.abs(x-h.x)<h.w/2+2&&Math.abs(z-h.z)<h.d/2+2))continue;for(let k=0;k<3;k++)grass.add('cone',[0x667f52,0x849369,0x70895e][k],[x+(k-1)*.12,.11,z],[.055,.22,.055],[0,rng()*TAU,(rng()-.5)*.35]);}if(grass.positions.length)scene.world.add(new T.Mesh(grass.finish(),scene.material(0xffffff,{vertexColors:true})));
}
