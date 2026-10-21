const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const vm = require("node:vm");
const source = readFileSync(resolve(__dirname, "../../src/ceremyn/dashboard/assets/core.js"), "utf8");
const core = vm.runInNewContext(source.slice(0, source.indexOf("const T =")) + "\nTerminalCore;");
const draft = { symbol: "reliance", side: "BUY", quantity: "2", price: "1234.567890",
  type: "MARKET", limit: "" };
const opportunity = n => ({ tradingsymbol: "STOCK" + n, pattern_name: "breakout",
  direction: "bullish", detected_at: "2026-10-20" });

test("rejects fractional, ambiguous, unsafe and negative order quantities", () => {
  for (const quantity of ["1.5", "2abc", "1e3", "-1", "0", "9007199254740993"]) {
    assert.throws(() => core.validateOrder({ ...draft, quantity }, "paper", {}), /whole number/);
  }
});
test("preserves decimal strings and separates market reference from limit", () => {
  const order = core.validateOrder(draft, "paper", {});
  assert.equal(order.reference_price, "1234.567890");
  assert.equal(order.limit_price, null);
  assert.equal(order.tradingsymbol, "RELIANCE");
  assert.equal(order.quantity, 2);
});
test("fails closed for unknown mode and locked live execution", () => {
  assert.throws(() => core.validateOrder(draft, undefined, {}), /unavailable/);
  assert.throws(() => core.validateOrder(draft, "live", {}), /locked/);
  assert.throws(() => core.validateOrder(draft, "backtest", {}), /unavailable/);
  assert.throws(() => core.validateOrder(draft, "research", {}), /research/);
  assert.doesNotThrow(() => core.validateOrder(draft, "live", { live_trading_permitted: true }));
});
test("rejects non-finite prices and requires a limit for limit orders", () => {
  for (const price of ["Infinity", "-1", "NaN", "0", "1e9"]) {
    assert.throws(() => core.validateOrder({ ...draft, price }, "paper", {}), /positive/);
  }
  assert.throws(() => core.validateOrder({ ...draft, type: "LIMIT" }, "paper", {}), /limit price/);
});
test("initial scan is a baseline; first new opportunity after an empty scan alerts", () => {
  const tracker = core.alertTracker();
  assert.equal(tracker.accept([], false).length, 0);
  assert.equal(tracker.accept([], true).length, 0);
  assert.equal(tracker.accept([opportunity(1)], true).length, 1);
  assert.equal(tracker.accept([opportunity(1)], true).length, 0);
});
test("does not flood the initial scan or repeat persisted opportunities", () => {
  const tracker = core.alertTracker();
  assert.equal(tracker.accept([opportunity(1), opportunity(2)], true).length, 0);
  assert.equal(tracker.accept([opportunity(1), opportunity(2), opportunity(3)], true).length, 1);
  const restored = core.alertTracker(tracker.keys());
  assert.equal(restored.accept([opportunity(3)], true).length, 0);
});
test("API and user text cannot inject HTML into template attributes", () => {
  assert.equal(core.escape('<img src=x onerror="x">'), "&lt;img src=x onerror=&quot;x&quot;&gt;");
  assert.equal(core.escape("' onclick='x"), "&#39; onclick=&#39;x");
});
