"""Eight interpretable accounting checks; unknown values remain unknown."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from ceremyn.domain.fundamentals import FundamentalScore, FundamentalSnapshot
from ceremyn.domain.market_data import _require_aware


def known_as_of(
    history: Sequence[FundamentalSnapshot], symbol: str, as_of: datetime
) -> tuple[FundamentalSnapshot, ...]:
    _require_aware(as_of)
    latest: dict[str, FundamentalSnapshot] = {}
    for row in history:
        if row.symbol != symbol or row.period_type != "annual" or row.published_at > as_of:
            continue
        key = row.period_end.isoformat()
        if key not in latest or latest[key].published_at < row.published_at:
            latest[key] = row
    return tuple(sorted(latest.values(), key=lambda r: r.period_end, reverse=True))


def _ratio(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None or b <= 0 else a / b


def _greater(a: Decimal | None, b: Decimal | None, *, equal: bool = False) -> bool | None:
    return None if a is None or b is None else (a >= b if equal else a > b)


def score(
    history: Sequence[FundamentalSnapshot], symbol: str, as_of: datetime, price: Decimal
) -> FundamentalScore | None:
    if price <= 0:
        raise ValueError("price must be positive")
    rows = known_as_of(history, symbol, as_of)
    if len(rows) < 2:
        return None
    cur, prev = rows[:2]
    # Do not compare non-consecutive annual periods as if they were one year apart.
    if not 300 <= (cur.period_end - prev.period_end).days <= 430:
        return None
    zero = Decimal(0)
    checks = {
        "profitable": _greater(cur.net_income, zero),
        "positive operating cash flow": _greater(cur.operating_cash_flow, zero),
        "cash flow exceeds profit": _greater(cur.operating_cash_flow, cur.net_income),
        "return on assets improving": _greater(
            _ratio(cur.net_income, cur.total_assets), _ratio(prev.net_income, prev.total_assets)
        ),
        "leverage falling": _greater(
            _ratio(prev.total_debt, prev.total_assets), _ratio(cur.total_debt, cur.total_assets)
        ),
        "current ratio improving": _greater(
            _ratio(cur.current_assets, cur.current_liabilities),
            _ratio(prev.current_assets, prev.current_liabilities),
        ),
        "no share dilution": _greater(prev.shares_outstanding, cur.shares_outstanding, equal=True),
        "asset turnover improving": _greater(
            _ratio(cur.revenue, cur.total_assets), _ratio(prev.revenue, prev.total_assets)
        ),
    }
    flags = []
    if cur.promoter_pledge_pct is not None and cur.promoter_pledge_pct >= 25:
        flags.append("high promoter pledge")
    if _greater(zero, cur.net_income) and _greater(zero, cur.operating_cash_flow):
        flags.append("loss with negative operating cash flow")
    return FundamentalScore(
        symbol=symbol,
        as_of=as_of,
        checks_passed=tuple(k for k, v in checks.items() if v is True),
        checks_failed=tuple(k for k, v in checks.items() if v is False),
        checks_missing=tuple(k for k, v in checks.items() if v is None),
        earnings_yield=_ratio(
            cur.net_income, price * cur.shares_outstanding if cur.shares_outstanding else None
        ),
        debt_to_assets=_ratio(cur.total_debt, cur.total_assets),
        red_flags=tuple(flags),
        source=cur.source,
    )
