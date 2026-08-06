"""The served dashboard shell.

A single self-contained HTML document (inline CSS + JS, Plotly from CDN) rendering the
Ceremyn operations console. Pure presentation: it opens the existing WebSocket, subscribes
to every channel, and renders each page from pushed snapshot frames — no business logic.
Design language: "quiet terminal" — near-black surfaces, hairline borders, a single warm
gold identity accent, green/red reserved for P&L, dense tables, tabular numerals.
"""

SHELL_HTML = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ceremyn</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --bg:#0a0b0e; --bg-2:#0e1014; --panel:#12141a; --panel-2:#171a21;
  --border:#22262f; --text:#e9ebef; --muted:#9099a6; --faint:#5d6570;
  --gold:#d9a441; --gold-dim:rgba(217,164,65,.13);
  --green:#43b86a; --red:#e05252; --amber:#e0862c; --blue:#5b8def;
  --grid:rgba(255,255,255,.06);
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
:root[data-theme="light"]{
  --bg:#f6f6f4; --bg-2:#f0efec; --panel:#ffffff; --panel-2:#faf9f7;
  --border:#e3e2dd; --text:#191b1f; --muted:#6b7280; --faint:#9aa0a8;
  --gold:#a97e22; --gold-dim:rgba(169,126,34,.10);
  --green:#1e8f4d; --red:#c93b3b; --amber:#b26a15; --blue:#3b66c4;
  --grid:rgba(0,0,0,.07);
}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:13.5px;line-height:1.5;-webkit-font-smoothing:antialiased}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.app{display:grid;grid-template-columns:auto 1fr;min-height:100vh}
.sidebar{background:var(--bg-2);border-right:1px solid var(--border);width:212px;
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;padding:16px 14px 14px;border-bottom:1px solid var(--border)}
.brand .mark{width:28px;height:28px;border:1px solid var(--gold);border-radius:6px;flex:none;
  display:grid;place-items:center;color:var(--gold);font-size:12px}
.brand .name{font-weight:650;letter-spacing:.14em;font-size:13px;text-transform:uppercase}
.brand .sub{color:var(--faint);font-size:10.5px;letter-spacing:.02em}
.nav{padding:10px 8px;display:flex;flex-direction:column;gap:1px;flex:1;overflow-y:auto}
.nav a{display:flex;align-items:center;gap:11px;padding:8px 11px;border-radius:7px;color:var(--muted);
  font-size:13px;text-decoration:none;cursor:pointer;border-left:2px solid transparent}
.nav a:hover{background:var(--panel);color:var(--text)}
.nav a.active{background:var(--gold-dim);color:var(--text);border-left-color:var(--gold)}
.nav a .ic{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round}
.nav a.active .ic{stroke:var(--gold)}
.sidefoot{padding:10px 14px;border-top:1px solid var(--border);color:var(--faint);font-size:11px}
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;gap:10px;padding:10px 20px;border-bottom:1px solid var(--border);
  background:var(--bg-2);position:sticky;top:0;z-index:5}
.page-title{font-size:15px;font-weight:600}
.spacer{flex:1}
.menu-btn{display:none;background:none;border:1px solid var(--border);color:var(--text);border-radius:7px;
  width:32px;height:32px;cursor:pointer}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:6px;font-size:11.5px;
  font-weight:550;border:1px solid var(--border);color:var(--muted);background:var(--panel);white-space:nowrap}
.chip .dot{width:6px;height:6px;border-radius:50%;background:var(--faint)}
.chip.ok{color:var(--green);border-color:color-mix(in srgb,var(--green) 35%,var(--border))}
.chip.ok .dot{background:var(--green)}
.chip.bad{color:var(--red);border-color:color-mix(in srgb,var(--red) 35%,var(--border))}
.chip.bad .dot{background:var(--red)}
.chip.warn{color:var(--amber)} .chip.warn .dot{background:var(--amber)}
.clock{font-family:var(--mono);color:var(--muted);font-size:12px;min-width:88px;text-align:right}
.theme-btn{background:none;border:1px solid var(--border);color:var(--muted);width:32px;height:32px;
  border-radius:7px;cursor:pointer;font-size:13px}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:5px;font-size:10.5px;
  font-weight:650;letter-spacing:.06em;text-transform:uppercase}
