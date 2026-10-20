"""The served dashboard shell.

A single self-contained HTML document (inline CSS + JS, Plotly from CDN) rendering the
Ceremyn operations console. Pure presentation: it opens the existing WebSocket, subscribes
to every channel, and renders each page from pushed snapshot frames — no business logic.
Design language: "Industry" blueprint/schematic system — square corners, hairline
dividers, small "+" corner registration marks on every card, Barlow Condensed
headings/numerics over Barlow body text, a single steel-blue accent reserved for
the one primary action per screen, green/red reserved for P&L.

CSS lives in `shell_styles.py`, split out to keep this file under the project's
500-line limit.
"""

from ceremyn.dashboard.shell_styles import SHELL_CSS

SHELL_HTML = r"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ceremyn</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="mark">◆</div>
      <div class="brand-text"><div class="name">Ceremyn</div><div class="sub">Market Intelligence</div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <div class="sidefoot">
      <span id="verFoot">—</span>
      <button class="collapse-btn" id="collapseBtn" title="Collapse sidebar">«</button>
    </div>
  </aside>
  <div class="main">
    <header class="topbar">
      <button class="menu-btn" id="menuBtn" title="Toggle navigation" aria-label="Toggle navigation">☰</button>
      <div class="page-title" id="pageTitle">Overview</div>
      <div class="spacer"></div>
      <div class="status-chips">
       <span class="chip" id="wsChip"><span class="dot"></span>Connecting</span>
       <span class="chip" id="runChip"><span class="dot"></span>Runtime</span>
       <span class="chip" id="marketChip"><span class="dot"></span>Market</span>
      </div>
      <span class="clock num" id="clock">--:--:--</span>
      <button class="theme-btn" id="themeBtn" title="Toggle theme">☀</button>
    </header>
    <main class="content" id="content"><div class="empty">Connecting to live feed…</div></main>
  </div>
</div>
<script>
const PAGES=[
 ["overview","Overview","M3 12h4l3 8 4-16 3 8h4"],
 ["markets","Markets","M3 17l6-6 4 4 8-8"],
 ["analysis","Analysis","M12 2a10 10 0 100 20 10 10 0 000-20z M12 7a5 5 0 100 10 5 5 0 000-10z M12 11a1 1 0 100 2 1 1 0 000-2z"],
 ["portfolio","Portfolio","M3 3v18h18 M7 15l4-4 3 3 5-6"],
 ["orders","Orders","M4 6h16 M4 12h16 M4 18h10"],
 ["risk","Risk","M12 3l9 16H3z M12 10v4 M12 17h.01"],
 ["research","Research","M11 4a7 7 0 100 14 7 7 0 000-14z M21 21l-4.3-4.3"],
 ["system","System","M12 8a4 4 0 100 8 4 4 0 000-8z M12 2v3 M12 19v3 M2 12h3 M19 12h3"],
];
const state={}; const series={equity:[],pnl:[],exposure:[]}; const MAXP=120;
const PAGE_IDS=PAGES.map(p=>p[0]);
const labelFor=(id)=>{const p=PAGES.find(p=>p[0]===id);return p?p[1]:'Overview';};
const pageFromHash=()=>{const h=location.hash.replace('#','');return PAGE_IDS.includes(h)?h:'overview';};
let active=pageFromHash(); let logFilter="all"; let logSearch="";
let tradeForm={symbol:"",side:"BUY",quantity:"",price:"",orderType:"MARKET",limitPrice:"",confirmLive:false};
let tradeBusy=false; let tradeMsg=null;
let executionForm={token:"",reason:"Manual trading session"};
let executionBusy=false; let executionMsg=null;
let opportunities=[]; const dismissedOpps=new Set(); const openOppDetails=new Set();
let scanState={scanning:false,last_scanned_at:null,symbols_scanned:0};
let analysisSymbol=""; let analysisResult=null; let analysisError=null; let analysisLoading=false;

const $=(id)=>document.getElementById(id);
const fmtNum=(v,d=2)=>Number(v??0).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});
const money=(v)=>"₹"+fmtNum(v,2);
const pct=(v)=>fmtNum(v,2)+"%";
const signCls=(v)=>v>0?"pos":(v<0?"neg":"neu");

function goToPage(id,opts){
 active=id;const label=labelFor(id);
 document.querySelectorAll('.nav a').forEach(n=>n.classList.toggle('active',n.dataset.page===id));
 $("pageTitle").textContent=label;document.title=label+' · Ceremyn';$("sidebar").classList.remove('open');
 if(location.hash.replace('#','')!==id){
  if(opts&&opts.replace)history.replaceState(null,'','#'+id);else location.hash=id;
 }
 if(id==='overview')loadEquityHistory();
 render();
}

const nav=$("nav");
PAGES.forEach(([id,label,d])=>{
 const a=document.createElement("a");a.dataset.page=id;a.className=(id===active?"active":"");
 a.title=label;
 a.innerHTML=`<svg class="ic" viewBox="0 0 24 24"><path d="${d}"/></svg><span>${label}</span>`;
 a.onclick=()=>goToPage(id);
 nav.appendChild(a);
});
window.addEventListener('hashchange',()=>{const id=pageFromHash();if(id!==active)goToPage(id,{replace:true});});
$("pageTitle").textContent=labelFor(active);document.title=labelFor(active)+' · Ceremyn';

$("menuBtn").onclick=()=>$("sidebar").classList.toggle('open');
$("themeBtn").onclick=()=>{const r=document.documentElement;
 const t=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',t);
 $("themeBtn").textContent=t==='dark'?'☾':'☀';try{localStorage.setItem('ceremyn-theme',t)}catch(e){}render();};
try{const s=localStorage.getItem('ceremyn-theme')||localStorage.getItem('aq-theme');
 if(s){document.documentElement.setAttribute('data-theme',s);$("themeBtn").textContent=s==='dark'?'☾':'☀';}}catch(e){}
$("collapseBtn").onclick=()=>{const on=$("sidebar").classList.toggle('collapsed');
 $("collapseBtn").textContent=on?'»':'«';try{localStorage.setItem('ceremyn-sidebar',on?'collapsed':'')}catch(e){}};
try{if(localStorage.getItem('ceremyn-sidebar')==='collapsed'){$("sidebar").classList.add('collapsed');
 $("collapseBtn").textContent='»';}}catch(e){}

