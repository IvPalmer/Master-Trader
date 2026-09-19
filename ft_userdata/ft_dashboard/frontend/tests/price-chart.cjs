// No HTTP server or live API: the built chart runs against synthetic candles.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch(process.env.CHROME_CHANNEL?{channel:process.env.CHROME_CHANNEL}:{});
 try{
 const page=await browser.newPage();await page.setContent('<div id="chart" style="width:800px;height:400px"></div>');
 await page.addScriptTag({path:require('path').join(__dirname,'../../static/price-chart.js')});
 const r=await page.evaluate(async()=>{
  const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  const el=document.getElementById('chart');const c=new window.TradingPriceChart(el);
  const bars=Array.from({length:120},(_,i)=>[1700000000000+i*3600000,100,101,99,102]);
  const trade={open_ts:bars[50][0]+1800000,open_rate:100,close_rate:101,stop_rate:50,is_open:true,exit_levels:[{price:160,label:'TP 1',state:'active'},{price:180,label:'TP 2',state:'pending'}]};
  c.render(bars,trade,'1h','price');await frame();
  c.chart.timeScale().setVisibleLogicalRange({from:20,to:60});await frame();
  c.render(bars,trade,'1h','price');await frame();const viewport=c.chart.timeScale().getVisibleLogicalRange();
  const price=c.series.options().autoscaleInfoProvider(()=>({priceRange:{minValue:99,maxValue:102}}));
  c.render(bars,trade,'1h','exits');const exits=c.series.options().autoscaleInfoProvider(()=>({priceRange:{minValue:99,maxValue:102}}));
  const labels=c.lines.map(x=>x.options().title);
  const entryLine=c.lines.find(x=>x.options().title==='Entry price').options();
  const entryMarker=c.markers.markers()[0];
  c.focusEntry();await frame();const focused=c.chart.timeScale().getVisibleLogicalRange();
  c.render(bars,{...trade,open_ts:bars[0][0]-3600000},'1h','price');const outsideMarkers=c.markers.markers().length;
  c.render(bars,{...trade,is_short:true},'1h','price');const shortMarker=c.markers.markers()[0];
  el.style.width='1100px';el.style.height='600px';c.resize();await frame();const width=Math.max(...Array.from(el.querySelectorAll('canvas'),x=>x.getBoundingClientRect().width));
  c.render(bars,trade,'4h','price');await frame();const reset=c.chart.timeScale().getVisibleLogicalRange();c.dispose();
  return {viewport,price,exits,labels,entryLine,entryMarker,focused,outsideMarkers,shortMarker,width,reset,disposed:c.isDisposed()};
 });
 assert(Math.abs(r.viewport.from-20)<1e-8&&Math.abs(r.viewport.to-60)<1e-8);assert.deepEqual(r.price.priceRange,{minValue:99,maxValue:102});assert.deepEqual(r.exits.priceRange,{minValue:50,maxValue:180});assert(r.labels.includes('TP 1')&&r.labels.includes('TP 2'));assert(r.width>800);assert(r.reset.to>60);assert(r.disposed);assert.equal(r.entryLine.lineWidth,2);assert.equal(r.entryLine.color,'#176c84');assert.equal(r.entryMarker.time,(1700000000000+50*3600000)/1000);assert.equal(r.entryMarker.shape,'arrowUp');assert.equal(r.shortMarker.shape,'arrowDown');assert.equal(r.outsideMarkers,0);assert(Math.abs(r.focused.from-38)<1e-8);assert(Math.abs(r.focused.to-62)<1e-8);console.log('Chart viewport, exit scales, target labels, resize, timeframe and disposal passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
