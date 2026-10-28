/* Pinned local vendor bundles; never fetch scripts from a runtime CDN. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
assert.equal(pkg.dependencies['lightweight-charts'],'5.2.1');
assert.equal(pkg.dependencies.three,'0.186.1');
const files=[['node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js','static/lightweight-charts.js'],['node_modules/lightweight-charts/LICENSE','docs/licenses/lightweight-charts-LICENSE.txt'],['node_modules/three/build/three.module.js','static/three.module.js'],['node_modules/three/build/three.core.js','static/three.core.js'],['node_modules/three/LICENSE','docs/licenses/three-LICENSE.txt']];
for(const[source,target]of files){const bytes=fs.readFileSync(path.join(root,source));if(process.argv.includes('--check'))assert.ok(bytes.equals(fs.readFileSync(path.join(root,target))),target+' differs from pinned package');else fs.writeFileSync(path.join(root,target),bytes);}
const notice=fs.readFileSync(path.join(root,'docs/licenses/lightweight-charts-NOTICE.txt'),'utf8')+'\n'+fs.readFileSync(path.join(root,'docs/licenses/lightweight-charts-LICENSE.txt'),'utf8')+'\nThree.js 0.186.1 · https://threejs.org/\n'+fs.readFileSync(path.join(root,'docs/licenses/three-LICENSE.txt'),'utf8');
if(process.argv.includes('--check'))assert.equal(fs.readFileSync(path.join(root,'static/third-party-notices.txt'),'utf8'),notice);else fs.writeFileSync(path.join(root,'static/third-party-notices.txt'),notice);
console.log('Pinned Lightweight Charts 5.2.1 / Three.js 0.186.1 bundles and attribution OK');
