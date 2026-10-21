/* Transport, subscriptions, and persistent-workspace interactions. */
const tracker = C.alertTracker(stored("seen-opportunities", []));
let socket, retry = 1000, stopped = false, analysisRequest = 0, queued = false;
function scheduleViews() {
  if (queued) return;
  queued = true; requestAnimationFrame(() => { queued = false; refreshViews(); });
}
function connection(online, label) {
  T.connected = online;
  $("connection").classList.toggle("online", online);
  $("connection").innerHTML = "<i></i>" + C.escape(label);
  $("footerStatus").textContent = online ? "Data connection active" : label;
  $("footerDot").classList.toggle("online", online);
  renderRisk();
}
async function refreshChannel(channel) {
  try { T.data[channel] = await request(T.base + "/api/" + channel); scheduleViews(); }
  catch (error) { toast("Could not refresh " + channel + ": " + error.message); }
}
function connect() {
  if (stopped) return;
  socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") +
    location.host + T.base + "/ws" + (T.token ? "?token=" + encodeURIComponent(T.token) : ""));
  socket.onopen = () => { retry = 1000; connection(true, "Connected"); };
  socket.onclose = event => {
    connection(false, event.code === 4401 ? "Authentication required" : "Reconnecting");
    if (event.code !== 4401 && !stopped) { setTimeout(connect, retry); retry = Math.min(retry * 2, 30000); }
  };
  socket.onerror = () => connection(false, "Connection interrupted");
  socket.onmessage = event => {
    let frame;
    try { frame = JSON.parse(event.data); } catch { return; }
    if (frame.kind === "snapshot") { T.data[frame.channel] = frame.payload; scheduleViews(); }
    if (frame.kind === "event") refreshChannel(frame.channel);
  };
}
let scanBusy = false;
async function loadOpportunities() {
  if (scanBusy) return;
  scanBusy = true; $("refreshScan").disabled = true;
  try {
    const data = await request("/opportunities/equity?limit=200");
    T.scan = data; T.opportunities = data.opportunities || []; T.scanError = "";
    const fresh = tracker.accept(T.opportunities, !!data.last_scanned_at);
    save("seen-opportunities", tracker.keys());
    if (fresh.length) {
      T.notifications = [...fresh, ...T.notifications].slice(0, 100); T.unread += fresh.length;
      toast(fresh.length + " new qualifying " + (fresh.length === 1 ? "opportunity" : "opportunities") + ". Open Alerts to inspect.");
      if ("Notification" in window && Notification.permission === "granted") {
        try {
          const n = new Notification("Ceremyn · " + fresh.length + " new setups",
            { body: fresh.slice(0, 3).map(o => o.tradingsymbol + " · " + C.title(o.pattern_name)).join("\n"),
              tag: "ceremyn-opportunities" });
          n.onclick = () => { window.focus(); setWorkspace("terminal"); setTab("alerts"); n.close(); };
        } catch { /* In-app alerts remain available when desktop delivery is blocked. */ }
      }
    }
    scheduleViews();
  } catch (error) { T.scanError = error.message; renderScanner(); }
  finally { scanBusy = false; $("refreshScan").disabled = false; }
}
async function loadEquity() {
  try { T.equity = (await request(T.base + "/api/equity_history")).points || []; if (!T.symbol) renderChart(); }
  catch { if (!T.symbol && !T.equity.length) html("priceChart", blank("Account history unavailable", "Reconnect to refresh recorded equity.")); }
}
async function loadStatus() {
  try { T.data.sys = await request("/system/status"); scheduleViews(); }
  catch { T.data.sys = null; renderRisk(); }
}
async function selectSymbol(value) {
  const symbol = value.trim().toUpperCase();
  if (!/^[A-Z0-9&._-]{1,30}$/.test(symbol)) { toast("Enter a valid NSE symbol."); return; }
  const sequence = ++analysisRequest;
  T.symbol = symbol; T.loading = true; T.analysisError = ""; T.analysis = null; T.candles = [];
  setWorkspace("terminal"); renderScanner(); renderChart(); renderEvidence();
  $("orderSymbol").value = symbol;
  // Never carry another instrument's price or quantity into a new draft.
  $("orderQty").value = ""; $("orderPrice").value = ""; $("limitPrice").value = ""; updateEstimate();
  try {
    const [analysis, history] = await Promise.all([request("/analysis/equity/" + encodeURIComponent(symbol)),
      request("/analysis/equity/" + encodeURIComponent(symbol) + "/candles")]);
    if (sequence !== analysisRequest) return;
    T.analysis = analysis; T.candles = history.candles;
  } catch (error) {
    if (sequence === analysisRequest) T.analysisError = error.status === 503
      ? "Daily history is being prepared. Try this symbol again when the scan completes."
      : error.message;
  }
  finally { if (sequence === analysisRequest) { T.loading = false; renderChart(); renderEvidence(); } }
}
function setWorkspace(workspace) {
  if (!["terminal", "research", "system"].includes(workspace)) workspace = "terminal";
  T.workspace = workspace;
  document.querySelectorAll("[data-workspace]").forEach(b => {
    b.classList.toggle("active", b.dataset.workspace === workspace);
    b.setAttribute("aria-current", b.dataset.workspace === workspace ? "page" : "false");
  });
  for (const selector of [".scanner", ".centre", ".ticket-column"]) document.querySelector(selector).hidden = workspace !== "terminal";
  $("auxWorkspace").hidden = workspace === "terminal";
  document.title = "Ceremyn / " + C.title(workspace);
  if (location.hash !== "#" + workspace) history.replaceState(null, "", "#" + workspace);
  renderAux();
  if (workspace === "terminal") requestAnimationFrame(() => renderChart(true));
}
function setTab(tab) {
  T.tab = tab; if (tab === "alerts") T.unread = 0; renderActivity();
}
function notificationStatus() {
  const supported = "Notification" in window && window.isSecureContext;
  const permission = supported ? Notification.permission : "unsupported";
  $("enableNotifications").textContent = permission === "granted" ? "Desktop alerts enabled ✓"
    : permission === "denied" ? "Desktop alerts blocked" : permission === "unsupported" ? "In-app alerts active" : "Enable desktop alerts ↗";
  $("notificationNote").textContent = permission === "denied" ? "Allow notifications in browser settings. In-app alerts still work."
    : "Keep this tab open. Notifications follow completed daily-data scans.";
  return permission;
}
document.querySelectorAll("[data-workspace]").forEach(b => b.onclick = () => setWorkspace(b.dataset.workspace));
document.querySelectorAll("[data-filter]").forEach(b => b.onclick = () => {
  T.filter = b.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(x => { x.classList.toggle("active", x === b); x.setAttribute("aria-pressed", String(x === b)); });
  renderScanner();
});
document.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => setTab(b.dataset.tab));
document.querySelector(".activity-tabs").onkeydown = event => {
  if (!["ArrowRight", "ArrowLeft"].includes(event.key)) return;
  const tabs = ["positions", "orders", "alerts"];
  const next = tabs[(tabs.indexOf(T.tab) + (event.key === "ArrowRight" ? 1 : 2)) % 3];
  setTab(next); $("tab-" + next).focus(); event.preventDefault();
};
document.querySelectorAll("[data-side]").forEach(b => b.onclick = () => { T.side = b.dataset.side; updateSide(); });
document.querySelectorAll("[data-range]").forEach(b => b.onclick = () => { T.range = Number(b.dataset.range); renderChart(true); });
document.addEventListener("click", event => {
  const button = event.target.closest("[data-symbol]");
  if (button) selectSymbol(button.dataset.symbol);
});
$("searchForm").onsubmit = event => { event.preventDefault(); selectSymbol($("symbolSearch").value); };
$("refreshScan").onclick = loadOpportunities;
$("portfolioChart").onclick = () => { ++analysisRequest; T.symbol = ""; T.analysis = null; T.loading = false; T.analysisError = ""; renderChart(true); renderEvidence(); renderScanner(); };
$("orderForm").oninput = updateEstimate;
$("orderType").onchange = updateEstimate;
$("orderForm").onsubmit = reviewOrder;
$("confirmOrder").onclick = confirmOrder;
$("executionButton").onclick = openExecution;
$("armForm").onsubmit = event => changeExecution("arm", event);
$("disarmButton").onclick = () => changeExecution("disarm");
$("executionDialog").addEventListener("close", () => { $("armToken").value = ""; });
$("reviewDialog").addEventListener("cancel", event => { if (T.submitting) event.preventDefault(); });
$("alertsButton").onclick = () => { setWorkspace("terminal"); setTab("alerts"); $("activityBody").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "center" }); };
$("enableNotifications").onclick = async () => {
  if (notificationStatus() !== "default") return;
  try { await Notification.requestPermission(); } catch { toast("Desktop notifications are unavailable. In-app alerts remain active."); }
  notificationStatus();
};
$("themeButton").onclick = () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme; save("theme", theme); renderChart(true);
};
const savedTheme = stored("theme", "dark");
document.documentElement.dataset.theme = ["dark", "light"].includes(savedTheme) ? savedTheme : "dark";
function route() {
  const hash = location.hash.slice(1);
  if (hash === "workspace") return;
  setWorkspace(hash);
  if (hash === "orders") setTab("orders");
  if (hash === "risk") openExecution();
}
window.addEventListener("hashchange", route);
window.addEventListener("pagehide", () => { stopped = true; socket?.close(); });
window.addEventListener("pageshow", event => { if (event.persisted) { stopped = false; connect(); } });
window.addEventListener("load", () => renderChart(true));
document.addEventListener("visibilitychange", () => { if (!document.hidden) { loadStatus(); loadOpportunities(); loadEquity(); } });
function clock() { $("clock").textContent = new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }) + " IST"; }
clock(); setInterval(clock, 1000);
route(); refreshViews(); renderChart(); notificationStatus(); connect(); loadStatus(); loadEquity(); loadOpportunities();
setInterval(loadStatus, 30000); setInterval(loadOpportunities, 30000); setInterval(loadEquity, 30000);
