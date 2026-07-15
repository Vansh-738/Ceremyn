# AlphaQuant — Project Context

> Single source of truth for resuming work with minimal context loss. Last updated after
> M12 (LLM Assistant), which followed M13 (Broker Integration) and the runtime-wiring commit
> (`0528a27`) that preceded it — milestones landed out of numeric order; M13 was built first,
> M12 second. Pair this with `CLAUDE.md` (enforced conventions) and `README.md` (setup +
> roadmap).

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

**Quality (all green):** 811 passed, 0 failed (unit suite; DB-gated integration tests skip
locally, run in CI). `ruff`, `ruff format --check`, `mypy --strict` (188 files), `lint-imports`
(17 contracts, all KEPT) all clean. Overall coverage ~96.1% (CI gate is 85%); every M12 file is
at 100% individually — see §11 for the (pre-existing, unrelated) DB-gated exceptions.

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
adapts the container's engines into the dashboard's read-only ports; `api/llm_runtime.py` adapts
them (plus the already-built `DashboardService`) into the LLM assistant's read-only ports;
`api/app.py::create_app()` wires all three and mounts `/execution` and `/llm` alongside
`/dashboard`, each a structurally separate router.

**Import-linter contracts (17, all KEPT)** — the load-bearing ones:
- `domain` is independent and cannot import infrastructure.
- `strategies` cannot import `execution`/`broker`.
- **`llm` cannot import `execution`/`risk`** — and because import-linter's `ForbiddenContract`
  checks transitively, this already forbids every package that itself reaches `risk`:
  `oms`, `paper`, `live`, `research`, `backtest`, `dashboard.backend` (confirmed by direct grep
  of each package's imports during the M12 design review, not assumed). `llm/`'s only
  `alphaquant.*` imports are `domain`, `core`, `config`, `features`, `strategies`, and
  `dashboard.models` (pure DTOs) — verified two ways: the transitive contract above, and a
  direct static-import test (`tests/unit/architecture/test_boundaries.py::
  test_llm_package_never_imports_execution_adjacent_packages`) that AST-parses every file under
  `src/alphaquant/llm/` and fails with a precise file/line on any forbidden import, rather than
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
   `ALPHAQUANT_TRADING_MODE=live`, (2) `ALPHAQUANT_LIVE_TRADING_ENABLED=true` — both via
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
   frozen DTO; there is no "run arbitrary code" or "call arbitrary AlphaQuant method" tool, so
   Claude's tool-use can only ever invoke this fixed, read-only set. (The one piece of writable
   state — watchlist symbols — is exactly as consequential as conversation history: session-
   scoped, in-memory, never touching a broker, order, or position.); (c) **`/llm` and
   `/execution` are separate FastAPI routers** — `api/llm.py` never references `api/execution.py`
   or `LiveTradingGate`; the only object shared between them is the read-only `Container`.
4. **Identical strategy/risk code across backtest, paper, and live** — the runners drive the
   same interfaces; never fork strategy logic per mode.

---

## 6. File structure (package-by-package)

`src/alphaquant/` (LOC approximate, source only):

- **`config/`** (209) — `settings.py` (`Settings`, nested `DB/Redis/Kite/Anthropic/Data/Risk`
  settings, `env_prefix="ALPHAQUANT_"`, `__` nesting), `modes.py` (`TradingMode`). `get_settings()`
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
- **`domain/`** (705) — pure models: `Instrument`/`OptionContract`, `Quote`/`Candle`,
  `Greeks`, `OptionChainSnapshot` (+`pcr`, OI totals, `atm_strike`), `Signal`/`SignalLeg`,
  `Order` (+ status state machine `transition_to`; `CREATED→SUBMITTED` is impossible — must pass
  risk), `Fill`, `Position` (weighted-avg-cost accounting), `Trade`, `PortfolioSnapshot`
  (+greeks/exposure/kill-switch), `StrategyDefinition`, enums.
