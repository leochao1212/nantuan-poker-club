const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(os.tmpdir(),'battle-disabled-')),probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port;
 const server=spawn(process.env.PYTHON||'python',['server.py','--host','127.0.0.1','--port',String(port)],{cwd:root,windowsHide:true,env:{...process.env,POKER_BATTLE_ENABLED:'0',POKER_DB:path.join(tmp,'disabled.sqlite3'),POKER_REQUIRE_INVITE:'0',POKER_SECURE_COOKIE:'0',POKER_PUBLIC_ORIGIN:'',POKER_MARKET_DATA:'0',PYTHONUTF8:'1'}});let browser,logs='';server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:393,height:852},isMobile:true,hasTouch:true}),requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
  for(let i=0;i<80;i++){try{if((await page.request.get(base+'/api/bootstrap')).ok())break;}catch{}await new Promise(r=>setTimeout(r,100));}
  const r=await page.request.post(base+'/api/register',{headers:{'X-Requested-With':'PokerClub'},data:{username:'disabled_battle_test',nickname:'停用測試',password:'SyntheticPreview123'}});assert.equal(r.status(),200,logs);
  await page.goto(base+'/#lobby');await page.locator('#lobby-games').waitFor();assert.equal(await page.locator('.battle-lobby-entry').count(),0);
  await page.goto(base+'/#battle');await page.getByRole('heading',{name:'射擊遊戲已停用'}).waitFor();assert.equal(await page.locator('#battle-console').count(),0);assert.ok(!requests.some(p=>p==='/three.module.js'||p==='/battle-scene.js'||p.startsWith('/api/battle')),'Disabled route must not start GPU rendering or battle requests');
  assert.equal((await page.request.post(base+'/api/battle/create',{headers:{'X-Requested-With':'PokerClub'},data:{bots:true}})).status(),410);
  console.log('Battle disabled: hidden lobby entry, direct-route notice, no renderer or battle polling, authenticated create blocked.');
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
