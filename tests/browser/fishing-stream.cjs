/* Deterministic silence/reconnect regression against the actual production module. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 let clock=0,serial=0,refreshes=0,commands=0,notices=0;const timers=new Map(),sources=[],events={};
 class Stream{constructor(url){this.url=url;this.listeners={};this.closed=false;sources.push(this);}addEventListener(k,fn){this.listeners[k]=fn;}close(){this.closed=true;}send(data){this.listeners.world({data:JSON.stringify(data)});}}
 const scope={window:{},document:{hidden:false,addEventListener(k,fn){events[k]=fn;},removeEventListener(k){delete events[k];}},Date:{now:()=>clock},EventSource:Stream,
  setInterval(fn,ms){timers.set(++serial,{fn,ms,at:clock+ms});return serial;},clearInterval(id){timers.delete(id);},
  setTimeout(fn,ms){timers.set(++serial,{fn,ms:0,at:clock+ms});return serial;},clearTimeout(id){timers.delete(id);}};
 async function advance(ms){const end=clock+ms;let limit=0;while(true){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;assert.ok(limit++<10000);const [id,t]=next;clock=t.at;if(t.ms)t.at+=t.ms;else timers.delete(id);t.fn();await Promise.resolve();await Promise.resolve();}clock=end;}
 vm.createContext(scope);vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/fishing-play.js'),'utf8'),scope);
 const state={member:{room_id:1},wallet:{balance:3000},cannons:[{interval:.24}]},play=scope.window.ClubFishingPlay.create({id:()=>String(++serial),user:1,now:()=>clock/1000,state:()=>state,mode:()=>'arcade',world(){},notice(){notices++;},refresh(){refreshes++;},api:async()=>({}),command:async()=>{commands++;return {};},blocked:()=>false,gears:()=>({cannon:0}),stake:()=>10,localShot(){}});
 play.open(1);sources[0].send({room_id:1,server_time:0,projectiles:[]});assert.equal(play.connected(),true);
 play.start(true);await advance(250);assert.ok(commands>0);const before=commands;
 await advance(7100);assert.equal(sources[0].closed,true);assert.equal(sources.length,2);assert.equal(play.connected(),false);assert.ok(refreshes>0&&notices>0);
 const settled=commands;await advance(600);assert.equal(commands,settled,'no automatic firing during recovery');assert.ok(settled>=before);
 sources[1].send({room_id:1,server_time:clock/1000,projectiles:[]});assert.equal(play.connected(),true);
 sources[0].send({room_id:1,server_time:999,projectiles:[]});assert.notEqual(play.world().server_time,999,'stale stream generation cannot overwrite state');
 scope.document.hidden=true;events.visibilitychange();assert.equal(sources[1].closed,true);play.open(1);await advance(50000);assert.equal(sources.length,2,'late refresh cannot reopen a hidden stream');
 scope.document.hidden=false;events.visibilitychange();assert.equal(sources.length,3);sources[2].send({room_id:1,server_time:clock/1000,projectiles:[]});await advance(500);assert.equal(commands,settled,'returning never resumes auto fire');
 play.destroy();await advance(60000);assert.equal(sources.length,3);assert.equal(timers.size,0);assert.equal(commands,settled);
 console.log('Fishing silence rebuild, stale generation fence, background recovery and no auto debit: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
