# AlphaQuant

An institutional-grade, AI-assisted **options trading research platform** for Indian
markets (NIFTY & BANKNIFTY options in v1).

AlphaQuant is not a gambling bot and not a market-prediction AI. It is a quantitative
research platform for discovering, validating, and operating statistically profitable
options strategies — with risk management and reliability as first-class concerns.

## Safety model

**Live trading is disabled by default.** A real order can only ever be placed when
three independent gates all pass:

| Gate | What | Where |
|------|------|-------|
| 1 | `ALPHAQUANT_TRADING_MODE=live` | environment / `.env` |
| 2 | `ALPHAQUANT_LIVE_TRADING_ENABLED=true` | environment / `.env` |
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

Set via `ALPHAQUANT_TRADING_MODE` (default: `research`).

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
.venv/bin/uvicorn alphaquant.api.main:app --reload
# http://127.0.0.1:8000/health          -> {"status": "ok"}
# http://127.0.0.1:8000/system/status   -> mode & gate status
```

Or run everything in Docker: `docker compose up --build`.

## Personal deployment (your own machine)

The stack is designed to run unattended on a home machine — `docker-compose.yml`'s
`postgres`/`redis`/`app` services all use `restart: unless-stopped`, so as long as the Docker
daemon starts on boot (its default on Linux/macOS/Windows installs), the whole thing comes back
up after a reboot with no manual step. `docker compose up -d --build` starts it as a background
daemon.

1. **Secrets** — fill in `.env` from `.env.example` before first run: real (non-`change-me`)
   `ALPHAQUANT_DB__PASSWORD`, `ALPHAQUANT_KITE__API_KEY`/`API_SECRET` (market data; only needed
   for `paper`/`live` modes), `ALPHAQUANT_ANTHROPIC__API_KEY` (only needed for `/llm`), and — if
   you ever intend to arm live trading — `ALPHAQUANT_EXECUTION__ARMING_SECRET`. Leaving any of
   these empty is safe; the corresponding feature just refuses cleanly instead of running.
2. **Data durability** — `postgres`'s `pgdata` volume holds the OMS order journal, trade
   journal, and instrument/candle history introduced across M8–M15. Back it up periodically
   (`docker compose exec postgres pg_dump -U alphaquant alphaquant > backup.sql`) if you'd mind
   losing trade history on a disk failure.
3. **Reaching it from your phone** — `postgres`/`redis` are bound to `127.0.0.1` only (not
   exposed to your LAN), but `app` publishes `8000` on all interfaces. For personal use, prefer
   [Tailscale](https://tailscale.com) over port-forwarding your router: install it on this
   machine and your phone, then browse to `http://<this-machine's-tailscale-name>:8000/dashboard/`
   from anywhere — encrypted, no public exposure, no domain/TLS cert to manage. Port-forwarding
   8000 directly to the public internet is **not recommended** for an app that can hold real
   broker credentials and (once armed) place real orders.
4. **Before exposing beyond `localhost`** (including over Tailscale), set
   `ALPHAQUANT_DASHBOARD__AUTH_ENABLED=true` and real `ADMIN_TOKEN`/`VIEWER_TOKEN` values —
   unset, every request is silently granted the VIEWER role.

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
src/alphaquant/
├── config/      settings (pydantic-settings), trading-mode model
├── core/        logging, exceptions, event bus, NSE market calendar, DI container
├── domain/      pure entities: Instrument, OptionChain, Greeks, Signal, Order, ...
├── data/        providers (Kite, NSE bhavcopy), repositories, analytics services
│                (greeks, IV, PCR, OI, IV rank, max pain)
├── strategies/  strategy engine: Strategy ABC, registry, built-in strategies
├── risk/        pre-trade rule pipeline, portfolio-greek limits, kill switch
├── backtest/    event-driven backtester, Indian cost model, performance metrics
├── execution/   broker protocol, paper broker, Kite broker (gated), OMS
├── journal/     trade journal and performance analytics
├── llm/         Claude-powered analysis (reports, reviews, explanations only)
├── api/         FastAPI routers and schemas
├── runtime/     Runtime orchestrator (live data → strategies → risk → OMS → broker)
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
| M13 | Broker integration: real `KiteBroker`, triple-gated live trading, `/execution` admin API | ✅ |
| M12 | LLM assistant: analysis-only Claude tool-calling loop, 16 read-only tools, `/llm` API | ✅ |
| M14 | Institutional Options Strategy Library: 9 multi-leg strategies, shared declarative engine | ✅ |
| M15 | Trading Runtime & Production Readiness: orchestrator, order journaling + restart-restore, multi-leg compensation | ✅ |
| — | Manual Order Ticket: `/manual-orders` API + dashboard "Order Ticket" page for personal, non-algorithmic trading — same `Signal → RiskEngine → OMS → GatedBrokerAdapter` path every strategy uses | ✅ |

No numbered milestone is in progress; see [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) for full
detail, known gaps, and next steps. Notably: the M15 runtime orchestrator still ships with zero
strategies wired by default (safe-by-default, not yet trading anything algorithmic out of the
box) — the Manual Order Ticket is a separate, always-available path that doesn't depend on it.

## Disclaimer

This software is a research tool. Nothing it produces is investment advice.
Options trading involves substantial risk of loss.
