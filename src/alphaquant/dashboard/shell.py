"""The served dashboard shell.

A single self-contained HTML document (inline CSS + JS, Plotly from CDN) that renders a
professional dark-theme trading dashboard. It is pure presentation: it opens the existing
WebSocket, subscribes to every channel, and renders each page from the pushed snapshot
frames — no polling, no business logic, no duplicated backend code. Time-series charts are
accumulated client-side from successive snapshot frames.

The Order Ticket page (`shell_pages.py`) is the one exception to "pure presentation, no
business logic reachable" — it's the shell's first write action, calling the sibling
`/manual-orders/*` router directly. It lives in a separate source file, spliced into this
document at import time via the `/*..._INSERT*/` markers below, purely to keep this file
under the project's 500-line convention rather than growing it past that with inline markup.
"""

from alphaquant.dashboard.shell_pages import (
    TICKET_PAGE_ICON,
    TICKET_PAGE_ID,
    TICKET_PAGE_JS,
    TICKET_PAGE_LABEL,
)

_SHELL_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AlphaQuant — Trading Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --bg:#0b0e14; --bg-2:#0f131c; --panel:#141a24; --panel-2:#1a2130; --border:#232c3b;
  --text:#e6edf3; --muted:#8b97a7; --faint:#5b6675;
  --accent:#3b82f6; --accent-2:#2563eb;
  --green:#22c55e; --red:#ef4444; --amber:#f59e0b; --cyan:#06b6d4; --violet:#8b5cf6;
  --shadow:0 6px 24px rgba(0,0,0,.35); --radius:14px;
  --sans:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
}
:root[data-theme="light"]{
  --bg:#f4f6fa; --bg-2:#eef1f6; --panel:#ffffff; --panel-2:#f7f9fc; --border:#e2e8f0;
  --text:#0f172a; --muted:#64748b; --faint:#94a3b8; --shadow:0 6px 20px rgba(15,23,42,.08);
}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:auto 1fr;min-height:100vh}
/* Sidebar */
.sidebar{background:var(--bg-2);border-right:1px solid var(--border);width:236px;
  display:flex;flex-direction:column;transition:width .2s ease;position:sticky;top:0;height:100vh}
.sidebar.collapsed{width:64px}
.brand{display:flex;align-items:center;gap:10px;padding:18px 16px;border-bottom:1px solid var(--border)}
.brand .logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--violet));
  display:grid;place-items:center;color:#fff;font-weight:800;flex:none}
.brand .name{font-weight:700;letter-spacing:.2px;white-space:nowrap}
.brand .sub{color:var(--muted);font-size:11px}
.sidebar.collapsed .brand .txt{display:none}
.nav{padding:10px 8px;display:flex;flex-direction:column;gap:2px;overflow-y:auto;flex:1}
.nav a{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;color:var(--muted);
  text-decoration:none;cursor:pointer;white-space:nowrap;transition:background .15s,color .15s}
.nav a:hover{background:var(--panel);color:var(--text)}
.nav a.active{background:var(--panel-2);color:var(--text);box-shadow:inset 0 0 0 1px var(--border)}
.nav a .ic{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:1.8}
.nav a.active .ic{stroke:var(--accent)}
.sidebar.collapsed .nav a .lbl{display:none}
.collapse{margin:8px;padding:9px;border:1px solid var(--border);background:var(--panel);color:var(--muted);
  border-radius:10px;cursor:pointer}
/* Topbar */
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;gap:14px;padding:12px 20px;border-bottom:1px solid var(--border);
  background:color-mix(in srgb,var(--bg-2) 80%,transparent);position:sticky;top:0;z-index:5;backdrop-filter:blur(6px)}
.page-title{font-size:18px;font-weight:700}
.spacer{flex:1}
.icon-btn{background:var(--panel);border:1px solid var(--border);color:var(--text);width:36px;height:36px;
  border-radius:10px;cursor:pointer;display:grid;place-items:center;font-size:15px}
