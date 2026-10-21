/* A two-stage, human-reviewed order flow. No automatic retries or order generation. */
function readOrderForm() {
  return { symbol: $("orderSymbol").value, side: T.side, quantity: $("orderQty").value,
    price: $("orderPrice").value, type: $("orderType").value, limit: $("limitPrice").value };
}
function updateEstimate() {
  const form = readOrderForm();
  const price = form.type === "LIMIT" ? Number(form.limit) : Number(form.price);
  const estimate = Number(form.quantity) * price;
  $("orderEstimate").textContent = C.money(Number.isFinite(estimate) ? estimate : 0);
  $("limitField").hidden = form.type !== "LIMIT";
  $("limitPrice").required = form.type === "LIMIT";
}
async function executionSnapshot() {
  const [sys, execution] = await Promise.all([request("/system/status"), request("/execution/status")]);
  T.data.sys = sys; T.data.execution = execution; renderRisk();
  return { sys, execution };
}
async function reviewOrder(event) {
  event.preventDefault();
  if (T.submitting || T.uncertain || !T.connected) return;
  $("orderMessage").textContent = "";
  $("reviewOrder").disabled = true;
  try {
    const { sys, execution } = await executionSnapshot();
    const payload = C.validateOrder(readOrderForm(), sys.effective_mode, execution);
    T.pending = { payload, mode: sys.effective_mode };
    $("reviewTitle").textContent = payload.side + " " + payload.quantity + " " + payload.tradingsymbol;
    html("reviewDetails", row("Execution mode", T.pending.mode.toUpperCase(), T.pending.mode === "live" ? "negative" : "") +
      row("Product", "NSE · CNC delivery") + row("Order type", payload.order_type) +
      row("Risk reference", C.money(payload.reference_price)) +
      row("Limit", payload.limit_price ? C.money(payload.limit_price) : "Market price") +
      row("Estimated notional", C.money(payload.quantity * Number(payload.limit_price || payload.reference_price))));
    $("confirmLive").checked = false;
    $("liveConfirmation").hidden = T.pending.mode !== "live";
    $("reviewError").textContent = "";
    $("confirmOrder").disabled = false;
    $("confirmOrder").textContent = "Confirm " + T.pending.mode + " order";
    $("reviewDialog").showModal();
  } catch (error) { $("orderMessage").textContent = error.message; }
  finally { renderRisk(); }
}
async function confirmOrder() {
  if (!T.pending || T.submitting || T.uncertain) return;
  const pending = T.pending;
  if (pending.mode === "live" && !$("confirmLive").checked) {
    $("reviewError").textContent = "Confirm the use of real funds to continue."; return;
  }
  T.submitting = true; $("confirmOrder").disabled = true; $("reviewError").textContent = "";
  let sent = false;
  try {
    const { sys, execution } = await executionSnapshot();
    if (sys.effective_mode !== pending.mode) throw Error("Trading mode changed. Close this review and review the order again.");
    if (pending.mode === "live" && !execution.live_trading_permitted) throw Error("Live execution was disarmed. This order has not been sent.");
    sent = true;
    const result = await request("/trading/equity", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...pending.payload, confirm_live_execution: pending.mode === "live" && $("confirmLive").checked }) });
    if (!Array.isArray(result) || !result.length) throw Error("No order acknowledgement returned.");
    const order = result[0];
    $("orderMessage").textContent = "Order " + order.oms_order_id + " · " + C.title(order.execution_state);
    $("orderForm").reset(); T.side = "BUY"; updateSide(); updateEstimate();
    T.pending = null; $("reviewDialog").close(); setTab("orders");
    toast("Order acknowledged · " + C.title(order.execution_state));
    refreshChannel("orders");
  } catch (error) {
    // A transport/5xx failure after dispatch may hide an accepted broker order.
    T.uncertain = sent && (!error.status || error.status >= 500);
    $("reviewError").textContent = T.uncertain
      ? "Order status is uncertain. Check the order book and broker before placing anything else. Do not resubmit."
      : error.message;
    if (T.uncertain) $("orderMessage").textContent = $("reviewError").textContent;
  } finally {
    T.submitting = false; $("confirmOrder").disabled = T.uncertain; renderRisk();
  }
}
function updateSide() {
  document.querySelectorAll("[data-side]").forEach(b => {
    b.classList.toggle("active", b.dataset.side === T.side);
    b.setAttribute("aria-pressed", String(b.dataset.side === T.side));
  });
}
async function openExecution() {
  $("executionMessage").textContent = "";
  $("executionDialog").showModal();
  try { await executionSnapshot(); renderExecution(); }
  catch (error) { $("executionMessage").textContent = error.message; $("armForm").hidden = true; $("disarmButton").hidden = true; }
}
function renderExecution() {
  const s = T.data.sys, x = T.data.execution;
  html("executionStatus", row("Mode configured", s?.configured_mode || "Unknown") +
    row("Live flag enabled", s?.live_trading_enabled ? "Yes" : "No") +
    row("Runtime armed", x?.armed ? "Yes" : "No") +
    row("Active broker", x?.active_broker || "Unknown"));
  $("armForm").hidden = s?.effective_mode !== "live" || !!x?.armed;
  $("disarmButton").hidden = !x?.armed;
}
async function changeExecution(action, event) {
  event?.preventDefault();
  const button = $(action === "arm" ? "armButton" : "disarmButton");
  button.disabled = true;
  $("executionMessage").textContent = "";
  const payload = action === "arm" ? { token: $("armToken").value, reason: $("armReason").value } : { reason: "Operator disarmed via terminal" };
  try {
    T.data.execution = await request("/execution/" + action, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    $("armToken").value = ""; renderExecution(); renderRisk();
    $("executionMessage").textContent = action === "arm" ? "Live execution armed for this process." : "Live execution disarmed.";
  } catch (error) { $("executionMessage").textContent = error.message; }
  finally { button.disabled = false; }
}