.badge.green{background:color-mix(in srgb,var(--green) 14%,transparent);color:var(--green)}
.badge.red{background:color-mix(in srgb,var(--red) 14%,transparent);color:var(--red)}
.badge.amber{background:color-mix(in srgb,var(--amber) 14%,transparent);color:var(--amber)}
.badge.blue{background:color-mix(in srgb,var(--blue) 14%,transparent);color:var(--blue)}
.badge.gold{background:var(--gold-dim);color:var(--gold)}
.badge.gray{background:var(--panel-2);color:var(--muted)}
.content{padding:20px;display:flex;flex-direction:column;gap:14px}
.grid{display:grid;gap:12px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.cols-2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:var(--panel);border:1px solid var(--border);border-radius:9px;padding:16px}
.card h3{margin:0 0 12px;font-size:11px;color:var(--faint);font-weight:650;letter-spacing:.09em;text-transform:uppercase}
.kpi .label{color:var(--faint);font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase}
.kpi .val{font-size:22px;font-weight:600;margin-top:6px;font-family:var(--mono);font-variant-numeric:tabular-nums}
.kpi .sub{margin-top:4px;font-size:11.5px;color:var(--muted)}
.pos{color:var(--green)} .neg{color:var(--red)} .neu{color:var(--text)}
.chart{width:100%;height:250px}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th{color:var(--faint);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:600;
  text-align:left;padding:6px 10px;border-bottom:1px solid var(--border)}
.tbl td{padding:7px 10px;border-bottom:1px solid var(--border)}
.tbl tr:last-child td{border-bottom:none}
.tbl td.r,.tbl th.r{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
.kv{display:flex;flex-direction:column}
.kv .row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 2px;
  border-bottom:1px solid var(--border)}
.kv .row:last-child{border-bottom:none}
.kv .k{color:var(--muted);font-size:12.5px}
.kv .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:12.5px}
.bar{height:5px;background:var(--panel-2);border-radius:99px;overflow:hidden;margin-top:6px}
.bar>span{display:block;height:100%;background:var(--gold);border-radius:99px}
.empty{color:var(--faint);text-align:center;padding:22px;font-size:12.5px}
.alert{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:7px;
  border:1px solid var(--border);background:var(--panel-2);margin-bottom:8px}