.icon-btn:hover{background:var(--panel-2)}
.icon-btn.warn-confirm{background:rgba(239,68,68,.15);border-color:var(--red);color:var(--red)}
.clock{font-family:var(--mono);color:var(--muted);font-size:13px;min-width:96px;text-align:right}
/* Chips / badges */
.chip{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;border-radius:999px;font-size:12px;
  font-weight:600;background:var(--panel);border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.chip .dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
.chip.ok{color:var(--green)} .chip.ok .dot{background:var(--green);box-shadow:0 0 8px var(--green)}
.chip.bad{color:var(--red)} .chip.bad .dot{background:var(--red);box-shadow:0 0 8px var(--red)}
.chip.warn{color:var(--amber)} .chip.warn .dot{background:var(--amber)}
.badge{display:inline-flex;align-items:center;padding:3px 9px;border-radius:8px;font-size:11px;font-weight:700;
  letter-spacing:.3px;text-transform:uppercase}
.badge.green{background:rgba(34,197,94,.15);color:var(--green)}
.badge.red{background:rgba(239,68,68,.15);color:var(--red)}
.badge.amber{background:rgba(245,158,11,.15);color:var(--amber)}
.badge.blue{background:rgba(59,130,246,.15);color:var(--accent)}
.badge.gray{background:var(--panel-2);color:var(--muted)}
/* Content + cards */
.content{padding:22px;display:flex;flex-direction:column;gap:20px;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.grid{display:grid;gap:16px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.cols-2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.cols-3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px;
  box-shadow:var(--shadow);transition:transform .15s,border-color .15s}
.card:hover{border-color:color-mix(in srgb,var(--accent) 30%,var(--border))}
.card h3{margin:0 0 14px;font-size:13px;color:var(--muted);font-weight:600;letter-spacing:.4px;text-transform:uppercase}
.kpi .label{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.3px;text-transform:uppercase}
.kpi .val{font-size:26px;font-weight:750;margin-top:8px;font-family:var(--mono);letter-spacing:-.5px}
.kpi .sub{margin-top:6px;font-size:12px;color:var(--muted)}
.pos{color:var(--green)} .neg{color:var(--red)} .neu{color:var(--text)}
.chart{width:100%;height:260px}
/* list rows (cards, not tables) */
.rows{display:flex;flex-direction:column;gap:8px}
.row{display:flex;align-items:center;gap:12px;padding:11px 13px;background:var(--panel-2);
  border:1px solid var(--border);border-radius:10px}
.row .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .k{color:var(--muted);font-size:12px} .row .v{font-family:var(--mono);font-weight:600}
.mono{font-family:var(--mono)}
.bar{height:8px;background:var(--panel-2);border-radius:999px;overflow:hidden;margin-top:8px}
.bar>span{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--cyan));border-radius:999px;
  transition:width .4s ease}
.empty{color:var(--faint);text-align:center;padding:26px;font-size:13px}
.alert{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;border-radius:10px;border:1px solid var(--border);
  background:var(--panel-2)}
.alert.critical{border-color:rgba(239,68,68,.4)} .alert.warning{border-color:rgba(245,158,11,.4)}
.alert .sev{width:8px;height:8px;border-radius:50%;margin-top:7px;flex:none;background:var(--muted)}
.alert.critical .sev{background:var(--red);box-shadow:0 0 8px var(--red)}
.alert.warning .sev{background:var(--amber)}
.input{background:var(--panel-2);border:1px solid var(--border);border-radius:10px;color:var(--text);
  padding:9px 12px;font-size:13px;width:100%;font-family:var(--sans)}
.input:focus{outline:none;border-color:var(--accent)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.pill-filter{padding:7px 12px;border-radius:999px;border:1px solid var(--border);background:var(--panel);
  color:var(--muted);cursor:pointer;font-size:12px;font-weight:600}
.pill-filter.on{color:var(--text);border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,var(--panel))}
.log-line{display:grid;grid-template-columns:88px 70px 1fr;gap:12px;padding:8px 12px;border-radius:8px;
  font-family:var(--mono);font-size:12.5px;background:var(--panel-2);border:1px solid var(--border)}
