import {createChart, CandlestickSeries, ColorType, LineStyle, type UTCTimestamp, type AutoscaleInfoProvider, type IPriceLine} from 'lightweight-charts';
type Level={price:number;label:string;state?:string};
type Trade={open_rate:number;close_rate:number;stop_rate?:number;is_open?:boolean;exit_levels?:Level[]};
class PriceChart {
  private chart; private series; private lines:IPriceLine[]=[]; private timeframe=''; private dead=false;
  private exits:Level[]=[]; private mode='price';
  constructor(private el:HTMLElement) {
    this.chart=createChart(el,{autoSize:true,localization:{locale:"en-US"},layout:{background:{type:ColorType.Solid,color:'#ffffff'},textColor:'#526170',fontSize:12,attributionLogo:true},grid:{vertLines:{visible:false},horzLines:{color:'#edf0f2'}},rightPriceScale:{borderVisible:false,scaleMargins:{top:.12,bottom:.12}},timeScale:{borderVisible:false,timeVisible:true,secondsVisible:false,rightOffset:4},crosshair:{mode:0}});
    this.series=this.chart.addSeries(CandlestickSeries,{upColor:'#16714b',downColor:'#c23b35',borderVisible:false,wickUpColor:'#16714b',wickDownColor:'#c23b35',lastValueVisible:false,priceLineVisible:false,autoscaleInfoProvider:((original)=>{const info=original();if(!info?.priceRange || this.mode!=='exits')return info;for(const x of this.exits){info.priceRange.minValue=Math.min(info.priceRange.minValue,x.price);info.priceRange.maxValue=Math.max(info.priceRange.maxValue,x.price);}return info;}) as AutoscaleInfoProvider});
  }
  render(rows:number[][],trade:Trade,tf:string,mode:string) {
    const data=rows.filter(r=>r.length>=5 && r.every(Number.isFinite)).map(r=>({time:Math.floor(r[0]/1000) as UTCTimestamp,open:r[1],close:r[2],low:r[3],high:r[4]})).sort((a,b)=>a.time-b.time).filter((r,i,a)=>!i||r.time!==a[i-1].time);
    if(!data.length)return;
    const previous=this.chart.timeScale().getVisibleLogicalRange();
    this.mode=mode;
    this.exits=[{price:trade.open_rate,label:'Entry'},{price:trade.close_rate,label:trade.is_open?'Current':'Exit'},...(trade.is_open && trade.stop_rate?[{price:trade.stop_rate,label:trade.is_open?'Bot stop':'Recorded stop',state:'stop'}]:[]),...(trade.exit_levels||[])].filter(x=>Number.isFinite(x.price)&&x.price>0);
    const reference=data[data.length-1].close;
    const precision=Math.min(10,Math.max(2,4-Math.floor(Math.log10(reference))));
    this.series.applyOptions({priceFormat:{type:'price',precision,minMove:10**-precision}});
    this.series.setData(data);
    this.lines.forEach(line=>this.series.removePriceLine(line));
    this.lines=this.exits.map(x=>this.series.createPriceLine({price:x.price,title:x.label,axisLabelVisible:true,color:x.state==='stop'?'#c23b35':x.state==='active'?'#16714b':x.state==='pending'?'#9a690a':'#657482',lineStyle:x.state==='active'?LineStyle.Solid:LineStyle.Dashed,lineWidth:1}));
    if(previous&&this.timeframe===tf)this.chart.timeScale().setVisibleLogicalRange(previous);
    else this.chart.timeScale().setVisibleLogicalRange({from:Math.max(0,data.length-90),to:data.length+3});
    this.timeframe=tf;
  }
  getDom(){return this.el;} isDisposed(){return this.dead;}
  resize(){if(!this.dead)this.chart.resize(this.el.clientWidth,this.el.clientHeight);}
  dispose(){this.dead=true;this.chart.remove();}
}
(window as unknown as {TradingPriceChart:typeof PriceChart}).TradingPriceChart=PriceChart;
