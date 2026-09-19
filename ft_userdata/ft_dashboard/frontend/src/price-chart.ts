import {createChart, createSeriesMarkers, CandlestickSeries, ColorType, LineStyle, type UTCTimestamp, type AutoscaleInfoProvider, type IPriceLine} from 'lightweight-charts';
type Level={price:number;label:string;state?:string};
type Trade={open_ts?:number|string;is_short?:boolean;open_rate:number;close_rate:number;stop_rate?:number;is_open?:boolean;exit_levels?:Level[]};
class PriceChart {
  private chart; private series; private lines:IPriceLine[]=[]; private timeframe=''; private dead=false;
  private exits:Level[]=[]; private mode='price'; private markers; private entryIndex=-1;
  constructor(private el:HTMLElement) {
    this.chart=createChart(el,{autoSize:true,localization:{locale:"en-US"},layout:{background:{type:ColorType.Solid,color:'#ffffff'},textColor:'#526170',fontSize:12,attributionLogo:true},grid:{vertLines:{visible:false},horzLines:{color:'#edf0f2'}},rightPriceScale:{borderVisible:false,scaleMargins:{top:.12,bottom:.12}},timeScale:{borderVisible:false,timeVisible:true,secondsVisible:false,rightOffset:4},crosshair:{mode:0}});
    this.series=this.chart.addSeries(CandlestickSeries,{upColor:'#16714b',downColor:'#c23b35',borderVisible:false,wickUpColor:'#16714b',wickDownColor:'#c23b35',lastValueVisible:false,priceLineVisible:false,autoscaleInfoProvider:((original)=>{const info=original();if(!info?.priceRange || this.mode!=='exits')return info;for(const x of this.exits){info.priceRange.minValue=Math.min(info.priceRange.minValue,x.price);info.priceRange.maxValue=Math.max(info.priceRange.maxValue,x.price);}return info;}) as AutoscaleInfoProvider});
    this.markers=createSeriesMarkers(this.series,[]);
  }
  render(rows:number[][],trade:Trade,tf:string,mode:string) {
    const data=rows.filter(r=>r.length>=5 && r.every(Number.isFinite)).map(r=>({time:Math.floor(r[0]/1000) as UTCTimestamp,open:r[1],close:r[2],low:r[3],high:r[4]})).sort((a,b)=>a.time-b.time).filter((r,i,a)=>!i||r.time!==a[i-1].time);
    if(!data.length)return;
    const previous=this.chart.timeScale().getVisibleLogicalRange();
    this.mode=mode;
    this.exits=[{price:trade.open_rate,label:'Entry price',state:'entry'},{price:trade.close_rate,label:trade.is_open?'Current':'Exit'},...(trade.is_open && trade.stop_rate?[{price:trade.stop_rate,label:trade.is_open?'Bot stop':'Recorded stop',state:'stop'}]:[]),...(trade.exit_levels||[])].filter(x=>Number.isFinite(x.price)&&x.price>0);
    const reference=data[data.length-1].close;
    const precision=Math.min(10,Math.max(2,4-Math.floor(Math.log10(reference))));
    this.series.applyOptions({priceFormat:{type:'price',precision,minMove:10**-precision}});
    this.series.setData(data);
    this.lines.forEach(line=>this.series.removePriceLine(line));
    this.lines=this.exits.map(x=>this.series.createPriceLine({price:x.price,title:x.label,axisLabelVisible:true,color:x.state==='entry'?'#176c84':x.state==='stop'?'#c23b35':x.state==='active'?'#16714b':x.state==='pending'?'#9a690a':'#657482',lineStyle:x.state==='entry'||x.state==='active'?LineStyle.Solid:LineStyle.Dotted,lineWidth:x.state==='entry'?2:1}));
    const raw=trade.open_ts;
    const numeric=Number(raw);
    const opened=raw==null?NaN:Number.isFinite(numeric)?(numeric<1e12?numeric*1000:numeric):Date.parse(String(raw));
    const seconds=opened/1000;
    const duration=({"5m":300,"15m":900,"1h":3600,"4h":14400} as Record<string,number>)[tf];
    const candle=duration&&Number.isFinite(seconds)?data.find(r=>r.time<=seconds&&seconds<r.time+duration):undefined;
    this.entryIndex=candle?data.indexOf(candle):-1;
    this.markers.setMarkers(candle?[{time:candle.time,position:trade.is_short?'aboveBar':'belowBar',shape:trade.is_short?'arrowDown':'arrowUp',color:'#176c84',text:'Entry',size:1.5}]:[]);
    if(previous&&this.timeframe===tf)this.chart.timeScale().setVisibleLogicalRange(previous);
    else this.chart.timeScale().setVisibleLogicalRange({from:Math.max(0,data.length-90),to:data.length+3});
    this.timeframe=tf;
  }
  focusEntry(){if(this.entryIndex<0)return false;this.chart.timeScale().setVisibleLogicalRange({from:Math.max(0,this.entryIndex-12),to:this.entryIndex+12});return true;}
  getDom(){return this.el;} isDisposed(){return this.dead;}
  resize(){if(!this.dead)this.chart.resize(this.el.clientWidth,this.el.clientHeight);}
  dispose(){this.dead=true;this.chart.remove();}
}
(window as unknown as {TradingPriceChart:typeof PriceChart}).TradingPriceChart=PriceChart;

import "./analytics";