.log-line .t{color:var(--faint)}
@media(max-width:780px){.sidebar{position:fixed;z-index:20;height:100vh;transform:translateX(-100%)}
  .sidebar.open{transform:none}.app{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="logo">A</div>
      <div class="txt"><div class="name">AlphaQuant</div><div class="sub">Observability</div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <button class="collapse" id="collapseBtn" title="Collapse">«</button>
  </aside>
  <div class="main">
    <header class="topbar">
      <button class="icon-btn" id="menuBtn">☰</button>
      <div class="page-title" id="pageTitle">Overview</div>
      <div class="spacer"></div>
      <span class="chip" id="wsChip"><span class="dot"></span>Connecting</span>
      <span class="chip" id="brokerChip"><span class="dot"></span>Broker</span>
      <span class="chip" id="marketChip"><span class="dot"></span>Market</span>
      <span class="clock" id="clock">--:--:--</span>
      <button class="icon-btn" id="themeBtn" title="Toggle theme">☾</button>
    </header>
    <main class="content" id="content"><div class="empty">Connecting to live feed…</div></main>
  </div>
</div>
<script>
const PAGES=[
 ["overview","Overview","M3 12h4l3 8 4-16 3 8h4"],
 ["live","Live Market","M3 17l6-6 4 4 8-8"],
 ["portfolio","Portfolio","M3 3v18h18 M7 15l4-4 3 3 5-6"],
 ["orders","Orders","M4 6h16 M4 12h16 M4 18h10"],
 ["positions","Positions","M4 7h16v10H4z M4 11h16"],
 ["oms","OMS","M12 3l8 4v6c0 5-3.5 7-8 8-4.5-1-8-3-8-8V7z"],
 ["risk","Risk","M12 3l9 16H3z M12 10v4 M12 17h.01"],
 ["research","Research","M11 4a7 7 0 100 14 7 7 0 000-14z M21 21l-4.3-4.3"],
 ["features","Feature Store","M4 6h16v4H4z M4 14h16v4H4z"],
 ["paper","Paper Trading","M6 3h9l3 3v15H6z M9 8h6 M9 12h6 M9 16h4"],
 ["logs","Logs","M5 4h14v16H5z M8 8h8 M8 12h8 M8 16h5"],
 ["settings","Settings","M12 8a4 4 0 100 8 4 4 0 000-8z M19 12l2-1-2-4-2 1-2-2 0-2-4 0 0 2-2 2-2-1-2 4 2 1v2l-2 1 2 4 2-1 2 2 0 2 4 0 0-2 2-2z"],
 /*PAGES_INSERT*/
];
const state={}; const series={equity:[],pnl:[],exposure:[]}; const MAXP=120;
let active="overview"; let logFilter="all"; let logSearch="";

const $=(id)=>document.getElementById(id);
const fmtNum=(v,d=2)=>Number(v??0).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});
const money=(v)=>"₹"+fmtNum(v,2);
const pct=(v)=>fmtNum(v,2)+"%";
const signCls=(v)=>v>0?"pos":(v<0?"neg":"neu");
const arrow=(v)=>v>0?"▲":(v<0?"▼":"■");

// ---- nav ----
const nav=$("nav");
PAGES.forEach(([id,label,d])=>{
 const a=document.createElement("a");a.dataset.page=id;a.className=(id===active?"active":"");
 a.innerHTML=`<svg class="ic" viewBox="0 0 24 24"><path d="${d}"/></svg><span class="lbl">${label}</span>`;
 a.onclick=()=>{active=id;document.querySelectorAll('.nav a').forEach(n=>n.classList.toggle('active',n.dataset.page===id));
   $("pageTitle").textContent=label;$("sidebar").classList.remove('open');render();};
 nav.appendChild(a);
});
$("collapseBtn").onclick=()=>$("sidebar").classList.toggle('collapsed');
$("menuBtn").onclick=()=>$("sidebar").classList.toggle('open');
$("themeBtn").onclick=()=>{const r=document.documentElement;
 const t=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',t);
 $("themeBtn").textContent=t==='dark'?'☾':'☀';try{localStorage.setItem('aq-theme',t)}catch(e){}render();};
try{const s=localStorage.getItem('aq-theme');if(s){document.documentElement.setAttribute('data-theme',s);
 $("themeBtn").textContent=s==='dark'?'☾':'☀';}}catch(e){}