setInterval(()=>{try{$("clock").textContent=new Intl.DateTimeFormat('en-IN',
 {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date())+" IST";}catch(e){}},1000);

const BASE=location.pathname.replace(/\/+$/,'');
// Only present when the operator turns on dashboard auth (off by default); harmless
// no-op otherwise. Pass it via the page URL: /dashboard/?token=<your-token>.
const TOKEN=new URLSearchParams(location.search).get('token');
const WS_URL=(location.protocol==='https:'?'wss':'ws')+'://'+location.host+BASE+'/ws'
 +(TOKEN?('?token='+encodeURIComponent(TOKEN)):'');
function authedFetch(path){
 return fetch(BASE+path,TOKEN?{headers:{Authorization:'Bearer '+TOKEN}}:{});
}
let ws;
function connect(){
 ws=new WebSocket(WS_URL);
 ws.onopen=()=>setChip("wsChip","ok","Live");
 ws.onclose=()=>{setChip("wsChip","bad","Disconnected");setTimeout(connect,2000);};
 ws.onerror=()=>setChip("wsChip","bad","Error");
 ws.onmessage=(e)=>{const f=JSON.parse(e.data);
  if(f.kind==='snapshot'){state[f.channel]=f.payload;sample(f.channel);statusChips();
    if(dependsOn(active,f.channel))render();}
  else if(f.kind==='event'){
    // Event frames carry the raw domain event, not the channel's full view shape —
    // refetch the real snapshot for that channel instead of rendering stale state.
    authedFetch('/api/'+f.channel).then(r=>r.ok?r.json():null).then(payload=>{
      if(payload){state[f.channel]=payload;statusChips();
        if(dependsOn(active,f.channel))render();}
    }).catch(()=>{});
  }
 };
}
function setChip(id,cls,txt){const c=$(id);c.className="chip "+cls;c.innerHTML=`<span class="dot"></span>${txt}`;}
function dependsOn(page,ch){const map={
 overview:['overview','metrics','portfolio','positions','alerts','execution'],
 markets:['live'],portfolio:['portfolio','positions','metrics'],orders:['orders','oms','execution'],
 risk:['risk','portfolio','alerts'],research:['research','features'],
 system:['health','logs','alerts','metrics']};
 return (map[page]||[]).includes(ch);}
function sample(ch){const now=Date.now();
 // Never record two points closer than 3s: a burst of frames arriving back-to-back
 // must not zoom the x-axis into a meaningless microsecond window.
 if(ch==='metrics'&&state.metrics){push(series.pnl,now,state.metrics.pnl||0);
   push(series.exposure,now,state.metrics.gross_exposure||0);}}
function push(arr,t,v){if(arr.length&&t-arr[arr.length-1][0]<3000)return;
 arr.push([t,v]);if(arr.length>MAXP)arr.shift();}
function loadEquityHistory(){
 authedFetch('/api/equity_history').then(r=>r.ok?r.json():null).then(payload=>{
  if(!payload||!payload.points)return;
  series.equity=payload.points.map(p=>[new Date(p.timestamp).getTime(),p.equity]);
  if(active==='overview')render();
 }).catch(()=>{});}
function loadSystemStatus(){
 fetch('/system/status').then(r=>r.ok?r.json():null).then(payload=>{
  if(payload){state.sys=payload;statusChips();$("verFoot").textContent='v'+(payload.version||'—')
   +' · '+(payload.effective_mode||'');if(active==='overview')render();}
 }).catch(()=>{});}
function loadOpportunities(){
 fetch('/opportunities/equity').then(r=>r.ok?r.json():null).then(payload=>{
  if(payload){opportunities=payload.opportunities||[];scanState=payload;if(active==='markets')render();}
 }).catch(()=>{});}
function runAnalysis(symbol){
 symbol=(symbol||'').trim().toUpperCase();
 if(!symbol)return;
 analysisSymbol=symbol;analysisLoading=true;analysisError=null;analysisResult=null;render();
 fetch('/analysis/equity/'+encodeURIComponent(symbol)).then(async(r)=>{
  const body=await r.json().catch(()=>null);
  if(r.ok){analysisResult=body;}
  else{analysisError=(body&&body.detail)||`Request failed (${r.status})`;}
 }).catch(()=>{analysisError='Network error — could not reach the analysis API.';})
 .finally(()=>{analysisLoading=false;render();});}
function statusChips(){
 const h=state.health,l=state.live,s=state.sys;
 if(s)setChip("runChip",s.runtime_ready?"ok":"warn",s.runtime_ready?"Runtime ready":"Runtime off");
 else if(h){const ok=h.heartbeat_healthy!==false;setChip("runChip",ok?"ok":"bad",ok?"Engine up":"Engine down");}
 const ms=(l&&l.underlyings&&l.underlyings[0])?l.underlyings[0].market_status:null;
 if(ms)setChip("marketChip",ms==='open'?"ok":"warn",ms==='open'?"Market open":("Market "+ms));
}

const CORNERS='<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
function kpi(label,val,sub,cls){return `<div class="card kpi">${CORNERS}<div class="label">${label}</div>
 <div class="val ${cls||''}">${val}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`;}
function card(title,body){return `<div class="card">${CORNERS}<h3>${title}</h3>${body}</div>`;}
function kvrow(k,v){return `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`;}
function kv(rows){return `<div class="kv">${rows}</div>`;}
function empty(t){return `<div class="empty">${t||'No data yet'}</div>`;}
function chartBox(id){return `<div id="${id}" class="chart"></div>`;}
function bar(p){return `<div class="bar"><span style="width:${Math.max(0,Math.min(100,p))}%"></span></div>`;}
function tbl(cols,rows){return `<table class="tbl"><thead><tr>${cols.map(c=>
 `<th class="${c[1]||''}">${c[0]}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;}
function stateBadge(s){const m={filled:'green',pending:'blue',partially_filled:'amber',routed:'blue',
 validated:'blue',new:'gray',rejected:'red',failed:'red',cancelled:'gray',expired:'gray',cancel_pending:'amber'};
 return `<span class="badge ${m[s]||'gray'}">${(s||'').replace('_',' ')}</span>`;}
function humanize(s){return(s||'').split('_').map(w=>w?w[0].toUpperCase()+w.slice(1):w).join(' ');}
function themeColors(){const dark=document.documentElement.getAttribute('data-theme')!=='light';
 const cs=getComputedStyle(document.documentElement);
 return{grid:cs.getPropertyValue('--grid').trim()||(dark?'rgba(255,255,255,.06)':'rgba(0,0,0,.07)'),
  font:cs.getPropertyValue('--muted').trim()||'#9099a6'};}
function line(id,data,color){const t=themeColors();
 if(!data||data.length<2||(data[data.length-1][0]-data[0][0])<60000)
  {const el=$(id);if(el)el.innerHTML='<div class="empty">Not enough history yet — collecting…</div>';return;}
 Plotly.react(id,[{x:data.map(p=>new Date(p[0])),y:data.map(p=>p[1]),type:'scatter',mode:'lines',
  line:{color:color,width:1.8},fill:'tozeroy',
  fillcolor:color.replace('rgb','rgba').replace(')',',0.07)')}],
 {margin:{l:52,r:10,t:6,b:26},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:t.font,size:11},xaxis:{gridcolor:t.grid},yaxis:{gridcolor:t.grid},showlegend:false},
 {displayModeBar:false,responsive:true});}