- **`data/`** (1164) — `providers/bhavcopy.py` (NSE UDiFF download+parse), `providers/kite.py`
  (market data only), `repositories/` (SQLAlchemy async: instruments/candles/chains) + Alembic,
  `services/pricing.py` (Black-Scholes price/greeks, Brent IV), `services/chain_analytics.py`
  (`iv_rank`, `iv_percentile`, `max_pain`, `atm_iv`, enrich), `services/ingest.py`,
  `services/snapshots.py` (`ChainService`, `ChainSnapshotJob`).
- **`strategies/`** (565) — `base.py` (`Strategy` ABC + `StrategyContext` + `emit`), `registry.py`
  (`register`, `create`, `available_types`), `common.py` (delta selection, exits), 3 built-ins:
  `short_strangle`, `iron_condor`, `expiry_day_theta`.
- **`risk/`** (1139) — `engine.py` (`RiskEngine.evaluate/validate(portfolio, signal) →
  RiskDecision`), rule pipeline (`rules/`: drawdown, event, exposure, greeks, liquidity, margin,
  position, time, volatility), `registry.py`, `context.py`, `models.py`.
- **`backtest/`** (1463) — `runner.py` (`BacktestRunner.run(events) → BacktestReport`), `engine.py`
  (event-driven), `simulator.py` (`ExecutionSimulator`: market/limit/stop, partial fills),
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
  (gate #3 status only, read-only), and (M12) `permissions.py`'s `Permission.USE_LLM` (granted
  to both `Role.VIEWER` and `Role.ADMIN` — reused as-is by `/llm`'s auth, no new auth surface).
- **`api/`** — `app.py` (`create_app` — the single application: health/system + Swagger + mounts
  the dashboard at `/dashboard` and, when a container is wired, the admin router at
  `/execution` and the LLM assistant at `/llm`), `main.py` (`app = create_app()`; uvicorn entry),
  `runtime.py` (`build_dashboard_sources(container)` — composition-edge adapters translating
  `Container` engines into the dashboard's read ports, including `_ExecutionSourceAdapter`),
  `execution.py` (`build_execution_router` — `POST /execution/arm`, `POST /execution/disarm`,
  `GET /execution/status`; structurally separate from `/dashboard`, never imported by it),
  `llm_runtime.py` (M12 — `_ExperimentDetailAdapter`, `_RecapAdapter`; `build_assistant(container,
  dashboard_service) → Assistant`, wiring `container.llm_client` as a **lazy factory**, never
  touched at mount time), `llm.py` (M12 — `build_llm_router`; SSE endpoints, structurally
  separate from both `/dashboard` and `/execution`). See §10 for the full M12 write-up.
- **`broker/`** — `NullBrokerAdapter` (raises on submit; used as a placeholder/test double),
  `SimulatedBroker` (the real safe-fallback broker OMS actually uses whenever ungated — reuses
  `paper.broker.PaperBroker` + `oms.positions.OMSPortfolio`).
- **`execution/`** — `kite_broker.py` (`KiteBroker`, real Kite Connect order placement), `gate.py`
  (`LiveTradingGate`, `GateEvent`), `gated_broker.py` (`GatedBrokerAdapter`). See §5.
- **`llm/`** (M12) — `client.py` (`ClaudeClient`, thin Anthropic SDK wrapper, `from_settings()`),
  `providers.py` (structural Protocols: `DashboardReader` — duck-typed by the real
  `DashboardService`, `llm` never imports `alphaquant.dashboard`; `ExperimentDetailReader`,
  `RecapReader`), `snapshots.py` (`ExperimentDetailBrief`, `RecapBrief`, `StrategyCatalogEntry` —
  new frozen DTOs for the two data needs nothing else in the platform exposed), `tools.py` (16
  read-only tool definitions + dispatch table + `ToolResult(data, source)`), `assistant.py`
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
- Config only via `alphaquant.config.get_settings()`; never read `os.environ` elsewhere.
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
  → list[Signal]`.
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
  — raises `LLMProviderError` without `ALPHAQUANT_ANTHROPIC__API_KEY`, never touched until a
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

Run: `.venv/bin/uvicorn alphaquant.api.main:app --reload` → open `http://127.0.0.1:8000/dashboard/`.
Arm/disarm (needs `ALPHAQUANT_EXECUTION__ARMING_SECRET` set): `curl -X POST
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
  `alphaquant.dashboard` or `alphaquant.oms`/`alphaquant.paper`/etc. to satisfy them. At the
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
  verified against a running `uvicorn` process with no `ALPHAQUANT_ANTHROPIC__API_KEY`
  configured: `/llm/watchlist/*` works end-to-end; `/llm/chat` and `/llm/reports/daily-recap`
  stream real, live tool-call frames (pre-fetched from the real `Container` engines) and then a
  clean `{"type": "error", "message": "ALPHAQUANT_ANTHROPIC__API_KEY is not configured"}` SSE
  frame — never a crash, and `/dashboard`/`/execution`/`/health` stay unaffected throughout.
- **EventBus**: after any report/recap, the assistant publishes `AssistantReportGenerated`
  (`llm/events.py`, pure pydantic) onto `container.event_bus` — makes LLM activity observable
  (e.g. a future "recent AI reports" dashboard panel) without inventing new auto-triggering
  behavior.

Run: same single app as the dashboard (`.venv/bin/uvicorn alphaquant.api.main:app --reload`);
set `ALPHAQUANT_ANTHROPIC__API_KEY=...` for `/llm/chat` etc. to actually complete (unset, they
still mount and stream a clean error frame). Watchlist example: `curl -X POST
127.0.0.1:8000/llm/watchlist/s1 -d '{"action":"add","symbol":"NIFTY"}'`.

---

## 11. Outstanding issues / known gaps

1. **Logs source is a stub** — `LogSource` returns injected `LogRow`s; there is no structlog→ring-
   buffer bridge yet. Logs page renders whatever a log source provides (empty by default).
2. **2026 NSE holidays are PROVISIONAL** (`core/nse_holidays.py`) — verify against the official
   circular before relying on 2026 calendar/expiry math.
3. **Integration tests require Postgres** (Docker not installed locally) — 4 skips locally; they
   run in CI (`TEST_DATABASE_URL`).
4. **No secrets configured** — Kite/Anthropic keys and `execution.arming_secret` are all empty in
   dev; live data, LLM, and arming all need real values to do anything beyond their safe defaults
   (empty `arming_secret` means `/execution/arm` always 403s, and no `ALPHAQUANT_ANTHROPIC__
   API_KEY` means `/llm/chat` etc. always stream a clean SSE error frame — both refused, not
   silently permitted/faked, when unconfigured; manually verified for `/llm` — see §10).
5. `create_dashboard_app` still exists (test helper only). Production uses the single app.
6. **`core/container.py`'s data-layer providers (`_db`, `instrument_repository`,
   `chain_service`, `kite_provider`, etc.) stay below the ~95% per-package coverage convention**
   in isolation — pre-existing, requires Postgres/Kite creds to exercise, unrelated to M13/M12
   (every M13- and M12-added provider is fully covered; see `test_kite_broker_is_never_touched_
   without_credentials` / `test_kite_broker_constructs_when_credentials_are_present` and the
   equivalent `test_llm_client_is_never_touched_without_credentials`-style tests in
   `tests/unit/core/test_container.py`).
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

---

## 12. Next tasks

- Optional, smaller follow-ups (none blocking anything currently planned): structlog→LogSource
  bridge; persistent (`JSONJournalStore`-backed) audit trail for `LiveTradingGate`; a dashboard
  UI panel for the execution/gate status and/or an LLM chat widget; Redis-backed feature cache /
  experiment store / conversation store; wire the chain-snapshot scheduler for proprietary
  intraday history; verify `KiteBroker` and `ClaudeClient` against real Kite/Anthropic
  credentials once available; a news/earnings ingestion pipeline (would unlock the
  currently-out-of-scope LLM capabilities CLAUDE.md mentions).
- **Live trading go-live checklist (before ever setting `ALPHAQUANT_TRADING_MODE=live` for
  real):** paper burn-in per the roadmap's own note, real Kite credentials configured, a real
  `execution.arming_secret` configured (not the empty default), and a deliberate, out-of-band
  decision to call `POST /execution/arm` — never automate that call.
- No milestone is currently in progress. Every milestone through M13, plus M12 (landed after
  M13 in this session), is ✅ (see §2); the roadmap has no further numbered milestone defined
  yet — next steps are user-directed.

---

## 13. Commands

```bash
# Tests (unit)                     integration needs: docker compose up -d postgres redis
.venv/bin/pytest tests/unit -q
.venv/bin/pytest -q                                   # full (integration auto-skips w/o DB)
.venv/bin/pytest tests/unit/<pkg> --cov=alphaquant.<pkg> --cov-fail-under=95

# Quality gates (all must pass before commit)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/lint-imports

# Run the single app (dashboard at /dashboard/, Swagger at /docs)
.venv/bin/uvicorn alphaquant.api.main:app --reload

# Run with arming enabled (still needs TRADING_MODE=live + LIVE_TRADING_ENABLED=true + the
# right token via POST /execution/arm before any order would actually go live)
ALPHAQUANT_EXECUTION__ARMING_SECRET=... .venv/bin/uvicorn alphaquant.api.main:app --reload
```

---

## 14. Workflow conventions (how this project has been built)

- **Milestone-gated**: one module per milestone (M0…). After each: tests + all gates green →
  commit → **STOP and wait for user approval** before the next.
- **Plan first for big work**: review the repo, present a design/plan (plan mode), get approval,
  then implement. Do not write code before architecture is approved on milestone-sized tasks.
  M12 followed this exactly: repo review → design review (with two `AskUserQuestion`
  clarifications: watchlist persistence, LLM API auth) → plan-mode approval → implementation.
- **Do not modify completed modules** unless the task explicitly requires it. Exceptions so far:
  `api/app.py` (dashboard integration, then M13's `/execution` mount, then M12's `/llm` mount),
  M13's dashboard-port additions (`dashboard/backend.py`/`models.py`/`views.py`/`api.py` — a new
  `ExecutionSource` port + `ExecutionView` + `/api/execution` channel — explicitly requested as
  part of "reuse the Dashboard"), `config/settings.py` (new `ExecutionSettings`), `pyproject.toml`
  (new import-linter contracts), and M12's single additive edit to `dashboard/permissions.py`
  (`Permission.USE_LLM`, granted to both existing roles — explicitly requested as part of
  "reuse the dashboard's bearer-token settings" for LLM auth). When gaps surface in already-
  completed modules that block a new milestone safely (e.g. `HeartbeatMonitor` had no public
  state reader), prefer a composition-root-only subclass adding a pure accessor (see
  `core/instrumentation.py`) over editing the completed module directly.
- **Commits**: milestone commits `M# Name`; otherwise Conventional Commits (`feat(ui): …`).
  End messages with `Co-Authored-By: Claude <model> <noreply@anthropic.com>` naming whichever
  model authored the commit (varies by session — check recent git log rather than assuming one).
  Branch off `main` only if asked; this project commits milestones directly to `main`.
- `CLAUDE.md` and `AGENTS.md` are the same conventions in two files (tooling reads both).

## 15. Git history (recent)

`M12 LLM Assistant` is this commit, immediately following `7f63e25` (`M13 Broker Integration`)
below — milestones landed out of numeric order in this session (M13 first, M12 second).

```
7f63e25 M13 Broker Integration
0528a27 feat(api): wire live/OMS/paper/risk/feature/research engines into the composition root
b5db7be feat(ui): professional trading dashboard      07a3da8 M11 Dashboard & Observability
5b1e118 M10 Order Management System                    0c03927 M9 Live Market Data Engine
d698d3d M8 Paper Trading                               b7d51cd M7 Feature Store
7325945 M6 Research Lab                                4447c7f M5 Institutional Backtesting Engine
cca3751 M4 Risk Engine                                 caa6c75 M3.5 Architecture Hardening
7fd4796 M2 Data layer   e2b0b92 M1 Domain+core   6255d9c M0 Scaffolding
```