// ---- clock (UI timer, not backend polling) ----
setInterval(()=>{try{$("clock").textContent=new Intl.DateTimeFormat('en-IN',
 {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date())+" IST";}catch(e){}},1000);

// ---- websocket ----
const BASE=location.pathname.replace(/\/+$/,'');
const WS_URL=(location.protocol==='https:'?'wss':'ws')+'://'+location.host+BASE+'/ws';
let ws;
function connect(){
 ws=new WebSocket(WS_URL);
 ws.onopen=()=>setChip("wsChip","ok","Live");
 ws.onclose=()=>{setChip("wsChip","bad","Disconnected");setTimeout(connect,2000);};
 ws.onerror=()=>setChip("wsChip","bad","Error");
 ws.onmessage=(e)=>{const f=JSON.parse(e.data);
  if(f.kind==='snapshot'){state[f.channel]=f.payload;sample(f.channel);statusChips();
    if(dependsOn(active,f.channel))render();}
  else if(f.kind==='event'){if(active==='overview'||active==='logs')render();}
 };
}
function setChip(id,cls,txt){const c=$(id);c.className="chip "+cls;c.innerHTML=`<span class="dot"></span>${txt}`;}
function dependsOn(page,ch){const map={overview:['overview','metrics','portfolio','alerts'],
 live:['live'],portfolio:['portfolio','metrics'],orders:['orders'],positions:['positions'],
 oms:['oms'],risk:['risk','portfolio'],research:['research'],features:['features'],
 paper:['paper'],logs:['logs','alerts'],settings:['health','metrics']};
 return (map[page]||[]).includes(ch);}
function sample(ch){const now=Date.now();
 if(ch==='portfolio'&&state.portfolio){const v=(state.portfolio.buying_power||0)+(state.portfolio.margin_used||0);
   push(series.equity,now,v);}
 if(ch==='metrics'&&state.metrics){push(series.pnl,now,state.metrics.pnl||0);
   push(series.exposure,now,state.metrics.gross_exposure||0);}}
function push(arr,t,v){arr.push([t,v]);if(arr.length>MAXP)arr.shift();}
function statusChips(){
 const h=state.health,o=state.oms,l=state.live;
 if(h){const ok=h.heartbeat_healthy!==false;setChip("brokerChip",ok?"ok":"bad",ok?"Broker up":"Broker down");}
 const ms=(l&&l.underlyings&&l.underlyings[0])?l.underlyings[0].market_status:null;
 if(ms)setChip("marketChip",ms==='open'?"ok":"warn",ms==='open'?"Market open":("Market "+ms));
}

// ---- render helpers ----
function kpi(label,val,sub,cls){return `<div class="card kpi"><div class="label">${label}</div>
 <div class="val ${cls||''}">${val}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`;}
function card(title,body){return `<div class="card"><h3>${title}</h3>${body}</div>`;}
function row(k,v){return `<div class="row"><div class="grow k">${k}</div><div class="v">${v}</div></div>`;}
function empty(t){return `<div class="empty">${t||'No data yet'}</div>`;}
function chartBox(id){return `<div id="${id}" class="chart"></div>`;}
function bar(p){return `<div class="bar"><span style="width:${Math.max(0,Math.min(100,p))}%"></span></div>`;}
function stateBadge(s){const m={filled:'green',pending:'blue',partially_filled:'amber',routed:'blue',
 validated:'blue',new:'gray',rejected:'red',failed:'red',cancelled:'gray',expired:'gray',cancel_pending:'amber'};
 return `<span class="badge ${m[s]||'gray'}">${(s||'').replace('_',' ')}</span>`;}

function line(id,data,color,name){
 Plotly.react(id,[{x:data.map(p=>new Date(p[0])),y:data.map(p=>p[1]),type:'scatter',mode:'lines',
  name:name||'',line:{color:color,width:2,shape:'spline'},fill:'tozeroy',
  fillcolor:color.replace('rgb','rgba').replace(')',',0.08)')}],
 {margin:{l:48,r:12,t:8,b:28},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:'#8b97a7',size:11},xaxis:{gridcolor:'rgba(255,255,255,.05)'},
  yaxis:{gridcolor:'rgba(255,255,255,.05)'},showlegend:false},{displayModeBar:false,responsive:true});}
function barsChart(id,x,y,color){
 Plotly.react(id,[{x:x,y:y,type:'bar',marker:{color:color}}],
 {margin:{l:44,r:12,t:8,b:40},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:'#8b97a7',size:11},xaxis:{gridcolor:'rgba(255,255,255,.05)'},
  yaxis:{gridcolor:'rgba(255,255,255,.05)'}},{displayModeBar:false,responsive:true});}

