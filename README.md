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
└── dashboard/   FastAPI-served Plotly dashboards
```

## Roadmap

| Milestone | Scope | Status |
|-----------|-------|--------|
| M0 | Scaffolding: config, logging, Docker, CI | ✅ |
| M1 | Domain models + core (market calendar, events, container) | — |
| M2 | Data layer: bhavcopy ingest, Kite provider, greeks/IV/PCR analytics | — |
| M3 | Strategy engine + built-in strategies | — |
| M4 | Risk engine + kill switch | — |
| M5 | Backtester + Indian cost model + metrics | — |
| M6 | Paper trading (OMS, paper broker, scheduler) | — |
| M7 | API + Plotly dashboard | — |
| M8 | Trade journal + analytics | — |
| M9 | LLM assistant (reports, reviews, explanations) | — |
| M10 | Live trading (triple-gated) | — |

## Disclaimer

This software is a research tool. Nothing it produces is investment advice.
Options trading involves substantial risk of loss.
