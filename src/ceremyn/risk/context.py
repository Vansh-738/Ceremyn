"""Risk-evaluation context and projected portfolio helpers."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from ceremyn.config import RiskSettings, Settings
from ceremyn.core.timeutils import to_ist
from ceremyn.domain import (
    OptionContract,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Signal,
)
from ceremyn.domain.enums import KillSwitchState, Side

# Instruments with no expiry (e.g. equities) have no expiry-proximity risk to
# measure; this sentinel makes `ExpiryRestrictionsRule`'s threshold checks a no-op
# for them without threading `int | None` through every consumer. Asset-class-aware
# time-based risk rules are a later milestone's scope, not this domain widening.
_NO_EXPIRY_DAYS = 10**6


def _as_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(str(value))


class RiskContext(BaseModel):
    """All inputs a risk rule may inspect."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=False)

    portfolio: PortfolioSnapshot
    signal: Signal
    config: RiskSettings
    evaluated_at: datetime

    @classmethod
    def from_inputs(
        cls,
        *,
        portfolio: PortfolioSnapshot,
        signal: Signal,
        configuration: RiskSettings | Settings,
        evaluated_at: datetime,
    ) -> "RiskContext":
        config = configuration.risk if isinstance(configuration, Settings) else configuration
        return cls(portfolio=portfolio, signal=signal, config=config, evaluated_at=evaluated_at)

    @field_validator("evaluated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self.signal.metadata

    @property
    def signal_lots_total(self) -> int:
        return sum(leg.lots for leg in self.signal.legs)

    @property
    def signal_underlying(self) -> str:
        return self.signal.underlying or self.signal.legs[0].contract.underlying

    @property
    def signal_notional(self) -> Decimal:
        total = Decimal("0")
        for leg in self.signal.legs:
            if not isinstance(leg.contract, OptionContract):
                continue
            quantity = leg.quantity
            total += leg.contract.strike * quantity
        return total

    @property
    def signal_short_option_units(self) -> int:
        return sum(leg.quantity for leg in self.signal.legs if leg.side is Side.SELL)

    @property
    def market_time(self) -> datetime:
        return to_ist(self.signal.market_timestamp or self.signal.created_at)

    @property
    def days_to_expiry(self) -> int:
        expiry = self.signal.expiry or self.signal.legs[0].contract.expiry
        if expiry is None:
            return _NO_EXPIRY_DAYS
        return (expiry - self.market_time.date()).days

    @property
    def has_kill_switch_block(self) -> bool:
        return (
            self.config.block_on_kill_switch
            and self.portfolio.kill_switch_state is KillSwitchState.TRIGGERED
        )

    @property
    def signal_margin_required(self) -> Decimal:
        """Total margin for the *net projected* position (current holdings with this
        signal's legs applied), using the same per-leg model
        `backtest.portfolio.BacktestPortfolio._margin_used()` applies to filled
        positions: net-short symbols at `short_option_margin_ratio`, net-long at
        `long_option_margin_ratio`. Kept in sync via `RiskMarginSettings` and
        `Container._portfolio_config()`, the shared source both read from.

        Computed from the net position per symbol, not the signal's legs in
        isolation -- a SELL leg that *closes* an existing long (e.g. an exit signal)
        must not be charged short-side margin just because the leg itself sells;
        only a leg that leaves the symbol net short should be."""
        strikes: dict[str, Decimal] = {
            position.contract.tradingsymbol: position.contract.strike
            for position in self.portfolio.positions
            if isinstance(position.contract, OptionContract)
        }
        for leg in self.signal.legs:
            if isinstance(leg.contract, OptionContract):
                strikes[leg.contract.tradingsymbol] = leg.contract.strike
        total = Decimal("0")
        for symbol, quantity in self.projected_position_quantities.items():
            if quantity == 0:
                continue
            ratio = (
                self.config.margin.short_option_margin_ratio
                if quantity < 0
                else self.config.margin.long_option_margin_ratio
            )
            # Non-option symbols contribute no margin here (asset-aware margin
            # dispatch is out of scope for this widening); every symbol reachable
            # today is an option, so `strikes` always has a real entry in practice.
            total += strikes.get(symbol, Decimal("0")) * abs(quantity) * ratio
        return total

    @property
    def projected_margin_used(self) -> Decimal:
        projected = self.metadata.get("projected_margin_used")
        if projected is not None:
            return _as_decimal(projected)
        margin_required = self.metadata.get("margin_required")
        if margin_required is not None:
            return self.portfolio.margin_used + _as_decimal(margin_required)
        return self.signal_margin_required

    @property
    def total_capital_base(self) -> Decimal:
        return self.portfolio.buying_power + self.portfolio.margin_used

    @property
    def projected_margin_usage_ratio(self) -> float:
        capital_base = self.total_capital_base
        if capital_base <= 0:
            return 1.0 if self.projected_margin_used > 0 else 0.0
        return float(self.projected_margin_used / capital_base)

    @property
    def projected_portfolio_greeks(self) -> PortfolioGreeks:
        projected = self.metadata.get("projected_portfolio_greeks")
        if projected is not None:
            return PortfolioGreeks.model_validate(projected)

        signal_greeks = self.metadata.get("signal_greeks", {})
        return PortfolioGreeks(
            delta=self.portfolio.portfolio_greeks.delta + float(signal_greeks.get("delta", 0.0)),
            gamma=self.portfolio.portfolio_greeks.gamma + float(signal_greeks.get("gamma", 0.0)),
            theta=self.portfolio.portfolio_greeks.theta + float(signal_greeks.get("theta", 0.0)),
            vega=self.portfolio.portfolio_greeks.vega + float(signal_greeks.get("vega", 0.0)),
            rho=self.portfolio.portfolio_greeks.rho + float(signal_greeks.get("rho", 0.0)),
        )

    @property
    def projected_exposure(self) -> PortfolioExposure:
        projected = self.metadata.get("projected_exposure")
        if projected is not None:
            return PortfolioExposure.model_validate(projected)

        gross_notional = self.portfolio.exposure.gross_notional + self.signal_notional
        net_signed = self.portfolio.exposure.net_notional
        by_underlying = dict(self.portfolio.exposure.by_underlying)
        net_option_units = self.portfolio.exposure.net_option_units
        short_option_units = self.portfolio.exposure.short_option_units

        signal_net_notional = Decimal("0")
        signal_gross_notional = Decimal("0")
        signal_short_units = 0
        signal_net_units = 0
        signal_underlying_total = by_underlying.get(self.signal_underlying, Decimal("0"))

        for leg in self.signal.legs:
            signed_quantity = leg.quantity if leg.side is Side.BUY else -leg.quantity
            # Non-option notional contribution is 0 until asset-aware exposure
            # dispatch lands; unreachable today (every leg is an option).
            reference_price = (
                leg.contract.strike if isinstance(leg.contract, OptionContract) else Decimal("0")
            )
            signed_notional = reference_price * signed_quantity
            signal_net_notional += signed_notional
            signal_gross_notional += reference_price * leg.quantity
            signal_net_units += signed_quantity
            if leg.side is Side.SELL:
                signal_short_units += leg.quantity
            signal_underlying_total += signed_notional

        gross_notional = self.portfolio.exposure.gross_notional + signal_gross_notional
        net_signed += signal_net_notional
        net_option_units += signal_net_units
        short_option_units += signal_short_units
        by_underlying[self.signal_underlying] = signal_underlying_total

        return PortfolioExposure(
            gross_notional=gross_notional,
            net_notional=net_signed,
            short_option_units=short_option_units,
            net_option_units=net_option_units,
            by_underlying=by_underlying,
        )

    @property
    def projected_position_quantities(self) -> dict[str, int]:
        projected = {
            position.contract.tradingsymbol: position.quantity
            for position in self.portfolio.positions
        }
        for leg in self.signal.legs:
            signed_quantity = leg.quantity if leg.side is Side.BUY else -leg.quantity
            symbol = leg.contract.tradingsymbol
            projected[symbol] = projected.get(symbol, 0) + signed_quantity
        return projected

    @property
    def projected_open_positions(self) -> int:
        return sum(1 for quantity in self.projected_position_quantities.values() if quantity != 0)

    @property
    def projected_open_positions_in_underlying(self) -> int:
        existing_symbols = {
            position.contract.tradingsymbol
            for position in self.portfolio.positions
            if position.contract.underlying == self.signal_underlying and position.quantity != 0
        }
        signal_symbols = {leg.contract.tradingsymbol for leg in self.signal.legs}
        projected = self.projected_position_quantities
        return sum(
            1 for symbol in existing_symbols | signal_symbols if projected.get(symbol, 0) != 0
        )

    @property
    def underlying_concentration_ratio(self) -> float:
        gross = self.projected_exposure.gross_notional
        if gross <= 0:
            return 0.0
        underlying_exposure = abs(
            self.projected_exposure.by_underlying.get(self.signal_underlying, Decimal("0"))
        )
        return float(underlying_exposure / gross)

    @property
    def implied_volatility(self) -> float | None:
        return _as_float(self.metadata.get("implied_volatility"))

    @property
    def volatility_percentile(self) -> float | None:
        return _as_float(self.metadata.get("volatility_percentile"))

    @property
    def has_high_impact_event(self) -> bool:
        return bool(self.metadata.get("has_high_impact_event", False))

    @property
    def event_types(self) -> tuple[str, ...]:
        event_types = self.metadata.get("event_types", ())
        if isinstance(event_types, str):
            return (event_types,)
        return tuple(str(event_type) for event_type in event_types)

    @property
    def liquidity_scores(self) -> tuple[float, ...]:
        raw_scores = self.metadata.get("liquidity_scores")
        if isinstance(raw_scores, Mapping):
            return tuple(float(score) for score in raw_scores.values())
        score = self.metadata.get("liquidity_score")
        if score is None:
            return ()
        return (float(score),)

    @property
    def bid_ask_spread_ratios(self) -> tuple[float, ...]:
        raw_ratios = self.metadata.get("bid_ask_spread_ratios")
        if isinstance(raw_ratios, Mapping):
            return tuple(float(ratio) for ratio in raw_ratios.values())
        ratio = self.metadata.get("bid_ask_spread_ratio")
        if ratio is None:
            return ()
        return (float(ratio),)
