"""Backtest portfolio state and accounting."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.ledger import CashLedgerEntry, ClosedTrade, TradeLedger
from ceremyn.backtest.statistics import EquityPoint
from ceremyn.core.timeutils import to_ist
from ceremyn.domain import (
    Fill,
    Instrument,
    KillSwitchState,
    OptionContract,
    Order,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Position,
)
from ceremyn.domain.enums import Side


@dataclass(slots=True)
class _OpenLot:
    contract: Instrument
    quantity: int
    price: Decimal
    opened_at: datetime
    direction: Side
    strategy_id: str
    signal_id: UUID | None
    entry_costs: Decimal


class PortfolioConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_cash: Decimal = Field(default=Decimal("1000000"), ge=0)
    short_option_margin_ratio: Decimal = Field(default=Decimal("0.15"), ge=0)
    long_option_margin_ratio: Decimal = Field(default=Decimal("0.0"), ge=0)
    kill_switch_drawdown_limit: Decimal | None = Field(default=None, ge=0)


class BacktestPortfolio:
    def __init__(self, config: PortfolioConfig | None = None) -> None:
        self.config = config or PortfolioConfig()
        self.cash = self.config.initial_cash
        self.positions: dict[str, Position] = {}
        self._open_lots: dict[str, list[_OpenLot]] = defaultdict(list)
        self._realized_pnl = Decimal("0")
        self.ledger = TradeLedger()
        self.equity_curve: list[EquityPoint] = []
        self._peak_equity = self.config.initial_cash
        self._latest_snapshot = PortfolioSnapshot(buying_power=self.config.initial_cash)
        self._last_prices: dict[str, Decimal] = {}
        # Baseline for `daily_pnl`: reset to the previous day's closing equity on the
        # first mark of each new IST trading day, so a bad day doesn't permanently
        # suppress new entries via `MaximumDailyLossRule` for the account's whole life.
        self._trading_day: date | None = None
        self._day_start_equity = self.config.initial_cash
        self._last_equity = self.config.initial_cash

    def apply_fill(
        self,
        *,
        fill: Fill,
        order: Order,
        strategy_id: str,
        signal_id: UUID | None,
        costs: Decimal,
    ) -> None:
        position_before = self.positions.get(
            order.contract.tradingsymbol,
            Position(contract=order.contract),
        )
        position_after = position_before.apply_fill(order.side, fill.quantity, fill.price)
        self._realized_pnl += position_after.realized_pnl - position_before.realized_pnl
        self.positions[order.contract.tradingsymbol] = position_after
        self._record_lots(
            fill=fill,
            order=order,
            strategy_id=strategy_id,
            signal_id=signal_id,
            costs=costs,
        )
        cash_delta = fill.price * fill.quantity
        self.cash = (
            self.cash - cash_delta - costs
            if order.side is Side.BUY
            else self.cash + cash_delta - costs
        )
        self._last_prices[order.contract.tradingsymbol] = fill.price
        self.ledger = self.ledger.add_cash_entry(
            CashLedgerEntry(
                timestamp=fill.timestamp,
                amount=(-cash_delta - costs) if order.side is Side.BUY else (cash_delta - costs),
                description=f"{order.side} {order.contract.tradingsymbol}",
            )
        )

    def mark_to_market(
        self,
        *,
        timestamp: datetime,
        last_prices: dict[str, Decimal],
        pending_orders: tuple[Order, ...] = (),
    ) -> PortfolioSnapshot:
        self._last_prices.update(last_prices)
        unrealized = Decimal("0")
        market_value = Decimal("0")
        realized = self._realized_pnl
        gross_notional = Decimal("0")
        net_notional = Decimal("0")
        short_option_units = 0
        net_option_units = 0
        by_underlying: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

        for position in self.positions.values():
            if position.is_flat:
                continue
            price = self._last_prices.get(position.contract.tradingsymbol, position.avg_price)
            unrealized += position.unrealized_pnl(price)
            # `cash` already moved by the position's entry cost/proceeds (see
            # `apply_fill` below); adding `unrealized_pnl` (a P&L *delta* from entry)
            # on top of that double-counts it. Equity needs the position's current
            # market value instead -- `price * quantity` is signed correctly for
            # both a long asset (positive) and a short liability (negative).
            market_value += price * position.quantity
            # Notional reference price: strike for options (unchanged formula), else
            # the position's own mark -- asset-class-aware margin/exposure dispatch
            # is out of scope here (M16 only widens the domain vocabulary; no
            # non-option position can be produced by any registered strategy yet).
            reference_price = (
                position.contract.strike if isinstance(position.contract, OptionContract) else price
            )
            gross_notional += reference_price * abs(position.quantity)
            signed_notional = reference_price * position.quantity
            net_notional += signed_notional
            by_underlying[position.contract.underlying] += signed_notional
            net_option_units += position.quantity
            if position.quantity < 0:
                short_option_units += abs(position.quantity)

        equity = self.cash + market_value
        trading_day = to_ist(timestamp).date()
        if self._trading_day != trading_day:
            self._trading_day = trading_day
            self._day_start_equity = self._last_equity
        self._last_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = self._peak_equity - equity
        margin_used = self._margin_used()
        buying_power = equity - margin_used
        kill_switch = KillSwitchState.DISARMED
        if (
            self.config.kill_switch_drawdown_limit is not None
            and drawdown >= self.config.kill_switch_drawdown_limit
        ):
            kill_switch = KillSwitchState.TRIGGERED

        snapshot = PortfolioSnapshot(
            positions=tuple(
                position for position in self.positions.values() if not position.is_flat
            ),
            pending_orders=pending_orders,
            buying_power=buying_power,
            margin_used=margin_used,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            daily_pnl=equity - self._day_start_equity,
            portfolio_greeks=self._portfolio_greeks(),
            exposure=PortfolioExposure(
                gross_notional=gross_notional,
                net_notional=net_notional,
                short_option_units=short_option_units,
                net_option_units=net_option_units,
                by_underlying=dict(by_underlying),
            ),
            drawdown=drawdown,
            kill_switch_state=kill_switch,
        )
        point = EquityPoint(timestamp=timestamp, cash=self.cash, equity=equity, drawdown=drawdown)
        self.equity_curve.append(point)
        self._latest_snapshot = snapshot
        return snapshot

    def snapshot(self) -> PortfolioSnapshot:
        return self._latest_snapshot

    @property
    def closed_trades(self) -> tuple[ClosedTrade, ...]:
        return self.ledger.closed_trades

    def _portfolio_greeks(self) -> PortfolioGreeks:
        return PortfolioGreeks()

    def _margin_used(self) -> Decimal:
        total = Decimal("0")
        for position in self.positions.values():
            if position.is_flat:
                continue
            ratio = (
                self.config.short_option_margin_ratio
                if position.quantity < 0
                else self.config.long_option_margin_ratio
            )
            reference_price = (
                position.contract.strike
                if isinstance(position.contract, OptionContract)
                else self._last_prices.get(position.contract.tradingsymbol, position.avg_price)
            )
            total += reference_price * abs(position.quantity) * ratio
        return total

    def _record_lots(
        self,
        *,
        fill: Fill,
        order: Order,
        strategy_id: str,
        signal_id: UUID | None,
        costs: Decimal,
    ) -> None:
        remaining = fill.quantity
        lots = self._open_lots[order.contract.tradingsymbol]
        opening_side = order.side
        opposite_side = Side.SELL if opening_side is Side.BUY else Side.BUY
        matched_costs = Decimal("0")

        while remaining > 0 and lots and lots[0].direction is opposite_side:
            open_lot = lots[0]
            matched = min(remaining, open_lot.quantity)
            gross = (
                (fill.price - open_lot.price) * matched
                if open_lot.direction is Side.BUY
                else (open_lot.price - fill.price) * matched
            )
            entry_cost_share = open_lot.entry_costs * Decimal(matched) / Decimal(open_lot.quantity)
            exit_cost_share = costs * Decimal(matched) / Decimal(fill.quantity)
            matched_costs += exit_cost_share
            self.ledger = self.ledger.add_closed_trade(
                ClosedTrade(
                    contract=order.contract,
                    strategy_id=open_lot.strategy_id,
                    signal_id=open_lot.signal_id,
                    quantity=matched,
                    direction=open_lot.direction,
                    entry_price=open_lot.price,
                    exit_price=fill.price,
                    entry_at=open_lot.opened_at,
                    exit_at=fill.timestamp,
                    gross_pnl=gross,
                    costs=entry_cost_share + exit_cost_share,
                )
            )
            open_lot.quantity -= matched
            remaining -= matched
            if open_lot.quantity == 0:
                lots.pop(0)

        if remaining > 0:
            residual_costs = costs - matched_costs
            lots.append(
                _OpenLot(
                    contract=order.contract,
                    quantity=remaining,
                    price=fill.price,
                    opened_at=fill.timestamp,
                    direction=opening_side,
                    strategy_id=strategy_id,
                    signal_id=signal_id,
                    entry_costs=residual_costs,
                )
            )
