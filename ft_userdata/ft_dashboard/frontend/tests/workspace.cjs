const {chromium,webkit}=require('playwright');
const fs=require('fs');const root=require('path').join(__dirname,'../../');const assert=require('node:assert/strict');
(async()=>{
 const browser=await (process.env.BROWSER_ENGINE==='webkit'?webkit:chromium).launch(process.env.CHROME_CHANNEL&&process.env.BROWSER_ENGINE!=='webkit'?{channel:process.env.CHROME_CHANNEL}:{});const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.addInitScript(()=>Object.defineProperty(navigator,'language',{get:()=> 'en-US@posix'}));const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const fixture=require('./fixture.cjs')(); let closeRequests=0;
 await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.pathname.includes('alpine'))return route.fulfill({path:require.resolve('alpinejs/dist/cdn.min.js'),contentType:'text/javascript'});if(url.pathname.endsWith('/close')) {closeRequests++;return route.fulfill({json:{state:'accepted'}});}if(url.pathname.startsWith('/api/'))return route.fulfill({json:fixture.response(url.pathname)});if(url.pathname.startsWith('/static/'))return route.fulfill({path:root+url.pathname.slice(1)});if(url.hostname==='dashboard.test')return route.fulfill({body:fs.readFileSync(root+'templates/index.html','utf8').replace('master-trader<span>','master-trader · Preview<span>'),contentType:'text/html'});return route.abort();});
 await page.goto('https://dashboard.test/');await page.waitForTimeout(1800);
 await page.evaluate(()=>Alpine.$data(document.body).setTab('portfolio'));await page.waitForTimeout(500);
 assert.equal(await page.locator('#chart-portfolio-equity .analytics-plot').count(),1);
 assert.equal(await page.locator('#chart-portfolio-strategy tbody tr').count(),3);
 assert.equal(await page.evaluate(()=>Boolean(window.echarts)),false);
 assert.equal(await page.evaluate(()=>Alpine.$data(document.body).stopTone({})), 'pending');
 const sections=await page.locator('.portfolio-analysis>.grid').evaluateAll(nodes=>nodes.map(el=>({top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom})));
 for(let i=1;i<sections.length;i++)assert(sections[i].top-sections[i-1].bottom>=20,'Portfolio sections must have a visible gutter');
 await page.getByRole('button',{name:/^positions/}).first().click();await page.waitForTimeout(1000);
 await page.getByRole('button',{name:'Close position…',exact:true}).first().click();
 if(process.env.SCREENSHOTS){fs.mkdirSync(process.env.SCREENSHOTS,{recursive:true});for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:process.env.SCREENSHOTS+'/close-'+width+'.png'});}await page.setViewportSize({width:1440,height:1000});}
 await page.getByLabel('Bot API username').fill('operator');await page.getByLabel('Bot API password').fill('synthetic');
 await page.getByRole('button',{name:'Confirm market close',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Exit request accepted'}).waitFor();
 assert.equal(closeRequests,1);assert.equal(await page.getByRole('button',{name:'Confirm market close',exact:true}).isDisabled(),true);
 assert.equal(await page.getByLabel('Bot API password').inputValue(),'');
 await page.getByRole('button',{name:'Dismiss',exact:true}).click();
 await page.getByRole('button',{name:'All exits',exact:true}).first().click();await page.getByRole('button',{name:'Expand chart',exact:true}).first().click();await page.waitForTimeout(400); assert.equal(await page.locator('.trade-card.expanded').count(),1);const expanded=await page.locator('.trade-card.expanded .trade-chart').boundingBox();assert(expanded.width>1200&&expanded.height>=600);
 await page.keyboard.press('Escape');assert.equal(await page.locator('.trade-card.expanded').count(),0);await page.setViewportSize({width:390,height:844});await page.waitForTimeout(400);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.setViewportSize({width:1440,height:1000}); await page.evaluate(()=>Alpine.$data(document.body).setTab('bot:killers-ft'));await page.waitForTimeout(500);
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});for(const tab of ['live','portfolio','trades','dryrun','bot:killers-ft']){await page.evaluate(tab=>Alpine.$data(document.body).setTab(tab),tab);await page.waitForTimeout(200);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${tab} overflow at ${width}`);
 if(tab==='portfolio'){for(let pass=0;pass<3;pass++){await page.evaluate(()=>Alpine.$data(document.body).renderPortfolioCharts());await page.waitForTimeout(100);const geometry=await page.locator('#chart-portfolio-equity [data-series]').evaluate(el=>({width:el.getBBox().width,plot:el.closest('svg').getBoundingClientRect().width}));assert(geometry.width>geometry.plot*.65,`Equity must fill plot after render/resize: ${JSON.stringify(geometry)}`);}}
 assert.equal((await page.locator('main:visible').innerText()).includes('undefined'),false);}}
 assert.deepEqual(errors,[]);console.log('Workspace overview, positions, expansion, Escape, mobile and bot detail passed');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
