import {scaleTime, scaleLinear} from 'd3-scale';
import {line, curveStepAfter, curveLinear} from 'd3-shape';
type Point = [number | Date, number];
type Curve = {label:string; data:Point[]; color:string; step?:boolean};
type View = {percent?:boolean; snapshot?:{label:string;value:number}|null; note?:string; empty?:string};
const money=(value:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2}).format(value);
const node=(tag:string,text='',className='')=>{const el=document.createElement(tag);el.textContent=text;el.className=className;return el;};
const svgNode=(tag:string,attrs:Record<string,string|number>={},text='')=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,String(value));el.textContent=text;return el;};

/** Continuous calendar-time plots for sparse accounting events. Candles use a separate trading chart. */
export class Analytics {
  private dead=false;
  private observer:ResizeObserver|null=null;
  private redraw:(()=>void)|null=null;
  constructor(private el:HTMLElement) {}
  private clear(){this.observer?.disconnect();this.observer=null;this.redraw=null;this.el.replaceChildren();}
  lines(curves:Curve[],options:View={}) {
    this.clear();this.el.classList.remove('comparison');
    const legend=node('div','','analytics-legend');
    for(const curve of curves){const label=node('span',curve.label);const swatch=node('i');swatch.style.background=curve.color;label.prepend(swatch);legend.append(label);}
    this.el.append(legend);
    if(options.snapshot){const snapshot=node('div','','equity-snapshot');snapshot.append(node('span',options.snapshot.label),node('strong',money(options.snapshot.value)));this.el.append(snapshot);}
    if(options.note)this.el.append(node('div',options.note,'analytics-note'));
    const clean=curves.map(c=>({...c,data:[...new Map(c.data.filter(p=>Number.isFinite(+p[0])&&Number.isFinite(p[1])).map(p=>[+p[0],p[1]])).entries()].sort((a,b)=>a[0]-b[0])}));
    const all=clean.flatMap(c=>c.data);
    if(options.percent && all.length && all.every(p=>p[1]===0)){this.el.append(node('div','No drawdown in the recorded history.','analytics-empty'));return;}
    if(!all.length){this.el.append(node('div',options.empty||'History not available yet','analytics-empty'));return;}
    const plot=node('div','','analytics-plot');this.el.append(plot);
    const valueLabel=options.percent?(v:number)=>v.toFixed(2)+'%':money;
    this.redraw=()=>{
      const width=plot.clientWidth,height=plot.clientHeight;
      if(width<100||height<60)return;
      plot.replaceChildren();
      const left=8,right=width-76,top=12,bottom=height-32;
      let minTime=Math.min(...all.map(p=>p[0])),maxTime=Math.max(...all.map(p=>p[0]));
      if(minTime===maxTime){minTime-=86400000;maxTime+=86400000;}
      let min=Math.min(...all.map(p=>p[1])),max=Math.max(...all.map(p=>p[1]));
      if(options.percent)max=Math.max(0,max);
      const pad=Math.max((max-min)*.12,options.percent ? .01 : Math.max(Math.abs(max)*.0005,.01));
      const x=scaleTime().domain([new Date(minTime),new Date(maxTime)]).range([left,right]);
      const y=scaleLinear().domain([min-pad,options.percent?Math.min(0,max):max+pad]).nice(4).range([bottom,top]);
      const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'img','aria-label':`${curves.map(c=>c.label).join(', ')} over time`});
      svg.append(svgNode('title',{},'Historical observations. Hover to inspect a date. Current equity is shown separately.'));
      for(const value of y.ticks(4)){const py=y(value);svg.append(svgNode('line',{x1:left,x2:right,y1:py,y2:py,stroke:'#edf1f4'}));svg.append(svgNode('text',{x:right+12,y:py+4,fill:'#61717f','font-size':12},valueLabel(value)));}
      const count=width<450?3:5;
      for(let i=0;i<count;i++){const time=minTime+(maxTime-minTime)*i/(count-1);svg.append(svgNode('text',{x:x(time),y:height-6,fill:'#61717f','font-size':12,'text-anchor':i===0?'start':i===count-1?'end':'middle'},new Date(time).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'})));}
      for(const curve of clean){const path=line<[number,number]>().x(p=>x(p[0])).y(p=>y(p[1])).curve(curve.step?curveStepAfter:curveLinear)(curve.data);if(path)svg.append(svgNode('path',{d:path,fill:'none',stroke:curve.color,'stroke-width':2,'data-series':curve.label}));if(curve.data.length===1)svg.append(svgNode('circle',{cx:x(curve.data[0][0]),cy:y(curve.data[0][1]),r:3,fill:curve.color}));}
      const cross=svgNode('line',{x1:left,x2:left,y1:top,y2:bottom,stroke:'#9ba8b3','stroke-dasharray':'3 3',visibility:'hidden'});svg.append(cross);
      const tooltip=node('div','','analytics-tooltip');tooltip.hidden=true;plot.append(svg,tooltip);
      svg.addEventListener('pointermove',event=>{const px=Math.max(left,Math.min(right,(event as PointerEvent).clientX-svg.getBoundingClientRect().left));const time=+x.invert(px);cross.setAttribute('x1',String(px));cross.setAttribute('x2',String(px));cross.setAttribute('visibility','visible');const values=clean.map(c=>{const eligible=c.data.filter(p=>p[0]<=time);const p=eligible[eligible.length-1];return p?`${c.label}: ${valueLabel(p[1])}`:'';}).filter(Boolean);tooltip.textContent=[new Date(time).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}),...values].join(' · ');tooltip.hidden=false;});
      svg.addEventListener('pointerleave',()=>{cross.setAttribute('visibility','hidden');tooltip.hidden=true;});
    };
    this.observer=new ResizeObserver(()=>this.redraw?.());this.observer.observe(plot);this.redraw();
  }
  comparison(rows:{label:string;realized:number;unrealized:number}[]) {
    this.clear();this.el.classList.add('comparison');
    if(!rows.length){this.el.append(node('div','No performance data yet','analytics-empty'));return;}
    const table=node('table','','contribution-table');const head=node('thead');const tr=node('tr');
    for(const title of ['Name','Realized','Open P&L','Total'])tr.append(node('th',title));head.append(tr);table.append(head);
    const body=node('tbody');for(const row of rows){const tr=node('tr');tr.append(node('th',row.label));for(const value of [row.realized,row.unrealized,row.realized+row.unrealized])tr.append(node('td',money(value),value<0?'neg':value>0?'pos':''));body.append(tr);}table.append(body);this.el.append(table);
  }
  getDom(){return this.el;} isDisposed(){return this.dead;}
  resize(){this.redraw?.();}
  dispose(){this.dead=true;this.clear();}
}
(window as unknown as {TradingAnalytics:typeof Analytics}).TradingAnalytics=Analytics;