// ---- pages ----
function render(){
 const c=$("content");const p=state;
 if(active==='overview')return renderOverview(c,p);
 if(active==='live')return renderLive(c,p);
 if(active==='portfolio')return renderPortfolio(c,p);
 if(active==='orders')return renderOrders(c,p);
 if(active==='positions')return renderPositions(c,p);
 if(active==='oms')return renderOMS(c,p);
 if(active==='risk')return renderRisk(c,p);
 if(active==='research')return renderResearch(c,p);
 if(active==='features')return renderFeatures(c,p);
 if(active==='paper')return renderPaper(c,p);
 if(active==='logs')return renderLogs(c,p);
 if(active==='settings')return renderSettings(c,p);
 /*RENDER_INSERT*/
}
function riskLevel(){const m=state.metrics||{};const a=(state.alerts&&state.alerts.alerts||[]).length;
 const crit=(state.alerts&&state.alerts.alerts||[]).some(x=>x.severity==='critical');
 if(crit)return['High','neg'];if(a>0)return['Elevated','neu'];return['Normal','pos'];}
function renderOverview(c){
 const o=state.overview||{},m=state.metrics||{},pf=state.portfolio||{};
 const val=(pf.buying_power||0)+(pf.margin_used||0);
 const pnl=pf.daily_pnl!==undefined?pf.daily_pnl:(m.pnl||0);
 const [rl,rlc]=riskLevel();
 c.innerHTML=`
 <div class="grid kpis">
  ${kpi('Portfolio Value',money(val))}
  ${kpi("Today's PnL",arrow(pnl)+' '+money(Math.abs(pnl)),null,signCls(pnl))}
  ${kpi('Open Orders',o.open_orders??0)}
  ${kpi('Positions',(state.positions&&state.positions.positions||[]).length)}
  ${kpi('Sharpe',fmtNum(m.sharpe,2))}
  ${kpi('Drawdown',money(m.drawdown||o.drawdown||0),null,'neg')}
  ${kpi('Broker Latency',fmtNum((m.broker_latency_seconds||0)*1000,0)+' ms')}
  ${kpi('Risk Level','<span class="badge '+(rlc==='neg'?'red':rlc==='pos'?'green':'amber')+'">'+rl+'</span>')}
 </div>
 <div class="grid cols-2">
  ${card('Equity Curve',chartBox('cEq'))}
  ${card('Daily PnL',chartBox('cPnl'))}
 </div>
 <div class="grid cols-2">
  ${card('Gross Exposure',chartBox('cExp'))}
  ${card('Recent Alerts',renderAlertList())}
 </div>`;
 line('cEq',series.equity,'rgb(59,130,246)','Equity');
 line('cPnl',series.pnl,'rgb(34,197,94)','PnL');
 line('cExp',series.exposure,'rgb(139,92,246)','Exposure');
}
function renderAlertList(){const a=(state.alerts&&state.alerts.alerts)||[];
 if(!a.length)return empty('No active alerts');
 return `<div class="rows">`+a.slice(0,8).map(x=>`<div class="alert ${x.severity}">
  <span class="sev"></span><div class="grow"><div>${x.message}</div>
  <div class="k" style="color:var(--muted);font-size:12px">${x.category.replace('_',' ')}</div></div>
  <span class="badge ${x.severity==='critical'?'red':'amber'}">${x.severity}</span></div>`).join('')+`</div>`;}
