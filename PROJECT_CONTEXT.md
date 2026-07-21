# Ceremyn — Project Context

> Single source of truth for resuming work with minimal context loss. Last updated after
> M16 (Domain & Instrument Generalization — the first milestone of the multi-asset platform
> migration, see §17), which followed M15 (Trading Runtime & Production Readiness), M14
> (Institutional Options Strategy Library), M12 (LLM Assistant), M13 (Broker Integration), and
> the runtime-wiring commit (`0528a27`) that preceded them — milestones have landed out of
> numeric order all session (M13 → M12 → M14 → M15 → M16). Pair this with `CLAUDE.md` (enforced
> conventions) and `README.md` (setup + roadmap).
>
> **Note:** this file's own milestone table/status sections were stale through M15 (that
> commit's own author never updated them — confirmed by diffing `PROJECT_CONTEXT.md` at HEAD,
> which still read "last updated after M14" despite M15 being committed). M16 fixes that gap
> for M15 and itself. Separately, the working tree also carries a large body of **pre-existing,
> unrelated uncommitted work** (new strategies, a REST poller, service-management scripts —
> see §12) that predates and is untouched by M16; it was deliberately left alone and not part
> of this commit.

---

## 1. Mission & scope

Institutional-grade, AI-assisted **options trading research platform** for Indian markets
(NIFTY / BANKNIFTY index options in v1). It is a **quantitative research platform**, not a
prediction bot. Priorities, in order: reliability, risk management, modular architecture,
extensive backtesting, paper-before-live, production-quality code.

**Confirmed product decisions** (do not re-litigate):
- Backtest data: NSE EOD derivatives **bhavcopy** (free, full chains + OI) behind a pluggable
  provider; paid intraday vendors can be added later.
- Universe v1: **NIFTY + BANKNIFTY** (instrument config is data-driven — widening is cheap).
- Dashboard: FastAPI-served, dark-theme SPA + Plotly (no separate JS build).
- Broker: Zerodha **Kite Connect** (market data; live order placement gated).
- LLM: Anthropic Claude, **analysis/explanation only** — architecturally barred from ordering.

---

## 2. Current status

| Milestone | Scope | State |
|---|---|---|
| M0 | Scaffolding: config, logging, Docker, CI | ✅ |
| M1 | Domain models + core (NSE calendar, events, container) | ✅ |
| M2 | Data layer: bhavcopy ingest, Kite provider, greeks/IV/PCR analytics | ✅ |
| M3 (+M3.5) | Strategy engine + built-ins; architecture hardening | ✅ |
| M4 | Risk engine + kill switch | ✅ |
| M5 | Institutional backtesting engine + Indian cost model + metrics | ✅ |
| M6 | Research Lab (experiments, optimization, walk-forward, CV, leaderboard, reports) | ✅ |
| M7 | Feature Store (19 cached, versioned, deterministic features) | ✅ |
| M8 | Paper Trading Engine (paper broker, OMS, journal, monitor, reconciliation) | ✅ |
| M9 | Live Market Data Engine (streaming, heartbeat, reconnect, snapshots) | ✅ |
| M10 | Order Management System (state machine, broker adapters, retries, idempotency) | ✅ |
| M11 | Dashboard & Observability (read-only API + WebSocket + professional dark UI) | ✅ |
| — | Runtime wiring: `core/container.py` constructs live/OMS/paper/risk/feature/research as real singletons; dashboard consumes real (if empty) state instead of `DashboardSources()` | ✅ |
| M13 | Broker integration: real `KiteBroker`, `SimulatedBroker` fallback, triple-gate arming (`LiveTradingGate` + `GatedBrokerAdapter`), `/execution` admin API | ✅ |
| M12 | LLM assistant: analysis-only Claude tool-calling loop, 16 read-only tools, 12 capabilities, SSE streaming, `/llm` API, incapable of execution by construction | ✅ |
| M14 | Institutional Options Strategy Library: shared declarative multi-leg engine + 6 new strategies (Iron Fly, Short Straddle, Vertical Spread + Bull Put/Bear Call presets, Calendar Spread) on top of the 3 existing (Iron Condor, Short Strangle, Expiry-Day Theta) — 9 total, adjustment rules, multi-expiry backtest support, dashboard + LLM catalog integration | ✅ |
| M15 | Trading Runtime & Production Readiness: new `runtime/` package (`Orchestrator` — live data → strategies → risk → OMS → broker → portfolio, fills/heartbeat/reconciliation polling loop; ships inert with zero strategies by default); `KiteTicker` callbacks drive the real heartbeat/reconnect state machine; OMS orders journaled and restored from `JSONJournalStore` at startup; `KiteBroker` order lookup round-trips Kite's own `tag` field; a shared compensation mechanism unwinds sibling legs of a multi-leg/correlated signal group when one leg is rejected. 936 tests passing at the time. | ✅ |
| M16 | **Multi-asset migration begins** — Domain & Instrument Generalization: `AssetClass` enum + `EquityInstrument`/`FutureContract`/`ETFInstrument` alongside the existing `OptionContract`; `Position`/`Order`/`SignalLeg`/`Trade`/`ClosedTrade` widened from `OptionContract` to the generic `Instrument` base. Zero behavior change for any of the 9 option strategies. See §17. | ✅ |

**Quality (all green, M16):** 947 passed, 0 failed, 4 skipped. `ruff`, `ruff format --check`,
`mypy --strict` (201 files), `lint-imports` (17 contracts, all KEPT — no new contracts needed
for M16) all clean. **Verified in true isolation** — `git stash`-ed every pre-existing
uncommitted file (see the note above and §12) before running the gate, so this reflects HEAD +
M16's own 16 changed files only, not the combined tree. (936 tests passed at M15; the combined
working tree including the pre-existing uncommitted WIP currently passes 1045 — a stale/inflated
number if read as "M16's own scope," since most of the delta belongs to that other WIP.)

**Environment:** Python **3.12.1**, virtualenv at `.venv/`. Docker is **not installed** on the
dev machine — integration tests (Postgres/Redis) are skipped locally and run in CI.

---

## 3. Tech stack

FastAPI · Uvicorn · Pydantic v2 + pydantic-settings · SQLAlchemy 2 (async) + Alembic · asyncpg ·
Redis · Polars + Pandas · NumPy + SciPy · Plotly · structlog · kiteconnect · anthropic ·
APScheduler · pytest (+asyncio, cov) · ruff · mypy(strict) · import-linter · Docker Compose.

---

## 4. Architecture

Clean architecture, `src/` layout. Dependencies point inward; enforced by **import-linter**.

```
interface   →  api/, dashboard/, scripts/
services    →  strategies/, risk/, backtest/, research/, features/, paper/, oms/, live/, data/services
infrastructure → data/providers (Kite, bhavcopy), data/repositories (Postgres/SQLAlchemy)
domain      →  domain/  (pure entities/value objects; imports nothing else in the project)
kernel      →  core/    (logging, events, calendar, timeutils, exceptions, DI container), config/
```

