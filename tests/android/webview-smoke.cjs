const { _android,request }=require('playwright'),{spawn,execFileSync}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/android',(process.env.ANDROID_NAV_MODE||'gestural')+'-'+(process.env.ANDROID_PROFILE||'standard')),pause=ms=>new Promise(r=>setTimeout(r,ms)),pkg='org.nantuan.nantuan_club';
(async()=>{fs.mkdirSync(out,{recursive:true});const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'nantuan-android-')),base='http://127.0.0.1:8765',errors=[],checks=[];let device,p,logs='';
 const proc=spawn(process.env.PYTHON||'python3',['server.py','--host','127.0.0.1','--port','8765'],{cwd:root,env:{...process.env,POKER_DB:path.join(tmp,'isolated.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',PYTHONIOENCODING:'utf-8'}});proc.stdout.on('data',x=>logs+=x);proc.stderr.on('data',x=>logs+=x);
 const c=await request.newContext(),api=async(p,d)=>{const r=d?await c.post(base+p,{headers:{'X-Requested-With':'PokerClub'},data:d}):await c.get(base+p);assert.equal(r.status(),200,p+' '+await r.text());return r.json();};
 const adb=(...args)=>execFileSync('adb',args,{timeout:30000});
 try{
  for(let i=0;i<100;i++){try{await api('/api/bootstrap');break;}catch{await pause(100);}}
  await api('/api/register',{username:'android_test',nickname:'Android流程測試',password:'SyntheticAndroid123'});
  adb('reverse','tcp:8765','tcp:8765');adb('shell','am','start','-n',pkg+'/.MainActivity');
  [device]=await _android.devices();assert.ok(device);device.setDefaultTimeout(30000);
  const w=await device.webView({pkg});p=await w.page();p.on('pageerror',e=>errors.push(e.message));
  await p.locator('#auth-form [name=username]').fill('android_test');await p.locator('#auth-form [name=password]').fill('SyntheticAndroid123');await p.locator('#auth-form button[type=submit]').click();await p.waitForFunction(()=>lobby&&liveReady);
  await p.locator('nav a[href="#rewards"]').click();await p.waitForSelector('.rewards-hub');await p.locator('#daily-claim').click();await p.waitForFunction(()=>lobby.wallet.daily_claimed);await p.locator('#hourly-claim').click();await p.waitForFunction(()=>!hourlyPending&&!lobby.wallet.hourly_available);assert.equal((await api('/api/online/lobby')).wallet.total,4200);checks.push('Android WebView login, daily and hourly supply');
  fs.writeFileSync(path.join(out,'android-rewards.png'),adb('exec-out','screencap','-p'));
  const r=await api('/api/online/rooms',{game_type:'slot',name:'Android實際開局',buy_in:1000,stake:10,operation_id:crypto.randomUUID()});await p.evaluate(id=>go(id),r.id);await p.waitForSelector('#deal-hand');await p.locator('#deal-hand').click();await p.waitForFunction(()=>room.hand_no===1&&!busy&&!pendingOperation);const state=await api('/api/online/rooms/'+r.id);checks.push('Real Android slot action and receipt confirmed');
  fs.writeFileSync(path.join(out,'android-game.png'),adb('exec-out','screencap','-p'));
  adb('shell','input','keyevent','4');await p.waitForFunction(()=>view==='lobby');assert.equal((await api('/api/online/lobby')).current_room_id,r.id);checks.push('Native Android Back returns to lobby and retains seat');
  adb('shell','input','keyevent','3');await pause(1000);adb('shell','am','start','-n',pkg+'/.MainActivity');await p.waitForFunction(()=>liveReady&&document.visibilityState==='visible');const recovered=await api('/api/online/rooms/'+r.id);assert.equal(recovered.hand_no,1);assert.equal(recovered.wallet.total,state.wallet.total);checks.push('Background return reconnects without a second debit');
  adb('shell','pm','grant',pkg,'android.permission.RECORD_AUDIO');assert.ok(adb('shell','dumpsys','package',pkg).toString().includes('android.permission.RECORD_AUDIO: granted=true'));assert.ok(await p.evaluate(()=>!!navigator.mediaDevices?.getUserMedia));checks.push('Native microphone permission and secure-context voice API available; physical two-way audio not certified');
  await require('./adaptive-layout.cjs')({p,adb,api,roomId:r.id,out,checks});
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors,scope:'Disposable Android 35 emulator and isolated server; no production data'},null,2));console.log(JSON.stringify({checks,errors}));
 }catch(e){
  try{fs.writeFileSync(path.join(out,'failure-state.json'),JSON.stringify(await p.evaluate(()=>({url:location.href,view,room:room?.id,liveReady,busy,pending:!!pendingOperation,active:document.activeElement?.tagName,width:innerWidth,height:innerHeight,visualHeight:visualViewport?.height})),null,2));}catch{}
  try{fs.writeFileSync(path.join(out,'android-failure.png'),adb('exec-out','screencap','-p'));}catch{}
  throw e;
 }finally{try{fs.writeFileSync(path.join(out,'logcat.txt'),adb('logcat','-d','-t','1000'));}catch{}await device?.close();await c.dispose();proc.kill();fs.writeFileSync(path.join(out,'server.log'),logs);}
})().catch(e=>{console.error(e);process.exitCode=1;});
