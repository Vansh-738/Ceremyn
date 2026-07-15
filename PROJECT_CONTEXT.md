# AlphaQuant — Project Context

> Single source of truth for resuming work with minimal context loss. Last updated after
> M13 (Broker Integration) and the runtime-wiring commit (`0528a27`) that preceded it. Pair
> this with `CLAUDE.md` (enforced conventions) and `README.md` (setup + roadmap).

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
| M12 | LLM assistant (reports, reviews, explanations) | ⛔ not started |
| M13 | Broker integration: real `KiteBroker`, `SimulatedBroker` fallback, triple-gate arming (`LiveTradingGate` + `GatedBrokerAdapter`), `/execution` admin API | ✅ |

**Quality (all green):** 696 passed / 4 skipped (700 collected; the 4 skips are DB-gated
integration tests). `ruff`, `ruff format --check`, `mypy --strict` (176 files), `lint-imports`
(17 contracts) all clean. Overall coverage 95.55% (CI gate is 85%); every new M13 package is
at or near 100% individually (see §10 for the one intentional exception).

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
live/OMS/paper/risk/feature/research engines, and (since M13) the broker layer: `null_broker`,
`simulated_broker`, `kite_broker`, `live_trading_gate`, `gated_broker`. Every engine is a
process-lifetime singleton, resolved on first use, never touching Postgres or Kite unless that
specific engine actually needs to (`kite_broker`/`kite_provider` raise without credentials —
deliberately never touched by default; see `execution.gated_broker.GatedBrokerAdapter`'s lazy
`live_factory`). `api/runtime.py` adapts the container's engines into the dashboard's read-only
ports; `api/app.py::create_app()` wires both by default and mounts `/execution` alongside
`/dashboard`.