**DI / composition root:** `core/container.py` (`Container`) builds the whole object graph
lazily via `cached_property` — data services, and (since the runtime-wiring milestone) the
live/OMS/paper/risk/feature/research engines, (since M13) the broker layer: `null_broker`,
`simulated_broker`, `kite_broker`, `live_trading_gate`, `gated_broker`, and (since M12) the LLM
layer: `llm_client`, `conversation_store`, `watchlist_store`. Every engine is a process-lifetime
singleton, resolved on first use, never touching Postgres, Kite, or Anthropic unless that
specific engine actually needs to (`kite_broker`/`kite_provider`/`llm_client` all raise without
credentials — deliberately never touched by default; the same lazy-factory shape used for
`GatedBrokerAdapter.live_factory` is reused for `Assistant`'s `client_factory`). `api/runtime.py`
adapts the container's engines into the dashboard's read-only ports (plus, since M14, a
`_StrategySourceAdapter` that needs no engine at all — a pure `strategies.catalog_entries()`
read); `api/llm_runtime.py` adapts them (plus the already-built `DashboardService`) into the LLM
assistant's read-only ports; `api/app.py::create_app()` wires all three and mounts `/execution`
and `/llm` alongside `/dashboard`, each a structurally separate router.

**Import-linter contracts (17, all KEPT — unchanged by M14, none needed)** — the load-bearing
ones:
- `domain` is independent and cannot import infrastructure.
- **`strategies` cannot import `execution`/`broker`** — held throughout M14: all 6 new strategy
  files import only `ceremyn.domain` and their own package, same discipline as the 3
  pre-existing ones, confirmed by `lint-imports` staying at 17/17 with zero new contracts.
  `dashboard → ceremyn.strategies` (added for the M14 strategy-catalog channel, §11) was
  already permitted — `strategies` was never in the "Dashboard cannot place orders" forbidden
  list, since it has no execution-adjacent imports of its own to leak.
- **`llm` cannot import `execution`/`risk`** — and because import-linter's `ForbiddenContract`
  checks transitively, this already forbids every package that itself reaches `risk`:
  `oms`, `paper`, `live`, `research`, `backtest`, `dashboard.backend` (confirmed by direct grep
  of each package's imports during the M12 design review, not assumed). `llm/`'s only
  `ceremyn.*` imports are `domain`, `core`, `config`, `features`, `strategies`, and
  `dashboard.models` (pure DTOs) — verified two ways: the transitive contract above, and a
  direct static-import test (`tests/unit/architecture/test_boundaries.py::
  test_llm_package_never_imports_execution_adjacent_packages`) that AST-parses every file under
  `src/ceremyn/llm/` and fails with a precise file/line on any forbidden import, rather than
  relying solely on `lint-imports` catching it after the fact.
- `risk` cannot import `broker`/`execution`/`strategies`/`llm`.
- **`oms` cannot import `broker`/`execution`** — OMS only ever codes against the `BrokerAdapter`
  protocol it defines itself (`oms/broker.py`); concrete adapters are injected at the
  composition root. Makes "do not leak broker-specific logic into OMS" a CI check.
- **`dashboard` cannot import order/broker/live-connection modules** (`oms.engine/executor/
  router/broker`, `live.engine/kite`, `paper.broker/engine`, `execution`, `broker`,
  `data.providers.kite`) — makes "dashboard never places orders / never bypasses OMS" a CI check.
  The dashboard's `/dashboard/api/execution` channel reads gate #3 status through the same
  read-port pattern as everything else (`ExecutionSource` protocol) — never the gate object,
  never a broker, never the arm/disarm actions themselves (those live only under `/execution`).

`broker/` holds gate-agnostic adapters (`NullBrokerAdapter`, `SimulatedBroker` — the realistic
fallback, reusing `paper.broker.PaperBroker`/`ExecutionSimulator`/`OMSPortfolio`). `execution/`
holds the real Kite integration and the triple-gate: `KiteBroker` (real Kite Connect calls),
`LiveTradingGate` (gate #3 runtime arming state + bounded audit trail), `GatedBrokerAdapter`
(the *only* broker OMS is ever wired with — routes live vs. fallback per-call).

---

## 5. Safety invariants (never violate, never "temporarily" bypass)

1. **Live trading disabled by default.** Three independent gates must all pass, all enforced
   inside `execution.gate.LiveTradingGate.permits_live_trading()`: (1) env
   `CEREMYN_TRADING_MODE=live`, (2) `CEREMYN_LIVE_TRADING_ENABLED=true` — both via
   `Settings.effective_mode` (LIVE degrades to PAPER without the flag) — and (3) a runtime
   arming token, submitted via `POST /execution/arm {token, reason}` *after* gates 1–2 are
   already open (`arm()` raises the pre-existing `LiveTradingLockedError` otherwise — arming is
   the deliberate last step, never a way to skip the other two). Arming requires the token to
   match `Settings.execution.arming_secret`; the armed *state* itself is runtime/in-memory only
   and always resets to disarmed on process restart — never lives in configuration. Disarming
   (`POST /execution/disarm`) needs no token: making the system safer is never gated. Missing
   any gate → `execution.gated_broker.GatedBrokerAdapter` (the only broker OMS is ever wired
   with) transparently routes every order to `broker.SimulatedBroker` instead of the real
   `execution.kite_broker.KiteBroker` — realistic simulated fills, never a live order.
2. **Every order passes through the risk engine.** Strategies emit `Signal` objects only; only
   the OMS constructs orders. Never hand a strategy a broker handle.
3. **The LLM never decides BUY/SELL — incapable of execution by construction, three ways**
   (M12): (a) **import-linter, transitively** — `llm` cannot reach `execution`, `broker`, `oms`,
   `paper`, or `live` through any import chain (see §4), so there is no code path from `llm` to
   `OrderManagementEngine`, `BrokerAdapter`, or `GatedBrokerAdapter` at import time; (b) **no
   write capability in the tool surface** — every one of the assistant's 16 tools
   (`llm/tools.py::TOOL_DEFINITIONS`) is a hand-written function that only reads and returns a
   frozen DTO; there is no "run arbitrary code" or "call arbitrary Ceremyn method" tool, so
   Claude's tool-use can only ever invoke this fixed, read-only set. (The one piece of writable
   state — watchlist symbols — is exactly as consequential as conversation history: session-
   scoped, in-memory, never touching a broker, order, or position.); (c) **`/llm` and
   `/execution` are separate FastAPI routers** — `api/llm.py` never references `api/execution.py`
   or `LiveTradingGate`; the only object shared between them is the read-only `Container`.
4. **Identical strategy/risk code across backtest, paper, and live** — the runners drive the
   same interfaces; never fork strategy logic per mode. Held through M14: all 6 new strategies
   are plain `Strategy[P]` subclasses driven by the same `StrategyContext`/`on_chain` interface
   as the 3 pre-existing ones — no new runner-specific branching. The one deliberate exception is
   Calendar Spread's cross-expiry data need (`ctx.other_expiries`): backtest populates it,
   paper/live do not yet (§11), so the *strategy* is identical everywhere, but it structurally
   degrades to never entering in paper/live today rather than acting on an incomplete chain.

---

## 6. File structure (package-by-package)

`src/ceremyn/` (LOC approximate, source only):

- **`config/`** (209) — `settings.py` (`Settings`, nested `DB/Redis/Kite/Anthropic/Data/Risk`
  settings, `env_prefix="CEREMYN_"`, `__` nesting), `modes.py` (`TradingMode`). `get_settings()`
  is the **only** sanctioned env access point.
- **`core/`** — `logging.py` (structlog: console in dev, JSON in prod), `events.py`
  (`EventBus`, async publish, sync/async handlers, `ExceptionGroup` on handler failure),
  `calendar.py` (`MarketCalendar`: trading days, session 09:15–15:30 IST, expiry rules as data —
  NIFTY weekly Tue, BANKNIFTY monthly last Tue, holiday-adjusted backward), `nse_holidays.py`
  (2024–2026; **2026 is PROVISIONAL — verify vs NSE circular**), `timeutils.py` (`IST`, `now_utc`,
  `now_ist`, `to_ist` — naive datetimes are bugs), `exceptions.py` (incl. `LiveTradingLockedError`,
  `BrokerError`), `container.py` (the composition root — see §4), `instrumentation.py`
  (`ReadableHeartbeatMonitor`, `ObservableRiskEngine` — composition-root-only subclasses that add
  pure read accessors over `live`/`risk` without touching those completed packages).
- **`domain/`** (705) — pure models: `Instrument` (generic base — `tradingsymbol`, `exchange`,
  `tick_size`, `broker_token`, `underlying`, `expiry: date | None`, `lot_size`) with four
  asset-class subclasses (M16): `OptionContract` (unchanged fields, `asset_class=OPTION`),
  `EquityInstrument`/`ETFInstrument` (`lot_size` defaults to 1), `FutureContract` (`expiry`/
  `lot_size` required, like options) — each sets `asset_class: ClassVar[AssetClass]`, mirroring
  `Strategy.strategy_type`. `Quote`/`Candle`, `Greeks`, `OptionChainSnapshot` (+`pcr`, OI totals,
  `atm_strike` — still `OptionContract`-only via `ChainEntry`, untouched by M16),
  `Signal`/`SignalLeg` (M16: `SignalLeg.contract` widened to `Instrument`; `_derive_scope`'s
  underlying/expiry equality checks needed no logic change since both fields now live on the
  base class), `Order` (+ status state machine `transition_to`; `CREATED→SUBMITTED` is
  impossible — must pass risk; M16: `contract` widened to `Instrument`), `Fill`, `Position`
  (weighted-avg-cost accounting; M16: `contract` widened to `Instrument`), `Trade` (M16: same),
  `PortfolioSnapshot` (+greeks/exposure/kill-switch), `StrategyDefinition`, enums (+`AssetClass`).
- **`data/`** (1164) — `providers/bhavcopy.py` (NSE UDiFF download+parse), `providers/kite.py`
  (market data only), `repositories/` (SQLAlchemy async: instruments/candles/chains) + Alembic,
  `services/pricing.py` (Black-Scholes price/greeks, Brent IV), `services/chain_analytics.py`
  (`iv_rank`, `iv_percentile`, `max_pain`, `atm_iv`, enrich), `services/ingest.py`,
  `services/snapshots.py` (`ChainService`, `ChainSnapshotJob`).
- **`strategies/`** (M14: 9 registered strategy types total) — `base.py` (`Strategy` ABC +
  `StrategyContext` + `emit`; M14-added `other_expiries: Mapping[date, OptionChainSnapshot]`,
  additive/empty-default, only Calendar Spread reads it), `registry.py` (`register`, `create`,
  `available_types`, M14-added `strategy_class(type)` + `catalog_entries()` — the single shared
  basis both the dashboard's and LLM's strategy-catalog DTOs build from), `common.py`
  (delta/ATM selection, marks, credit-only `premium_exit_reason`; M14-added sign-safe
  `net_pnl_pct`/`exit_reason_from_pnl_pct`, correct for both net-credit *and* net-debit
  positions — needed because the original `premium_exit_reason` silently never fires for a
  debit position). **M14's shared declarative multi-leg engine** (new, built for the 6 new
  strategies only — the 3 pre-existing ones are untouched): `legs.py` (`LegSpec` — delta or ATM
  selection, `resolve_legs`), `rules.py` (`EntryFilter`, `ExitRule`, `AdjustmentRule` +
  `entry_allowed`/`evaluate_exit`/`evaluate_adjustment` pure evaluators), `multi_leg.py`
  (`drive(strategy, ctx, params)` — the shared enter/exit/adjust driver every new strategy's
  `on_chain` delegates to). **9 registered strategies**: `iron_condor`, `short_strangle`,
  `expiry_day_theta` (M3, untouched) + `iron_fly`, `short_straddle`, `vertical_spread` (generic
  2-leg credit/debit engine), `bull_put_spread`/`bear_call_spread` (thin presets over
  `vertical_spread.py`, enforce `short_delta > long_delta` + fixed `option_type`),
  `calendar_spread` (M14, standalone — not on the multi_leg engine, since its legs cross two
  expiries; emits a *pair* of correlated single-leg `Signal`s sharing one `correlation_id`
  rather than one multi-leg signal, because `Signal` requires every leg to share one expiry).
  Adjustment rules (roll a breached short leg further OTM) are opt-in/off-by-default on the new
  engine — a genuinely new capability, not retrofitted onto the 3 pre-existing strategies.
- **`risk/`** (1139) — `engine.py` (`RiskEngine.evaluate/validate(portfolio, signal) →
  RiskDecision`), rule pipeline (`rules/`: drawdown, event, exposure, greeks, liquidity, margin,
  position, time, volatility), `registry.py`, `context.py`, `models.py`.
- **`backtest/`** (1463) — `runner.py` (`BacktestRunner.run(events) → BacktestReport`), `engine.py`
  (event-driven; M14: `latest_chains: dict[date, OptionChainSnapshot]` tracks one chain per
  expiry alongside the pre-existing single `latest_chain`, feeding `StrategyContext.
  other_expiries` on every `_run_strategy` call — additive, only Calendar Spread reads it),
  `simulator.py` (`ExecutionSimulator`: market/limit/stop, partial fills),
  `fills.py` (`PendingOrderState`/`VirtualFill`/`ExecutionContext`), `portfolio.py`
  (`BacktestPortfolio` — the canonical accounting), `commission.py` (Indian cost model),
  `slippage.py`, `metrics.py` (`compute_statistics`), `statistics.py`, `walkforward.py`,
  `montecarlo.py` (probability-of-ruin), `optimization.py`, `ledger.py`.
- **`research/`** (1574) — Research Lab over the backtester: `experiment_manager.py`, `experiment.py`
  (spec_hash reproducibility), `experiment_store.py` (protocol + JSON store), `optimizer.py`
  (grid/random/sweep), `parameter_grid.py`, `leaderboard.py`, `comparison.py`, `walkforward.py`,
  `cross_validation.py`, `statistics.py` (`ExperimentMetrics`, `metrics_from_report`), `report.py`
  (MD/JSON/HTML), `dataset.py`.
- **`features/`** (986) — Feature Store: `engine.py` (`FeatureEngine.compute_all(FeatureContext)
  → FeatureSet`, compute-once cache), `context.py`, `models.py`, `registry.py`, `cache.py`
  (protocol + `InMemoryFeatureCache`), `versioning.py`, `validation.py`, `indicators.py` (NumPy
  kernels), `chain_features.py` + `price_features.py` (19 features: PCR, OI, OI change, max pain,
  IV rank/percentile, expected move, liquidity, DTE, TTE, VWAP, ATR, EMA, RSI, ADX, HV, RV, trend
  strength, market regime).
- **`paper/`** (1003) — Paper Trading Engine: `engine.py` (`PaperTradingEngine.on_tick(MarketTick)`),
  `broker.py` (wraps `ExecutionSimulator` + order queue + latency), `orders.py` (`PaperOMS`),
  `portfolio.py` (wraps `BacktestPortfolio`), `journal.py`, `monitor.py` (`MonitorSnapshot`),
  `reconciliation.py`, `scheduler.py`, `events.py`, `fills.py`.
- **`live/`** (1220) — Live Market Data Engine: `engine.py` (`LiveMarketDataEngine`), `feed.py`,
  `kite.py` (streaming client), `heartbeat.py` (`HeartbeatState`), `reconnect.py`
  (`ReconnectState`), `metrics.py` (`LiveMetricsSnapshot`), `snapshot.py` (`MarketSnapshot`,
  `LiveTick`), `market_hours.py` (`MarketStatus`), `aggregator.py`, `cache.py`, `validator.py`,
  `stream.py`, `scheduler.py`, `events.py` (published on the core `EventBus`).
- **`oms/`** (2098) — Order Management System: `engine.py` (`OrderManagementEngine` /
  `OMSEngine`; `.orders`, `.portfolio`, `.kill_switch`, `metrics_snapshot()`, `submit_signal`,
  `arm/disarm_kill_switch`), `orders.py` (`OMSOrder`, `OMSExecutionState`, planner), `broker.py`
  (`BrokerAdapter` protocol + snapshots), `executor.py`, `router.py`, `fills.py`, `retry.py`,
  `idempotency.py`, `journal.py`, `ledger.py`, `metrics.py` (`OMSMetricsSnapshot`),
  `positions.py` (`OMSPortfolio`), `reconciliation.py` (`ReconciliationReport`), `state_machine.py`,
  `validators.py`, `events.py`.
- **`dashboard/`** — read-only observability (see §9), including the M13 `execution` channel
  (gate #3 status only, read-only), (M12) `permissions.py`'s `Permission.USE_LLM` (granted
  to both `Role.VIEWER` and `Role.ADMIN` — reused as-is by `/llm`'s auth, no new auth surface),
  and (M14) `models.py::StrategyEntry`/`StrategyView` + `backend.py::StrategySource` protocol +
  `DashboardService.strategies()` — a small new `GET /dashboard/api/strategies` channel listing
  all 9 registered strategies + their JSON-schema params, mirroring the LLM's catalog tool.
- **`api/`** — `app.py` (`create_app` — the single application: health/system + Swagger + mounts
  the dashboard at `/dashboard` and, when a container is wired, the admin router at
  `/execution` and the LLM assistant at `/llm`), `main.py` (`app = create_app()`; uvicorn entry),
  `runtime.py` (`build_dashboard_sources(container)` — composition-edge adapters translating
  `Container` engines into the dashboard's read ports, including `_ExecutionSourceAdapter` and,
  since M14, `_StrategySourceAdapter` — the one adapter here that needs no `Container` engine at
  all, a pure `strategies.catalog_entries()` read),
  `execution.py` (`build_execution_router` — `POST /execution/arm`, `POST /execution/disarm`,
  `GET /execution/status`; structurally separate from `/dashboard`, never imported by it),
  `llm_runtime.py` (M12 — `_ExperimentDetailAdapter`, `_RecapAdapter`; `build_assistant(container,
  dashboard_service) → Assistant`, wiring `container.llm_client` as a **lazy factory**, never
  touched at mount time), `llm.py` (M12 — `build_llm_router`; SSE endpoints, structurally
  separate from both `/dashboard` and `/execution`). See §10 for the M12 write-up, §11 for M14.
- **`broker/`** — `NullBrokerAdapter` (raises on submit; used as a placeholder/test double),
  `SimulatedBroker` (the real safe-fallback broker OMS actually uses whenever ungated — reuses
  `paper.broker.PaperBroker` + `oms.positions.OMSPortfolio`).
- **`execution/`** — `kite_broker.py` (`KiteBroker`, real Kite Connect order placement), `gate.py`
  (`LiveTradingGate`, `GateEvent`), `gated_broker.py` (`GatedBrokerAdapter`). See §5.
- **`llm/`** (M12) — `client.py` (`ClaudeClient`, thin Anthropic SDK wrapper, `from_settings()`),
  `providers.py` (structural Protocols: `DashboardReader` — duck-typed by the real
  `DashboardService`, `llm` never imports `ceremyn.dashboard`; `ExperimentDetailReader`,
  `RecapReader`), `snapshots.py` (`ExperimentDetailBrief`, `RecapBrief`, `StrategyCatalogEntry` —
  frozen DTOs; M14 added a `params_schema: dict[str, Any]` field, populated from each
  strategy's `params_model.model_json_schema()`, so strategy-explanation answers can describe
  configurable parameters for any of the 9 registered strategies with zero per-strategy code),
  `tools.py` (16 read-only tool definitions + dispatch table + `ToolResult(data, source)`; M14
  removed a hardcoded `_STRATEGY_CLASSES` dict that duplicated the registry — `get_strategy_
  catalog` now derives from `strategies.catalog_entries()` directly, so new strategies need zero
  `llm/` changes to appear in the catalog), `assistant.py`
  (`Assistant` — the single Claude tool-calling loop implementing all 12 capabilities;
  `chat/daily_recap/session_recap/generate_report/compare_experiments`; `StreamEvent`),
  `conversation.py` / `watchlist.py` (session-scoped, in-memory-only stores; bounded/LRU —
  reset on restart, never persisted), `prompts.py`, `events.py` (`AssistantReportGenerated`,
  published to the core `EventBus`), `exceptions.py`. See §10.

`tests/` mirrors `src/` under `tests/unit/<pkg>/`; `tests/integration/` (DB-gated,
`@pytest.mark.integration`, needs `TEST_DATABASE_URL`); shared helpers in
`tests/unit/backtest/helpers.py` (`make_chain`, `make_contract`, `make_strategy_definition`,
registered `test_backtest_strategy`).

---

## 7. Coding conventions (enforced — see CLAUDE.md)

- Python 3.12, full type hints, **`mypy --strict` must pass**.
- Ruff lint + format, **line length 100**. The dashboard `shell.py` HTML blob is exempted from
  E501/RUF00x in `pyproject.toml`.
- **All datetimes timezone-aware**; market logic in IST, storage/logs in UTC (DTZ lint rules).
- **Money/prices = `Decimal`** in domain/ledgers; floats only inside numerical kernels
  (greeks/IV/indicators) at the NumPy boundary.
- Logging via `structlog.get_logger(__name__)`; never `print`.
- Config only via `ceremyn.config.get_settings()`; never read `os.environ` elsewhere.
- Files ≤ 500 lines; split before exceeding.
- Every module ships with tests; new packages target **>95% unit coverage**.
- **Reuse, don't duplicate.** Established pattern across M6–M11: new layers compose existing
  engines behind protocols; persistence follows the "protocol + JSON store + in-memory" shape;
  runtime caches are in-memory behind a protocol (Redis-swappable). Frozen Pydantic value
  objects everywhere; `model_config = ConfigDict(frozen=True)`.

---

## 8. Key APIs / entry points (for quick reuse)

- Run one backtest: `BacktestRunner(strategy, definition, risk_engine, config).run(events) →
  BacktestReport` (`backtest/runner.py`).
- Build a strategy: `create(StrategyDefinition) → Strategy`; `Strategy.on_chain(StrategyContext)
  → list[Signal]`; `strategies.available_types()` / `strategy_class(type)` /
  `catalog_entries()` (M14) to enumerate/introspect all 9 registered types.
- Shared multi-leg engine (M14, `strategies/multi_leg.py`): `drive(strategy, ctx, params) →
  list[Signal]` — the common enter/exit/adjust driver 5 of the 6 new strategies configure
  instead of hand-implementing; `params` just needs `.lots` + `.legs: tuple[LegSpec,...]` +
  `.entry: EntryFilter` + `.exit_rule: ExitRule` + `.adjustment: AdjustmentRule` (structural,
  not a required base class). `legs.resolve_legs(chain, specs, lots) → tuple[SignalLeg,...] |
  None`. `rules.entry_allowed/evaluate_exit/evaluate_adjustment`.
- Risk check: `RiskEngine.evaluate(PortfolioSnapshot, Signal, evaluated_at=) → RiskDecision`
  (`.approved`, `.risk_score`, `.violations`).
- Features: `FeatureEngine().compute_all(FeatureContext(as_of, underlying, chain, iv_history,
  candles)) → FeatureSet` (compute-once, versioned).
- Research: `ExperimentManager(store).run(spec, dataset, risk_engine)`; `Optimizer(manager)
  .grid_search/random_search/sweep(...)`; `Leaderboard().rank(experiments, by=RankMetric)`.
- Paper: `PaperTradingEngine(strategies, risk_engine, config).on_tick(MarketTick)` /
  `.run(feed)`.
- Live: `LiveMarketDataEngine(underlyings, contracts, analytics, event_bus=, ...)`; reads:
  `LiveMetricsSnapshot`, `MarketSnapshot`, `HeartbeatState`, `ReconnectState`.
- OMS: `OrderManagementEngine(risk_engine, brokers, default_broker)`; reads: `.orders`,
  `.portfolio`, `.kill_switch`, `.metrics_snapshot()`, `.reconcile()`.
- Broker integration (M13): `GatedBrokerAdapter(live_factory, fallback, gate, settings)` — the
  single `BrokerAdapter` OMS is wired with; `live_factory` is called (and cached) only the first
  time `gate.permits_live_trading(settings)` is true, so a missing Kite API key never breaks
  construction outside live mode. `LiveTradingGate().arm(settings=, reason=)` /
  `.disarm(reason=)` / `.permits_live_trading(settings)` / `.history()`. `KiteBroker(kite:
  Any).from_settings(settings)` mirrors `KiteProvider.from_settings` exactly. `SimulatedBroker
  (market_data=LiveDataCache | None)` — realistic fills via the reused `ExecutionSimulator`.
- LLM assistant (M12): `Assistant(client_factory, dashboard, experiments, recap, watchlist,
  conversation, event_bus=)`; `.chat(session_id, message) → AsyncIterator[StreamEvent]`,
  `.daily_recap/.session_recap/.generate_report(topic=)/.compare_experiments(experiment_ids=)`
  (same call). `ClaudeClient.from_settings(settings)` mirrors `KiteBroker.from_settings` exactly
  — raises `LLMProviderError` without `CEREMYN_ANTHROPIC__API_KEY`, never touched until a
  turn actually needs it (`client_factory`, resolved+cached lazily inside `Assistant`).

---

## 9. Dashboard (M11) — how it works & how to run

Read-only observability. **No business logic, no order placement** (structurally: depends on
read-only port protocols, not the concrete engines). Since the runtime-wiring milestone it
consumes **real engine state** by default (via `core/container.py` + `api/runtime.py`), not
empty placeholders — pages render honest zero-state until something actually happens, rather
than showing zeros because nothing was ever connected.

- **Single app**: mounted into `api/app.py:create_app()` at prefix `/dashboard`.
  - UI shell: `GET /dashboard/`  · JSON: `GET /dashboard/api/{overview,portfolio,orders,
    positions,live,features,risk,oms,research,paper,health,metrics,alerts,logs,execution}` ·
    WebSocket: `/dashboard/ws` · Swagger: `/docs` · health: `/health`, `/system/status`.
  - **The dashboard itself exposes only GET/HEAD** (route-scan test scoped to `/dashboard*`
    enforces it). Since M13, `/execution/*` (arm/disarm/status) is a deliberately **separate**
    router with `POST` routes — mounted alongside the dashboard in the same app, but never
    reachable through it and never imported by it (`test_arm_and_disarm_are_not_reachable_under_
    dashboard`).
- **Ports** (`dashboard/backend.py`): `LiveSource`, `OMSSource`, `PortfolioSource`, `RiskSource`,
  `FeatureSource`, `PaperSource`, `ResearchSource`, `LogSource`, `ExecutionSource` (M13, gate #3
  status only) — the real engines don't satisfy these directly; `api/runtime.py`'s adapters
  (`_LiveSourceAdapter`, `_OMSSourceAdapter`, ..., `_ExecutionSourceAdapter`) hold a `Container`
  and translate lazily, so touching the dashboard never forces engine construction until a
  channel is actually read. Wired at the edge via `DashboardSources` (`build_dashboard_sources`).
  `DashboardService` assembles view models; `views/metrics/alerts/health.py` are pure builders.
- **WebSocket model**: on connect send full snapshot; live events pushed immediately via
  `EventBridge` (core `EventBus`, registered in `create_app()`'s lifespan against the shared
  `container.event_bus`); a broadcaster (in the app **lifespan**) pushes a channel frame only
  when its content hash changed (`SnapshotDiffer`). No client polling.
- **UI** (`dashboard/shell.py`): dark-theme SPA — collapsible sidebar (12 pages), navbar
  (connection/broker/market chips, live IST clock, theme toggle), KPI cards, Plotly charts,
  chips/badges/progress bars, log search/filters. Time series accumulated client-side from WS
  frames. Verified rendering in a real browser. **Not yet extended with an Execution page** —
  the M13 gate status is available via the JSON channel/WebSocket but has no dedicated UI panel
  (explicit scope decision; a small follow-up if wanted).

Run: `.venv/bin/uvicorn ceremyn.api.main:app --reload` → open `http://127.0.0.1:8000/dashboard/`.
Arm/disarm (needs `CEREMYN_EXECUTION__ARMING_SECRET` set): `curl -X POST
127.0.0.1:8000/execution/arm -d '{"token":"...","reason":"..."}'`.

---

## 10. LLM Assistant (M12) — how it works & how to run

Read-only, analysis/explanation-only assistant over the platform's existing data — never
places orders, never bypasses the risk engine or OMS, never calls a broker (see §5 invariant 3
for the three independent reasons it structurally cannot). Reuses the Dashboard, Feature Store,
Research Lab, Risk Engine, OMS, Paper Trading, and EventBus rather than duplicating any
analytics — the assistant's numbers are always the dashboard's numbers, because most of its
tools read through the exact same `DashboardService` instance the dashboard renders from.

- **Provider-based, not import-based.** `llm/providers.py` defines three structural Protocols
  (`DashboardReader`, `ExperimentDetailReader`, `RecapReader`); `llm` never imports
  `ceremyn.dashboard` or `ceremyn.oms`/`ceremyn.paper`/etc. to satisfy them. At the
  composition root (`api/app.py::create_app()`), the real `DashboardService` is handed to the
  assistant directly (duck-typed — it already has the right method surface); the two new
  Protocols are satisfied by small adapters in `api/llm_runtime.py` (`_ExperimentDetailAdapter`
  reads `container.experiment_store`; `_RecapAdapter` reads the OMS/Paper journals filtered
  since midnight IST, or cumulative engine metrics for the session). `api/` has no import
  restrictions, so this is where the (otherwise forbidden) edge from "LLM-reachable code" to
  the real engines is allowed to exist — never inside `llm/` itself.
- **One conversational engine, 16 tools, 12 capabilities.** `llm/assistant.py::Assistant` is a
  single Claude tool-calling loop (`llm/tools.py::TOOL_DEFINITIONS` + `TOOL_DISPATCH`); every
  tool only reads and returns a frozen DTO, carrying a `source: str`. Open-ended Q&A and
  explanations (portfolio, market, trade, risk, feature, strategy) go through
  `Assistant.chat(session_id, message)`, where the model picks tools freely. The four batch
  capabilities — daily recap, session recap, report generation, experiment comparison — are the
  *same* loop, seeded with a fixed system-prompt template (`llm/prompts.py`) and, where the
  needed tools are already known, pre-fetched deterministically as the first turn rather than
  left to the model to discover (cheaper, deterministic, zero duplicated streaming/citation
  logic).
- **Citations are structural, not just prompted.** Every tool result is `(DTO, source)`. The
  system prompt asks the model to cite `source` inline, but the API layer *also* independently
  collects every `source` actually invoked during a turn into `citations: list[str]` on the
  final `done` frame — guaranteed by construction from the tool-call log, never solely
  dependent on the model remembering to mention it.
- **Streaming**: `POST /llm/chat`, `/llm/reports/{daily-recap,session-recap,generate}`,
  `/llm/compare-experiments` all return `text/event-stream` SSE frames — `text_delta`,
  `tool_call` (name + source), `done` (+ citations), `error`. `GET/POST /llm/watchlist/
  {session_id}` are plain JSON (add/remove/list; symbols normalized `.strip().upper()`).
- **Conversation memory & watchlists are session-scoped, in-memory only** (`ConversationStore`/
  `WatchlistStore` protocols + `InMemoryConversationStore`/`InMemoryWatchlistStore`), keyed by a
  client-supplied `session_id`, bounded per-session + LRU-evicted across sessions (same bounded-
  growth discipline as `LiveTradingGate`'s audit trail). Reset on restart, never persisted —
  matches "conversation memory only within the current session" literally.
- **Auth reuses the dashboard's bearer-token settings exactly** — `dashboard/permissions.py`
  gained one additive `Permission.USE_LLM`, granted to both `Role.VIEWER` and `Role.ADMIN` (no
  new auth surface; `api/llm.py`'s `_auth_dependency` mirrors `dashboard/api.py`'s).
- **Lazy credentials, verified live.** `container.llm_client` (`ClaudeClient.from_settings`) is
  never touched at app-mount or `build_assistant()` time — only the first time a chat turn
  actually calls it (`Assistant._resolve_client()`, cached after first resolution). Manually
  verified against a running `uvicorn` process with no `CEREMYN_ANTHROPIC__API_KEY`
  configured: `/llm/watchlist/*` works end-to-end; `/llm/chat` and `/llm/reports/daily-recap`
  stream real, live tool-call frames (pre-fetched from the real `Container` engines) and then a
  clean `{"type": "error", "message": "CEREMYN_ANTHROPIC__API_KEY is not configured"}` SSE
  frame — never a crash, and `/dashboard`/`/execution`/`/health` stay unaffected throughout.
- **EventBus**: after any report/recap, the assistant publishes `AssistantReportGenerated`
  (`llm/events.py`, pure pydantic) onto `container.event_bus` — makes LLM activity observable
  (e.g. a future "recent AI reports" dashboard panel) without inventing new auto-triggering
  behavior.

Run: same single app as the dashboard (`.venv/bin/uvicorn ceremyn.api.main:app --reload`);
set `CEREMYN_ANTHROPIC__API_KEY=...` for `/llm/chat` etc. to actually complete (unset, they
still mount and stream a clean error frame). Watchlist example: `curl -X POST
127.0.0.1:8000/llm/watchlist/s1 -d '{"action":"add","symbol":"NIFTY"}'`.

---

## 11. Options Strategy Library (M14) — how it works

Nine registered institutional multi-leg strategies total: 3 pre-existing (Iron Condor, Short
Strangle, Expiry-Day Theta, all M3, untouched) + 6 new (Iron Fly, Short Straddle, Vertical
Spread, Bull Put Spread, Bear Call Spread, Calendar Spread). Reuses Backtesting, Research Lab,
Risk Engine, OMS, Paper Trading, Dashboard, and LLM Assistant with zero changes to any of
them — confirmed during design review that `OrderPlanner`/`ExecutionSimulator` already build
one order per leg generically (proven by the pre-existing 4-leg Iron Condor), `RiskEngine`
evaluates any `Signal` shape generically, and Research Lab's `ExperimentManager`/`Optimizer` are
fully generic over `strategy_type` strings.

- **A shared declarative multi-leg engine, not 6 copy-pasted strategies.** `strategies/legs.py`
  (`LegSpec` — delta-target or ATM selection) + `strategies/rules.py` (`EntryFilter`, `ExitRule`,
  `AdjustmentRule` + pure evaluators) + `strategies/multi_leg.py` (`drive()` — the shared
  enter/exit/adjust driver) let each of Iron Fly, Short Straddle, Vertical Spread declare *what*
  legs/rules it wants via a flat, grid-search-friendly params model (same shape as the
  pre-existing `IronCondorParams`) rather than hand-implementing chain lookups and P&L math
  again. `bull_put_spread.py`/`bear_call_spread.py` are ~30-line presets subclassing
  `VerticalSpreadParams`, fixing `option_type` and validating the credit-spread delta ordering
  the name promises — zero duplicated logic between the generic engine and its two named
  presets.
- **A real, pre-existing bug this milestone fixed without touching the old code**: the
  pre-existing `common.premium_exit_reason` silently never fires for a net-*debit* position
  (guards `credit <= 0: return None` — correct for the 3 original credit-only strategies, wrong
  once a debit strategy exists). New, additive `common.net_pnl_pct`/`exit_reason_from_pnl_pct`
  compute P&L% correctly for both credit and debit entries; `premium_exit_reason` itself is
  untouched, still used by the 3 original strategies exactly as before.
- **Calendar Spread needed a genuine, scoped architecture extension**: `OptionChainSnapshot`
  is single-expiry by design, and neither `BacktestEngine` nor `PaperTradingEngine` tracked more
  than one "current" chain before M14. `StrategyContext` gained `other_expiries: Mapping[date,
  OptionChainSnapshot]` (additive, empty default — the other 8 strategies never read it);
  `BacktestEngine` gained `latest_chains: dict[date, OptionChainSnapshot]` alongside the
  pre-existing single `latest_chain`, feeding `other_expiries` on every strategy invocation.
  **Backtest/research only** — paper/live intentionally out of scope this milestone (§12) since
  the live/paper data pipeline (`ChainService`/`ChainSnapshotJob`/`MarketTick`) only ever
  snapshots one expiry per underlying; wiring true multi-expiry paper/live support is separate,
  larger work. In paper/live mode Calendar Spread simply sees an empty `other_expiries` and
  never enters — an honest degrade, not a crash, matching the platform's "never fabricate data"
  philosophy already established for the dashboard/LLM.
- **A domain constraint discovered mid-implementation, resolved without touching `domain/`**:
  `Signal._derive_scope` (`domain/signals.py`) requires every leg within one `Signal` to share a
  single expiry — a deliberate, foundational invariant. A calendar spread's near+far legs can
  therefore never live in one `Signal`. `CalendarSpread` instead emits a *pair* of correlated
  single-leg `Signal`s (same `correlation_id`, one per expiry) on both entry and exit. Structural
  consequence: the risk engine evaluates each leg's signal independently rather than as one
  atomic 2-leg decision — unlike every other multi-leg strategy here, it's possible in principle
  for one Calendar Spread leg to be approved and the other rejected. Documented directly in
  `calendar_spread.py`'s module docstring, not hidden.
- **Adjustment rules are a genuinely new capability** (`AdjustmentRule`, opt-in, off by default):
  when enabled, rolls the first short leg whose `|delta|` breaches a configured threshold
  further OTM (closes the breached leg, opens a new one at a tighter target delta) as a single
  `ADJUST` signal — `domain/enums.py::SignalAction.ADJUST` already existed but was unused before
  M14. Demonstrated on the new multi-leg engine (available to Iron Fly/Short Straddle/Vertical
  Spread and its presets); not retrofitted onto the 3 pre-existing strategies.
- **Dashboard + LLM catalog integration, one shared source of truth.** `strategies/registry.py`
  gained `strategy_class(type)` and `catalog_entries()` (plain dicts: strategy_type, class_name,
  description, `params_model.model_json_schema()`). Both `llm/tools.py::_get_strategy_catalog`
  (dropping a hardcoded `_STRATEGY_CLASSES` dict that duplicated the registry) and the new
  `GET /dashboard/api/strategies` channel (`dashboard/models.py::StrategyEntry`/`StrategyView`,
  `backend.py::StrategySource`, `api/runtime.py::_StrategySourceAdapter` — the one dashboard
  adapter needing no `Container` engine at all) build their own DTOs from these same dicts, so
  a 10th strategy needs zero `llm/`/`dashboard/` changes to appear in either surface.

Run: same single app (`.venv/bin/uvicorn ceremyn.api.main:app --reload`); `curl
127.0.0.1:8000/dashboard/api/strategies` lists all 9 with full JSON-schema params. No new
settings, no new container providers — the strategy registry is pure, stateless Python state
populated at import time.

---

## 12. Outstanding issues / known gaps

1. **Logs source is a stub** — `LogSource` returns injected `LogRow`s; there is no structlog→ring-
   buffer bridge yet. Logs page renders whatever a log source provides (empty by default).
2. **2026 NSE holidays are PROVISIONAL** (`core/nse_holidays.py`) — verify against the official
   circular before relying on 2026 calendar/expiry math.
3. **Integration tests require Postgres** (Docker not installed locally) — 4 skips locally; they
   run in CI (`TEST_DATABASE_URL`).
4. **No secrets configured** — Kite/Anthropic keys and `execution.arming_secret` are all empty in
   dev; live data, LLM, and arming all need real values to do anything beyond their safe defaults
   (empty `arming_secret` means `/execution/arm` always 403s, and no `CEREMYN_ANTHROPIC__
   API_KEY` means `/llm/chat` etc. always stream a clean SSE error frame — both refused, not
   silently permitted/faked, when unconfigured; manually verified for `/llm` — see §10).
5. `create_dashboard_app` still exists (test helper only). Production uses the single app.
6. **`core/container.py`'s data-layer providers (`_db`, `instrument_repository`,
   `chain_service`, `kite_provider`, etc.) stay below the ~95% per-package coverage convention**
   in isolation — pre-existing, requires Postgres/Kite creds to exercise, unrelated to
   M13/M12/M14 (every M13- and M12-added provider is fully covered; see `test_kite_broker_is_
   never_touched_without_credentials` / `test_kite_broker_constructs_when_credentials_are_
   present` and the equivalent `test_llm_client_is_never_touched_without_credentials`-style
   tests in `tests/unit/core/test_container.py`; M14 added no new container providers at all —
   the strategy registry is stateless, populated at import time, no credentials involved).
7. **M13's audit trail is in-memory only** (`LiveTradingGate`'s bounded `deque`) — resets on
   restart along with the armed state itself (by design). A `JSONJournalStore`-backed version,
   matching the existing "protocol + JSON store + in-memory" pattern, is a natural follow-up if
   a persistent record of arm/disarm/routing events across restarts is wanted.
8. **`KiteBroker` is unit-tested against an injected fake client only** — there is no live/sandbox
   Kite account to test against in this environment. The request/response mapping (`place_order`/
   `modify_order`/`cancel_order`/`orders`/`trades`/`positions`/`margins`) is believed correct
   against the Kite Connect v3 docs but has never round-tripped a real API call.
9. **No dedicated dashboard UI for the M13 execution/gate status** — the JSON channel and
   WebSocket push both work (`/dashboard/api/execution`), but `dashboard/shell.py` has no visual
   panel for it yet (explicit scope decision, not an oversight).
10. **`ClaudeClient` is unit-tested against an injected fake Anthropic client only** (M12) — same
    shape as issue 8: no real Anthropic API call has ever round-tripped in this environment; the
    streaming/tool-use wiring is believed correct against the `anthropic` 0.116.0 SDK's documented
    async `messages.stream` shape but is unverified against the live API.
11. **No dedicated dashboard UI panel for the LLM assistant** (M12, explicit scope decision —
    "API-first design" was a stated requirement) — `/llm/*` is fully functional but there is no
    chat widget in `dashboard/shell.py` yet; a natural follow-up if a UI is wanted later.
12. **No news/earnings data source exists anywhere in the repo** — CLAUDE.md's mention of
    "news summaries, earnings explainers" under LLM use is aspirational for a future data-source
    milestone; M12 does not summarize news or earnings because there is nothing to summarize
    (explicit scope exclusion, confirmed during the M12 design review, not an oversight).
13. **Calendar Spread only trades in backtest/research** (M14, explicit scope decision — see
    §11) — paper/live never populate `StrategyContext.other_expiries` today, since the
    live/paper data pipeline (`ChainService.nearest_expiry` → `ChainSnapshotJob`) only ever
    snapshots one expiry per underlying. The strategy degrades safely (never enters) rather than
    acting on an incomplete chain; wiring true near+far snapshot support into the M2 data layer
    and M8/M9 paper/live engines is separate, larger follow-up work.
14. **A shared test helper hardcodes its tradingsymbol format regardless of expiry**
    (`tests/unit/domain/conftest.py::make_contract` — `tradingsymbol=f"{underlying}25JUL
    {strike}{suffix}"`, ignoring the `expiry` argument). Harmless for every single-expiry test
    (M3–M13), but two same-strike different-expiry contracts built via this helper collide on
    the same tradingsymbol — since position/order tracking is keyed by tradingsymbol, this
    would silently net two calendar-spread legs against each other. Discovered and worked
    around locally (not fixed in the shared helper, given its wide blast radius across
    oms/live/data/risk/strategies tests) in `tests/unit/backtest/test_multi_expiry.py::
    _with_distinct_tradingsymbols`. A real Kite tradingsymbol always encodes the actual
    expiry, so this is purely a test-fixture gap, not a production one — worth fixing in the
    shared helper if more multi-expiry test scenarios show up.
15. **Adjustment rules (M14) are demonstrated, not battle-tested** — `AdjustmentRule`'s roll
    logic (`rules.evaluate_adjustment`) is unit- and strategy-level tested (breach detection,
    roll-target resolution, opt-in/disabled paths) but has never been exercised through a
    multi-tick backtest showing a roll actually happening mid-trade over time; the current tests
    construct the breach condition directly rather than letting the underlying move into it.
16. **The working tree carries a large body of pre-existing, uncommitted work that predates
    M16 and is untouched by it** (discovered during M16's own commit prep — `git status` showed
    ~90 modified/untracked files before M16 made any edit). New untracked strategies
    (`long_strangle.py`, `long_contrarian.py`, `long_skew.py`, `max_pain_reversion.py`,
    `jade_lizard.py`, `broken_wing_butterfly.py`), a new `runtime/rest_poller.py` +
    `runtime/fills.py`, service-management scripts (`scripts/kite_login.py`,
    `scripts/install_service.sh`/`start_dashboard.sh`/`stop_dashboard.sh`/
    `uninstall_service.sh`, `scripts/backtest_all_strategies.py`/`tune_long_strangle.py`/etc.),
    an Alembic migration (`0002_option_chain_eod_lot_size.py`), and modifications across
    `api/`, `config/`, `core/`, `dashboard/`, `data/`, `execution/`, `oms/`, `runtime/`,
    `strategies/` beyond what M16 touched. This matches prior-session memory (long_contrarian
    live, jade_lizard/broken_wing_butterfly parameter-sweep findings) — it looks like real,
    intentional in-progress work, not clutter. **M16 deliberately did not stage or commit any of
    it** — only the specific files listed in §17's "what changed" were added to M16's commit.
    Whoever resumes next should run `git status` before assuming a clean tree and decide
    separately whether/how to commit this work.

---

## 13. Next tasks

- Optional, smaller follow-ups (none blocking anything currently planned): structlog→LogSource
  bridge; persistent (`JSONJournalStore`-backed) audit trail for `LiveTradingGate`; a dashboard
  UI panel for the execution/gate status and/or an LLM chat widget; Redis-backed feature cache /
  experiment store / conversation store; wire the chain-snapshot scheduler for proprietary
  intraday history; verify `KiteBroker` and `ClaudeClient` against real Kite/Anthropic
  credentials once available; a news/earnings ingestion pipeline (would unlock the
  currently-out-of-scope LLM capabilities CLAUDE.md mentions); paper/live Calendar Spread
  support (needs the M2/M8/M9 multi-expiry data-pipeline work from §12 item 13); fix
  `make_contract`'s tradingsymbol format to encode expiry (§12 item 14).
- **Live trading go-live checklist (before ever setting `CEREMYN_TRADING_MODE=live` for
  real):** paper burn-in per the roadmap's own note, real Kite credentials configured, a real
  `execution.arming_secret` configured (not the empty default), and a deliberate, out-of-band
  decision to call `POST /execution/arm` — never automate that call.
- No milestone is currently in progress. Every milestone through M13, plus M12 and M14 (both
  landed after M13 in this session), is ✅ (see §2); the roadmap has no further numbered
  milestone defined yet — next steps are user-directed.
- Deferred architectural questions surfaced by a post-M17 cleanup audit (`PaperTradingEngine`'s
  fate, the `RuntimeOrchestrator`/WebSocket-streaming future, `ChainSnapshotJob` scheduling, and
  the 1-of-15 live-selectable-strategies gap) are recorded in `ARCHITECTURE_DECISIONS.md` rather
  than acted on — each needs a product decision, not a mechanical fix.

---

## 14. Commands

```bash
# Tests (unit)                     integration needs: docker compose up -d postgres redis
.venv/bin/pytest tests/unit -q
.venv/bin/pytest -q                                   # full (integration auto-skips w/o DB)
.venv/bin/pytest tests/unit/<pkg> --cov=ceremyn.<pkg> --cov-fail-under=95

# Quality gates (all must pass before commit)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/lint-imports

# Run the single app (dashboard at /dashboard/, Swagger at /docs)
.venv/bin/uvicorn ceremyn.api.main:app --reload

# Run with arming enabled (still needs TRADING_MODE=live + LIVE_TRADING_ENABLED=true + the
# right token via POST /execution/arm before any order would actually go live)
CEREMYN_EXECUTION__ARMING_SECRET=... .venv/bin/uvicorn ceremyn.api.main:app --reload
```

---

## 15. Workflow conventions (how this project has been built)

- **Milestone-gated**: one module per milestone (M0…). After each: tests + all gates green →
  commit → **STOP and wait for user approval** before the next.
- **Plan first for big work**: review the repo, present a design/plan (plan mode), get approval,
  then implement. Do not write code before architecture is approved on milestone-sized tasks.
  M12 and M14 both followed this exactly: repo review → design review (M12: two
  `AskUserQuestion` clarifications on watchlist persistence/LLM auth; M14: four, on Calendar
  Spread's paper/live scope, the generic Vertical Spread shape, whether to touch the 3
  pre-existing strategies, and dashboard integration depth — all four "recommended" options
  accepted) → plan-mode approval → implementation.
- **Do not modify completed modules** unless the task explicitly requires it. Exceptions so far:
  `api/app.py` (dashboard integration, then M13's `/execution` mount, then M12's `/llm` mount),
  M13's dashboard-port additions (`dashboard/backend.py`/`models.py`/`views.py`/`api.py` — a new
  `ExecutionSource` port + `ExecutionView` + `/api/execution` channel — explicitly requested as
  part of "reuse the Dashboard"), `config/settings.py` (new `ExecutionSettings`), `pyproject.toml`
  (new import-linter contracts), M12's single additive edit to `dashboard/permissions.py`
  (`Permission.USE_LLM`, granted to both existing roles — explicitly requested as part of
  "reuse the dashboard's bearer-token settings" for LLM auth), and M14's purely-additive touches
  to `strategies/base.py` (`other_expiries`, empty-default), `strategies/common.py` (+2 new
  functions, the old `premium_exit_reason` untouched), `strategies/registry.py` (+2 new
  accessors), `backtest/engine.py` (+`latest_chains` dict alongside the untouched
  `latest_chain`), and the same M13-established `dashboard.backend`/`models`/`api` +
  `api/runtime.py` port-addition pattern reused for a new `StrategySource` — every M14 diff to
  a completed module is additive (new field/function/dict with a safe default), never a
  behavior change to existing code paths, confirmed by the pre-existing test suites for those
  modules passing unmodified. When gaps surface in already-completed modules that block a new
  milestone safely (e.g. `HeartbeatMonitor` had no public state reader), prefer a
  composition-root-only subclass adding a pure accessor (see `core/instrumentation.py`) over
  editing the completed module directly.
