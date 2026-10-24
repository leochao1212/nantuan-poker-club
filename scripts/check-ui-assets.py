"""Verify current asset fingerprints; --write updates the canonical references."""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
records=[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((ROOT/'static/assets').rglob('*')) if p.is_file()]
versions={r['path'].removeprefix('static/assets/'):r['sha256'][:12] for r in records}
changes={}
p=ROOT/'docs/assets-manifest.json';want=json.dumps(records,indent=2)+'\n'
if p.read_text(encoding='utf-8')!=want:changes[p]=want
p=ROOT/'static/ui-art.js';text=p.read_text(encoding='utf-8');want=re.sub(r'const versions=\{[^\n]*\};', 'const versions='+json.dumps(versions,separators=(',',':'))+';',text,count=1)
if text==want and 'const versions='+json.dumps(versions,separators=(',',':'))+';' not in text:raise SystemExit('Missing UI asset version table')
if text!=want:changes[p]=want
p=ROOT/'static/night.css';text=p.read_text(encoding='utf-8')
def version(match):
 key=match.group(1)
 if key not in versions:raise ValueError('Unknown current CSS artwork: '+key)
 return '/assets/'+key+'?v='+versions[key]
want=re.sub(r'/assets/([a-zA-Z0-9_/-]+\.(?:webp|svg))(?:\?v=[a-zA-Z0-9_-]+)?',version,text)
if want!=text:changes[p]=want
if changes and '--write' not in sys.argv:raise SystemExit('Update current asset fingerprints: python scripts/check-ui-assets.py --write\n'+ '\n'.join(str(p.relative_to(ROOT)) for p in changes))
for p,want in changes.items():p.write_text(want,encoding='utf-8',newline='\n')
print('Current UI asset fingerprints OK:',len(records),'assets')
