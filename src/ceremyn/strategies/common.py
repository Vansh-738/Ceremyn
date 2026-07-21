"""Shared building blocks: contract selection, marks, and premium exits."""

from decimal import Decimal

from ceremyn.domain import (
    ChainEntry,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Position,
    Side,
    SignalLeg,
)


def find_by_delta(
    chain: OptionChainSnapshot, option_type: OptionType, target_abs_delta: float
) -> ChainEntry | None:
    """The entry whose |delta| is nearest the target; None if no greeks exist."""
    candidates = [
        entry
        for entry in chain.entries
        if entry.contract.option_type is option_type and entry.greeks is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda e: abs(abs(e.greeks.delta) - target_abs_delta))  # type: ignore[union-attr]


def find_atm(chain: OptionChainSnapshot, option_type: OptionType) -> ChainEntry | None:
    return chain.get(chain.atm_strike, option_type)


def mark_price(entry: ChainEntry | None) -> Decimal | None:
    """Mid when both sides are quoted, else last traded price."""
    if entry is None or entry.quote is None:
        return None
    mid = entry.quote.mid
    if mid is not None and mid > 0:
        return mid
    return entry.quote.last_price if entry.quote.last_price > 0 else None


def net_entry_credit(positions: tuple[Position, ...]) -> Decimal:
    """Net premium received at entry (positive when net short)."""
    return sum((-p.avg_price * p.quantity for p in positions), Decimal(0))


def net_close_cost(positions: tuple[Position, ...], chain: OptionChainSnapshot) -> Decimal | None:
    """Net cost to close all positions at current marks; None if a mark is missing."""
    total = Decimal(0)
    for position in positions:
        if position.is_flat:
            continue
        if not isinstance(position.contract, OptionContract):
            # Every registered strategy today only ever holds option positions;
            # a non-option instrument here has no chain entry to price against.
            return None
        if position.contract.expiry != chain.expiry:
            # `chain.get()` matches by strike + option_type only -- a position held
            # across an expiry-listing change would otherwise silently price against
            # a *different* expiry's contract at the same strike. Treat it the same
            # as any other missing mark rather than return a wrong number.
            return None
        entry = chain.get(position.contract.strike, position.contract.option_type)
        mark = mark_price(entry)
        if mark is None:
            return None
        total += -mark * position.quantity
    return total


def exit_legs(positions: tuple[Position, ...]) -> tuple[SignalLeg, ...]:
    """Legs that flatten every open position."""
    legs = []
    for position in positions:
        if position.is_flat:
            continue
        legs.append(
            SignalLeg(
                contract=position.contract,
                side=Side.BUY if position.is_short else Side.SELL,
                lots=abs(position.quantity) // position.contract.lot_size,
            )
        )
    return tuple(legs)


def premium_exit_reason(
    credit: Decimal,
    close_cost: Decimal,
    profit_target_pct: float,
    stop_loss_pct: float,
) -> str | None:
    """Exit rationale for a net-credit position, or None to stay in.

    profit% = (credit - cost_to_close) / credit; loss% is the mirror image.
    """
    if credit <= 0:
        return None
    profit_pct = float((credit - close_cost) / credit * 100)
    if profit_pct >= profit_target_pct:
        return f"profit target: {profit_pct:.1f}% >= {profit_target_pct:.0f}%"
    if -profit_pct >= stop_loss_pct:
        return f"stop loss: {-profit_pct:.1f}% >= {stop_loss_pct:.0f}%"
    return None


def net_pnl_pct(entry_cashflow: Decimal, close_cashflow: Decimal) -> float:
    """P&L as a percentage of capital at risk, correct for both net-credit and net-debit
    entries (unlike `premium_exit_reason`'s formula, which only holds for entry_cashflow > 0).

    `entry_cashflow` is `net_entry_credit(...)` (positive = credit received at entry, negative
    = debit paid). `close_cashflow` is `-net_close_cost(...)` (positive = would receive money
    closing now, negative = would pay). P&L = entry_cashflow + close_cashflow; capital at risk
    is `abs(entry_cashflow)`.
    """
    if entry_cashflow == 0:
        return 0.0
    return float((entry_cashflow + close_cashflow) / abs(entry_cashflow) * 100)


def exit_reason_from_pnl_pct(
    pnl_pct: float,
    profit_target_pct: float,
    stop_loss_pct: float,
) -> str | None:
    """Exit rationale from a signed P&L percentage (see `net_pnl_pct`), or None to stay in."""
    if pnl_pct >= profit_target_pct:
        return f"profit target: {pnl_pct:.1f}% >= {profit_target_pct:.0f}%"
    if -pnl_pct >= stop_loss_pct:
        return f"stop loss: {-pnl_pct:.1f}% >= {stop_loss_pct:.0f}%"
    return None