- **Commits**: milestone commits `M# Name`; otherwise Conventional Commits (`feat(ui): …`).
  End messages with `Co-Authored-By: Claude <model> <noreply@anthropic.com>` naming whichever
  model authored the commit (varies by session — check recent git log rather than assuming one).
  Branch off `main` only if asked; this project commits milestones directly to `main`.
- `CLAUDE.md` and `AGENTS.md` are the same conventions in two files (tooling reads both).

## 16. Git history (recent)

`M16 Domain & Instrument Generalization` is this commit, immediately following `ef46d78`
(`M15 Trading Runtime & Production Readiness`) below — milestones landed out of numeric order
this session (M13 → M12 → M14 → M15 → M16).

```
ef46d78 M15 Trading Runtime & Production Readiness
947a655 M14 Options Strategy Library
f67a2ac M12 LLM Assistant
7f63e25 M13 Broker Integration
0528a27 feat(api): wire live/OMS/paper/risk/feature/research engines into the composition root
b5db7be feat(ui): professional trading dashboard      07a3da8 M11 Dashboard & Observability
5b1e118 M10 Order Management System                    0c03927 M9 Live Market Data Engine
d698d3d M8 Paper Trading                               b7d51cd M7 Feature Store
7325945 M6 Research Lab                                4447c7f M5 Institutional Backtesting Engine
cca3751 M4 Risk Engine                                 caa6c75 M3.5 Architecture Hardening
7fd4796 M2 Data layer   e2b0b92 M1 Domain+core   6255d9c M0 Scaffolding
```