**Import-linter contracts (17, all KEPT)** — the load-bearing ones:
- `domain` is independent and cannot import infrastructure.
- `strategies` cannot import `execution`/`broker`.
- `llm` cannot import `execution`/`risk`.
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
3. **The LLM never decides BUY/SELL** (import-linter enforced).
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
  (gate #3 status only, read-only).
- **`api/`** — `app.py` (`create_app` — the single application: health/system + Swagger + mounts
  the dashboard at `/dashboard` and, when a container is wired, the admin router at
  `/execution`), `main.py` (`app = create_app()`; uvicorn entry), `runtime.py`
  (`build_dashboard_sources(container)` — six-plus-one composition-edge adapters translating
  `Container` engines into the dashboard's read ports, including `_ExecutionSourceAdapter`),
  `execution.py` (`build_execution_router` — `POST /execution/arm`, `POST /execution/disarm`,
  `GET /execution/status`; structurally separate from `/dashboard`, never imported by it).
- **`broker/`** — `NullBrokerAdapter` (raises on submit; used as a placeholder/test double),
  `SimulatedBroker` (the real safe-fallback broker OMS actually uses whenever ungated — reuses
  `paper.broker.PaperBroker` + `oms.positions.OMSPortfolio`).
- **`execution/`** — `kite_broker.py` (`KiteBroker`, real Kite Connect order placement), `gate.py`
  (`LiveTradingGate`, `GateEvent`), `gated_broker.py` (`GatedBrokerAdapter`). See §5.
- **`llm/`** — still a placeholder package (boundary anchor only; M12, not started).

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

## 10. Outstanding issues / known gaps

1. **Logs source is a stub** — `LogSource` returns injected `LogRow`s; there is no structlog→ring-
   buffer bridge yet. Logs page renders whatever a log source provides (empty by default).
2. **2026 NSE holidays are PROVISIONAL** (`core/nse_holidays.py`) — verify against the official
   circular before relying on 2026 calendar/expiry math.
3. **Integration tests require Postgres** (Docker not installed locally) — 4 skips locally; they
   run in CI (`TEST_DATABASE_URL`).
4. **No secrets configured** — Kite/Anthropic keys and `execution.arming_secret` are all empty in
   dev; live data, LLM, and arming all need real values to do anything beyond their safe defaults
   (empty `arming_secret` means `/execution/arm` always 403s — arming is refused, not silently
   permitted, when unconfigured).
5. `create_dashboard_app` still exists (test helper only). Production uses the single app.
6. **`core/container.py`'s data-layer providers (`_db`, `instrument_repository`,
   `chain_service`, `kite_provider`, etc.) stay below the ~95% per-package coverage convention**
   in isolation — pre-existing, requires Postgres/Kite creds to exercise, unrelated to M13 (all
   M13-added providers are fully covered; see `test_kite_broker_is_never_touched_without_
   credentials` / `test_kite_broker_constructs_when_credentials_are_present`).
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

---

## 11. Next tasks

- **M12 — LLM assistant** (`src/alphaquant/llm/`): Claude client + use-cases (news summary,
  earnings/trade explainers, strategy review, report generation). Import-linter already forbids
  `llm → execution/risk`; add the client behind a protocol; reuse `research`/`journal` data as
  inputs. Analysis/explanation only. (Next milestone in roadmap order.)
- Optional, smaller follow-ups (none blocking M12): structlog→LogSource bridge; persistent
  (`JSONJournalStore`-backed) audit trail for `LiveTradingGate`; a dashboard UI panel for the
  execution/gate status; Redis-backed feature cache / experiment store; wire the chain-snapshot
  scheduler for proprietary intraday history; verify `KiteBroker` against a real Kite sandbox
  account once one is available.
- **Live trading go-live checklist (before ever setting `ALPHAQUANT_TRADING_MODE=live` for
  real):** paper burn-in per the roadmap's own note, real Kite credentials configured, a real
  `execution.arming_secret` configured (not the empty default), and a deliberate, out-of-band
  decision to call `POST /execution/arm` — never automate that call.

---

## 12. Commands

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

## 13. Workflow conventions (how this project has been built)

- **Milestone-gated**: one module per milestone (M0…). After each: tests + all gates green →
  commit → **STOP and wait for user approval** before the next.
- **Plan first for big work**: review the repo, present a design/plan (plan mode), get approval,
  then implement. Do not write code before architecture is approved on milestone-sized tasks.
- **Do not modify completed modules** unless the task explicitly requires it. Exceptions so far:
  `api/app.py` (dashboard integration), and M13's dashboard-port additions
  (`dashboard/backend.py`/`models.py`/`views.py`/`api.py` — a new `ExecutionSource` port +
  `ExecutionView` + `/api/execution` channel — explicitly requested as part of "reuse the
  Dashboard"), `config/settings.py` (new `ExecutionSettings`), and
  `pyproject.toml` (two new import-linter contracts). When gaps surface in already-completed
  modules that block a new milestone safely (e.g. `HeartbeatMonitor` had no public state reader),
  prefer a composition-root-only subclass adding a pure accessor (see `core/instrumentation.py`)
  over editing the completed module directly.
- **Commits**: milestone commits `M# Name`; otherwise Conventional Commits (`feat(ui): …`).
  End messages with `Co-Authored-By: Claude <model> <noreply@anthropic.com>` naming whichever
  model authored the commit (varies by session — check recent git log rather than assuming one).
  Branch off `main` only if asked; this project commits milestones directly to `main`.
- `CLAUDE.md` and `AGENTS.md` are the same conventions in two files (tooling reads both).

## 14. Git history (recent)

`M13 Broker Integration` is this commit, immediately following `0528a27` below.

```
0528a27 feat(api): wire live/OMS/paper/risk/feature/research engines into the composition root
b5db7be feat(ui): professional trading dashboard      07a3da8 M11 Dashboard & Observability
5b1e118 M10 Order Management System                    0c03927 M9 Live Market Data Engine
d698d3d M8 Paper Trading                               b7d51cd M7 Feature Store
7325945 M6 Research Lab                                4447c7f M5 Institutional Backtesting Engine
cca3751 M4 Risk Engine                                 caa6c75 M3.5 Architecture Hardening
7fd4796 M2 Data layer   e2b0b92 M1 Domain+core   6255d9c M0 Scaffolding
```
