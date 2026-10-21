/* Render only data regions. The ticket, focus, and user inputs remain mounted. */
function html(id, value) { if ($(id).innerHTML !== value) $(id).innerHTML = value; }
function blank(title, detail, icon = "⌁") {
  return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">${icon}</span><strong>${C.escape(title)}</strong><p>${C.escape(detail)}</p></div>`;
}
function row(label, value, cls = "") {
  return `<div class="data-row"><span>${C.escape(label)}</span><strong class="${cls}">${C.escape(value)}</strong></div>`;
}
function badge(value, cls = "") { return `<span class="badge ${cls}">${C.escape(value)}</span>`; }
function table(headings, rows) {
  return `<table><thead><tr>${headings.map(x => "<th>" + C.escape(x) + "</th>").join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}
function sign(value) { return value > 0 ? "positive" : value < 0 ? "negative" : ""; }
function renderTape() {
  const rows = T.data.live?.underlyings || [];
  html("marketTape", rows.length ? rows.map(r => {
    const stale = Date.now() - new Date(r.timestamp).getTime() > 300000;
    return `<div class="tape-item"><span>${C.escape(r.underlying)}</span><b>${C.number(r.spot)}</b><small class="${stale ? "warning" : ""}">${stale ? "STALE" : C.escape(r.market_status.toUpperCase())} · ${C.escape(C.timestamp(r.timestamp))}</small></div>`;
  }).join("") : '<div class="tape-item"><span>MARKET FEED</span><small>No quotes received · awaiting exchange data</small></div>');
}
function renderAccount() {
  const pf = T.data.portfolio;
  html("accountStrip", [
    ["Buying power", C.money(pf?.buying_power), ""],
    ["Day P&L", C.money(pf?.daily_pnl), sign(pf?.daily_pnl)],
    ["Margin used", C.money(pf?.margin_used), ""]
  ].map(([label, value, cls]) => `<div class="account-metric"><span>${label}</span><strong class="${cls}">${value}</strong></div>`).join(""));
  $("orderFunds").textContent = C.money(pf?.buying_power);
}
function renderScanner() {
  const items = T.opportunities.filter(o => T.filter === "all" || o.direction === T.filter);
  $("scanCount").textContent = items.length + " qualified setups";
  $("scanStatus").textContent = T.scanError ? "Scanner unavailable" : T.scan.scanning ? "Scan in progress" : T.scan.last_scanned_at ? C.number(T.scan.symbols_scanned, 0) + " symbols checked" : "Waiting for first scan";
  $("scanTime").textContent = "Last scan: " + C.timestamp(T.scan.last_scanned_at);
  document.querySelector(".scanner").classList.toggle("scanning", !!T.scan.scanning);
  html("scannerList", items.length ? items.map(o => `<button class="signal-row ${T.symbol === o.tradingsymbol ? "selected" : ""}" data-symbol="${C.escape(o.tradingsymbol)}">
    <span class="signal-row-top"><b>${C.escape(o.tradingsymbol)}</b>${badge(o.direction === "bullish" ? "↗ BULL" : "↘ BEAR", o.direction === "bullish" ? "positive" : "negative")}</span>
    <small>${C.escape(C.title(o.pattern_name))}</small><span class="signal-stat"><span>HIT RATE <strong>${C.number(o.hit_rate * 100, 1)}%</strong></span><span>N <strong>${C.number(o.occurrences, 0)}</strong></span></span>
  </button>`).join("") : blank(T.scanError ? "Scanner unavailable" : T.scan.scanning ? "Reading the market" : "No qualifying setups",
    T.scanError || (T.scan.scanning ? "The background scan is evaluating daily market history." : "New setups appear here after meeting the research thresholds. Search a symbol to inspect its evidence.")));
}
function renderRisk() {
  const x = T.data.execution, s = T.data.sys, oms = T.data.oms;
  html("riskSummary", row("Runtime", s ? (s.runtime_ready ? "Ready" : "Unavailable") : "Checking") +
    row("Live routing", x ? (x.live_trading_permitted ? "ARMED" : "Locked") : "Unknown", x?.live_trading_permitted ? "negative" : "") +
    row("Risk violations", T.data.risk?.violation_count ?? "—", T.data.risk?.violation_count ? "warning" : "") +
    row("OMS reconciliation", oms ? (oms.reconciled ? "In sync" : "Drift detected") : "Unknown", oms && !oms.reconciled ? "negative" : ""));
  const mode = s?.effective_mode;
  $("modeBadge").textContent = mode ? mode.toUpperCase() + " MODE" : "MODE UNKNOWN";
  $("modeBadge").classList.toggle("live", mode === "live");
  $("ticketMode").textContent = !T.connected ? "Disconnected. Reconnect before reviewing an order."
    : mode === "paper" ? "Paper trading · no real funds."
    : mode === "live" ? (x?.live_trading_permitted ? "Live broker armed · real funds." : "Live trading locked · review unavailable.")
    : mode === "research" ? "Research mode · order entry unavailable."
    : "Verifying execution mode…";
  $("reviewOrder").disabled = !T.connected || !["paper", "live"].includes(mode) || T.submitting || T.uncertain
    || (mode === "live" && !x?.live_trading_permitted);
}
function renderActivity() {
  const positions = T.data.positions?.positions || [], orders = T.data.orders?.orders || [];
  const systemAlerts = T.data.alerts?.alerts || [];
  const count = T.unread + systemAlerts.length;
  $("alertCount").textContent = String(count);
  $("alertsButton").setAttribute("aria-label", "Open alerts, " + count + " unread or active");
  $("activityAlertCount").textContent = count ? String(count) : "";
  $("activityBody").setAttribute("aria-labelledby", "tab-" + T.tab);
  document.querySelectorAll("[data-tab]").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === T.tab);
    b.setAttribute("aria-selected", String(b.dataset.tab === T.tab));
  });
  let body;
  if (T.tab === "positions") {
    $("activityMeta").textContent = positions.length + " OPEN";
    body = positions.length ? table(["Instrument", "Direction", "Quantity", "Average price"], positions.map(p =>
      `<tr><td><button class="row-button" data-symbol="${C.escape(p.tradingsymbol)}">${C.escape(p.tradingsymbol)}</button></td><td class="${p.direction === "long" ? "positive" : "negative"}">${C.escape(p.direction)}</td><td>${C.number(p.quantity, 0)}</td><td>${C.money(p.avg_price)}</td></tr>`))
      : blank("Your positions will appear here", "No open positions in the connected portfolio.", "≋");
  } else if (T.tab === "orders") {
    $("activityMeta").textContent = (T.data.orders?.total ?? 0) + " TOTAL";
    body = orders.length ? table(["Instrument", "Side", "Filled / Qty", "Status", "Updated"], orders.map(o =>
      `<tr><td>${C.escape(o.tradingsymbol)}</td><td class="${o.side === "BUY" ? "positive" : "negative"}">${C.escape(o.side)}</td><td>${o.filled_quantity} / ${o.quantity}</td><td title="${C.escape(o.last_error)}">${badge(C.title(o.execution_state))}</td><td>${C.escape(C.timestamp(o.updated_at))}</td></tr>`))
      : blank("No orders yet", "Reviewed orders and their execution status appear here.", "≡");
  } else {
    $("activityMeta").textContent = "SESSION ALERTS";
    body = systemAlerts.map(a => `<div class="alert-row"><span class="${a.severity === "critical" ? "negative" : "warning"}">●</span><div><b>${C.escape(C.title(a.category))}</b><p>${C.escape(a.message)}</p></div></div>`).join("") +
      T.notifications.map(o => `<div class="alert-row"><span class="positive">↗</span><div><b>${C.escape(o.tradingsymbol)}</b><p>${C.escape(C.title(o.pattern_name))} · ${C.escape(C.timestamp(o.detected_at))}</p></div><button data-symbol="${C.escape(o.tradingsymbol)}">Inspect ↗</button></div>`).join("");
    if (!body) body = blank("All caught up", "New opportunities and risk events will appear here.", "◷");
  }
  html("activityBody", body);
}
let chartSignature = "";
function renderChart(force = false) {
  const theme = document.documentElement.dataset.theme;
  const all = T.symbol ? T.candles : T.equity;
  const data = T.range && all.length ? all.filter(p => new Date(p.timestamp).getTime() >=
    new Date(all.at(-1).timestamp).getTime() - T.range * 86400000) : all;
  const signature = JSON.stringify([T.symbol, T.loading, T.analysisError, T.range, theme, data]);
  if (!force && signature === chartSignature) return;
  chartSignature = signature;
  $("instrumentTitle").textContent = T.symbol || "Portfolio equity";
  $("instrumentAvatar").textContent = T.symbol ? T.symbol.slice(0, 2) : "C";
  $("instrumentMeta").textContent = T.symbol ? "NSE · Daily candles" : "Recorded account history";
  $("chartSource").textContent = T.symbol ? "DAILY · EOD" : "ACCOUNT HISTORY";
  $("instrumentValue").textContent = C.money(T.symbol ? T.analysis?.latest_close : data.at(-1)?.equity);
  $("instrumentChange").textContent = T.symbol && T.analysis ? "Close · " + C.timestamp(T.analysis.as_of) : "";
  $("chartCaption").textContent = T.symbol ? "NSE daily history · " + data.length + " bars · not a live quote"
    : "Account equity · " + data.length + " recorded " + (data.length === 1 ? "observation" : "observations");
  document.querySelectorAll("[data-range]").forEach(b => b.classList.toggle("active", Number(b.dataset.range) === T.range));
  if (T.loading || T.analysisError || data.length < 2 || !window.Plotly) {
    if (window.Plotly) Plotly.purge("priceChart");
    html("priceChart", blank(T.loading ? "Loading price history" : T.analysisError ? "Analysis unavailable" :
      data.length < 2 ? "Waiting for recorded history" : "Chart library unavailable",
    T.analysisError || (data.length < 2 ? "The chart fills as verified observations arrive." : "Reconnect to load the chart. Other terminal controls remain available.")));
    return;
  }
  if (!$("priceChart").classList.contains("js-plotly-plot")) $("priceChart").innerHTML = "";
  const css = getComputedStyle(document.documentElement);
  const colour = name => css.getPropertyValue(name).trim();
  const trace = T.symbol ? { type: "candlestick", x: data.map(p => p.timestamp), open: data.map(p => p.open),
    high: data.map(p => p.high), low: data.map(p => p.low), close: data.map(p => p.close),
    increasing: { line: { color: colour("--green"), width: 1 }, fillcolor: colour("--green") },
    decreasing: { line: { color: colour("--red"), width: 1 }, fillcolor: colour("--red") } }
    : { type: "scatter", mode: "lines", x: data.map(p => p.timestamp), y: data.map(p => p.equity),
      line: { color: colour("--accent"), width: 2 }, fill: "tozeroy", fillcolor: theme === "light" ? "#315e2910" : "#c3ef780b" };
  Plotly.react("priceChart", [trace], {
    margin: { l: 12, r: 66, t: 20, b: 28 }, paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { family: "IBM Plex Mono, monospace", size: 9, color: colour("--quiet") },
    xaxis: { gridcolor: colour("--grid"), rangeslider: { visible: false }, showline: false, zeroline: false },
    yaxis: { side: "right", gridcolor: colour("--grid"), zeroline: false, fixedrange: false },
    showlegend: false, hovermode: "x unified", uirevision: T.symbol + T.range,
  }, { responsive: true, displayModeBar: false, scrollZoom: false });
}
function renderEvidence() {
  const r = T.analysis;
  $("evidencePanel").hidden = !r || !T.symbol;
  if (!r || !T.symbol) return;
  const patterns = r.patterns || [];
  const f = r.fundamentals?.score;
  html("evidencePanel", `<h2>Research evidence <span class="badge">DAILY DATA</span></h2><div class="evidence-summary">${badge(C.number(r.bars_analyzed, 0) + " bars")}${badge(C.number(r.latest_volume, 0) + " volume")}${badge(patterns.filter(p => p.active_now).length + " active patterns")}</div>` +
    (patterns.length ? table(["Pattern", "Direction", "Hit rate", "Avg move", "Samples", "Qualified"],
      patterns.map(p => `<tr><td>${C.escape(C.title(p.pattern_name))}${p.active_now ? " ●" : ""}</td><td>${C.escape(p.direction)}</td><td>${p.hit_rate == null ? "—" : C.number(p.hit_rate * 100, 1) + "%"}</td><td>${p.average_forward_return_pct == null ? "—" : C.number(p.average_forward_return_pct) + "%"}</td><td>${C.number(p.occurrences, 0)}</td><td>${p.is_opportunity_grade ? "Yes" : "No"}</td></tr>`))
      : "<p>No patterns detected in this history.</p>") +
    "<p>Fundamentals: " + C.escape(f ? f.checks_passed.length + " checks passed · " + f.checks_failed.length + " failed · " + f.checks_missing.length + " missing" : "No scored financial statements available.") + "</p>" +
    (r.fibonacci ? "<p>Fibonacci levels · 38.2% " + C.money(r.fibonacci.level_38_2) + " · 50% " + C.money(r.fibonacci.level_50_0) + " · 61.8% " + C.money(r.fibonacci.level_61_8) + "</p>" : "") +
    "<p>Historical results describe the sample. They do not guarantee the next trade.</p>");
}
function renderAux() {
  if (T.workspace === "terminal") return;
  if (T.workspace === "research") {
    const r = T.data.research, lb = r?.leaderboard || [];
    html("auxWorkspace", "<span class='eyebrow'>RESEARCH LIBRARY</span><h1>Evidence before execution.</h1><p>Completed experiments from the shared backtest engine.</p>" +
      (lb.length ? table(["Rank", "Strategy", "Sharpe", "Return", "Max drawdown", "Trades"], lb.map(x =>
        `<tr><td>${x.rank}</td><td>${C.escape(x.strategy_name)}</td><td>${C.number(x.sharpe)}</td><td>${C.number(x.total_return * 100)}%</td><td>${C.number(x.max_drawdown * 100)}%</td><td>${x.trade_count}</td></tr>`))
      : blank("No recorded experiments", "Completed and registered research runs will appear here. Use the terminal search for stock pattern evidence.")) +
      "<div class='aux-grid'><section><h2>Portfolio greeks</h2>" + ["delta","gamma","theta","vega","rho"].map(k => row(C.title(k), C.number(T.data.portfolio?.greeks?.[k], 4))).join("") +
      "</section><section><h2>Exposure</h2>" + row("Gross notional", C.money(T.data.portfolio?.exposure?.gross_notional)) + row("Net notional", C.money(T.data.portfolio?.exposure?.net_notional)) + "</section></div>");
  } else {
    const health = T.data.health, sys = T.data.sys, logs = T.data.logs?.logs || [];
    html("auxWorkspace", "<span class='eyebrow'>SYSTEM OBSERVATORY</span><h1>Know what is connected.</h1><p>Runtime health, execution gates, and operational events.</p>" +
      "<div class='aux-grid'><section><h2>Execution gates</h2>" + row("Configured mode", sys?.configured_mode || "Unknown") +
      row("Live enabled", sys ? (sys.live_trading_enabled ? "Yes" : "No") : "Unknown") +
      row("Runtime armed", T.data.execution ? (T.data.execution.armed ? "Yes" : "No") : "Unknown") +
      row("Broker", T.data.execution?.active_broker || "Unknown") + "</section><section><h2>Components</h2>" +
      ((health?.components || []).map(x => row(x.name, x.healthy ? "Healthy" : x.detail || "Unavailable", x.healthy ? "positive" : "negative")).join("") || row("Runtime", sys?.runtime_ready ? "Ready" : "Awaiting status")) +
      row("Heartbeat delay", C.number(health?.heartbeat_delay_seconds) + " s") + "</section></div><h2>Recent events</h2>" +
      (logs.length ? table(["Time", "Level", "Event"], logs.slice(-50).reverse().map(x => `<tr><td>${C.escape(C.timestamp(x.timestamp))}</td><td>${C.escape(x.level)}</td><td>${C.escape(x.event)}</td></tr>`))
      : blank("No events available", "Operational logs appear here when available to your account.")));
  }
}
function refreshViews() {
  renderTape(); renderAccount(); renderScanner(); renderRisk(); renderActivity(); renderAux();
}
