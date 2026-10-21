# Project review — 21 October 2026

The rebuilt terminal is suitable for local research and supervised paper workflows.
This review does **not** establish readiness for unattended or real-money trading.
The live-order lifecycle, broker reconciliation, and request idempotency gaps below
remain release blockers for that use.

## Scope and evidence

Ran the complete Python unit suite (1,311 tests), seven frontend regression tests,
Ruff lint/format, strict mypy over 247 source files, and all 21 import contracts.
All passed. Built the Python wheel to check that the terminal ships with the app.
The earlier coverage run measured 94.14%; the final unit run was without coverage.

Manual review focused on the dashboard, analysis and opportunity APIs, scan lifecycle,
manual-order authorization, broker submission/recovery, OMS reconciliation, runtime
startup, packaging, and CI. Browser checks covered navigation, themes, responsive
layout (1440px desktop and 390px mobile, without horizontal overflow), symbol search,
and the order review dialog. No order was submitted and live
execution was not armed during verification. This is a targeted code review with
project-wide automated checks, not an exhaustive security or trading certification.

Postgres/Redis integration tests and the Docker build were not run locally because
Docker is unavailable. All three jobs (quality, integration, and Docker) passed in
[CI for the terminal rebuild](https://github.com/Vansh-738/Ceremyn/actions/runs/39576435623).

## Fixed in this change

| Finding | Change and verification |
| --- | --- |
| The presentation was one large Python string with accumulated style overrides. | Replaced it with packaged HTML/CSS and separate helper, rendering, order-flow, and transport scripts. The Python loader is 16 lines. All new presentation files stay under 500 lines. |
| Incoming snapshots could disrupt form interactions; the screen lacked a coherent trading workflow. | A scanner, central chart/evidence/activity area, and persistent ticket now have distinct roles. Only data regions update. Themes, focus states, responsive breakpoints, and reduced-motion handling share one set of design tokens. |
| Order quantity parsing could silently accept malformed input; uncertain submissions could invite retries. | Whole-number validation, preserved decimal price strings, fresh mode checks at review and confirmation, and an explicit uncertain-outcome lock. Unknown/research modes fail closed. Frontend regressions cover validation. The server idempotency limitation below still applies. |
| First-scan notification handling and repeated polls could create misleading alerts. | The first completed scan establishes a baseline, including an empty result. Later unseen setups alert once, with bounded stored keys. Notification support/denial is handled; the UI states that the tab must remain open. Regression tests cover baseline and duplicate behavior. |
| The chart lacked a real, reusable price-history endpoint. | Added bounded, read-only cached OHLCV history. Tests cover unavailable/unknown symbols, bounds, and chronological timestamps. Daily candles are labelled EOD and never used as a fabricated live quote or automatic order reference. |
| Single-symbol qualification could disagree with market-wide corrected ranking. | The accepted pattern set now comes from the completed market-wide scan. Per-symbol descriptive statistics remain available. A regression distinguishes local statistics from scan qualification. |
| Liquidity filtering and fundamental preparation ran synchronously on the request event loop. | Both run in worker threads, as ranking already did. A regression verifies liquidity preparation runs off the request thread. This does not make the whole download/parse pipeline latency-free. |
| Kite recovery searched a full request hash, although submission used a 20-character broker tag. | Recovery uses the same shortened tag. A test starts a fresh adapter after submission and locates the existing order using the full request hash. This closes a concrete missed-recovery/duplicate-retry path. |
| The local service wrapper could miss launchd management under `pipefail`. | Replaced early-exiting `grep -q` detection; restarted the launchd-managed service successfully. |
| Auth documentation claimed development callers were viewers. | Corrected the comments to describe the actual ADMIN behavior when authentication is disabled. Permissions themselves were not broadened. |

## Remaining findings

### High — live orders lose their broker context when the gate changes

[`execution/gated_broker.py`](src/ceremyn/execution/gated_broker.py) resolves the
currently active broker for cancellation, replacement, lookup, and polling as well as
new submission. Disarming after a live order routes those later operations to the
paper fallback. A restart also resets runtime arming. An outstanding live order can
therefore remain at Kite while subsequent management looks at the fallback broker.

Before live release, persist broker/account ownership per order and restore it on
restart. Keep observation and management of existing live orders independent from
permission to submit new live orders. Test arm → submit → disarm → cancel/reconcile,
plus restart with open/part-filled live orders. Preserve all three submission gates.

### High — position reconciliation does not compare broker positions

[`oms/reconciliation.py`](src/ceremyn/oms/reconciliation.py) compares positions
derived from the local ledger with the local portfolio. It checks broker orders and
cash, but does not call `broker.fetch_positions()`. A position created outside Ceremyn
can be absent from both local structures without producing position drift.

Add a broker-position comparison, with exchange/product/account-aware identifiers
and explicit treatment of external positions. Validate external/manual fills,
partial fills, restarts, and account separation. The terminal's “OMS reconciliation”
status should not be read as proof that all broker holdings match.

### High — manual HTTP order requests lack durable client idempotency

[`api/trading.py`](src/ceremyn/api/trading.py) creates a new `Signal` per request.
The OMS request hash includes signal identity, so repeating the HTTP request after a
lost response can produce a distinct order even though retrying the same OMS command
is protected. The new browser blocks further submissions after an uncertain outcome
within that page session; a reload, another client, or a direct API retry bypasses that
UI protection.

Add a client-supplied idempotency key stored durably with the normalized payload and
result. Reject key reuse with a different payload; serialize concurrent requests for
the same key. Test timeouts, simultaneous requests, and process restarts.

### High for public hosting — development authentication is intentionally open

[`dashboard/permissions.py`](src/ceremyn/dashboard/permissions.py) grants ADMIN
when `auth_enabled=false`. The manual endpoint rejects unauthenticated live mode,
but development mode still exposes paper actions and operational information.
Do not expose this operator application publicly with that setting. A reviewer-only
demo is a separate surface. Public deployment needs authenticated access, TLS, secure
token handling, and a review of the full exposed route set.

### Medium — cold scans and failures need durable, visible state

[`api/opportunities.py`](src/ceremyn/api/opportunities.py) holds scan data in
process memory. Startup rebuilds history, and chart data becomes available only after
the scan completes. A failed refresh logs an error and leaves the prior successful
scan available, without a structured last-error field for the terminal. The history
fetcher also skips individual failed download days, which can leave gaps.

Persist validated daily bars, fetch incrementally, expose scan progress/error and
data-completeness metadata, and distinguish “no setups” from incomplete history.
The browser reports request failures and last successful scan time, but cannot infer
missing backend failure metadata. Browser opportunity alerts currently require an
open tab; reliable off-tab delivery needs a server-side delivery queue and receipts.

The final live check also observed an API request exceed a 10-second timeout while
background processing and quote-feed failures were occurring. A subsequent request
completed in roughly four seconds. Moving preparation into threads does not establish
acceptable latency under load; profile event-loop stalls and logging/CPU contention,
then isolate heavy scanning and verify response-time budgets under feed failures.

### Medium — raw equity history has no corporate-action adjustment stage

[`data/services/equity_history.py`](src/ceremyn/data/services/equity_history.py)
turns cash bhavcopy values directly into candles. This path has no split/bonus
adjustment or corporate-action exclusion. Such discontinuities can distort pattern
statistics and forward returns. Introduce versioned adjustments or exclude affected
windows and verify against known action fixtures before relying on those samples.

### Current environment — the live quote feed requires renewed credentials

During the browser review, the System page reported Kite rejecting the configured
API key/access token. Configuration being present does not prove it is valid. Paper
orders require fresh exchange quotes to fill, so missing quotes must remain an
explicit unavailable state. Renew the broker session through the supported operator
flow; no credentials were changed during this work.

## Architecture assessment

The clean domain boundary, protocol-based services, shared strategy/risk interfaces,
and enforced LLM restrictions are sound foundations. All 21 dependency contracts
remain intact. The frontend now separates presentation, data transport, and deliberate
order interaction without creating another execution path. The next structural work
should address broker ownership, durable idempotency, and data provenance before
adding more trading features.
