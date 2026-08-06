# Ceremyn

**Ceremyn is an AI-powered Market Intelligence Platform.** It continuously analyzes
markets, surfaces trading opportunities, explains the reasoning behind them, and ranks
them by expected edge — with execution as one consumer of that intelligence, not the
platform's sole purpose.

Ceremyn is not a gambling bot and not a black-box prediction engine. Every opportunity
it surfaces is backed by an explainable, backtested, risk-managed process. **v1 scope**
is institutional-grade options trading research for Indian markets (NIFTY & BANKNIFTY
options): discovering, validating, and operating statistically profitable strategies —
with risk management and reliability as first-class concerns. Broader market coverage
is the platform's long-term direction (see `ARCHITECTURE_DECISIONS.md`), built out
incrementally on top of this same risk-first foundation.

## Safety model

**Live trading is disabled by default.** A real order can only ever be placed when
three independent gates all pass:

| Gate | What | Where |
|------|------|-------|
| 1 | `CEREMYN_TRADING_MODE=live` | environment / `.env` |
| 2 | `CEREMYN_LIVE_TRADING_ENABLED=true` | environment / `.env` |
| 3 | Runtime arming token submitted via the API after startup | never stored in config |

If any gate is missing, the platform degrades to **paper** mode. Additional invariants:

- Every order passes through the **Risk Engine** — there is no strategy→broker code path.
- The **LLM (Claude) never decides BUY or SELL.** It only summarizes news, explains
  earnings and trades, reviews strategies, and generates reports. This is enforced
  architecturally (the `llm` module cannot import execution code; checked in CI).
- Strategies run **identical code** in backtesting, paper trading, and live trading.
- Every strategy must pass a paper-trading burn-in before it is eligible for live.

## Operating modes

- **research** — data ingestion, option-chain analytics, backtesting, reports.
- **paper** — live market data, simulated fills, full risk engine, trade journal.
- **live** — real orders via Zerodha Kite Connect, behind the three gates above.

Set via `CEREMYN_TRADING_MODE` (default: `research`).

## Quickstart

```bash
# 1. Configure
cp .env.example .env        # then fill in credentials

# 2. Infrastructure
docker compose up -d postgres redis

# 3. Python environment (3.12)
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install --no-deps -e .

# 4. Run the API
.venv/bin/uvicorn ceremyn.api.main:app --reload
# http://127.0.0.1:8000/health          -> {"status": "ok"}
# http://127.0.0.1:8000/system/status   -> mode & gate status
```

Or run everything in Docker: `docker compose up --build`.

**Running unattended (macOS):** the two commands above only run in your current
terminal/foreground session and won't survive a reboot or crash. For a paper-trading
setup you want left running, use `scripts/install_service.sh` instead — it installs a
macOS LaunchAgent that starts the dashboard on login and restarts it automatically if
it ever crashes. Remove it with `scripts/uninstall_service.sh`. Once installed, manage
it via `launchctl` (or the uninstall script), not `scripts/stop_dashboard.sh` — that
script talks to the process directly and launchd would just restart it underneath you.

## Development

```bash
.venv/bin/pytest tests/unit -q          # unit tests
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy                          # strict type-checking
.venv/bin/lint-imports                  # architecture contracts
```

Integration tests need the Docker services: `pytest tests/integration -m integration`.

## Architecture

Clean architecture with a src layout — see [CLAUDE.md](CLAUDE.md) for the full
conventions and dependency rules.

```
src/ceremyn/
├── config/      settings (pydantic-settings), trading-mode model
├── core/        logging, exceptions, event bus, NSE market calendar, DI container
├── domain/      pure entities: Instrument, MarketSnapshot, OptionChain, Greeks, Signal, Order, ...
├── data/        providers (Kite, NSE bhavcopy), repositories, analytics services
│                (greeks, IV, PCR, OI, IV rank, max pain)
├── strategies/  strategy engine: Strategy ABC, registry, built-in strategies
├── patterns/    read-only market intelligence: Pattern detection (candlestick, via
│                TA-Lib) + historical hit-rate study -- no path to execution/risk/OMS
├── risk/        pre-trade rule pipeline, portfolio-greek limits, kill switch
├── backtest/    event-driven backtester, Indian cost model, performance metrics
├── execution/   broker protocol, paper broker, Kite broker (gated), OMS
├── journal/     trade journal and performance analytics
├── llm/         Claude-powered analysis (reports, reviews, explanations only)
├── api/         FastAPI routers and schemas
└── dashboard/   FastAPI-served Plotly dashboards
```

## Roadmap

| Milestone | Scope | Status |
|-----------|-------|--------|
| M0 | Scaffolding: config, logging, Docker, CI | ✅ |
| M1 | Domain models + core (market calendar, events, container) | ✅ |
| M2 | Data layer: bhavcopy ingest, Kite provider, greeks/IV/PCR analytics | ✅ |
| M3 | Strategy engine + built-in strategies (+ M3.5 architecture hardening) | ✅ |
| M4 | Risk engine + kill switch | ✅ |
| M5 | Backtester + Indian cost model + metrics | ✅ |
| M6 | Research Lab: experiments, optimization, walk-forward, cross-validation, leaderboard, comparison, reports | ✅ |
| M7 | Feature Store: 19 cached, versioned, deterministic market features + engine/registry/cache/validation | ✅ |
| M8 | Paper trading: real-time engine, paper broker (queue + latency), OMS, journal, monitor, reconciliation | ✅ |
| M9 | Live Market Data Engine (streaming, heartbeat, reconnect, snapshots) | ✅ |
| M10 | Order Management System (state machine, broker adapters, retries, idempotency, reconciliation) | ✅ |
| M11 | Dashboard & Observability: read-only API + WebSocket, views, metrics, alerts, system health | ✅ |
| M12 | LLM assistant (reports, reviews, explanations) | — |
| M13 | Live trading (triple-gated) | — |

## Disclaimer

This software is a research tool. Nothing it produces is investment advice.
Options trading involves substantial risk of loss.
