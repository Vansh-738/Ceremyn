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

## Placing a manual trade

`POST /trading/equity` submits one specific equity order you choose — `tradingsymbol`,
`side`, `quantity`, `reference_price` (required: an equity has no static price the way
an option has a strike, so there is no safe default). It goes through the *exact same*
`RiskEngine`/`GatedBrokerAdapter` pipeline a strategy's own signal does — paper unless
all three live-trading gates above are open. This is the one endpoint outside a
`Strategy` that may submit an order; it never decides *what* to trade, only submits
what you explicitly asked for.

```bash
curl -X POST localhost:8000/trading/equity -H 'Content-Type: application/json' -d '{
  "tradingsymbol": "RELIANCE", "side": "BUY", "quantity": 10, "reference_price": "1489.25"
}'
```

**Known gap:** in paper/simulated mode, fills are currently only simulated against the
live *option-chain* cache (`broker.simulated.SimulatedBroker._build_context`) — an
equity order is risk-validated and submitted correctly, but may sit open rather than
auto-filling until a live equity quote feed is wired into the simulator. Live orders
(once armed) go straight to Kite and fill for real, unaffected by this.

## Finding opportunities

`GET /opportunities/equity` is read-only market intelligence: it runs every pattern
detector in `ceremyn.patterns` (candlestick, swing structure, Cup-and-Handle, Double
Top/Bottom, Head-and-Shoulders) and ranks what fired on the latest bar by its own real
historical hit rate — same guarantee as `ceremyn.patterns` itself, no path to
execution/risk/OMS. It's what the dashboard's Markets page shows under "Top
Opportunities."

Off by default (`CEREMYN_OPPORTUNITIES__SCAN_ENABLED=false`) — a real scan is a real,
repeated NSE bhavcopy fetch, so it shouldn't run implicitly. Turn it on in `.env`:

```bash
CEREMYN_OPPORTUNITIES__SCAN_ENABLED=true
# watchlist | nifty500 | all_equities (default) -- see .env.example for what each means
CEREMYN_OPPORTUNITIES__UNIVERSE=all_equities
```

**Universe defaults to the whole market, not a market-cap tier.** Quality is enforced by
liquidity, not by restricting to an index: `CEREMYN_OPPORTUNITIES__MIN_AVG_DAILY_TURNOVER`
(default ₹1 crore/day average traded value = close price × volume) is the load-bearing
filter — thin daily turnover, not nominal market cap, is what actually makes a stock
cheap to move with a small amount of money. `nifty500` (NSE's own published constituent
list) and `watchlist` (a small built-in liquid set) are still available if you'd rather
also restrict by index membership, but neither is the default.

**Opportunities are a month-plus horizon, not a quick flip.** Each pattern's historical
hit rate and average return are measured `CEREMYN_OPPORTUNITIES__FORWARD_DAYS` (default
30 trading days, ~a month and a half) after it fires, and only surfaced at all if that
average move clears `CEREMYN_OPPORTUNITIES__MIN_AVG_FORWARD_RETURN_PCT` (default 15%) —
compared against the *size* of the move, not its direction, so a strong bearish setup
qualifies exactly like a strong bullish one. Real evidence for a move too small to act
on still doesn't clear this bar.

It then runs as a background task (never blocking the dashboard/WebSocket), once at
startup and every `CEREMYN_OPPORTUNITIES__SCAN_INTERVAL_HOURS` (default 6) after that —
bhavcopy only updates once per trading day, so scanning more often wouldn't find
anything new. For a one-off scan from the command line instead, see
`scripts/find_opportunities.py --all-equities`.

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

# 4. Pick your active runtime strategy roster in .env
# CEREMYN_RUNTIME__ACTIVE_STRATEGY_TYPES=["long_contrarian"]

# 5. Daily-use checks
./scripts/ceremyn.sh doctor

# 6. Start Ceremyn locally
./scripts/ceremyn.sh start
# http://127.0.0.1:8000/health          -> {"status": "ok"}
# http://127.0.0.1:8000/system/status   -> mode & gate status
# http://127.0.0.1:8000/dashboard/      -> main UI
```

For day-to-day use, prefer the operator wrapper instead of raw `uvicorn`:

```bash
./scripts/ceremyn.sh status
./scripts/ceremyn.sh logs
./scripts/ceremyn.sh restart
./scripts/ceremyn.sh open
```

Or run everything in Docker: `docker compose up --build`.

**Running unattended (macOS):** if you want Ceremyn available every day without
manually starting it, use `./scripts/ceremyn.sh install`. That installs a macOS
LaunchAgent which starts Ceremyn on login and restarts it automatically if it crashes.
Remove it with `./scripts/ceremyn.sh uninstall`. Once installed, manage it via
`launchctl` or the wrapper above rather than `scripts/stop_dashboard.sh`, because a
LaunchAgent will restart the app after a manual kill.

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
├── patterns/    read-only market intelligence: Pattern detection (candlestick via
│                TA-Lib; swing structure -- Higher/Lower High/Low; chart shapes --
│                Cup-and-Handle, Double Top/Bottom, Head-and-Shoulders + Inverse)
│                + historical hit-rate study -- no path to execution/risk/OMS
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