function barsChart(id,x,y,color){const t=themeColors();
 Plotly.react(id,[{x:x,y:y,type:'bar',marker:{color:color}}],
 {margin:{l:46,r:10,t:6,b:40},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:t.font,size:11},xaxis:{gridcolor:t.grid},yaxis:{gridcolor:t.grid}},
 {displayModeBar:false,responsive:true});}

function render(){
 const c=$("content");
 if(active==='overview')return renderOverview(c);
 if(active==='markets')return renderMarkets(c);
 if(active==='analysis')return renderAnalysis(c);
 if(active==='portfolio')return renderPortfolio(c);
 if(active==='orders')return renderOrders(c);
 if(active==='risk')return renderRisk(c);
 if(active==='research')return renderResearch(c);
 if(active==='system')return renderSystem(c);
}
function runtimeCard(){
 const s=state.sys,x=state.execution||{};
 if(!s)return card('Trading Runtime',empty('Status unavailable'));
 const gate=(label,on)=>`<div class="gate ${on?'on':'off'}"><span class="st"></span>${label}</div>`;
 const strat=(s.active_strategy_ids||[]).map(i=>`<span class="badge gold">${i}</span>`).join(' ')||
  '<span class="badge gray">none</span>';
 return card('Trading Runtime',`
  <div class="kv">
   ${kvrow('Mode',`<span class="badge ${s.effective_mode==='live'?'red':'blue'}">${s.effective_mode}</span>`)}
   ${kvrow('Active strategies',strat)}
   ${kvrow('Broker',`<span class="badge gray">${x.active_broker||'simulated'}</span>`)}
   ${kvrow('Kite API key',s.kite_api_configured?'<span class="badge green">configured</span>':'<span class="badge amber">missing</span>')}
   ${kvrow('Kite session token',s.kite_access_token_configured?'<span class="badge green">present</span>':'<span class="badge amber">run kite_login.py</span>')}
  </div>
  <h3 style="margin-top:14px">Live-order gates — all three must pass</h3>
  <div class="gates">
   ${gate('1 · mode=live',s.configured_mode==='live')}
   ${gate('2 · live trading enabled',!!s.live_trading_enabled)}
   ${gate('3 · armed at runtime',!!x.armed)}
  </div>`);
}
function renderOverview(c){
 const o=state.overview||{},m=state.metrics||{},pf=state.portfolio||{};
 const val=(pf.buying_power||0)+(pf.margin_used||0);
 const pnl=pf.daily_pnl!==undefined?pf.daily_pnl:(m.pnl||0);
 const dd=m.drawdown||o.drawdown||0;
 const live=state.live||{};const market=(live.underlyings||[])[0];
 const marketLabel=market?`${market.underlying} · ${market.market_status}`:'Market intelligence is standing by';
 c.innerHTML=`
 <section class="workspace-hero">
  <div><div class="hero-eyebrow">Operator console / ${new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}</div>
   <h1>See the market.<br/><span>Know the risk.</span></h1>
   <p>Research evidence, portfolio posture, and execution controls in one disciplined workspace.</p></div>
  <div class="hero-status"><span class="pulse"></span><div><b>${marketLabel}</b><small>${market?'Live market context':'Waiting for verified market data'}</small></div></div>
 </section>
 <div class="grid kpis">
  ${kpi('Portfolio Value',money(val))}
  ${kpi("Today's P&L",money(pnl),null,signCls(pnl))}
  ${kpi('Open Orders',o.open_orders??0)}
  ${kpi('Positions',(state.positions&&state.positions.positions||[]).length)}
  ${kpi('Drawdown',money(dd),null,dd>0?'neg':'neu')}
  ${kpi('Broker Latency',fmtNum((m.broker_latency_seconds||0)*1000,0)+' ms')}
 </div>
 <div class="grid cols-2">
  ${runtimeCard()}
  ${card('Recent Alerts',renderAlertList())}
 </div>
 <div class="grid cols-2">
  ${card('Equity Curve',chartBox('cEq'))}
  ${card('Session P&L',chartBox('cPnl'))}
 </div>`;
 line('cEq',series.equity,'rgb(44,121,247)');
 line('cPnl',series.pnl,'rgb(30,143,77)');
}
function renderAlertList(){const a=(state.alerts&&state.alerts.alerts)||[];
 if(!a.length)return empty('No active alerts');
 return a.slice(0,8).map(x=>`<div class="alert ${x.severity}">
  <span class="sev"></span><div style="flex:1;min-width:0"><div>${x.message}</div>
  <div style="color:var(--faint);font-size:11.5px">${(x.category||'').replace('_',' ')}</div></div>
  <span class="badge ${x.severity==='critical'?'red':'amber'}">${x.severity}</span></div>`).join('');}
function marketsEmptyMessage(){const s=state.sys;
 if(!s)return'No market feed yet — connecting…';
 if(!s.kite_api_configured)return'No market feed — add a Kite API key to .env to enable live data.';
 if(!s.kite_access_token_configured)return'No market feed — the session token is missing or expired. Run scripts/kite_login.py.';
 return'Credentials are configured, but no ticks have arrived yet — the market may be closed, or the feed is still connecting.';}
