// Static, offline UI preview: no API server or trading connection.
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
const root=path.resolve(__dirname,'../..');const out=process.argv[2]||path.join(os.tmpdir(),'mt-dashboard-preview','preview.html');
const mock=require('esbuild').buildSync({stdin:{contents:`const fixture=require('./tests/fixture.cjs')();window.fetch=async input=>({ok:true,json:async()=>fixture.response(new URL(typeof input==='string'?input:input.url,location.href).pathname)});`,resolveDir:path.resolve(__dirname,'..')},bundle:true,write:false}).outputFiles[0].text;
const scripts=[mock,fs.readFileSync(path.join(root,'static/price-chart.js'),'utf8'),fs.readFileSync(path.join(root,'static/dashboard.js'),'utf8'),fs.readFileSync(require.resolve('alpinejs/dist/cdn.min.js'),'utf8')];
let styles=['styles.css','workspace.css'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n');
styles=styles.replace(/url\("(\/static\/fonts\/[^" ]+)"\)/g,(_,url)=>`url("data:font/woff2;base64,${fs.readFileSync(path.join(root,url.slice(1))).toString('base64')}")`);
let html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/^<link[^\n]*\n/gm,'').replace('</head>',`<style>${styles}</style></head>`);
html=html.replace('<div class="shell">','<div style="padding:12px 24px;background:#e8f2f5;color:#125568;text-align:center;font:13px system-ui">Local preview · Synthetic data · No trading connection</div><div class="shell">');
html=html.replace('</body>',()=>scripts.map(script=>'<script>'+script.replace(/<\/script/gi,'<\\/script')+'</script>').join('\n')+'</body>');
fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,html);console.log(out);
