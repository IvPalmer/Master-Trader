const {chromium,webkit}=require('playwright');
const fs=require('fs');const luminance=([r,g,b])=>{const [x,y,z]=[r,g,b].map(v=>v/255).map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4);return 0.2126*x+0.7152*y+0.0722*z;};const contrast=(a,b)=>{const [x,y]=[luminance(a),luminance(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);};const root=require('path').join(__dirname,'../../');const assert=require('node:assert/strict');
(async()=>{
 const launchOptions=process.env.CHROME&&process.env.BROWSER_ENGINE!=='webkit'?{executablePath:process.env.CHROME}:process.env.CHROME_CHANNEL&&process.env.BROWSER_ENGINE!=='webkit'?{channel:process.env.CHROME_CHANNEL}:{};const browser=await (process.env.BROWSER_ENGINE==='webkit'?webkit:chromium).launch(launchOptions);const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.addInitScript(()=>Object.defineProperty(navigator,'language',{get:()=> 'en-US@posix'}));const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const fixture=require('./fixture.cjs')(); let closeRequests=0; const cancelRequests=[];
 await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.pathname.includes('alpine'))return route.fulfill({path:require.resolve('alpinejs/dist/cdn.min.js'),contentType:'text/javascript'});if(url.pathname.endsWith('/close')) {closeRequests++;return route.fulfill({json:{state:'accepted'}});}if(url.pathname.endsWith('/cancel-entry')){cancelRequests.push({path:url.pathname,action:route.request().headers()['x-trade-action'],body:route.request().postDataJSON()});return route.fulfill({json:{state:'cancelled'}});}if(url.pathname.startsWith('/api/'))return route.fulfill({json:fixture.response(url.pathname)});if(url.pathname.startsWith('/static/'))return route.fulfill({path:root+url.pathname.slice(1)});if(url.hostname==='dashboard.test')return route.fulfill({body:fs.readFileSync(root+'templates/index.html','utf8').replace('master-trader<span>','master-trader · Preview<span>'),contentType:'text/html'});return route.abort();});
 await page.goto('https://dashboard.test/');await page.waitForTimeout(1800);
 await page.locator('details.workspace-research').evaluate(el=>{el.open=true});await page.waitForTimeout(300);
 assert.match(await page.locator('main:visible .workspace-vitals').innerText(),/4 open positions · 1 entry pending/,'Pending entries are counted apart from positions');
 const recentLive=page.locator('details.workspace-research table.ledger');
 assert.equal((await recentLive.locator('thead th').nth(1).textContent()).trim(),'strategy','Merged live-bot ledger must name the bot');
 const recentBots=await recentLive.locator('tbody tr').evaluateAll(rows=>rows.map(row=>row.cells[1].textContent.trim()));
 assert.equal(recentBots.length,6);assert.deepEqual([...new Set(recentBots)].sort(),['funding-fade','keltner-bounce','killers-scalp']);
 assert.equal((await recentLive.locator('.pnl-audit:visible').textContent()).trim(),'userFills · FT raw −$10.04');
 if(process.env.SCREENSHOTS){fs.mkdirSync(process.env.SCREENSHOTS,{recursive:true});await recentLive.screenshot({path:process.env.SCREENSHOTS+'/reconciled-pnl-ledger.png'});}
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
  bot._pnl=bot.pnl;bot._events=bot.realized_events;bot.pnl={...bot.pnl,closed:bot.pnl.closed+3,closed_trades:bot.pnl.closed,all_coin:bot.pnl.all_coin+3};bot.realized_events=[...bot.realized_events,[fillTs,3]];t.partial_exits=[[fillTs,3]];t.realized_abs=3;
  const curve=d.fleetPerformanceData.realized;const i=curve.findIndex(p=>p[0]===fillTs);
  return {step:i>0?Number((curve[i][1]-curve[i-1][1]).toFixed(4)):null,pair:Number((d.portfolioPairRows.find(r=>r.pair===t.pair).realized-pairBefore).toFixed(4)),expectancyUnchanged:d.hero.expectancyPerTrade===expBefore};},fillTs);
 assert.deepEqual(booked,{step:3,pair:3,expectancyUnchanged:true});
 await page.waitForTimeout(200);
 assert.match(await page.locator('.trade-card',{hasText:'LINK/USDC:USDC'}).locator('.trade-pnl .abs').textContent(),/booked \+\$3\.00\)$/);
 await page.evaluate(()=>{const bot=Alpine.$data(document.body).raw.bots['killers-ft'];const t=bot.open_trades.find(x=>x.pair==='LINK/USDC:USDC');bot.pnl=bot._pnl;bot.realized_events=bot._events;delete bot._pnl;delete bot._events;delete t.partial_exits;delete t.realized_abs;});
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
 // #277: a stopped live epoch keeps counting in realized results only; a stopped paper epoch stays in validation.
 {const st=fixture.state;const end=Date.now()-2*86400000;const s0=end-10*86400000;const close=s0+2*86400000;
  const rec={trade_id:901,pair:'SOL/USDC:USDC',is_open:false,open_rate:100,close_rate:104,amount:.25,stake_amount:25,profit_abs:4,profit_pct:16,open_timestamp:s0+86400000,close_timestamp:close,open_date:new Date(s0+86400000).toISOString(),close_date:new Date(close).toISOString(),exit_reason:'roi'};
  const stopped=(key,dry)=>({key,bot_key:key.split('.')[0],label:key.split('.')[0],name:key.split('.')[0],reachable:false,stopped:true,dry_run:dry,venue:'hyperliquid',account_group:'hl-retained',wallet:{starting_capital:98,bot_owned:null,total:null},pnl:{closed:4,unrealized:0,all_coin:4,all_pct:4.08,closed_trades:4},stats:{closed_trade_count:1,winning_trades:1,losing_trades:0,winrate:1,max_drawdown:.02,gross_profit:4,gross_loss:0,profit_factor:null},capital_at_risk:{abs_loss:0},epoch:{label:'synthetic epoch',version:'Synthetic',start_ts_ms:s0,end_ts_ms:end,reason:'moved to dry-run',issue:999},open_trades:[],recent_trades:[rec],realized_events:[[close,4]],per_pair:[{pair:rec.pair,pnl:4,count:1}],no_baseline:true,observational:true,gate1:null,gate2:null,gate3:null,history:{complete:true,count:1},native_stop:{status:'not-applicable'},readiness:{status:'not-applicable',label:'epoch ended',healthy:null}});
  const before=await page.evaluate(()=>{const d=Alpine.$data(document.body);return {realized:d.hero.totalRealizedPnl,closed:d.hero.closedTrades,risk:d.hero.capitalAtRisk,open:d.hero.openCount,events:d.liveBots.flatMap(b=>b.realized_events).reduce((s,e)=>s+e[1],0)};});
  st.bots['killers-ft.live-r1']=stopped('killers-ft.live-r1',false);st.bots['oi-trend.paper-r1']=stopped('oi-trend.paper-r1',true);
  st.account_health.accounts['hl-retained']={equity:50,free:50,margin:0};st.account_health.drawdown_pct=2.5;
  st.epoch_records={errors:[],coverage:{uncovered:[{db:'tradesv3.live.Synthetic.sqlite',count:2,trade_ids:[1,2]}],unverified:[]}};
  await page.evaluate(()=>Alpine.$data(document.body).setTab('live'));await page.evaluate(()=>Alpine.$data(document.body).refresh());await page.waitForTimeout(500);
  const got=await page.evaluate(()=>{const d=Alpine.$data(document.body);const paper=d.dryRunBots.find(b=>b.key==='oi-trend.paper-r1');return {live:d.liveBots.map(b=>b.key),stopped:d.stoppedBots.map(b=>b.key),realized:d.hero.totalRealizedPnl,closed:d.hero.closedTrades,risk:d.hero.capitalAtRisk,open:d.hero.openCount,accounts:d.liveAccountCount,curve:d.fleetPerformanceData,verdict:paper&&d.dryBotVerdict(paper).text,incident:d.attentionItems.find(i=>/belong to no epoch/.test(i.subject))?.color};});
  assert.equal(got.live.length,3,'A stopped epoch is not a running bot');assert.deepEqual(got.stopped,['killers-ft.live-r1'],'Paper records stay out of the live hero');
  assert.equal(Number((got.realized-before.realized).toFixed(4)),4,'All-time realized P&L includes the stopped epoch');assert.equal(got.closed,before.closed+1);
  assert.equal(got.risk,before.risk,'Stop risk is running bots only');assert.equal(got.open,before.open,'Open count is running bots only');
  assert.equal(got.accounts,3,'A funded account with only stopped bots still counts');assert.equal(got.verdict,'stopped');assert.equal(got.incident,'amber','Unarchived trades warn without red status');
  assert.equal(got.curve.zeroBased,true);assert.equal(got.curve.realized[0][1],0,'Fleet curve starts at zero');assert.equal(Number(got.curve.realized.at(-1)[1].toFixed(4)),Number((before.events+4).toFixed(4)),'Fleet curve sums running and stopped realized events');
  assert.equal((await page.locator('#chart-drawdown .analytics-legend').textContent()).trim(),'Below peak · includes open P&L','Codex #277 P2: a drawdown with the open mark says so');
 const stoppedRows=page.locator('.bot-table tbody').nth(1).locator('tr');assert.equal(await stoppedRows.count(),2);const stoppedText=await stoppedRows.nth(1).innerText();assert.match(stoppedText,/STOPPED/);assert.match(stoppedText,/moved to dry-run · #999/);assert.match(stoppedText,/max DD 2\.00%/);
  await page.evaluate(()=>Alpine.$data(document.body).setTab('portfolio'));await page.waitForTimeout(300);assert.match(await page.locator('main:visible .fact-list').innerText(),/Current breaker drawdown · Binance \+ Killers\s+-2\.50%/);assert.match(await page.locator('main:visible .workspace-vitals').innerText(),/Worst bot drawdown/);
  await page.evaluate(()=>Alpine.$data(document.body).setTab('bot:killers-ft.live-r1'));await page.waitForTimeout(300);const inspector=page.locator('main:visible');assert.match(await inspector.innerText(),/STOPPED EPOCH/i);assert.equal(await inspector.locator('.card-title:text-is("Open trade status"):visible').count(),0,'No open-trade card for a record');assert.equal(await inspector.locator('.close-position:visible').count(),0,'A record has no trade controls');
  await page.route('**/api/trade_candles/gone*',route=>route.fulfill({status:410,json:{error:'Bot candles unavailable: synthetic',unavailable:true}}));
  const chartError=await page.evaluate(async()=>{const d=Alpine.$data(document.body);const t={bot_key:'gone',pair:'SOL/USDC:USDC',open_ts:Date.now()-7200000,close_ts:Date.now()-3600000,is_open:false,duration_min:60};await d.renderTradeChart(t);return d.tradeChartStatus(t).error;});
  assert.equal(chartError,'Bot candles unavailable: synthetic','The UI shows the server unavailable message');}
 assert.deepEqual(errors,[]);console.log('Workspace overview, positions, expansion, Escape, mobile and bot detail, theme passed');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
