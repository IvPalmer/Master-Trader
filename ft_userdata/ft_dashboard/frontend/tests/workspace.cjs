const {chromium,webkit}=require('playwright');
const fs=require('fs');const luminance=([r,g,b])=>{const [x,y,z]=[r,g,b].map(v=>v/255).map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4);return 0.2126*x+0.7152*y+0.0722*z;};const contrast=(a,b)=>{const [x,y]=[luminance(a),luminance(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);};const root=require('path').join(__dirname,'../../');const assert=require('node:assert/strict');
(async()=>{
 const browser=await (process.env.BROWSER_ENGINE==='webkit'?webkit:chromium).launch(process.env.CHROME_CHANNEL&&process.env.BROWSER_ENGINE!=='webkit'?{channel:process.env.CHROME_CHANNEL}:{});const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.addInitScript(()=>Object.defineProperty(navigator,'language',{get:()=> 'en-US@posix'}));const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const fixture=require('./fixture.cjs')(); let closeRequests=0; const cancelRequests=[];
 await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.pathname.includes('alpine'))return route.fulfill({path:require.resolve('alpinejs/dist/cdn.min.js'),contentType:'text/javascript'});if(url.pathname.endsWith('/close')) {closeRequests++;return route.fulfill({json:{state:'accepted'}});}if(url.pathname.endsWith('/cancel-entry')){cancelRequests.push({path:url.pathname,action:route.request().headers()['x-trade-action'],body:route.request().postDataJSON()});return route.fulfill({json:{state:'cancelled'}});}if(url.pathname.startsWith('/api/'))return route.fulfill({json:fixture.response(url.pathname)});if(url.pathname.startsWith('/static/'))return route.fulfill({path:root+url.pathname.slice(1)});if(url.hostname==='dashboard.test')return route.fulfill({body:fs.readFileSync(root+'templates/index.html','utf8').replace('master-trader<span>','master-trader · Preview<span>'),contentType:'text/html'});return route.abort();});
 await page.goto('https://dashboard.test/');await page.waitForTimeout(1800);
 await page.locator('details.workspace-research').evaluate(el=>{el.open=true});await page.waitForTimeout(300);
 assert.match(await page.locator('main:visible .workspace-vitals').innerText(),/4 open positions · 1 entry pending/,'Pending entries are counted apart from positions');
 const recentLive=page.locator('details.workspace-research table.ledger');
 assert.equal((await recentLive.locator('thead th').nth(1).textContent()).trim(),'strategy','Merged live-bot ledger must name the bot');
 const recentBots=await recentLive.locator('tbody tr').evaluateAll(rows=>rows.map(row=>row.cells[1].textContent.trim()));
 assert.equal(recentBots.length,6);assert.deepEqual([...new Set(recentBots)].sort(),['funding-fade','keltner-bounce','killers-scalp']);
 await page.evaluate(()=>Alpine.$data(document.body).setTab('portfolio'));await page.waitForTimeout(500);
 assert.equal(await page.locator('#chart-portfolio-equity .analytics-plot').count(),1);
 assert.equal(await page.locator('#chart-portfolio-strategy tbody tr').count(),3);
 assert.equal(await page.evaluate(()=>Boolean(window.echarts)),false);
 assert.equal(await page.evaluate(()=>Alpine.$data(document.body).stopTone({})), 'pending');
 const sections=await page.locator('.portfolio-analysis>.grid').evaluateAll(nodes=>nodes.map(el=>({top:el.getBoundingClientRect().top,bottom:el.getBoundingClientRect().bottom})));
 for(let i=1;i<sections.length;i++)assert(sections[i].top-sections[i-1].bottom>=20,'Portfolio sections must have a visible gutter');
 await page.getByRole('button',{name:/^positions/}).first().click();await page.waitForTimeout(1000);
 // Strategy-managed exits: rendered from the bot's reported policy, never as orders.
 const policyCard=page.locator('.trade-card',{hasText:'TRX/USDT'});
 assert.match(await policyCard.locator('.exit-policy-head').textContent(),/not resting exchange orders/);
 assert.deepEqual(await policyCard.locator('.exit-policy dl>div').evaluateAll(rows=>rows.map(row=>[row.querySelector('dt').textContent,row.querySelector('dd').textContent,row.title])),[
  ['ROI','Exits above +2.00% P&L now · final step since 24h',''],['Trailing','Off',''],
  ['Time','Exits after 96h if P&L is negative (in effect now)','Exit reason: v2_failed_reversion'],
  ['Time','Exits after 168h if P&L is below +1.00% (in 1.0d)','Exit reason: v2_expired_episode']]);
 const hlContext=await page.locator('.trade-card',{hasText:'LINK/USDC:USDC'}).locator('.position-context').innerText();
 assert.match(hlContext,/3× leverage · P&L % is on margin/);assert.match(hlContext,/Price \+8\.00% from entry/);
 const policyRows=await page.evaluate(()=>{const d=Alpine.$data(document.body);const now=Date.UTC(2026,9,1);const at=min=>({is_open:true,open_ts:now-min*60000,close_ts:now,open_rate:100,close_rate:101});
  const rows=(trade,policy)=>d.exitPolicyRows({...trade,exit_policy:policy}).map(r=>r.label+': '+r.text);
  return {young:rows(at(100),{roi:[[0,.08],[360,.05]],trailing:{enabled:false},rules:[{kind:'time',after_hours:36,profit_below:null,reason:'time_exit_36h'},{kind:'signal',text:'RSI(14) is below 30',reason:'x'}]}),
   shortOffset:rows({...at(10),is_short:true,leverage:3},{roi:[[0,100]],stoploss:-.06,trailing:{enabled:true,positive:.03,offset:.05,only_offset_reached:true},rules:[],receiver_driven:true}),
   fromEntry:rows({...at(10),leverage:3},{roi:[],stoploss:-.06,trailing:{enabled:true,positive:.03,offset:.05,only_offset_reached:false},rules:[]}),
   unreported:rows(at(10),{roi:null,stoploss:null,trailing:null,rules:[]}),
   closed:rows({...at(10),is_open:false},{roi:[[0,.08]],trailing:{enabled:false},rules:[]})};});
 assert.deepEqual(policyRows,{
  young:['ROI: Exits above +8.00% P&L now · +5.00% from 6h (in 4.3h)','Trailing: Off','Time: Exits after 36h (in 1.4d)','Signal: Exits when RSI(14) is below 30'],
  shortOffset:['ROI: Off · table set to +10000.00%','Trailing: Starts once P&L reaches +5.00%, then trails 1.00% above the lowest price','Receiver: Target exits and stop moves come from the source signal; the strategy adds no time or signal exit'],
  fromEntry:['ROI: No ROI table','Trailing: Trails 2.00% below the highest price; 1.00% once P&L exceeds +5.00%'],
  unreported:['ROI: Not reported by the bot','Trailing: Not reported by the bot'],closed:[]});
 await page.getByRole('button',{name:'Close position…',exact:true}).first().click();
 if(process.env.SCREENSHOTS){fs.mkdirSync(process.env.SCREENSHOTS,{recursive:true});for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:process.env.SCREENSHOTS+'/close-'+width+'.png'});}await page.setViewportSize({width:1440,height:1000});}
 await page.getByLabel('Bot API username').fill('operator');await page.getByLabel('Bot API password').fill('synthetic');
 await page.getByRole('button',{name:'Confirm market close',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Exit request accepted'}).waitFor();
 assert.equal(closeRequests,1);assert.equal(await page.getByRole('button',{name:'Confirm market close',exact:true}).isDisabled(),true);
 assert.equal(await page.getByLabel('Bot API password').inputValue(),'');
 await page.getByRole('button',{name:'Dismiss',exact:true}).click();
 // An unfilled limit entry is an order, not a position (#159).
 const pendingCard=page.locator('.trade-card',{hasText:'ENA/USDC:USDC'});
 assert.equal((await pendingCard.locator('.trade-reason').textContent()).trim(),'ENTRY PENDING');
 assert.equal(await pendingCard.locator('.trade-pnl').isVisible(),false,'No P&L before a fill');
 assert.equal(await pendingCard.locator('.exit-levels').isVisible(),false,'No placeholder stop or TP chips before a fill');
 assert.equal((await pendingCard.locator('.trade-entry-price').textContent()).replace(/\s+/g,' ').trim(),'Entry limit 0.22500');
 assert.equal(await pendingCard.getByRole('button',{name:'Close position…',exact:true}).count(),0);
 const pendingRows=await pendingCard.locator('.entry-order dl>div').evaluateAll(rows=>rows.map(r=>[r.querySelector('dt').textContent,r.querySelector('dd').textContent]));
 assert.deepEqual(pendingRows.map(r=>r[0]),['Order','Resting','Expires','Price','Stop']);
 assert.equal(pendingRows[0][1],'Limit buy 413 at 0.22500');assert.match(pendingRows[1][1],/^Since \d+-\d{2} \d{2}:\d{2} UTC \(3\.0h\)$/);
 assert.match(pendingRows[2][1],/ \(in 21\.0h\) · bot cancels it if still unfilled$/);assert.equal(pendingRows[3][1],'Now 0.23100 · the limit is -2.60% from here');
 assert.equal(pendingRows[4][1],'Not active until the entry fills · signal stop 0.20000 applies after the fill');
 const hero=await page.evaluate(()=>{const h=Alpine.$data(document.body).hero;return [h.openNotional,h.openCount,h.pendingEntries];});
 assert.deepEqual(hero,[87,4,1],'A resting entry is neither exposure nor an open position');
 // Hyperliquid can report amount before the order record's fill: never pending then.
 const lagging=await page.evaluate(()=>{const d=Alpine.$data(document.body);const list=d.raw.bots['killers-ft'].open_trades;list.push({...list.find(t=>t.trade_id===15),trade_id:16,pair:'SUI/USDC:USDC',amount:50});const row=d.openTradesAll.find(t=>t.trade_id===16);const out=[row.entry_pending,d.canCancelEntry(row),d.hero.pendingEntries];list.pop();return out;});
 assert.deepEqual(lagging,[false,false,1]);
 // #185: a booked partial exit (TP rung) of an open trade is realized at its fill time, not only when the trade closes.
 const fillTs=Date.now()-86400000;
 const booked=await page.evaluate(fillTs=>{const d=Alpine.$data(document.body);const bot=d.raw.bots['killers-ft'];const t=bot.open_trades.find(x=>x.pair==='LINK/USDC:USDC');
  const pairBefore=d.portfolioPairRows.find(r=>r.pair===t.pair).realized;const expBefore=d.hero.expectancyPerTrade;
  bot._pnl=bot.pnl;bot.pnl={...bot.pnl,closed:bot.pnl.closed+3,closed_trades:bot.pnl.closed,all_coin:bot.pnl.all_coin+3};t.partial_exits=[[fillTs,3]];t.realized_abs=3;
  const curve=d.fleetPerformanceData.realized;const i=curve.findIndex(p=>p[0]===fillTs);
  return {step:i>0?Number((curve[i][1]-curve[i-1][1]).toFixed(4)):null,pair:Number((d.portfolioPairRows.find(r=>r.pair===t.pair).realized-pairBefore).toFixed(4)),expectancyUnchanged:d.hero.expectancyPerTrade===expBefore};},fillTs);
 assert.deepEqual(booked,{step:3,pair:3,expectancyUnchanged:true});
 await page.waitForTimeout(200);
 assert.match(await page.locator('.trade-card',{hasText:'LINK/USDC:USDC'}).locator('.trade-pnl .abs').textContent(),/booked \+\$3\.00\)$/);
 await page.evaluate(()=>{const bot=Alpine.$data(document.body).raw.bots['killers-ft'];const t=bot.open_trades.find(x=>x.pair==='LINK/USDC:USDC');bot.pnl=bot._pnl;delete bot._pnl;delete t.partial_exits;delete t.realized_abs;});
 const partialCard=page.locator('.trade-card',{hasText:'OP/USDT'});
 assert.equal((await partialCard.locator('.trade-reason').textContent()).trim(),'OPEN');assert.equal(await partialCard.locator('.trade-pnl').isVisible(),true);
 assert.equal(await partialCard.getByRole('button',{name:/Cancel entry order|Close position/}).count(),0,'No dashboard cancel once any quantity fills');
 assert.match(await partialCard.locator('.entry-order-note').textContent(),/^Dashboard cancel is off because part of this entry has filled/);
 assert.equal(await pendingCard.locator('.entry-order-note').isVisible(),false);
 await page.evaluate(()=>Alpine.$data(document.body).setTab('bot:killers-ft'));await page.waitForTimeout(300);
 const pendingActivity=await page.locator('main:visible .arow',{hasText:'ENA'}).innerText();assert.match(pendingActivity,/entry pending/);assert.match(pendingActivity,/limit 0\.22500/);assert.doesNotMatch(pendingActivity,/\+0\.00%|100% open/);
 await page.evaluate(()=>Alpine.$data(document.body).setTab('trades'));await page.waitForTimeout(500);
 const partialRows=await page.evaluate(()=>{const now=Date.UTC(2026,9,3);return Alpine.$data(document.body).entryOrderRows({is_open:true,close_ts:now,close_rate:.231,entry:{state:'partial',side:'buy',order_type:'limit',price:.225,requested:413,filled:200,placed_ts:now-3600000,expires_ts:null}}).map(r=>r.label+': '+r.text);});
 assert.deepEqual(partialRows,['Order: Limit buy 413 at 0.22500 · 200 of 413 filled','Resting: Since 10-02 23:00 UTC (1.0h)','Expires: Timeout not reported by the bot','Price: Now 0.23100 · the limit is -2.60% from here']);
 await pendingCard.getByRole('button',{name:'Cancel entry order…',exact:true}).click();
 assert.equal(await page.locator('#close-title').textContent(),'Cancel the resting entry order?');
 await page.getByLabel('Bot API password').fill('synthetic');await page.getByRole('button',{name:'Confirm cancel entry',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Entry order cancelled: the bot no longer reports it resting, and nothing filled.'}).waitFor();
 assert.deepEqual(cancelRequests.map(r=>[r.path,r.action,r.body.order_id,r.body.amount,r.body.pair]),[['/api/trades/killers-ft/15/cancel-entry','cancel-entry','synthetic-entry-15',0,'ENA/USDC:USDC']]);
 assert.equal(closeRequests,1);await page.getByRole('button',{name:'Dismiss',exact:true}).click();
 await pendingCard.getByRole('button',{name:'Cancel entry order…',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'Confirm cancel entry',exact:true}).isDisabled(),true,'A submitted action stays locked for that trade');
 await page.getByRole('button',{name:'Dismiss',exact:true}).click();assert.equal(cancelRequests.length,1);
 await page.getByRole('button',{name:'All exits',exact:true}).first().click();await page.getByRole('button',{name:'Expand chart',exact:true}).first().click();await page.waitForTimeout(400); assert.equal(await page.locator('.trade-card.expanded').count(),1);const expanded=await page.locator('.trade-card.expanded .trade-chart').boundingBox();assert(expanded.width>1200&&expanded.height>=600);
 await page.keyboard.press('Escape');assert.equal(await page.locator('.trade-card.expanded').count(),0);await page.setViewportSize({width:390,height:844});await page.waitForTimeout(400);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.setViewportSize({width:1440,height:1000}); await page.evaluate(()=>Alpine.$data(document.body).setTab('bot:killers-ft'));await page.waitForTimeout(500);
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});for(const tab of ['live','portfolio','trades','dryrun','bot:killers-ft']){await page.evaluate(tab=>Alpine.$data(document.body).setTab(tab),tab);await page.waitForTimeout(200);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${tab} overflow at ${width}`);
 if(tab==='portfolio'){for(let pass=0;pass<3;pass++){await page.evaluate(()=>Alpine.$data(document.body).renderPortfolioCharts());await page.waitForTimeout(100);const geometry=await page.locator('#chart-portfolio-equity [data-series]').evaluate(el=>({width:el.getBBox().width,plot:el.closest('svg').getBoundingClientRect().width}));assert(geometry.width>geometry.plot*.65,`Equity must fill plot after render/resize: ${JSON.stringify(geometry)}`);}}
 assert.equal((await page.locator('main:visible').innerText()).includes('undefined'),false);}}
 await page.emulateMedia({colorScheme:'light'});await page.evaluate(()=>Alpine.$data(document.body).openPositionsTab());await page.waitForTimeout(1000);
 const rgb=hex=>{const h=hex.trim().replace('#','');return [0,2,4].map(i=>parseInt(h.slice(i,i+2),16));};
 const theme=()=>page.evaluate(()=>{const root=document.documentElement,token=name=>getComputedStyle(root).getPropertyValue(name).trim();return {theme:root.dataset.theme,scheme:getComputedStyle(root).colorScheme,bg:getComputedStyle(document.body).backgroundColor,bgToken:token('--bg-0'),chartToken:token('--chart-bg'),gridToken:token('--hairline'),label:document.querySelector('.theme-toggle').getAttribute('aria-label')};});
 const chartPixel=()=>page.locator('.trade-chart').first().evaluate(el=>{const canvas=[...el.querySelectorAll('canvas')].sort((a,b)=>b.width*b.height-a.width*a.height)[0];return Array.from(canvas.getContext('2d').getImageData(2,2,1,1).data.slice(0,3));});
 let themed=await theme();assert.equal(themed.theme,'light');assert.equal(themed.label,'Theme: system. Switch theme');assert.deepEqual(await chartPixel(),rgb(themed.chartToken));
 const toggle=page.locator('.theme-toggle');await toggle.focus();await page.keyboard.press('Enter');await page.waitForTimeout(200);assert.equal((await theme()).theme,'light');assert.equal((await theme()).label,'Theme: light. Switch theme');await page.keyboard.press('Enter');await page.waitForTimeout(400);
 themed=await theme();assert.equal(themed.theme,'dark');assert.equal(themed.scheme,'dark');assert.equal(themed.bg,`rgb(${rgb(themed.bgToken).join(', ')})`);assert.notDeepEqual(rgb(themed.bgToken),[244,246,248]);assert.equal(themed.label,'Theme: dark. Switch theme');
 assert.deepEqual(await chartPixel(),rgb(themed.chartToken),'Position chart background must follow the theme');
 await page.evaluate(()=>Alpine.$data(document.body).setTab('portfolio'));await page.waitForTimeout(500);
 assert.equal(await page.locator('#chart-portfolio-equity svg line').first().getAttribute('stroke'),themed.gridToken);
 await toggle.click();await page.waitForTimeout(200);assert.equal(await page.locator('#chart-portfolio-equity svg line').first().getAttribute('stroke'),(await theme()).gridToken,'Analytics must redraw on theme change');assert.notEqual((await theme()).gridToken,themed.gridToken);
 await toggle.click();await toggle.click();await page.waitForTimeout(200);
 await page.reload();await page.waitForTimeout(1800);themed=await theme();assert.equal(themed.theme,'dark','Theme preference must persist across reload');assert.equal(themed.label,'Theme: dark. Switch theme');
 await page.evaluate(()=>Alpine.$data(document.body).openPositionsTab());await page.waitForTimeout(1000);const logoFill=(await page.locator('.trade-chart #tv-attr-logo path[fill="var(--fill)"]').first().evaluate(el=>getComputedStyle(el).fill)).match(/\d+/g).slice(0,3).map(Number);const logoRatio=contrast(logoFill,rgb(themed.chartToken));assert(logoRatio>=3,`TradingView logo created in dark must stay legible: ${logoRatio}`);console.log('Dark logo contrast at creation',logoRatio);
 await toggle.click();await page.waitForTimeout(200);assert.equal((await theme()).theme,'light');
 await page.emulateMedia({colorScheme:'dark'});await page.waitForTimeout(200);assert.equal((await theme()).theme,'dark','System must follow prefers-color-scheme');
 await page.emulateMedia({colorScheme:'light'});await page.waitForTimeout(200);assert.equal((await theme()).theme,'light');
 await page.reload();await page.waitForTimeout(1800);assert.equal((await theme()).label,'Theme: system. Switch theme');
 assert.deepEqual(errors,[]);console.log('Workspace overview, positions, expansion, Escape, mobile and bot detail, theme passed');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