---

## 17. Multi-Asset Platform Migration (M16+) — how it works and what's next

The user requested a migration from an options-only platform to a multi-asset one (equities,
futures, ETFs, options now; commodities/currency futures scaffolded for later), plus three
trading modes (Research / Assisted / Automated). This is far bigger than any single milestone,
so it's tracked as its own roadmap, M16 onward, each milestone design-reviewed and approved the
same way M12–M15 were.

**Roadmap:**

| # | Milestone | Depends on | Scope |
|---|---|---|---|
| M16 | Domain & Instrument Generalization | — | ✅ this commit |
| M17 | Data Layer Generalization | M16 | `MarketDataProvider` protocol; generic OHLCV ingest for equities/futures reusing `CandleRepository`; instrument repository widened; asset-class-aware universe config |
| M18 | Strategy Engine: bar-driven path | M16, M17 | Parallel `on_bar`/`BarEvent` hook for equity/futures strategies alongside the untouched `on_chain` path |
| M19 | Risk & Backtest asset-awareness | M16 | Asset-class-dispatched margin/exposure math (currently a documented placeholder — see below) |
| M20 | Trading Modes: Assisted & Automated | M16, M19 | New orthogonal automation axis (not a 4th `TradingMode`); OMS approval-queue; per-strategy permissions/limits + audit log |
| M21 | Dashboard multi-asset UI | M16–M19 | Make the ~6 option-specific dashboard fields conditional; generic instrument terminology |
| M22 | AI Assistant: cross-asset trade recommendations | M16–M20 | Non-executing `propose_trade_idea` tool, reusing the existing `Assistant` tool-loop |