function renderLive(c){const l=state.live||{};const u=l.underlyings||[];
 const focus=['NIFTY','BANKNIFTY','FINNIFTY'];
 const cards=focus.map(name=>{const r=u.find(x=>x.underlying===name);
  if(!r)return kpi(name,'<span class="badge gray">no feed</span>');
  return `<div class="card"><div class="label">${name}
   <span class="badge ${r.market_status==='open'?'green':'amber'}" style="float:right">${r.market_status}</span></div>
   <div class="val">${fmtNum(r.spot,2)}</div>
   <div class="sub">ATM ${fmtNum(r.atm_strike,0)} · PCR ${fmtNum(r.pcr,2)} · ${fmtNum(r.latency_ms,1)}ms</div></div>`;}).join('');
 c.innerHTML=`<div class="grid kpis">${cards}</div>
  <div class="grid cols-2">
   ${card('Market Metrics',`<div class="rows">
     ${row('Messages / sec',fmtNum(l.messages_per_second,1))}
     ${row('Reconnects',l.reconnect_count??0)}
     ${row('Heartbeat delay',fmtNum(l.heartbeat_delay_seconds,2)+'s')}</div>`)}
   ${card('Underlyings',u.length?`<div class="rows">`+u.map(r=>row(r.underlying,fmtNum(r.spot,2))).join('')+`</div>`:empty())}
  </div>`;}
function renderPortfolio(c){const pf=state.portfolio||{};const g=pf.greeks||{};const e=pf.exposure||{};
 const val=(pf.buying_power||0)+(pf.margin_used||0);
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Account Value',money(val))}
  ${kpi('Buying Power',money(pf.buying_power||0))}
  ${kpi('Margin Used',money(pf.margin_used||0))}
  ${kpi('Realized PnL',money(pf.realized_pnl||0),null,signCls(pf.realized_pnl||0))}
  ${kpi('Unrealized PnL',money(pf.unrealized_pnl||0),null,signCls(pf.unrealized_pnl||0))}
  ${kpi('Positions',pf.position_count??0)}</div>
  <div class="grid cols-2">
   ${card('Greeks',`<div class="rows">${['delta','gamma','theta','vega','rho'].map(k=>row(k.toUpperCase(),fmtNum(g[k],4))).join('')}</div>`)}
   ${card('Exposure by Underlying',expBody(e))}</div>`;}
function expBody(e){const by=e.by_underlying||{};const keys=Object.keys(by);
 if(!keys.length)return `<div class="rows">${row('Gross Notional',money(e.gross_notional||0))}${row('Net Notional',money(e.net_notional||0))}</div>`;
 const max=Math.max(...keys.map(k=>Math.abs(by[k])),1);
 return `<div class="rows">`+keys.map(k=>`<div class="row"><div class="grow"><div class="k">${k}</div>
  ${bar(Math.abs(by[k])/max*100)}</div><div class="v">${money(by[k])}</div></div>`).join('')+`</div>`;}
function renderOrders(c){const o=state.orders||{};const rows=o.orders||[];
 c.innerHTML=`<div class="grid cols-3">
  ${kpi('Open',o.open_count??0)}${kpi('Filled',o.filled_count??0,null,'pos')}${kpi('Rejected',o.rejected_count??0,null,'neg')}</div>
  ${card('Order Book ('+(o.total??0)+')',rows.length?`<div class="rows">`+rows.map(r=>`<div class="row">
   <div class="grow mono">${r.tradingsymbol}</div>
   <span class="badge ${r.side==='BUY'?'green':'red'}">${r.side}</span>
   <div class="v">${r.filled_quantity}/${r.quantity}</div>${stateBadge(r.execution_state)}
   ${r.last_error?`<span class="badge red" title="${r.last_error}">err</span>`:''}</div>`).join('')+`</div>`:empty('No orders'))}`;}
function renderPositions(c){const p=state.positions||{};const rows=p.positions||[];
 c.innerHTML=`<div class="grid cols-2">${kpi('Long',p.long_count??0,null,'pos')}${kpi('Short',p.short_count??0,null,'neg')}</div>
  ${card('Open Positions',rows.length?`<div class="rows">`+rows.map(r=>`<div class="row">
   <div class="grow mono">${r.tradingsymbol}</div>
   <span class="badge ${r.direction==='long'?'green':'red'}">${r.direction}</span>
   <div class="v">${r.quantity} @ ${fmtNum(r.avg_price,2)}</div></div>`).join('')+`</div>`:empty('Flat'))}`;}
function renderOMS(c){const o=state.oms||{};
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Submitted',o.orders_submitted??0)}${kpi('Filled',o.orders_filled??0,null,'pos')}
  ${kpi('Partial',o.partial_fills??0)}${kpi('Rejected',o.rejections??0,null,'neg')}
  ${kpi('Fill Ratio',pct((o.fill_ratio||0)*100))}
  ${kpi('Broker Latency',fmtNum((o.broker_latency_seconds||0)*1000,0)+' ms')}</div>
  <div class="grid cols-2">
   ${card('Latency Percentiles',`<div class="rows">
     ${row('p95',fmtNum((o.p95_latency_seconds||0)*1000,0)+' ms')}
     ${row('p99',fmtNum((o.p99_latency_seconds||0)*1000,0)+' ms')}
     ${row('Retries',o.retry_count??0)}
     ${row('Broker uptime',pct((o.broker_uptime_ratio??1)*100))}</div>`)}
   ${card('Safety',`<div class="rows">
     <div class="row"><div class="grow">Kill Switch</div><span class="badge ${o.kill_switch_armed?'red':'green'}">${o.kill_switch_armed?'ARMED':'safe'}</span></div>
     ${o.kill_switch_reason?row('Reason',o.kill_switch_reason):''}
     <div class="row"><div class="grow">Reconciliation</div><span class="badge ${o.reconciled?'green':'red'}">${o.reconciled?'clean':'drift '+(o.reconciliation_drift||0)}</span></div>
    </div>`)}
  </div>`;}
