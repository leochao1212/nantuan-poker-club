/* Original lightweight character rig: blended stance, planted stride and two-bone grips. */
import * as T from './three.module.js?v=0-186-1';
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),damp=(a,b,dt,rate=12)=>a+(b-a)*(1-Math.exp(-dt*rate));
const DOWN=new T.Vector3(0,-1,0),TAU=Math.PI*2;
export function createMotion(actor){
  return {aim:0,sprint:0,drop:0,reload:0,reloading:false,reloadClock:0,equip:0,slot:'',
    arms:actor.arms.map(()=>({target:new T.Vector3(),direction:new T.Vector3(),pole:new T.Vector3(),elbow:new T.Vector3(),fore:new T.Vector3(),rotation:new T.Quaternion()}))};
}
function grip(actor,index,x,y,z,release,drop){
  const arm=actor.arms[index],joint=actor.elbows[index],rig=actor.motion.arms[index],side=index===0?1:-1;
  rig.target.set(x,y,z).applyEuler(actor.weapon.rotation).add(actor.weapon.position);
  if(index===1){rig.target.x+=(side*.13-rig.target.x)*release;rig.target.y+=(.95-rig.target.y)*release;rig.target.z+=(.03-rig.target.z)*release;}
  rig.target.x+=(side*.48-rig.target.x)*drop;rig.target.y+=(1.89-rig.target.y)*drop;rig.target.z+=(.05-rig.target.z)*drop;
  rig.direction.copy(rig.target).sub(arm.position);const distance=clamp(rig.direction.length(),.04,.575);rig.direction.normalize();
  // A stable outward/down pole prevents the elbows flipping when aim crosses the shoulder.
  rig.pole.set(side*.8,-.6,.25);rig.pole.addScaledVector(rig.direction,-rig.pole.dot(rig.direction)).normalize();
  const along=distance*.5,height=Math.sqrt(Math.max(0,.29*.29-along*along));
  rig.elbow.copy(rig.direction).multiplyScalar(along).addScaledVector(rig.pole,height);
  arm.quaternion.setFromUnitVectors(DOWN,rig.elbow.normalize());
  rig.elbow.multiplyScalar(.29);rig.fore.copy(rig.direction).multiplyScalar(distance).sub(rig.elbow).normalize();
  rig.rotation.setFromUnitVectors(DOWN,rig.fore);joint.quaternion.copy(arm.quaternion).invert().multiply(rig.rotation);
}
export function poseSoldier(scene,actor,p,controls,dt){
  const local=p.id===scene.state.self.id,m=actor.motion,crouching=local?controls.crouch:p.animation==='crouch',dropping=p.animation==='drop';
  const inputLength=Math.hypot(controls.forward,controls.strafe),speed=local?(scene.state.phase==='playing'?Math.min(1,inputLength)*(controls.sprint&&!controls.aim&&!crouching?7.5:crouching?2.2:4.5)*(scene.state.self.heal?.35:1):0):Math.hypot(p.vx,p.vz),moving=speed>.08;
  const forward=local?controls.forward:Math.sin(p.yaw)*p.vx-Math.cos(p.yaw)*p.vz,side=local?controls.strafe:Math.cos(p.yaw)*p.vx+Math.sin(p.yaw)*p.vz,n=Math.max(.001,Math.hypot(forward,side));
  actor.walk=damp(actor.walk,moving?Math.min(1,speed/3):0,dt,14);actor.crouch=damp(actor.crouch,crouching?1:0,dt,15);
  m.aim=damp(m.aim,local&&controls.aim?1:0,dt);m.sprint=damp(m.sprint,speed>6&&!dropping?1:0,dt,9);m.drop=damp(m.drop,dropping?1:0,dt,dropping?18:12);
  const reload=local?scene.state.self.reload:0,duration=scene.weapons[p.slot]?.reload||2;
  if(reload&&!m.reloading)m.reloadClock=Math.max(0,duration-reload);
  if(reload)m.reloadClock=clamp(Math.max(m.reloadClock+dt,duration-reload),0,duration);
  m.reloading=!!reload;const progress=clamp(m.reloadClock/duration,0,1),reloadPose=reload?Math.sin(Math.PI*progress)**.65:0;
  m.reload=damp(m.reload,reloadPose,dt,16);actor.reloadBlend=m.reload;
  if(m.slot!==p.slot){m.slot=p.slot;m.equip=1;}m.equip=damp(m.equip,0,dt,10);
  actor.gaitPhase+=dt*speed*2.4;const phase=actor.gaitPhase,c=actor.crouch,stride=(.24+m.sprint*.08-c*.09)*actor.walk;
  actor.body.position.y=-.48*c+(scene.reduced?0:Math.sin(phase*2)*.012*actor.walk+Math.sin(scene.elapsed*2+p.id)*.004*(1-actor.walk));
  actor.body.rotation.x=damp(actor.body.rotation.x,forward/n*.045*actor.walk+m.sprint*.025,dt,10);
  actor.body.rotation.z=damp(actor.body.rotation.z,-side/n*.045*actor.walk,dt,10);
  for(let i=0;i<2;i++){
    const cycle=((phase/TAU+i*.5)%1+1)%1,stance=.62,swing=clamp((cycle-stance)/(1-stance),0,1),travel=cycle<stance?1-2*cycle/stance:-Math.cos(swing*Math.PI),lift=Math.sin(swing*Math.PI)*(.10+m.sprint*.025)*actor.walk;
    const z=travel*stride*forward/n,x=travel*stride*side/n,vertical=.8-.33*c-lift,distance=clamp(Math.hypot(vertical,z),.1,.819),alpha=Math.atan2(-z,vertical),beta=Math.acos(distance/.82),leg=actor.limbs[i];
    leg.position.y=.88+.15*c;leg.rotation.x=alpha+beta;leg.rotation.z=-Math.atan2(x,vertical);actor.knees[i].rotation.x=-2*beta;actor.feet[i].rotation.set(-leg.rotation.x+2*beta+Math.sin(swing*Math.PI)*.10,0,-leg.rotation.z);
  }
  const pitch=local?scene.pitch:p.pitch,kick=.045*Math.exp(-Math.max(0,scene.elapsed-actor.shotAt)*35);
  actor.weapon.position.set(damp(actor.weapon.position.x,.12,dt),damp(actor.weapon.position.y,1.32-m.equip*.14,dt),damp(actor.weapon.position.z,-.28+kick,dt));
  actor.weapon.rotation.set(pitch+m.reload*.30+m.sprint*.32+kick*.7,0,m.reload*.35+(scene.reduced?0:Math.sin(phase)*.010*actor.walk*(1-m.aim*.8)));
  grip(actor,0,.015,-.16,.10,0,m.drop);grip(actor,1,-.025,-.065,p.slot==='pistol'?.035:-.15,m.reload,m.drop);
  actor.flash.visible=actor.flashFrames>0||scene.elapsed-actor.shotAt<.06;if(actor.flashFrames>0)actor.flashFrames--;
  actor.chuteScale=m.drop;actor.chute.visible=m.drop>.015;actor.chute.scale.setScalar(Math.max(.001,m.drop));actor.chute.rotation.z=scene.reduced?0:Math.sin(scene.elapsed*1.5+p.id)*.035;
}
