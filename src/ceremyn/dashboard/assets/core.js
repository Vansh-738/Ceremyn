/* Pure presentation helpers. Also exercised directly by Node regression tests. */
const TerminalCore = (() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g,
    char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—"
    : Number(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const money = value => value == null ? "—" : "₹" + number(value);
  const title = value => String(value || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
  const key = o => [o.tradingsymbol, o.pattern_name, o.direction, o.detected_at].join("|");
  const timestamp = value => {
    const date = new Date(value);
    return !value || Number.isNaN(date.getTime()) ? "Unavailable" : date.toLocaleString("en-IN",
      { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST";
  };
  function validateOrder(form, mode, execution) {
    if (["research", "backtest"].includes(mode)) throw Error("Manual orders are unavailable in " + mode + " mode.");
    if (!["paper", "live"].includes(mode)) throw Error("Execution mode is unavailable. Reconnect before trading.");
    if (mode === "live" && !execution?.live_trading_permitted) throw Error("Live execution is locked. All three gates must pass.");
    const symbol = form.symbol.trim().toUpperCase();
    if (!/^[A-Z0-9&._-]{1,30}$/.test(symbol)) throw Error("Enter a valid NSE trading symbol.");
    if (!/^[1-9]\d*$/.test(form.quantity) || !Number.isSafeInteger(Number(form.quantity))) {
      throw Error("Quantity must be a positive whole number.");
    }
    const price = form.price.trim();
    const positiveDecimal = value => /^(?:\d+\.?\d*|\.\d+)$/.test(value)
      && Number.isFinite(Number(value)) && Number(value) > 0;
    if (!positiveDecimal(price)) throw Error("Enter a positive current reference price.");
    if (!["BUY", "SELL"].includes(form.side)) throw Error("Select Buy or Sell.");
    if (!["MARKET", "LIMIT"].includes(form.type)) throw Error("Select Market or Limit.");
    const limit = form.limit.trim();
    if (form.type === "LIMIT" && !positiveDecimal(limit)) throw Error("Enter a positive limit price.");
    return { tradingsymbol: symbol, side: form.side, quantity: Number(form.quantity),
      reference_price: price, product: "CNC", order_type: form.type,
      limit_price: form.type === "LIMIT" ? limit : null };
  }
  function alertTracker(previous = []) {
    let ready = previous.length > 0;
    const seen = new Set(previous.slice(-1000));
    return {
      accept(items, completed) {
        if (!completed) return [];
        const fresh = ready ? items.filter(item => !seen.has(key(item))) : [];
        items.forEach(item => seen.add(key(item)));
        while (seen.size > 1000) seen.delete(seen.values().next().value);
        ready = true;
        return fresh;
      },
      keys: () => [...seen]
    };
  }
  return { escape, number, money, title, key, timestamp, validateOrder, alertTracker };
})();

const T = {
  data: {}, opportunities: [], scan: {}, scanError: "", filter: "all", symbol: "",
  analysis: null, candles: [], equity: [], loading: false, analysisError: "",
  range: 0, tab: "positions", workspace: "terminal", side: "BUY", connected: false,
  notifications: [], unread: 0, pending: null, submitting: false, uncertain: false,
  base: location.pathname.replace(/\/+$/, ""), token: new URLSearchParams(location.search).get("token"),
};
const $ = id => document.getElementById(id);
const C = TerminalCore;
function stored(name, fallback) {
  try { return JSON.parse(localStorage.getItem("ceremyn-terminal-" + name)) ?? fallback; }
  catch { return fallback; }
}
function save(name, value) {
  try { localStorage.setItem("ceremyn-terminal-" + name, JSON.stringify(value)); } catch { /* Storage is optional. */ }
}
async function request(path, options = {}) {
  const headers = { ...options.headers };
  if (T.token) headers.Authorization = "Bearer " + T.token;
  const response = await fetch(path, { ...options, headers, cache: "no-store",
    signal: options.signal || AbortSignal.timeout(20000) });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail) ? detail.map(x => x.msg).join("; ") : detail;
    const error = new Error(typeof message === "string" ? message : "Request failed (" + response.status + ").");
    error.status = response.status;
    throw error;
  }
  return data;
}
let toastTimer;
function toast(message) {
  $("toast").textContent = message; $("toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, 7000);
}