function renderRisk(c){const r=state.risk||{};const pf=state.portfolio||{};const e=pf.exposure||{};
 const decs=r.decisions||[];
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Latest Score',fmtNum(r.latest_score??0,1))}
  ${kpi('Violations',r.violation_count??0,null,(r.violation_count?'neg':'pos'))}
  ${kpi('Gross Exposure',money(e.gross_notional||0))}
  ${kpi('Net Exposure',money(e.net_notional||0))}</div>
  <div class="grid cols-2">
   ${card('Risk Decisions',decs.length?`<div class="rows">`+decs.slice(0,10).map(d=>`<div class="row">
     <span class="badge ${d.approved?'green':'red'}">${d.approved?'approved':'rejected'}</span>
     <div class="grow k">${(d.violations||[]).join(', ')||'—'}</div>
     <div class="v">${fmtNum(d.risk_score,1)}</div></div>`).join('')+`</div>`:empty('No decisions'))}
   ${card('Alerts',renderAlertList())}</div>`;}
function renderResearch(c){const r=state.research||{};const lb=r.leaderboard||[];
 c.innerHTML=`<div class="grid kpis">${kpi('Experiments',r.experiment_count??0)}
   ${kpi('Ranked',lb.length)}</div>
  ${card('Leaderboard',lb.length?`<div class="rows">`+lb.map(x=>`<div class="row">
   <span class="badge blue">#${x.rank}</span><div class="grow">${x.strategy_name}</div>
   <div class="v">Sh ${fmtNum(x.sharpe,2)}</div><div class="v">${pct(x.total_return)}</div></div>`).join('')+`</div>`:empty('No experiments'))}
  <div class="grid cols-2">${card('Sharpe',chartBox('cSharpe'))}${card('Return',chartBox('cRet'))}</div>`;
 if(lb.length){barsChart('cSharpe',lb.map(x=>x.strategy_name),lb.map(x=>x.sharpe),'#3b82f6');
  barsChart('cRet',lb.map(x=>x.strategy_name),lb.map(x=>x.total_return),'#22c55e');}}
function renderFeatures(c){const f=state.features||{};
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Features',f.feature_count??0)}
  ${kpi('Cache Size',f.cache_size??0)}
  ${kpi('Hits',f.cache_hits??0,null,'pos')}
  ${kpi('Misses',f.cache_misses??0,null,'neg')}</div>
  ${card('Cache Hit Rate',`<div class="val mono">${pct((f.cache_hit_rate||0)*100)}</div>${bar((f.cache_hit_rate||0)*100)}
    <div class="sub">version ${f.feature_set_version||'—'}</div>`)}
  ${card('Latest Features',f.sample&&Object.keys(f.sample).length?`<div class="rows">`+
    Object.entries(f.sample).map(([k,v])=>row(k,v)).join('')+`</div>`:empty())}`;}