.alert:last-child{margin-bottom:0}
.alert .sev{width:7px;height:7px;border-radius:50%;margin-top:6px;flex:none;background:var(--muted)}
.alert.critical .sev{background:var(--red)} .alert.warning .sev{background:var(--amber)}
.gates{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.gate{display:flex;align-items:center;gap:7px;padding:7px 11px;border-radius:7px;border:1px solid var(--border);
  background:var(--panel-2);font-size:12px}
.gate .st{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.gate.on .st{background:var(--green)} .gate.off .st{background:var(--faint)}
.input{background:var(--panel-2);border:1px solid var(--border);border-radius:7px;color:var(--text);
  padding:8px 11px;font-size:12.5px;width:100%;font-family:var(--sans)}
.input:focus{outline:none;border-color:var(--gold)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.pill{padding:5px 11px;border-radius:6px;border:1px solid var(--border);background:var(--panel);
  color:var(--muted);cursor:pointer;font-size:11.5px;font-weight:600}
.pill.on{color:var(--gold);border-color:var(--gold);background:var(--gold-dim)}
.log-line{display:grid;grid-template-columns:80px 64px 1fr;gap:10px;padding:6px 10px;
  font-family:var(--mono);font-size:12px;border-bottom:1px solid var(--border)}
.log-line:last-child{border-bottom:none}
.log-line .t{color:var(--faint)} .log-line .k{color:var(--faint)}
@media(max-width:820px){.sidebar{position:fixed;z-index:20;height:100vh;transform:translateX(-100%);transition:transform .2s}
 .sidebar.open{transform:none}.app{grid-template-columns:1fr}.menu-btn{display:block}}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="mark">◆</div>
      <div><div class="name">Ceremyn</div><div class="sub">Market Intelligence</div></div>
    </div>
    <nav class="nav" id="nav"></nav>
    <div class="sidefoot" id="verFoot">—</div>
  </aside>
  <div class="main">
    <header class="topbar">
      <button class="menu-btn" id="menuBtn">☰</button>
      <div class="page-title" id="pageTitle">Overview</div>
      <div class="spacer"></div>
      <span class="chip" id="wsChip"><span class="dot"></span>Connecting</span>
      <span class="chip" id="runChip"><span class="dot"></span>Runtime</span>
      <span class="chip" id="marketChip"><span class="dot"></span>Market</span>
      <span class="clock num" id="clock">--:--:--</span>
      <button class="theme-btn" id="themeBtn" title="Toggle theme">☾</button>
    </header>
    <main class="content" id="content"><div class="empty">Connecting to live feed…</div></main>
  </div>
</div>
<script>
const PAGES=[
 ["overview","Overview","M3 12h4l3 8 4-16 3 8h4"],
 ["markets","Markets","M3 17l6-6 4 4 8-8"],
 ["portfolio","Portfolio","M3 3v18h18 M7 15l4-4 3 3 5-6"],
 ["orders","Orders","M4 6h16 M4 12h16 M4 18h10"],
 ["risk","Risk","M12 3l9 16H3z M12 10v4 M12 17h.01"],
 ["research","Research","M11 4a7 7 0 100 14 7 7 0 000-14z M21 21l-4.3-4.3"],
 ["system","System","M12 8a4 4 0 100 8 4 4 0 000-8z M12 2v3 M12 19v3 M2 12h3 M19 12h3"],
];
const state={}; const series={equity:[],pnl:[],exposure:[]}; const MAXP=120;
let active="overview"; let logFilter="all"; let logSearch="";

const $=(id)=>document.getElementById(id);
const fmtNum=(v,d=2)=>Number(v??0).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});
const money=(v)=>"₹"+fmtNum(v,2);
const pct=(v)=>fmtNum(v,2)+"%";
const signCls=(v)=>v>0?"pos":(v<0?"neg":"neu");

const nav=$("nav");
PAGES.forEach(([id,label,d])=>{
 const a=document.createElement("a");a.dataset.page=id;a.className=(id===active?"active":"");
 a.innerHTML=`<svg class="ic" viewBox="0 0 24 24"><path d="${d}"/></svg><span>${label}</span>`;
 a.onclick=()=>{active=id;document.querySelectorAll('.nav a').forEach(n=>n.classList.toggle('active',n.dataset.page===id));
   $("pageTitle").textContent=label;$("sidebar").classList.remove('open');
   if(id==='overview')loadEquityHistory();render();};
 nav.appendChild(a);
});
$("menuBtn").onclick=()=>$("sidebar").classList.toggle('open');
$("themeBtn").onclick=()=>{const r=document.documentElement;
 const t=r.getAttribute('data-theme')==='dark'?'light':'dark';r.setAttribute('data-theme',t);
 $("themeBtn").textContent=t==='dark'?'☾':'☀';try{localStorage.setItem('ceremyn-theme',t)}catch(e){}render();};
try{const s=localStorage.getItem('ceremyn-theme')||localStorage.getItem('aq-theme');
 if(s){document.documentElement.setAttribute('data-theme',s);$("themeBtn").textContent=s==='dark'?'☾':'☀';}}catch(e){}

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
function statusChips(){
 const h=state.health,l=state.live,s=state.sys;
 if(s)setChip("runChip",s.runtime_ready?"ok":"warn",s.runtime_ready?"Runtime ready":"Runtime off");
 else if(h){const ok=h.heartbeat_healthy!==false;setChip("runChip",ok?"ok":"bad",ok?"Engine up":"Engine down");}
 const ms=(l&&l.underlyings&&l.underlyings[0])?l.underlyings[0].market_status:null;
 if(ms)setChip("marketChip",ms==='open'?"ok":"warn",ms==='open'?"Market open":("Market "+ms));
}

function kpi(label,val,sub,cls){return `<div class="card kpi"><div class="label">${label}</div>
 <div class="val ${cls||''}">${val}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`;}
function card(title,body){return `<div class="card"><h3>${title}</h3>${body}</div>`;}
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
 c.innerHTML=`
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
 line('cEq',series.equity,'rgb(217,164,65)');
 line('cPnl',series.pnl,'rgb(67,184,106)');
}
function renderAlertList(){const a=(state.alerts&&state.alerts.alerts)||[];
 if(!a.length)return empty('No active alerts');
 return a.slice(0,8).map(x=>`<div class="alert ${x.severity}">
  <span class="sev"></span><div style="flex:1;min-width:0"><div>${x.message}</div>
  <div style="color:var(--faint);font-size:11.5px">${(x.category||'').replace('_',' ')}</div></div>
  <span class="badge ${x.severity==='critical'?'red':'amber'}">${x.severity}</span></div>`).join('');}
function renderMarkets(c){const l=state.live||{};const u=l.underlyings||[];
 const cards=u.length?u.map(r=>`<div class="card kpi"><div class="label">${r.underlying}
   <span class="badge ${r.market_status==='open'?'green':'amber'}" style="float:right">${r.market_status}</span></div>
   <div class="val">${fmtNum(r.spot,2)}</div>
   <div class="sub num">ATM ${fmtNum(r.atm_strike,0)} · PCR ${fmtNum(r.pcr,2)} · ${fmtNum(r.latency_ms,1)}ms</div></div>`).join('')
  :card('Underlyings',empty('No market feed — the runtime needs a Kite API key and a fresh session token'));
 c.innerHTML=`<div class="grid kpis">${cards}</div>
  ${card('Feed',kv(
    kvrow('Messages / sec',fmtNum(l.messages_per_second,1))+
    kvrow('Reconnects',l.reconnect_count??0)+
    kvrow('Heartbeat delay',fmtNum(l.heartbeat_delay_seconds,2)+'s')))}`;}
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
function renderOrders(c){const o=state.orders||{};const rows=o.orders||[];const m=state.oms||{};
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Open',o.open_count??0)}${kpi('Filled',o.filled_count??0,null,'pos')}
  ${kpi('Rejected',o.rejected_count??0,null,(o.rejected_count?'neg':'neu'))}
  ${kpi('Fill Ratio',pct((m.fill_ratio||0)*100))}
  ${kpi('Broker Latency',fmtNum((m.broker_latency_seconds||0)*1000,0)+' ms')}</div>
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
  </div>`;}
