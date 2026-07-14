from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from alphaquant.config import Settings
from alphaquant.domain import (
    Exchange,
    KillSwitchState,
    OptionContract,
    OptionType,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Position,
    Side,
    Signal,
    SignalAction,
    SignalLeg,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def ist_now() -> datetime:
    return datetime(2026, 7, 14, 10, 0, tzinfo=IST)


def make_contract(
    *,
    symbol: str,
    strike: str = "25000",
    expiry: date,
    underlying: str = "NIFTY",
    option_type: OptionType = OptionType.CALL,
) -> OptionContract:
    return OptionContract(
        tradingsymbol=symbol,
        exchange=Exchange.NFO,
        underlying=underlying,
        expiry=expiry,
        strike=Decimal(strike),
        option_type=option_type,
        lot_size=25,
    )


@pytest.fixture
def base_settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def risk_settings(base_settings: Settings):
    return base_settings.risk


@pytest.fixture
def option_contract(ist_now: datetime) -> OptionContract:
    return make_contract(symbol="NIFTY26JUL25000CE", expiry=ist_now.date() + timedelta(days=7))


@pytest.fixture
def second_contract(ist_now: datetime) -> OptionContract:
    return make_contract(
        symbol="NIFTY26JUL25100PE",
        strike="25100",
        expiry=ist_now.date() + timedelta(days=7),
        option_type=OptionType.PUT,
    )


def make_signal(
    *,
    created_at: datetime,
    expiry: date,
    legs: tuple[SignalLeg, ...],
    metadata: dict[str, object] | None = None,
) -> Signal:
    return Signal(
        strategy_id="strategy-1",
        strategy_version="1.2.3",
        created_at=created_at,
        market_timestamp=created_at,
        signal_type=SignalAction.ENTER,
        confidence=0.8,
        priority=60,
        reason="test signal",
        metadata=metadata or {},
        legs=legs,
        expiry=expiry,
        underlying=legs[0].contract.underlying,
    )


@pytest.fixture
def signal(ist_now: datetime, option_contract: OptionContract) -> Signal:
    return make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
        metadata={
            "margin_required": "50000",
            "signal_greeks": {"delta": -100.0, "gamma": 5.0, "theta": -50.0, "vega": 80.0},
            "liquidity_score": 0.9,
            "bid_ask_spread_ratio": 0.01,
            "implied_volatility": 0.2,
            "volatility_percentile": 0.5,
            "event_types": (),
        },
    )


@pytest.fixture
def portfolio(option_contract: OptionContract) -> PortfolioSnapshot:
    position = Position(contract=option_contract, quantity=-25, avg_price=Decimal("110"))
    return PortfolioSnapshot(
        positions=(position,),
        buying_power=Decimal("900000"),
        margin_used=Decimal("100000"),
        realized_pnl=Decimal("25000"),
        unrealized_pnl=Decimal("5000"),
        daily_pnl=Decimal("1000"),
        portfolio_greeks=PortfolioGreeks(delta=-50.0, gamma=2.0, theta=-20.0, vega=30.0),
        exposure=PortfolioExposure(
            gross_notional=Decimal("625000"),
            net_notional=Decimal("-625000"),
            short_option_units=25,
            net_option_units=-25,
            by_underlying={"NIFTY": Decimal("-625000")},
        ),
        drawdown=Decimal("20000"),
        kill_switch_state=KillSwitchState.DISARMED,
    )


@pytest.fixture
def utc_now() -> datetime:
    return datetime(2026, 7, 14, 4, 30, tzinfo=UTC)
