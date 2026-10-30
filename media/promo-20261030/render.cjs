/* Deterministic canvas export, separate from application UI and production data. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process'),{once}=require('node:events');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'artifacts/promo-20261030'),preview=process.argv.includes('--preview');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const server=http.createServer((req,res)=>{const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname);if(name.includes('..')||!(name==='/media/promo-20261030/film.html'||name.startsWith('/static/assets/'))){res.writeHead(404);res.end();return;}const file=path.join(root,name);fs.readFile(file,(err,data)=>{if(err){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',name.endsWith('.html')?'text/html; charset=utf-8':'image/webp');res.end(data);});});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const b=await chromium.launch({headless:true});
 try{
  const p=await b.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  await p.goto(`http://127.0.0.1:${server.address().port}/media/promo-20261030/film.html`);await p.evaluate(()=>window.ready);
  const times=[1,3,5.5,7.5,11,13,16,18,21,23,25,28.8];
  for(const t of times){await p.evaluate(t=>window.seek(t),t);const data=await p.evaluate(()=>document.getElementById('film').toDataURL('image/png').split(',')[1]);fs.writeFileSync(path.join(out,`frame-${t}.png`),Buffer.from(data,'base64'));}
  if(preview){console.log('Storyboard frames ready.');return;}
  const music=spawnSync('python',[path.join(__dirname,'audio.py')],{cwd:root,encoding:'utf8',windowsHide:true});if(music.status!==0)throw Error(music.stderr);
  const enc=spawn('ffmpeg',['-y','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate','30','-i','pipe:0','-i',path.join(out,'soundtrack.wav'),'-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:a','aac','-b:a','192k','-t','30','-movflags','+faststart',path.join(out,'nantuan-friends-30s.mp4')],{windowsHide:true,stdio:['pipe','inherit','inherit']});
  const done=once(enc,'close');enc.stdin.on('error',()=>{});
  for(let frame=0;frame<900;frame++){
   await p.evaluate(t=>window.seek(t),frame/30);
   const data=await p.evaluate(()=>document.getElementById('film').toDataURL('image/jpeg',.95).split(',')[1]);
   if(!enc.stdin.write(Buffer.from(data,'base64')))await once(enc.stdin,'drain');
   if(frame%150===0)console.log(`Rendered ${frame}/900 frames`);
  }
  enc.stdin.end();const [code]=await done;if(code!==0)throw Error('ffmpeg failed: '+code);
  console.log('Finished 1920×1080, 30fps, 30 seconds with original stereo music.');
 }finally{await b.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