**M16 (this commit) — what changed:**
- `domain/enums.py`: additive `AssetClass` enum (`EQUITY`/`FUTURES`/`ETF`/`OPTION`/`COMMODITY`/
  `CURRENCY_FUTURES` — the last two scaffolded now, zero provider/strategy work behind them yet).
- `domain/instruments.py`: `underlying`/`expiry`/`lot_size` promoted from `OptionContract` to
  the base `Instrument` (`expiry: date | None = None`, `lot_size` defaults to 1); each subclass
  sets `asset_class: ClassVar[AssetClass]`. Three new instrument types:
  `EquityInstrument`/`ETFInstrument` (thin, `lot_size=1` default), `FutureContract` (`expiry`/
  `lot_size` required, same shape as `OptionContract` minus `strike`/`option_type`).
- `Position.contract`, `Order.contract`, `SignalLeg.contract`, `Trade.contract`,
  `ClosedTrade.contract` (`backtest/ledger.py`), `_OpenLot.contract` (`backtest/portfolio.py`):
  all widened from `OptionContract` to the generic `Instrument`. `OMSPortfolio`/
  `ExecutionSimulator`/OMS as a whole needed **zero changes** — confirmed during design review
  they only ever touch `.contract.tradingsymbol`/`.lot_size`, both on the base class now.
