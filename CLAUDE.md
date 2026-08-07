# Ceremyn — project conventions

Ceremyn is an AI-powered **market intelligence platform**: it analyzes markets, surfaces
and explains trading opportunities, and ranks them by expected edge. Execution is one
consumer of that intelligence, not the point of the platform. v1 scope is options
trading research for Indian markets (NIFTY/BANKNIFTY options v1). Not a prediction bot —
every opportunity surfaced is explainable and backtested, not a black-box guess.
Reliability and risk management outrank features.

## Safety invariants (never violate, never "temporarily" bypass)

1. **Live trading is disabled by default.** Three independent gates must all pass
   before a live order is possible: `CEREMYN_TRADING_MODE=live` env var,
   `CEREMYN_LIVE_TRADING_ENABLED=true`, and a runtime arming token submitted
   after startup. Missing any gate → orders route to the paper broker.
   Gate logic lives in `Settings.effective_mode` (config/settings.py) and the
   execution layer.
2. **Every order passes through `RiskEngine.validate()`.** Strategies emit
   `Signal` objects only; the OMS alone constructs orders. Never give a strategy
   a broker handle.
3. **The LLM never decides BUY or SELL.** `ceremyn.llm` must not import
   `ceremyn.execution` or `ceremyn.risk` (import-linter enforces this).
   LLM use is limited to: news summaries, earnings explainers, report
   generation, trade explanations, strategy reviews.
4. **Identical strategy/risk code across backtest, paper, and live** — the three
   runners drive the same interfaces. Never fork strategy logic per mode.

## Architecture

Clean architecture, src layout (`src/ceremyn/`):
- `domain/` — pure entities/value objects; imports nothing else in the project.
- `data/`, `strategies/`, `risk/`, `backtest/`, `execution/`, `journal/`, `llm/`
  — service layer coded against protocols, not concrete infra.
- `data/providers/`, `data/repositories/` — infrastructure (Kite, NSE bhavcopy,
  Postgres, Redis).
- `api/`, `dashboard/`, `scripts/` — thin interface layer.
- DI via composition root in `core/container.py`; FastAPI `Depends` pulls from it.

## Conventions

- Python 3.12, full type hints, `mypy --strict` must pass.
- Ruff for lint + format (line length 100). `ruff check . && ruff format .`
- All timestamps timezone-aware; market times in IST (`Asia/Kolkata`), storage
  in UTC. Naive datetimes are lint errors (DTZ rules).
- Money/prices: `Decimal` in domain models and ledgers; floats only inside
  numerical kernels (greeks/IV) at the NumPy boundary.
- Logging via `structlog.get_logger(__name__)`; never `print`.
- Config only via `ceremyn.config.get_settings()`; never read `os.environ`
  elsewhere.
- Files ≤ 800 lines; split before you exceed it.
- Every module lands with tests. Unit tests in `tests/unit` (mirror src);
  integration tests in `tests/integration`, marked `@pytest.mark.integration`.

## Commands

- Test: `.venv/bin/pytest tests/unit -q`  (integration: needs `docker compose up -d postgres redis`)
- Lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- Types: `.venv/bin/mypy`
- Contracts: `.venv/bin/lint-imports`
- Run API: `.venv/bin/uvicorn ceremyn.api.main:app --reload`

## Workflow

One module per milestone (M0–M10, see README roadmap). After each: tests green,
lint/type/contract checks clean, commit, then STOP and wait for user approval
before the next module.