function renderPaper(c){const p=state.paper||{};
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Submitted',p.submitted??0)}${kpi('Filled',p.filled??0,null,'pos')}
  ${kpi('Rejected',p.rejected??0,null,'neg')}${kpi('Cancelled',p.cancelled??0)}
  ${kpi('Fill Rate',pct((p.fill_rate||0)*100))}
  ${kpi('Avg Latency',fmtNum(p.avg_latency_seconds,2)+'s')}</div>
  <div class="grid cols-2">
   ${card('Performance',`<div class="rows">
     ${row('Realized PnL',money(p.realized_pnl||0))}
     ${row('Unrealized PnL',money(p.unrealized_pnl||0))}
     ${row('Max Latency',fmtNum(p.max_latency_seconds,2)+'s')}</div>`)}
   ${card('Orders',`<div class="rows">${row('Submitted',p.submitted??0)}${row('Filled',p.filled??0)}${row('Rejected',p.rejected??0)}</div>`)}
  </div>`;}
function renderLogs(c){const rows=(state.logs&&state.logs.logs)||[];
 const levels=['all','info','warning','error'];
 const filtered=rows.filter(r=>(logFilter==='all'||r.level===logFilter)&&
   (!logSearch||JSON.stringify(r).toLowerCase().includes(logSearch)));
 c.innerHTML=card('System Logs',`<div class="toolbar" style="margin-bottom:12px">
   <input class="input" id="logSearch" placeholder="Search logs…" value="${logSearch}" style="max-width:280px"/>
   ${levels.map(l=>`<span class="pill-filter ${logFilter===l?'on':''}" data-lv="${l}">${l}</span>`).join('')}</div>
   ${filtered.length?`<div class="rows">`+filtered.map(r=>`<div class="log-line">
    <span class="t">${(r.timestamp||'').slice(11,19)}</span>
    <span class="badge ${r.level==='error'?'red':r.level==='warning'?'amber':'blue'}">${r.level}</span>
    <span class="grow">${r.event} ${Object.entries(r.context||{}).map(([k,v])=>`<span class="k">${k}=${v}</span>`).join(' ')}</span>
   </div>`).join('')+`</div>`:empty('No matching logs')}`);
 const si=$("logSearch");if(si){si.oninput=(e)=>{logSearch=e.target.value.toLowerCase();const p=si.selectionStart;render();
   const n=$("logSearch");if(n){n.focus();n.setSelectionRange(p,p);}};}
 document.querySelectorAll('.pill-filter').forEach(x=>x.onclick=()=>{logFilter=x.dataset.lv;render();});}
function renderSettings(c){const h=state.health||{};const comps=h.components||[];
 c.innerHTML=`<div class="grid cols-2">
  ${card('System Health',`<div class="rows">
    <div class="row"><div class="grow">Overall</div><span class="badge ${h.heartbeat_healthy?'green':'red'}">${h.heartbeat_healthy?'healthy':'degraded'}</span></div>
    ${row('Heartbeat delay',fmtNum(h.heartbeat_delay_seconds,2)+'s')}
    ${row('Reconnect attempts',h.reconnect_attempts??0)}
    ${row('Broker uptime',pct((h.broker_uptime_ratio??1)*100))}
    ${row('Messages / sec',fmtNum(h.messages_per_second,1))}</div>`)}
  ${card('Components',comps.length?`<div class="rows">`+comps.map(x=>`<div class="row">
    <div class="grow">${x.name}</div><span class="badge ${x.healthy?'green':'gray'}">${x.healthy?'connected':'—'}</span></div>`).join('')+`</div>`:empty())}
  ${card('Appearance',`<div class="rows"><div class="row"><div class="grow">Theme</div>
    <span class="badge blue" id="themeState">${document.documentElement.getAttribute('data-theme')}</span></div>
    <div class="sub">Use the ☾ button in the top bar to toggle light / dark.</div></div>`)}
 </div>`;}

/*SCRIPT_INSERT*/
connect();
</script>
</body></html>
"""

SHELL_HTML = (
    _SHELL_HTML_TEMPLATE.replace(
        "/*PAGES_INSERT*/",
        f'["{TICKET_PAGE_ID}","{TICKET_PAGE_LABEL}","{TICKET_PAGE_ICON}"],',
    )
    .replace("/*RENDER_INSERT*/", f"if(active==='{TICKET_PAGE_ID}')return renderTicket(c);")
    .replace("/*SCRIPT_INSERT*/", TICKET_PAGE_JS)
)