- **A real, necessary correction discovered mid-implementation** (not in the original design
  doc, which under-scoped this): several places read option-only fields (`.strike`,
  `.option_type`) directly off a `Position`/`SignalLeg`'s now-generic `.contract` —
  `strategies/common.py::net_close_cost`, `strategies/rules.py::evaluate_adjustment`,
  `strategies/calendar_spread.py` (two spots), and `risk/context.py` (`signal_notional`,
  `signal_margin_required`, `projected_exposure`). Each got a minimal
  `isinstance(x.contract, OptionContract)` guard, behaviorally inert today (every position/leg
  produced by any of the 9 registered strategies is still an `OptionContract`) but required for
  `mypy --strict` to pass now that the field type is `Instrument`. Documented inline at each site
  as a placeholder for M19's real asset-aware dispatch, not a design decision.
- **Margin/notional math is explicitly a placeholder for non-options**, not yet real: strike-based
  formulas (`backtest/portfolio.py::mark_to_market`/`_margin_used`,
  `risk/context.py::signal_notional`/`signal_margin_required`/`projected_exposure`) fall back to
  the position's last-known price (backtest) or contribute zero (risk context, which has no price
  feed available) for a non-option instrument. Unreachable in M16 (no equity/futures strategy
  exists yet), correct for every option path (byte-identical formulas), but **not a real equity/
  futures margin model** — that's M19's job.
