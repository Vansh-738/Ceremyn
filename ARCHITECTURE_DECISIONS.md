# Architecture Decisions — Deferred Questions

Ceremyn's long-term direction is an AI-powered Market Intelligence Platform — market
analysis, opportunity discovery, and explanation as the product, with execution as one
consumer of that intelligence rather than the point of the platform. The questions below
are about today's v1 architecture (options research/paper/live trading for Indian
markets), not that end-state; several of them (the runtime driver split, the
single-strategy live path) are exactly the kind of thing a broader evolution would need
to revisit. See `PROJECT_CONTEXT.md` §1 for the mission statement and `ROADMAP_V2.md` for
the phased architectural roadmap toward that longer-term direction.

Findings from the architectural cleanup audit (see git history around
`refactor(cleanup): remove verified dead code`) that require a product
decision rather than a mechanical fix. Left unchanged pending that decision.
Cross-reference: `PROJECT_CONTEXT.md`.

---

## 1. `PaperTradingEngine`'s fate

`container.paper_engine` is constructed with `strategies=[]` (hardcoded, no
configuration path to populate it) and nothing ever calls `.on_tick()`/`.run()`
on it in production. Its only two remaining call sites
(`api/llm_runtime.py:69,89`) are read-only (`.monitor.snapshot()`,
`.journal.entries()`) and will always report zero activity, since the engine
is never driven.

**Open question:** retire `PaperTradingEngine` (repoint those two LLM-recap
read sites to `oms_engine`, the same way the dashboard's Paper page was
already repointed) or actually wire strategies into it as a second paper-mode
path alongside `RestPricePoller`?

Not actioned: this changes what capability exists, not just wiring.

---

## 2. `LiveMarketDataEngine` / `RuntimeOrchestrator`'s WebSocket-streaming future

`container.live_engine` is built with no streaming client (`.start()` is an
explicit no-op by design). `container.orchestrator` is built with
`strategies=()` (hardcoded). Both are fully implemented and tested (M9, M15)
but structurally cannot drive a real trade under current wiring —
`RestPricePoller` is the only mechanism that actually does.

**Important nuance discovered during this audit:** `RuntimeOrchestrator`
serves two different roles bundled into one class: (a) driving its own
`self._strategies` via the tick-consumption loop (currently always empty,
genuinely idle), and (b) `_maintenance_loop`'s reconciliation/heartbeat/
fill-polling against the *shared* `oms_engine` singleton — which is
load-bearing for orders submitted through `RestPricePoller` too, since
`RestPricePoller` never calls `oms_engine.reconcile()` itself. Any future
change that stops the orchestrator from starting (e.g., because it has no
strategies of its own) must not also disable role (b), or reconciliation and
heartbeat checks would silently stop for live/paper trades submitted via the
REST-polling path.

**Open question:** is real-time WebSocket streaming still the intended future
(in which case this stays as-is, awaiting a Kite session-auth flow for
streaming), or has `RestPricePoller` fully superseded it (in which case the
maintenance-loop responsibilities should likely move to a component that
isn't coupled to "the WebSocket-streaming strategy-driving orchestrator")?

Not actioned: resolving this requires deciding the target execution
architecture, which is explicitly out of scope for a cleanup pass.

---

## 3. `ChainSnapshotJob` scheduling

`container.chain_snapshot_job` is fully implemented and wired into the
container, but nothing (no scheduler, no cron, no API endpoint) ever calls
`.run_once()` on it. This matches `PROJECT_CONTEXT.md`'s own pre-existing
"Next tasks" note: *"wire the chain-snapshot scheduler for proprietary
intraday history."*

**Open question:** wire it to run automatically (needs a scheduling decision
— interval, process model) or remove the container property until it's
actually needed?

Not actioned: this is already-documented, intentionally-deferred future work,
not a defect.

---

## 4. Only 1 of 15 registered strategies is live/paper-selectable

`container.rest_poller` hardcodes exactly one `StrategyDefinition`
(`long_contrarian`). The other 14 registered strategies are catalogued and
fully backtestable but cannot run in the live/paper path today, since nothing
else constructs and passes them to any running engine. This is a deliberate,
documented, account-size-driven decision (see the inline comment on
`container.rest_poller`), not a defect.

**Open question:** at what account size / under what process should
additional strategies be added to the live roster?

Not actioned: this is a trading/risk decision, not a code cleanup.