function opportunityKey(o){return o.tradingsymbol+'|'+o.pattern_name+'|'+o.detected_at;}
function opportunityStatusLine(){
 if(scanState.scanning)return '<div class="sub" style="margin:-6px 0 4px">Scanning the market for opportunities — first results may take a few minutes…</div>';
 if(scanState.last_scanned_at){
  const t=new Date(scanState.last_scanned_at);
  const label=isNaN(t)?scanState.last_scanned_at:t.toLocaleString('en-IN',
   {hour:'2-digit',minute:'2-digit',day:'2-digit',month:'short'});
  return `<div class="sub" style="margin:-6px 0 4px">Last scanned ${label} · ${scanState.symbols_scanned} symbol(s) checked</div>`;
 }
 return '';}
function opportunityCards(){
 const visible=opportunities.filter(o=>!dismissedOpps.has(opportunityKey(o)));
 if(!visible.length)return opportunityStatusLine()+card('Top Opportunities',
  empty(scanState.scanning?'Scanning the market for opportunities — check back shortly.':
   'No qualifying opportunities right now — checked against real historical hit-rate, not every pattern that fires.'));
 const items=visible.map(o=>{
  const key=opportunityKey(o);const bullish=o.direction==='bullish';const isOpen=openOppDetails.has(key);
  const detail=isOpen?`<div class="sub num" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)">
    Historical move: <span class="${o.average_forward_return_pct>=0?'pos':'neg'}">${o.average_forward_return_pct>=0?'+':''}${fmtNum(o.average_forward_return_pct,1)}%</span>
    over ${o.forward_days} trading day${o.forward_days===1?'':'s'} (historical average, n=${o.occurrences})</div>`:'';
  return `<div class="card kpi" data-oppkey="${key}" style="cursor:pointer">${CORNERS}
   <div class="label">${o.tradingsymbol}<span class="badge ${bullish?'green':'red'}" style="float:right">${o.direction}</span></div>
   <div class="val" style="font-size:16px">${humanize(o.pattern_name)}</div>
   <div class="sub num">Hit rate ${pct(o.hit_rate*100)} · avg ${o.average_forward_return_pct>=0?'+':''}${fmtNum(o.average_forward_return_pct,1)}% · n=${o.occurrences}</div>
   <div class="sub">${o.hit_rate_lift!=null?'Lift '+pct(o.hit_rate_lift*100)+' · adjusted p '+fmtNum(o.adjusted_p_value,3):'Legacy evidence'} · ${bullish?'Long research':'Avoid / exit research'}</div>
   ${detail}
   <div style="margin-top:10px;display:flex;gap:8px">
    <button class="btn" style="flex:1" data-reject="${key}">Dismiss</button>
    ${bullish?`<button class="btn btn-primary" style="flex:1" data-approve="${key}" data-symbol="${o.tradingsymbol}" data-side="BUY">Prepare order</button>`:'<span class="sub">No cash short entry</span>'}
   </div></div>`;}).join('');
 return `${opportunityStatusLine()}<div class="section-label">Top Opportunities</div><div class="grid kpis">${items}</div>`;}
function wireOpportunityButtons(){
 document.querySelectorAll('[data-oppkey]').forEach(el=>{
  el.onclick=(e)=>{
   if(e.target.closest('button'))return;
   const key=el.dataset.oppkey;
   if(openOppDetails.has(key))openOppDetails.delete(key);else openOppDetails.add(key);
   render();};});
 document.querySelectorAll('[data-reject]').forEach(btn=>{
  btn.onclick=()=>{dismissedOpps.add(btn.dataset.reject);render();};});
 document.querySelectorAll('[data-approve]').forEach(btn=>{
  btn.onclick=()=>{
   tradeForm.symbol=btn.dataset.symbol;tradeForm.side=btn.dataset.side;
   tradeForm.quantity='';tradeForm.price='';tradeMsg=null;
   goToPage('orders');};});}
function renderMarkets(c){const l=state.live||{};const u=l.underlyings||[];
 const cards=u.length?u.map(r=>`<div class="card kpi">${CORNERS}<div class="label">${r.underlying}
   <span class="badge ${r.market_status==='open'?'green':'amber'}" style="float:right">${r.market_status}</span></div>
   <div class="val">${fmtNum(r.spot,2)}</div>
   <div class="sub num">ATM ${fmtNum(r.atm_strike,0)} · PCR ${fmtNum(r.pcr,2)} · ${fmtNum(r.latency_ms,1)}ms</div></div>`).join('')
  :card('Underlyings',empty(marketsEmptyMessage()));
 c.innerHTML=`<div class="grid kpis">${cards}</div>
  ${card('Feed',kv(
    kvrow('Messages / sec',fmtNum(l.messages_per_second,1))+
    kvrow('Reconnects',l.reconnect_count??0)+
    kvrow('Heartbeat delay',fmtNum(l.heartbeat_delay_seconds,2)+'s')))}
  ${opportunityCards()}`;
 wireOpportunityButtons();}
function analysisSearchCard(){
 return `<div class="card">${CORNERS}<h3>Analyze a Stock</h3>
  <div style="display:flex;gap:8px">
   <input class="input" id="analysisInput" placeholder="e.g. RELIANCE" value="${analysisSymbol}" style="flex:1"/>
   <button class="btn btn-primary" id="analysisBtn"${analysisLoading?' disabled':''}>${analysisLoading?'Analyzing…':'Analyze'}</button>
  </div>
  ${analysisError?`<div class="sub neg" style="margin-top:10px">${analysisError}</div>`:''}</div>`;}
function wireAnalysisForm(){
 const inp=$("analysisInput");
 if(inp){
  inp.oninput=(e)=>{analysisSymbol=e.target.value;};
  inp.onkeydown=(e)=>{if(e.key==='Enter')runAnalysis(inp.value);};
 }
 const btn=$("analysisBtn");
 if(btn)btn.onclick=()=>runAnalysis(($("analysisInput")||{}).value||analysisSymbol);}
