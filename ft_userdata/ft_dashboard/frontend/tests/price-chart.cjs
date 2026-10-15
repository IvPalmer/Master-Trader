// No HTTP server or live API: the built chart runs against synthetic candles.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const channels=color=>color.startsWith('#')?[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)):color.match(/\d+/g).slice(0,3).map(Number);
const luminance=color=>{const [r,g,b]=channels(color).map(v=>v/255).map(v=>v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4);return 0.2126*r+0.7152*g+0.0722*b;};
const contrast=(a,b)=>{const [x,y]=[luminance(a),luminance(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);};
(async()=>{
 const launchOptions=process.env.CHROME?{executablePath:process.env.CHROME}:process.env.CHROME_CHANNEL?{channel:process.env.CHROME_CHANNEL}:{};
 const browser=await chromium.launch(launchOptions);
 try{
 const page=await browser.newPage();await page.setContent('<div id="chart" style="width:800px;height:400px"></div>');for(const sheet of ['styles.css','workspace.css'])await page.addStyleTag({path:require('path').join(__dirname,'../../static',sheet)});
 await page.addScriptTag({path:require('path').join(__dirname,'../../static/price-chart.js')});
 const r=await page.evaluate(async()=>{
  const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  const el=document.getElementById('chart');const c=new window.TradingPriceChart(el);
  const bars=Array.from({length:120},(_,i)=>[1700000000000+i*3600000,100,101,99,102]);
  const trade={open_ts:bars[50][0]+1800000,open_rate:100,close_rate:101,stop_rate:50,is_open:true,exit_levels:[{price:160,label:'TP 1',state:'active'},{price:180,label:'TP 2',state:'pending'}]};
  c.render(bars,trade,'1h','price');await frame();
  c.chart.timeScale().setVisibleLogicalRange({from:20,to:60});await frame();
  c.render(bars,trade,'1h','price');await frame();const viewport=c.chart.timeScale().getVisibleLogicalRange();
  const token=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();const lightBg=c.chart.options().layout.background.color;const logo=()=>getComputedStyle(el.querySelector('#tv-attr-logo path[fill="var(--fill)"]')).fill;const lightLogo=logo();
  document.documentElement.dataset.theme='dark';document.dispatchEvent(new CustomEvent('themechange'));await frame();
  const themed={range:c.chart.timeScale().getVisibleLogicalRange(),bg:c.chart.options().layout.background.color,bgToken:token('--chart-bg'),text:c.chart.options().layout.textColor,textToken:token('--chart-text'),up:c.series.options().upColor,upToken:token('--chart-up'),entry:c.lines.find(x=>x.options().title==='Entry price').options().color,marker:c.markers.markers()[0].color,entryToken:token('--chart-entry'),logo:logo()};
  document.documentElement.dataset.theme='light';document.dispatchEvent(new CustomEvent('themechange'));await frame();const relitLogo=logo();
  const price=c.series.options().autoscaleInfoProvider(()=>({priceRange:{minValue:99,maxValue:102}}));
  c.render(bars,trade,'1h','exits');const exits=c.series.options().autoscaleInfoProvider(()=>({priceRange:{minValue:99,maxValue:102}}));
  const labels=c.lines.map(x=>x.options().title);
  const entryLine=c.lines.find(x=>x.options().title==='Entry price').options();
  const entryMarker=c.markers.markers()[0];
  c.focusEntry();await frame();const focused=c.chart.timeScale().getVisibleLogicalRange();
  c.render(bars,{...trade,open_ts:bars[0][0]-3600000},'1h','price');const outsideMarkers=c.markers.markers().length;
  c.render(bars,{...trade,is_short:true},'1h','price');const shortMarker=c.markers.markers()[0];
  c.render(bars,{...trade,stop_rate:undefined,exit_levels:[],entry_pending:true},'1h','price');const pending={labels:c.lines.map(x=>x.options().title),style:c.lines[0].options().lineStyle,markers:c.markers.markers().length,focus:c.focusEntry()};
  el.style.width='1100px';el.style.height='600px';c.resize();await frame();const width=Math.max(...Array.from(el.querySelectorAll('canvas'),x=>x.getBoundingClientRect().width));
  c.render(bars,trade,'4h','price');await frame();const reset=c.chart.timeScale().getVisibleLogicalRange();c.dispose();
  return {pending,viewport,lightBg,lightLogo,relitLogo,themed,price,exits,labels,entryLine,entryMarker,focused,outsideMarkers,shortMarker,width,reset,disposed:c.isDisposed()};
 });
 assert(Math.abs(r.viewport.from-20)<1e-8&&Math.abs(r.viewport.to-60)<1e-8);assert.equal(r.lightBg,'#ffffff');assert.notEqual(r.themed.bg,r.lightBg);assert.equal(r.themed.bg,r.themed.bgToken);assert.equal(r.themed.text,r.themed.textToken);assert.equal(r.themed.up,r.themed.upToken);assert.equal(r.themed.entry,r.themed.entryToken);assert.equal(r.themed.marker,r.themed.entryToken);const logoRatio=contrast(r.themed.logo,r.themed.bgToken);assert(logoRatio>=3,`TradingView logo must stay legible in dark: ${logoRatio}`);assert.equal(r.lightLogo,'rgb(19, 23, 34)');assert.equal(r.relitLogo,r.lightLogo);console.log('Dark logo contrast',logoRatio);assert(Math.abs(r.themed.range.from-20)<1e-8&&Math.abs(r.themed.range.to-60)<1e-8,'Theme change must keep the visible range');assert.deepEqual(r.price.priceRange,{minValue:99,maxValue:102});assert.deepEqual(r.exits.priceRange,{minValue:50,maxValue:180});assert(r.labels.includes('TP 1')&&r.labels.includes('TP 2'));assert(r.width>800);assert(r.reset.to>60);assert(r.disposed);assert.equal(r.entryLine.lineWidth,2);assert.equal(r.entryLine.color,'#176c84');assert.equal(r.entryMarker.time,(1700000000000+50*3600000)/1000);assert.equal(r.entryMarker.shape,'arrowUp');assert.equal(r.shortMarker.shape,'arrowDown');assert.equal(r.outsideMarkers,0);assert.deepEqual(r.pending,{labels:['Entry limit','Current'],style:1,markers:0,focus:false},'An unfilled entry is a limit, not a fill');assert(Math.abs(r.focused.from-38)<1e-8);assert(Math.abs(r.focused.to-62)<1e-8);console.log('Chart viewport, theme switch, exit scales, target labels, resize, timeframe and disposal passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
