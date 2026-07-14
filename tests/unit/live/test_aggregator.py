from datetime import timedelta
from decimal import Decimal

from alphaquant.features.engine import FeatureEngine
from alphaquant.live.aggregator import TickAggregator
from alphaquant.live.feed import build_subscription_plan
from alphaquant.live.snapshot import InstrumentKind, LiveTick
from tests.unit.live.conftest import BASE_TS


def test_aggregator_builds_snapshot_with_features(underlyings, contracts, analytics) -> None:
    plan = build_subscription_plan(underlyings=underlyings, contracts=contracts)
    aggregator = TickAggregator(
        plan.instruments,
        analytics,
        feature_engine=FeatureEngine(),
    )

    assert aggregator.update(aggregator_tick(plan.all_tokens[0], "24010")) is None
    assert (
        aggregator.update(aggregator_tick(plan.all_tokens[1], "150", bid="149.5", ask="150.5"))
        is None
    )
    snapshot = aggregator.update(
        aggregator_tick(
            plan.all_tokens[2],
            "145",
            bid="144.5",
            ask="145.5",
            timestamp=BASE_TS + timedelta(seconds=1),
        )
    )

    assert snapshot is not None
    assert snapshot.underlying == "NIFTY"
    assert snapshot.spot == 24010
    assert snapshot.option_chain.atm_strike == contracts[0].strike
    assert snapshot.features is not None
    assert snapshot.feature_context.candles
    assert all(entry.greeks is not None for entry in snapshot.option_chain.entries)


def aggregator_tick(token: int, price: str, **kwargs):
    return TickAggregatorTestHelper.normalize_payload(token, price, **kwargs)


class TickAggregatorTestHelper:
    @staticmethod
    def normalize_payload(token: int, price: str, **kwargs):
        received = kwargs.pop("timestamp", BASE_TS)
        return LiveTick(
            instrument_token=token,
            tradingsymbol="NIFTY 50" if token == 256265 else f"TOKEN{token}",
            underlying="NIFTY",
            instrument_kind=InstrumentKind.INDEX if token == 256265 else InstrumentKind.OPTION,
            timestamp=received,
            last_price=Decimal(price),
            bid=None if "bid" not in kwargs else Decimal(kwargs["bid"]),
            ask=None if "ask" not in kwargs else Decimal(kwargs["ask"]),
            volume=1000,
            open_interest=1000,
            received_at=received,
            sequence_id=f"{token}|{received.isoformat()}|{price}",
        )
