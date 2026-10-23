const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),files=fs.readdirSync(path.join(root,'static')).filter(n=>n.endsWith('.js'));
for(const f of files){const r=spawnSync(process.execPath,['--check',path.join(root,'static',f)],{stdio:'inherit'});if(r.status!==0)process.exit(r.status||1);}
console.log('JavaScript syntax OK: '+files.length+' files');