- `risk/context.py::days_to_expiry`: a large sentinel (`_NO_EXPIRY_DAYS = 10**6`) is returned for
  an instrument with no expiry, so `ExpiryRestrictionsRule`'s threshold checks become a
  correctness-preserving no-op for non-expiring instruments without threading `int | None`
  through `risk/rules/time.py`.
- Test suite: 947 passed, 0 failed, 4 skipped (DB-gated integration, unchanged) — verified with
  the pre-existing uncommitted WIP stashed out, i.e. HEAD + M16 only, not the combined tree. New
  tests in `tests/unit/domain/test_instruments.py` (new instrument types + `asset_class` per
  type), `test_positions.py`/`test_orders.py`/`test_signals.py` (a `Position`/`Order` holding a
  non-option `Instrument`; an all-equity `Signal` with `expiry=None` on every leg passing
  `_derive_scope` unmodified).
- **A second, real correction discovered during commit prep**: `risk/context.py` and
  `backtest/portfolio.py` already carried unrelated, pre-existing *uncommitted* changes (a
  margin-ratio-settings feature — `signal_margin_required`, `RiskMarginSettings.
  short_option_margin_ratio`/`long_option_margin_ratio` — and a daily-P&L-baseline-reset feature,
  respectively) that predate M16 and were never part of it. M16's edits had been layered on top
  of that WIP rather than on HEAD, so the initial staged diff would have smuggled unrelated,
  half-finished, cross-file-dependent work into this commit. Both files were reconstructed from
  `git show HEAD:<file>` with *only* M16's own edits re-applied, verified via `diff` against
  HEAD to confirm the diff contains nothing else, then the full quality gate was re-run with
  every other pre-existing uncommitted file `git stash`-ed out — see the isolation note above.

**Explicitly out of scope for M16** (each is a later milestone): no new data provider or
repository change (still options-only — M17), no bar-driven strategy path (M18), no real
asset-aware margin model (M19), no new trading mode (M20), no dashboard/UI change (M21), no LLM
capability change (M22).