function fibonacciCard(r){
 const f=r.fibonacci;
 if(!f)return card('Fibonacci Retracement',empty('No clear confirmed swing high/low pair yet to anchor retracement levels.'));
 const bullish=f.direction==='bullish';
 const levels=[['23.6%',f.level_23_6,false],['38.2%',f.level_38_2,false],['50.0%',f.level_50_0,true],
  ['61.8%',f.level_61_8,true],['78.6%',f.level_78_6,false]];
 const rows=levels.map(([label,val,pocket])=>
  `<div class="row"><span class="k">${label}${pocket?' <span class="badge gold" style="margin-left:6px">golden pocket</span>':''}</span><span class="v">${money(val)}</span></div>`
 ).join('');
 return card('Fibonacci Retracement',`
  <div class="sub" style="margin-bottom:8px">
   <span class="badge ${bullish?'green':'red'}">${f.direction}</span> leg ·
   ${money(f.swing_start)} (${new Date(f.swing_start_at).toLocaleDateString('en-IN')}) →
   ${money(f.swing_end)} (${new Date(f.swing_end_at).toLocaleDateString('en-IN')})
  </div>
  <div class="kv">${rows}</div>`);}
function fundamentalsBody(f){
 if(!f||!f.available)return empty('No imported financial statements. Add publication-dated CSV filings to enable these checks.');
 const s=f.score;
 if(!s)return empty('Statements available; two consecutive annual periods are needed to compare results.');
 const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 return `<div class="sub">As of ${esc(f.as_of.slice(0,10))} · ${esc(s.source)}</div><p>${s.checks_passed.length} passed · ${s.checks_failed.length} failed · ${s.checks_missing.length} unavailable</p><p>${s.checks_passed.map(esc).join(' · ')}</p><p class="neg">${s.red_flags.map(esc).join(' · ')}</p>`;}
function analysisResultBody(){
 if(!analysisResult)return '';
 const r=analysisResult;
 const rows=(r.patterns||[]).map(p=>`<tr>
   <td>${humanize(p.pattern_name)}</td>
   <td><span class="badge ${p.direction==='bullish'?'green':'red'}">${p.direction}</span></td>
   <td>${humanize(p.source)}</td>
   <td>${p.active_now?'<span class="badge gold">active</span>':''}</td>
   <td class="r">${p.hit_rate!=null?pct(p.hit_rate*100):'—'}</td>
   <td class="r">${p.average_forward_return_pct!=null?(p.average_forward_return_pct>=0?'+':'')+fmtNum(p.average_forward_return_pct,1)+'%':'—'}</td>
   <td class="r">${p.occurrences}</td>
   <td>${p.is_opportunity_grade?'<span class="badge green">yes</span>':'<span class="badge gray">no</span>'}</td>
  </tr>`).join('');
 return `
  <div class="grid kpis">
   ${kpi('Latest Close',money(r.latest_close))}
   ${kpi('Latest Volume',fmtNum(r.latest_volume,0))}
   ${kpi('Bars Analyzed',r.bars_analyzed)}
  </div>
  ${fibonacciCard(r)}
  ${card('Fundamentals',fundamentalsBody(r.fundamentals))}
  ${card(r.tradingsymbol+' — Pattern Track Record',
    rows?tbl([['Pattern'],['Direction'],['Source'],['Now'],['Hit Rate','r'],['Avg Move','r'],['N','r'],['Opp. Grade']],rows)
    :empty("No patterns detected across this stock's history."))}
  <div class="sub" style="margin-top:-6px">As of ${new Date(r.as_of).toLocaleDateString('en-IN')} · scan data from ${new Date(r.last_scanned_at).toLocaleString('en-IN')}</div>`;}
function renderAnalysis(c){
 c.innerHTML=`${analysisSearchCard()}${analysisResultBody()}`;
 wireAnalysisForm();}