function renderRisk(c){const r=state.risk||{};const pf=state.portfolio||{};const e=pf.exposure||{};
 const decs=r.decisions||[];
 c.innerHTML=`<div class="grid kpis">
  ${kpi('Latest Score',fmtNum(r.latest_score??0,1))}
  ${kpi('Violations',r.violation_count??0,null,(r.violation_count?'neg':'pos'))}
  ${kpi('Gross Exposure',money(e.gross_notional||0))}
  ${kpi('Net Exposure',money(e.net_notional||0))}</div>
  <div class="grid cols-2">
   ${card('Risk Decisions',decs.length?tbl([['Decision'],['Violations'],['Score','r']],
     decs.slice(0,10).map(d=>`<tr><td><span class="badge ${d.approved?'green':'red'}">${d.approved?'approved':'rejected'}</span></td>
      <td style="color:var(--muted)">${(d.violations||[]).join(', ')||'—'}</td>
      <td class="r">${fmtNum(d.risk_score,1)}</td></tr>`).join(''))
    :empty('No decisions yet — every order is evaluated here before it can route'))}
   ${card('Alerts',renderAlertList())}</div>`;}
function renderResearch(c){const r=state.research||{};const lb=r.leaderboard||[];const f=state.features||{};
 c.innerHTML=`<div class="grid kpis">${kpi('Experiments',r.experiment_count??0)}
   ${kpi('Ranked',lb.length)}${kpi('Features',f.feature_count??0)}
   ${kpi('Feature Cache',pct((f.cache_hit_rate||0)*100))}</div>
  ${card('Strategy Leaderboard',lb.length?tbl([['#','r'],['Strategy'],['Sharpe','r'],['Return','r']],
    lb.map(x=>`<tr><td class="r">${x.rank}</td><td>${x.strategy_name}</td>
     <td class="r">${fmtNum(x.sharpe,2)}</td><td class="r">${pct(x.total_return)}</td></tr>`).join(''))
   :empty('No experiments yet — run a backtest to populate the leaderboard'))}
  <div class="grid cols-2">${card('Sharpe',chartBox('cSharpe'))}${card('Return',chartBox('cRet'))}</div>
  ${card('Latest Features',f.sample&&Object.keys(f.sample).length?kv(
    Object.entries(f.sample).map(([k,v])=>kvrow(k,v)).join('')):empty('No features computed yet'))}`;
 if(lb.length){barsChart('cSharpe',lb.map(x=>x.strategy_name),lb.map(x=>x.sharpe),'#d9a441');
  barsChart('cRet',lb.map(x=>x.strategy_name),lb.map(x=>x.total_return),'#43b86a');}}
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
  ${card('Components',comps.length?kv(comps.map(x=>kvrow(x.name,
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

connect();
loadEquityHistory();
loadSystemStatus();
setInterval(loadSystemStatus,30000);
setInterval(()=>{if(active==='overview')loadEquityHistory();},30000);
</script>
</body></html>
"""
