"""The Order Ticket page's markup/JS fragment, split out of `shell.py` to keep that file
under the project's 500-line convention (it was already at 451/500 before this page).

Spliced into `SHELL_HTML` at import time via a simple string substitution — `shell.py`
stays "one served HTML document," just assembled from two source files instead of one.

This is the shell's first *write* page: every other page renders read-only WebSocket
snapshot state. The ticket page instead calls the sibling `/manual-orders/*` router
directly via `fetch` — note these are **site-root paths**, not `/dashboard`-relative like
the rest of the shell's calls (`BASE` in `shell.py` is `/dashboard`-scoped and must not be
used here). It's also the shell's first page that needs an auth token: `/manual-orders/
submit` requires `Permission.SUBMIT_ORDER` (admin-only), and the shell has never sent an
`Authorization` header before now, so this page gets its own small token field, persisted
in `localStorage` the same way the theme toggle already is.
"""

TICKET_PAGE_ID = "ticket"
TICKET_PAGE_LABEL = "Order Ticket"
TICKET_PAGE_ICON = "M9 3v18 M15 3v18 M3 9h18 M3 15h18"

TICKET_PAGE_JS = r"""
// ---- Order Ticket (the shell's one write page — see shell_pages.py) ----
const ticketState={underlyings:[],expiries:[],chain:null,contract:null,confirming:false};
function adminToken(){try{return localStorage.getItem('aq-admin-token')||''}catch(e){return ''}}
function setAdminToken(t){try{localStorage.setItem('aq-admin-token',t)}catch(e){}}
function authHeader(){const t=adminToken();return t?{'Authorization':'Bearer '+t}:{};}
async function ticketFetch(path,opts){
 const res=await fetch(path,Object.assign({},opts,{headers:Object.assign({},authHeader(),
   (opts&&opts.headers)||{},path.endsWith('/submit')?{'Content-Type':'application/json'}:{})}));
 const body=await res.json().catch(()=>({}));
 if(!res.ok)throw new Error((body&&(body.detail&&(body.detail.message||body.detail)))||res.statusText);
 return body;
}
function renderTicket(c){
 c.innerHTML=`<div class="grid cols-2">
  ${card('Live Gate Status',`<div id="ticketGate" class="rows">${empty('Loading…')}</div>`)}
  ${card('Admin Token',`<div class="rows"><input class="input" id="ticketToken" type="password"
    placeholder="Bearer token for order submission" value="${adminToken()}"/>
    <div class="sub">Stored only in this browser (localStorage). Required to submit — read-only
    lookups below work without it when auth is disabled.</div></div>`)}
 </div>
 <div class="card">
  <h3>New Order</h3>
  <div class="grid cols-3">
   <div><div class="k" style="margin-bottom:6px">Underlying</div>
     <select class="input" id="tUnderlying"><option>Loading…</option></select></div>
   <div><div class="k" style="margin-bottom:6px">Expiry</div>
     <select class="input" id="tExpiry"><option>—</option></select></div>
   <div><div class="k" style="margin-bottom:6px">Option Type</div>
     <select class="input" id="tOptType"><option value="CE">CE (Call)</option><option value="PE">PE (Put)</option></select></div>
  </div>
  <div class="grid cols-3" style="margin-top:12px">
   <div><div class="k" style="margin-bottom:6px">Strike</div>
     <select class="input" id="tStrike"><option>—</option></select></div>
   <div><div class="k" style="margin-bottom:6px">Side</div>
     <select class="input" id="tSide"><option value="BUY">BUY</option><option value="SELL">SELL</option></select></div>
   <div><div class="k" style="margin-bottom:6px">Lots</div>
     <input class="input" id="tLots" type="number" min="1" value="1"/></div>
  </div>
  <div class="grid cols-3" style="margin-top:12px">
   <div><div class="k" style="margin-bottom:6px">Premium (LTP)</div>
     <input class="input" id="tPremium" readonly value="—"/></div>
  </div>
  <div class="sub" id="tQtyLine" style="margin-top:8px">Select a contract to see total quantity.</div>
  <div id="tError" style="margin-top:12px"></div>
  <div style="margin-top:14px;display:flex;gap:10px">
   <button class="icon-btn" id="tSubmitBtn" style="width:auto;padding:9px 18px">Submit</button>
  </div>
 </div>`;
 $("ticketToken").onchange=(e)=>setAdminToken(e.target.value.trim());
 loadGateStatus(); loadUnderlyings();
 $("tUnderlying").onchange=onUnderlyingChange;
 $("tExpiry").onchange=onExpiryChange;
 $("tOptType").onchange=onOptTypeChange;
 $("tStrike").onchange=onStrikeChange;
 $("tLots").oninput=updateQtyLine;
 $("tSubmitBtn").onclick=onSubmitClick;
}
async function loadGateStatus(){
 try{
  // BASE is the dashboard's own /dashboard-scoped root (see shell.py) — unlike every
  // /manual-orders/* call above, this one *does* use it, since /dashboard/api/execution
  // is the dashboard's own (read-only) channel, not the sibling manual-order router.
  const r=await fetch(BASE+'/api/execution',{headers:authHeader()});
  const g=await r.json();
  $("ticketGate").innerHTML=`<div class="row"><div class="grow">Routing</div>
   <span class="badge ${g.live_trading_permitted?'red':'blue'}">${g.live_trading_permitted?'LIVE — real broker':'SIMULATED — paper fills'}</span></div>
   <div class="row"><div class="grow">Gate #3 armed</div><span class="badge ${g.armed?'red':'green'}">${g.armed?'armed':'disarmed'}</span></div>`;
 }catch(e){$("ticketGate").innerHTML=empty('Could not load gate status');}
}
async function loadUnderlyings(){
 try{
  const d=await ticketFetch('/manual-orders/underlyings');
  ticketState.underlyings=d.underlyings;
  $("tUnderlying").innerHTML=d.underlyings.map(u=>`<option value="${u}">${u}</option>`).join('');
  onUnderlyingChange();
 }catch(e){showTicketError(e.message);}
}
async function onUnderlyingChange(){
 const u=$("tUnderlying").value;
 $("tExpiry").innerHTML='<option>Loading…</option>';$("tStrike").innerHTML='<option>—</option>';
 try{
  const d=await ticketFetch('/manual-orders/expiries?underlying='+encodeURIComponent(u));
  ticketState.expiries=d.expiries;
  $("tExpiry").innerHTML=d.expiries.map(x=>`<option value="${x}">${x}</option>`).join('');
  onExpiryChange();
 }catch(e){showTicketError(e.message);}
}
async function onExpiryChange(){
 const u=$("tUnderlying").value,x=$("tExpiry").value;
 if(!x)return;
 $("tStrike").innerHTML='<option>Loading…</option>';
 try{
  const chain=await ticketFetch(`/manual-orders/chain?underlying=${encodeURIComponent(u)}&expiry=${encodeURIComponent(x)}`);
  ticketState.chain=chain;
  populateStrikes();
  onStrikeChange();
 }catch(e){showTicketError(e.message);}
}
function populateStrikes(){
 const chain=ticketState.chain,optType=$("tOptType").value;
 if(!chain){$("tStrike").innerHTML='<option>—</option>';return;}
 const strikes=[...new Set(chain.entries.filter(e=>e.option_type===optType).map(e=>e.strike))];
 $("tStrike").innerHTML=strikes.map(s=>{
  const isAtm=Number(s)===Number(chain.atm_strike);
  return `<option value="${s}" ${isAtm?'selected':''}>${s}${isAtm?' (ATM)':''}</option>`;}).join('');
}
function onOptTypeChange(){populateStrikes();onStrikeChange();}
function onStrikeChange(){
 const chain=ticketState.chain;
 if(!chain){return;}
 const strike=$("tStrike").value,optType=$("tOptType").value;
 const entry=chain.entries.find(e=>Number(e.strike)===Number(strike)&&e.option_type===optType);
 ticketState.contract=entry||null;
 $("tPremium").value=entry&&entry.last_price!=null?entry.last_price:'—';
 updateQtyLine();
}
function updateQtyLine(){
 const lots=Number($("tLots").value||0),entry=ticketState.contract;
 if(!entry){$("tQtyLine").textContent='Select a contract to see total quantity.';return;}
 $("tQtyLine").textContent=`Total quantity = ${lots} lot(s) × ${entry.lot_size} = ${lots*entry.lot_size}`;
}
function showTicketError(msg){$("tError").innerHTML=`<div class="alert critical"><span class="sev"></span><div class="grow">${msg}</div></div>`;}
async function onSubmitClick(){
 $("tError").innerHTML='';
 const entry=ticketState.contract;
 if(!entry){showTicketError('Pick underlying / expiry / strike first.');return;}
 const btn=$("tSubmitBtn");
 if(!ticketState.confirming){
  ticketState.confirming=true;
  btn.textContent='Confirm — places a REAL order';
  btn.classList.add('warn-confirm');
  setTimeout(()=>{ticketState.confirming=false;btn.textContent='Submit';btn.classList.remove('warn-confirm');},5000);
  return;
 }
 ticketState.confirming=false;btn.textContent='Submit';btn.classList.remove('warn-confirm');
 const payload={underlying:$("tUnderlying").value,expiry:$("tExpiry").value,
  strike:$("tStrike").value,option_type:entry.option_type,side:$("tSide").value,
  lots:Number($("tLots").value||1)};
 try{
  const res=await ticketFetch('/manual-orders/submit',{method:'POST',body:JSON.stringify(payload)});
  $("tError").innerHTML=`<div class="alert"><span class="sev" style="background:var(--green)"></span>
   <div class="grow">Submitted: `+res.orders.map(o=>`${o.tradingsymbol} ${o.side} ${o.quantity} — ${o.execution_state}`).join(', ')+`</div></div>`;
 }catch(e){showTicketError(e.message);}
}
"""