function renderPortfolio(c){const pf=state.portfolio||{};const g=pf.greeks||{};const e=pf.exposure||{};
 const p=state.positions||{};const rows=p.positions||[];
 const val=(pf.buying_power||0)+(pf.margin_used||0);
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Account Value',money(val))}
  ${kpi('Buying Power',money(pf.buying_power||0))}
  ${kpi('Margin Used',money(pf.margin_used||0))}
  ${kpi('Realized P&L',money(pf.realized_pnl||0),null,signCls(pf.realized_pnl||0))}
  ${kpi('Unrealized P&L',money(pf.unrealized_pnl||0),null,signCls(pf.unrealized_pnl||0))}</div>
  ${card('Open Positions — '+(p.long_count??0)+' long / '+(p.short_count??0)+' short',
   rows.length?tbl([['Instrument'],['Side'],['Qty','r'],['Avg Price','r']],
    rows.map(r=>`<tr><td class="num">${r.tradingsymbol}</td>
     <td><span class="badge ${r.direction==='long'?'green':'red'}">${r.direction}</span></td>
     <td class="r">${r.quantity}</td><td class="r">${fmtNum(r.avg_price,2)}</td></tr>`).join(''))
   :empty('Flat — no open positions'))}
  <div class="grid cols-2">
   ${card('Portfolio Greeks',kv(['delta','gamma','theta','vega','rho'].map(k=>kvrow(k.toUpperCase(),fmtNum(g[k],4))).join('')))}
   ${card('Exposure by Underlying',expBody(e))}</div>`;}
function expBody(e){const by=e.by_underlying||{};const keys=Object.keys(by);
 if(!keys.length)return kv(kvrow('Gross Notional',money(e.gross_notional||0))+kvrow('Net Notional',money(e.net_notional||0)));
 const max=Math.max(...keys.map(k=>Math.abs(by[k])),1);
 return `<div class="kv">`+keys.map(k=>`<div class="row"><span class="k" style="flex:1">${k}${bar(Math.abs(by[k])/max*100)}</span>
  <span class="v">${money(by[k])}</span></div>`).join('')+`</div>`;}
function tradeFormCard(){
 const mode=(state.sys&&state.sys.effective_mode)||'paper';
 const live=mode==='live';
 const livePermitted=!!(state.execution&&state.execution.live_trading_permitted);
 const submitBlocked=live&&!livePermitted;
 const limitField=tradeForm.orderType==='LIMIT'?`<div><label class="k" style="display:block;margin-bottom:4px">Limit price (₹)</label>
    <input class="input" id="tradeLimitPrice" type="number" min="0" step="0.05" placeholder="1480.00" value="${tradeForm.limitPrice}"/></div>`:'';
 const liveNotice=live?`<div class="sub ${livePermitted?'neg':'amber'}" style="margin-top:10px">${livePermitted
  ?'Live broker is armed. This order can use real funds.'
  :'Live order routing is locked. Configure both live gates and arm the runtime before submitting.'}</div>`
  :'<div class="sub" style="margin-top:10px">Paper mode is active. No real-money order can be sent.</div>';
 const executionControls=live?`<div style="border-top:1px solid var(--line);margin-top:16px;padding-top:14px"><h3>Live execution control</h3>
  ${livePermitted?`<div class="sub">The live broker is armed for this process.</div><button class="btn" id="disarmBtn"${executionBusy?' disabled':''} style="margin-top:10px">${executionBusy?'Disarming…':'Disarm live trading'}</button>`:
  `<div class="grid cols-2" style="gap:10px 14px"><div><label class="k" style="display:block;margin-bottom:4px">Arming token</label><input class="input" id="armToken" type="password" autocomplete="off" placeholder="Runtime arming token" value="${executionForm.token}"/></div><div><label class="k" style="display:block;margin-bottom:4px">Reason</label><input class="input" id="armReason" placeholder="Why are you enabling live trading?" value="${executionForm.reason}"/></div></div><button class="btn" id="armBtn"${executionBusy?' disabled':''} style="margin-top:10px">${executionBusy?'Arming…':'Arm live trading'}</button>`}
  ${executionMsg?`<div class="sub ${executionMsg.ok?'pos':'neg'}" style="margin-top:10px">${executionMsg.text}</div>`:''}</div>`:'';
 return card('Place Manual Trade',`
  <div class="grid cols-2" style="gap:10px 14px">
   <div><label class="k" style="display:block;margin-bottom:4px">Symbol</label>
    <input class="input" id="tradeSymbol" placeholder="e.g. RELIANCE" value="${tradeForm.symbol}"/></div>
   <div><label class="k" style="display:block;margin-bottom:4px">Side</label>
    <select class="input" id="tradeSide">
     <option value="BUY" ${tradeForm.side==='BUY'?'selected':''}>BUY</option>
     <option value="SELL" ${tradeForm.side==='SELL'?'selected':''}>SELL</option>
    </select></div>
   <div><label class="k" style="display:block;margin-bottom:4px">Quantity</label>
    <input class="input" id="tradeQty" type="number" min="1" step="1" placeholder="10" value="${tradeForm.quantity}"/></div>
   <div><label class="k" style="display:block;margin-bottom:4px">Reference price (₹)</label>
    <input class="input" id="tradePrice" type="number" min="0" step="0.05" placeholder="1489.25" value="${tradeForm.price}"/></div>
   <div><label class="k" style="display:block;margin-bottom:4px">Order type</label>
    <select class="input" id="tradeOrderType">
     <option value="MARKET" ${tradeForm.orderType==='MARKET'?'selected':''}>MARKET</option>
     <option value="LIMIT" ${tradeForm.orderType==='LIMIT'?'selected':''}>LIMIT</option>
    </select></div>
   ${limitField}
  </div>
  <div class="sub" style="margin-top:8px">Cash equity delivery only (CNC). The reference price is used for risk validation; it is not a limit price.</div>
  ${live?`<label style="display:flex;gap:8px;align-items:flex-start;margin-top:12px;font-size:12px;color:var(--muted)"><input id="tradeLiveConfirm" type="checkbox" ${tradeForm.confirmLive?'checked':''}/><span>I understand this is a real-money order and it will be sent to the connected broker.</span></label>`:''}
  <div style="margin-top:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
   <button class="btn btn-primary" id="tradeSubmitBtn"${tradeBusy||submitBlocked?' disabled':''}>${tradeBusy?'Submitting…':live?'Submit live order':'Submit paper order'}</button>
   <span style="font-size:11.5px;color:var(--muted)">Routes through the same risk engine as every strategy · mode: <b>${mode}</b></span>
  </div>
  ${liveNotice}
  ${executionControls}
  ${tradeMsg?`<div class="sub ${tradeMsg.ok?'pos':'neg'}" style="margin-top:10px">${tradeMsg.text}</div>`:''}`);
}
function wireTradeForm(){
 const sy=$("tradeSymbol");if(sy)sy.oninput=(e)=>{tradeForm.symbol=e.target.value;};
 const sd=$("tradeSide");if(sd)sd.onchange=(e)=>{tradeForm.side=e.target.value;};
 const qt=$("tradeQty");if(qt)qt.oninput=(e)=>{tradeForm.quantity=e.target.value;};
 const pr=$("tradePrice");if(pr)pr.oninput=(e)=>{tradeForm.price=e.target.value;};
 const ot=$("tradeOrderType");if(ot)ot.onchange=(e)=>{tradeForm.orderType=e.target.value;render();};
 const lp=$("tradeLimitPrice");if(lp)lp.oninput=(e)=>{tradeForm.limitPrice=e.target.value;};
 const lc=$("tradeLiveConfirm");if(lc)lc.onchange=(e)=>{tradeForm.confirmLive=e.target.checked;};
 const sb=$("tradeSubmitBtn");if(sb)sb.onclick=submitTrade;
 const at=$("armToken");if(at)at.oninput=(e)=>{executionForm.token=e.target.value;};
 const ar=$("armReason");if(ar)ar.oninput=(e)=>{executionForm.reason=e.target.value;};
 const ab=$("armBtn");if(ab)ab.onclick=()=>updateExecution('arm');
 const db=$("disarmBtn");if(db)db.onclick=()=>updateExecution('disarm');
}
function updateExecution(action){
 if(action==='arm'&&!executionForm.token){executionMsg={ok:false,text:'Enter the runtime arming token.'};render();return;}
 if(!confirm(action==='arm'?'Arm live trading for this running process?':'Disarm live trading now?'))return;
 executionBusy=true;executionMsg=null;render();
 const payload=action==='arm'?{token:executionForm.token,reason:executionForm.reason}:{reason:'Manual dashboard disarm'};
 fetch('/execution/'+action,{method:'POST',headers:Object.assign({'Content-Type':'application/json'},TOKEN?{Authorization:'Bearer '+TOKEN}:{}),body:JSON.stringify(payload)})
  .then(async(r)=>{const body=await r.json().catch(()=>null);if(r.ok){state.execution=body;executionForm.token='';executionMsg={ok:true,text:body.armed?'Live trading is armed for this process.':'Live trading is disarmed.'};}else{executionMsg={ok:false,text:(body&&body.detail)||`Request failed (${r.status})`};}})
  .catch(()=>{executionMsg={ok:false,text:'Network error — could not reach the execution API.'};})
  .finally(()=>{executionBusy=false;render();});
}
function submitTrade(){
 const symbol=(tradeForm.symbol||'').trim().toUpperCase();
 const qty=parseInt(tradeForm.quantity,10);
 const price=parseFloat(tradeForm.price);
 if(!symbol){tradeMsg={ok:false,text:'Enter a trading symbol.'};render();return;}
 if(!qty||qty<=0){tradeMsg={ok:false,text:'Quantity must be a positive whole number.'};render();return;}
 if(!price||price<=0){tradeMsg={ok:false,text:'Reference price must be greater than zero.'};render();return;}
 const mode=(state.sys&&state.sys.effective_mode)||'paper';
 const live=mode==='live';
 if(live&&!state.execution?.live_trading_permitted){tradeMsg={ok:false,text:'Live routing is locked. Configure and arm the runtime first.'};render();return;}
 if(live&&!tradeForm.confirmLive){tradeMsg={ok:false,text:'Confirm that you want to use real funds before submitting.'};render();return;}
 if(tradeForm.orderType==='LIMIT'&&(!parseFloat(tradeForm.limitPrice)||parseFloat(tradeForm.limitPrice)<=0)){
  tradeMsg={ok:false,text:'Enter a valid limit price.'};render();return;
 }
 if(!confirm(`Submit ${tradeForm.side} ${qty} ${symbol} as a ${tradeForm.orderType} order in ${mode.toUpperCase()} mode?`))return;
 tradeBusy=true;tradeMsg=null;render();
 fetch('/trading/equity',{method:'POST',
  headers:Object.assign({'Content-Type':'application/json'},TOKEN?{Authorization:'Bearer '+TOKEN}:{}),
  body:JSON.stringify({tradingsymbol:symbol,side:tradeForm.side,quantity:qty,
   reference_price:String(price),product:'CNC',order_type:tradeForm.orderType,
   limit_price:tradeForm.orderType==='LIMIT'?String(tradeForm.limitPrice):null,
   confirm_live_execution:live&&tradeForm.confirmLive})
 }).then(async(r)=>{
  const body=await r.json().catch(()=>null);
  if(r.ok){const first=(body&&body[0])||{};
    tradeMsg={ok:true,text:`Submitted — ${first.execution_state||'accepted'} (order ${first.oms_order_id||'—'})`};
    tradeForm.quantity='';tradeForm.price='';tradeForm.limitPrice='';tradeForm.confirmLive=false;}
  else{tradeMsg={ok:false,text:(body&&body.detail)||`Request failed (${r.status})`};}
 }).catch(()=>{tradeMsg={ok:false,text:'Network error — could not reach the trading API.'};})
 .finally(()=>{tradeBusy=false;render();});
}
function renderOrders(c){const o=state.orders||{};const rows=o.orders||[];const m=state.oms||{};
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Open',o.open_count??0)}${kpi('Filled',o.filled_count??0,null,'pos')}
  ${kpi('Rejected',o.rejected_count??0,null,(o.rejected_count?'neg':'neu'))}
  ${kpi('Fill Ratio',pct((m.fill_ratio||0)*100))}
  ${kpi('Broker Latency',fmtNum((m.broker_latency_seconds||0)*1000,0)+' ms')}</div>
  ${tradeFormCard()}
  ${card('Order Book ('+(o.total??0)+')',rows.length?tbl(
    [['Instrument'],['Side'],['Filled / Qty','r'],['State'],['']],
    rows.map(r=>`<tr><td class="num">${r.tradingsymbol}</td>
     <td><span class="badge ${r.side==='BUY'?'green':'red'}">${r.side}</span></td>
     <td class="r">${r.filled_quantity}/${r.quantity}</td><td>${stateBadge(r.execution_state)}</td>
     <td>${r.last_error?`<span class="badge red" title="${r.last_error}">error</span>`:''}</td></tr>`).join(''))
   :empty('No orders yet'))}
  <div class="grid cols-2">
   ${card('Execution Quality',kv(
     kvrow('p95 latency',fmtNum((m.p95_latency_seconds||0)*1000,0)+' ms')+
     kvrow('p99 latency',fmtNum((m.p99_latency_seconds||0)*1000,0)+' ms')+
     kvrow('Retries',m.retry_count??0)+
     kvrow('Broker uptime',pct((m.broker_uptime_ratio??1)*100))))}
   ${card('Safety',kv(
     kvrow('Kill switch',`<span class="badge ${m.kill_switch_armed?'red':'green'}">${m.kill_switch_armed?'ARMED':'safe'}</span>`)+
     (m.kill_switch_reason?kvrow('Reason',m.kill_switch_reason):'')+
     kvrow('Reconciliation',`<span class="badge ${m.reconciled?'green':'red'}">${m.reconciled?'clean':'drift '+(m.reconciliation_drift||0)}</span>`)))}
  </div>`;
 wireTradeForm();}
function renderRisk(c){const r=state.risk||{};const pf=state.portfolio||{};const e=pf.exposure||{};
 const decs=r.decisions||[];const oms=state.oms||{};const violations=r.violation_count||0;
 const posture=violations?'Risk attention required':'Risk posture is clear';
 const postureCopy=violations?'Review the latest violations before adding or changing exposure.':'No rule violations are currently recorded. Every proposed order is still evaluated at submission.';
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Latest Score',fmtNum(r.latest_score??0,1),'Most recent risk assessment')}
  ${kpi('Violations',violations,violations?'Action may be required':'No active rule breaches',violations?'neg':'pos')}
  ${kpi('Gross Exposure',money(e.gross_notional||0),'Total market exposure')}
  ${kpi('Net Exposure',money(e.net_notional||0),'Directional market exposure')}</div>
  <section class="risk-banner ${violations?'attention':'clear'}"><div class="risk-icon">${violations?'!':'✓'}</div><div>
   <div class="risk-banner-title">${posture}</div><p>${postureCopy}</p></div>
   <span class="badge ${violations?'red':'green'}">${violations?'review needed':'monitoring'}</span></section>
  <div class="grid cols-2">
   ${card('Risk Decisions',decs.length?tbl([['Decision'],['Violations'],['Score','r']],
     decs.slice(0,10).map(d=>`<tr><td><span class="badge ${d.approved?'green':'red'}">${d.approved?'approved':'rejected'}</span></td>
      <td style="color:var(--muted)">${(d.violations||[]).join(', ')||'—'}</td>
      <td class="r">${fmtNum(d.risk_score,1)}</td></tr>`).join(''))
    :empty('No decisions yet — every order is evaluated here before it can route'))}
   ${card('Control Posture',kv(
     kvrow('Kill switch',`<span class="badge ${oms.kill_switch_armed?'red':'green'}">${oms.kill_switch_armed?'armed':'safe'}</span>`)+
     kvrow('Reconciliation',`<span class="badge ${oms.reconciled===false?'red':'green'}">${oms.reconciled===false?'drift detected':'clean'}</span>`)+
     kvrow('Portfolio drawdown',money(pf.drawdown||0))))}</div>
  ${card('Alerts',renderAlertList())}`;}
function renderResearch(c){const r=state.research||{};const lb=r.leaderboard||[];const f=state.features||{};
 const leader=lb[0];
 const leaderBody=leader?`<div class="leader-name">${leader.strategy_name}</div>
   <div class="leader-metrics"><span><b class="pos">${fmtNum(leader.sharpe,2)}</b> Sharpe</span>
   <span><b class="${signCls(leader.total_return)}">${pct(leader.total_return)}</b> return</span>
   <span><b>${leader.trade_count}</b> trades</span></div>
   <div class="sub">Ranked from completed experiments. Treat as research evidence, not a trading recommendation.</div>`
   :empty('Run a backtest to establish a research baseline.');
 c.innerHTML=`<div class="grid kpis">${kpi('Experiments',r.experiment_count??0,'Completed research runs')}
   ${kpi('Ranked',lb.length,'Strategies with results')}${kpi('Features',f.feature_count??0,'Current feature set')}
   ${kpi('Feature Cache',pct((f.cache_hit_rate||0)*100),'Reuse rate')}</div>
  <div class="grid cols-2">${card('Current Leader',leaderBody)}
   ${card('Research Guardrails',kv(
    kvrow('Ranking metric','Sharpe ratio')+
    kvrow('Selection basis','Completed experiments only')+
    kvrow('Decision status','<span class="badge blue">Research only</span>')))}</div>
  ${card('Strategy Leaderboard',lb.length?tbl([['#','r'],['Strategy'],['Sharpe','r'],['Return','r'],['Max DD','r'],['Trades','r']],
    lb.map(x=>`<tr><td class="r">${x.rank}</td><td><b>${x.strategy_name}</b></td>
     <td class="r ${x.sharpe>=0?'pos':'neg'}">${fmtNum(x.sharpe,2)}</td><td class="r ${signCls(x.total_return)}">${pct(x.total_return)}</td>
     <td class="r neg">${pct(x.max_drawdown)}</td><td class="r">${x.trade_count}</td></tr>`).join(''))
   :empty('No experiments yet — run a backtest to populate the leaderboard'))}
  <div class="grid cols-2">${card('Sharpe',lb.length?chartBox('cSharpe'):empty('No data yet'))}${card('Return',lb.length?chartBox('cRet'):empty('No data yet'))}</div>
  ${card('Latest Features',f.sample&&Object.keys(f.sample).length?kv(
    Object.entries(f.sample).map(([k,v])=>kvrow(k,v)).join('')):empty('No features computed yet'))}`;
 if(lb.length){barsChart('cSharpe',lb.map(x=>x.strategy_name),lb.map(x=>x.sharpe),'#2c79f7');
  barsChart('cRet',lb.map(x=>x.strategy_name),lb.map(x=>x.total_return),'#1e8f4d');}}
function renderSystem(c){const h=state.health||{};const comps=h.components||[];
 const rows=(state.logs&&state.logs.logs)||[];
 const levels=['all','info','warning','error'];
 const filtered=rows.filter(r=>(logFilter==='all'||r.level===logFilter)&&
   (!logSearch||JSON.stringify(r).toLowerCase().includes(logSearch)));
 c.innerHTML=`<div class="grid cols-2">
  ${card('System Health',kv(
    kvrow('Overall',`<span class="badge ${h.heartbeat_healthy?'green':'red'}">${h.heartbeat_healthy?'healthy':'degraded'}</span>`)+
    kvrow('Heartbeat delay',fmtNum(h.heartbeat_delay_seconds,2)+'s')+
    kvrow('Reconnect attempts',h.reconnect_attempts??0)+
    kvrow('Broker uptime',pct((h.broker_uptime_ratio??1)*100))+
    kvrow('Messages / sec',fmtNum(h.messages_per_second,1))))}
  ${card('Components',comps.length?kv(comps.map(x=>kvrow(humanize(x.name),
    `<span class="badge ${x.healthy?'green':'gray'}">${x.healthy?'connected':'—'}</span>`)).join('')):empty())}
 </div>
 ${card('Logs',`<div class="toolbar">
   <input class="input" id="logSearch" placeholder="Search logs…" value="${logSearch}" style="max-width:260px"/>
   ${levels.map(l=>`<span class="pill ${logFilter===l?'on':''}" data-lv="${l}">${l}</span>`).join('')}</div>
   ${filtered.length?filtered.map(r=>`<div class="log-line">
    <span class="t">${(r.timestamp||'').slice(11,19)}</span>
    <span class="badge ${r.level==='error'?'red':r.level==='warning'?'amber':'blue'}">${r.level}</span>
    <span>${r.event} ${Object.entries(r.context||{}).map(([k,v])=>`<span class="k">${k}=${v}</span>`).join(' ')}</span>
   </div>`).join(''):empty('No matching logs')}`)}`;
 const si=$("logSearch");if(si){si.oninput=(e)=>{logSearch=e.target.value.toLowerCase();const p=si.selectionStart;render();
   const n=$("logSearch");if(n){n.focus();n.setSelectionRange(p,p);}};}
 document.querySelectorAll('.pill').forEach(x=>x.onclick=()=>{logFilter=x.dataset.lv;render();});}

render();
connect();
loadEquityHistory();
loadSystemStatus();
loadOpportunities();
setInterval(loadSystemStatus,30000);
setInterval(()=>{if(active==='overview')loadEquityHistory();},30000);
setInterval(loadOpportunities,5*60000);
</script>
</body></html>
"""

# Plain string substitution, not str.format/f-string: the HTML/JS above is full of
# literal `{`/`}` (CSS rules, JS objects) that would need escaping otherwise.
SHELL_HTML = SHELL_HTML.replace("<style>\n</style>", "<style>" + SHELL_CSS + "</style>")
