from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

from ceremyn.backtest.fills import ExecutionContext, PendingOrderState
from ceremyn.backtest.simulator import ExecutionSimulator, SimulationConfig
from ceremyn.backtest.slippage import FixedBpsSlippageModel, NoSlippageModel
from ceremyn.domain import Candle, Order, Quote, Signal, SignalLeg
from ceremyn.domain.enums import (
    OrderStatus,
    OrderType,
    ProductType,
    Side,
    SignalAction,
    TimeFrame,
)
from tests.unit.backtest.helpers import make_chain


def test_default_slippage_matches_paper_broker_assumption() -> None:
    """A confidence-building backtest must not be frictionless by accident."""
    simulator = ExecutionSimulator()

    assert isinstance(simulator.slippage_model, FixedBpsSlippageModel)
    assert simulator.slippage_model.bps == Decimal("5")


def test_market_order_fills_at_ask_for_buy(signal: Signal, timestamp_one: datetime) -> None:
    # This test is about fill mechanics (does a market order fill at the ask),
    # not slippage (covered separately in test_slippage.py) -- pin the exact
    # reference price by opting out of the simulator's own default slippage.
    simulator = ExecutionSimulator(slippage_model=NoSlippageModel())
    order = simulator.orders_from_signal(signal, created_at=timestamp_one)[0]
    chain = make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101")

    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=chain),
        strategy_id=signal.strategy_id,
    )

    assert pending == ()
    assert len(fills) == 1
    assert fills[0].fill.price == Decimal("101")


def test_limit_order_stays_open_until_price_crosses(
    signal: Signal,
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
    # Fill-mechanics test (does a limit order wait for the price to cross),
    # not a slippage test -- pin the exact reference price.
    simulator = ExecutionSimulator(slippage_model=NoSlippageModel())
    limit_signal = signal.model_copy(
        update={
            "metadata": {
                "execution": {
                    "order_types": OrderType.LIMIT,
                    "limit_prices": Decimal("98"),
                }
            }
        }
    )
    order = simulator.orders_from_signal(limit_signal, created_at=timestamp_one)[0]
    first_chain = make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101")
    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=first_chain),
        strategy_id=signal.strategy_id,
    )

    assert len(pending) == 1
    assert fills == ()
    assert pending[0].order.status is OrderStatus.OPEN

    candle = Candle(
        tradingsymbol=order.contract.tradingsymbol,
        timeframe=TimeFrame.MINUTE,
        timestamp=timestamp_two,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("97"),
        close=Decimal("98"),
        volume=100,
    )
    pending_after, fills_after = simulator.simulate_pending(
        pending,
        context=ExecutionContext(
            timestamp=timestamp_two,
            chain=first_chain,
            candles={candle.tradingsymbol: candle},
        ),
        strategy_id=signal.strategy_id,
    )

    assert pending_after == ()
    assert len(fills_after) == 1
    assert fills_after[0].fill.price == Decimal("98")


def test_stop_market_order_triggers_and_partial_fills(
    signal: Signal,
    timestamp_one: datetime,
) -> None:
    # 3 lots requested (contract lot_size is 25 -> 75 units); volume/participation
    # clears exactly 1 lot's worth (40 * 0.4 = 40, rounded down to the nearest
    # 25-multiple = 25) -- a real, lot-aligned partial fill. A real broker can
    # never partially fill below one lot's granularity, so this must land on a
    # lot boundary, not an arbitrary unit count.
    multi_lot_signal = signal.model_copy(
        update={"legs": tuple(leg.model_copy(update={"lots": 3}) for leg in signal.legs)}
    )
    simulator = ExecutionSimulator(config=SimulationConfig(max_volume_participation=0.4))
    stop_signal = multi_lot_signal.model_copy(
        update={
            "metadata": {
                "execution": {
                    "order_types": OrderType.SL_MARKET,
                    "trigger_prices": Decimal("100"),
                    "products": ProductType.NRML,
                }
            }
        }
    )
    order = simulator.orders_from_signal(stop_signal, created_at=timestamp_one)[0]
    assert order.quantity == 75
    chain = make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101", volume=100)
    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=chain),
        strategy_id=signal.strategy_id,
    )

    assert len(fills) == 1
    assert fills[0].fill.quantity == 25
    assert fills[0].updated_order.status is OrderStatus.PARTIALLY_FILLED
    assert len(pending) == 1
    assert pending[0].remaining_quantity == 50


def test_no_fill_when_available_volume_is_below_one_lot(
    signal: Signal,
    timestamp_one: datetime,
) -> None:
    """Real volume that doesn't clear even one lot must produce no fill at all
    this tick (order stays fully pending) -- not a fill for the whole remaining
    quantity. Silently ignoring the volume cap here would defeat its entire
    purpose whenever the order is larger than a single lot's worth of volume."""
    simulator = ExecutionSimulator(config=SimulationConfig(max_volume_participation=0.4))
    order = simulator.orders_from_signal(signal, created_at=timestamp_one)[0]
    assert order.quantity == 25  # 1 lot
    chain = make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101", volume=20)

    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=chain),
        strategy_id=signal.strategy_id,
    )

    assert fills == ()
    assert len(pending) == 1
    assert pending[0].remaining_quantity == 25


def test_symbol_specific_execution_and_stop_limit_paths(
    signal: Signal,
    timestamp_one: datetime,
) -> None:
    simulator = ExecutionSimulator()
    symbol = signal.legs[0].contract.tradingsymbol
    stop_limit_signal = signal.model_copy(
        update={
            "metadata": {
                "execution": {
                    "order_types": {symbol: OrderType.SL_LIMIT},
                    "limit_prices": {symbol: Decimal("102")},
                    "trigger_prices": {symbol: Decimal("100")},
                    "products": {symbol: ProductType.NRML},
                }
            }
        }
    )
    order = simulator.orders_from_signal(stop_limit_signal, created_at=timestamp_one)[0]
    chain = make_chain(timestamp=timestamp_one, last_price="100", bid="100", ask="101")
    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=chain),
        strategy_id=signal.strategy_id,
    )

    assert order.product is ProductType.NRML
    assert pending == ()
    assert len(fills) == 1


def test_unfilled_market_order_without_quote_stays_open(
    signal: Signal,
    timestamp_one: datetime,
) -> None:
    simulator = ExecutionSimulator()
    order = simulator.orders_from_signal(signal, created_at=timestamp_one)[0]
    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one),
        strategy_id=signal.strategy_id,
    )

    assert len(pending) == 1
    assert pending[0].order.status is OrderStatus.OPEN
    assert fills == ()


def test_sell_limit_and_low_volume_paths(timestamp_one: datetime) -> None:
    simulator = ExecutionSimulator(config=SimulationConfig(max_volume_participation=0.4))
    contract = (
        make_chain(
            timestamp=timestamp_one,
            last_price="100",
            bid="99",
            ask="101",
        )
        .entries[0]
        .contract
    )
    sell_signal = Signal(
        strategy_id="test_backtest_strategy",
        strategy_version="1",
        created_at=timestamp_one,
        market_timestamp=timestamp_one,
        underlying=contract.underlying,
        expiry=contract.expiry,
        signal_type=SignalAction.ENTER,
        reason="sell signal",
        metadata={"execution": {"order_types": OrderType.LIMIT, "limit_prices": Decimal("99")}},
        legs=(SignalLeg(contract=contract, side=Side.SELL, lots=1),),
    )
    order = simulator.orders_from_signal(sell_signal, created_at=timestamp_one)[0]
    chain = make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101", volume=1)
    pending, fills = simulator.simulate_pending(
        (PendingOrderState(order=order, remaining_quantity=order.quantity),),
        context=ExecutionContext(timestamp=timestamp_one, chain=chain),
        strategy_id=sell_signal.strategy_id,
    )

    assert len(pending) == 1
    assert fills == ()


def test_simulator_helper_branches(timestamp_one: datetime) -> None:
    simulator = ExecutionSimulator()
    contract = (
        make_chain(
            timestamp=timestamp_one,
            last_price="100",
            bid="99",
            ask="101",
        )
        .entries[0]
        .contract
    )
    sell_limit = Signal(
        strategy_id="test_backtest_strategy",
        strategy_version="1",
        created_at=timestamp_one,
        market_timestamp=timestamp_one,
        underlying=contract.underlying,
        expiry=contract.expiry,
        signal_type=SignalAction.ENTER,
        reason="sell limit",
        metadata={"execution": {"order_types": OrderType.LIMIT, "limit_prices": Decimal("102")}},
        legs=(SignalLeg(contract=contract, side=Side.SELL, lots=1),),
    )
    order = simulator.orders_from_signal(sell_limit, created_at=timestamp_one)[0]
    candle = Candle(
        tradingsymbol=contract.tradingsymbol,
        timeframe=TimeFrame.MINUTE,
        timestamp=timestamp_one,
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal("98"),
        close=Decimal("102"),
        volume=10,
    )

    assert simulator._limit_fill(order, None, candle) is True
    assert simulator._limit_price(order, None) == Decimal("102")
    assert simulator._stop_triggered(order, None, candle) is False

    stop_sell_signal = sell_limit.model_copy(
        update={
            "metadata": {
                "execution": {
                    "order_types": OrderType.SL_MARKET,
                    "trigger_prices": Decimal("99"),
                }
            }
        }
    )
    stop_order = simulator.orders_from_signal(stop_sell_signal, created_at=timestamp_one)[0]
    assert simulator._stop_triggered(stop_order, None, candle) is True


def test_simulator_covers_remaining_edge_paths(
    signal: Signal,
    timestamp_one: datetime,
) -> None:
    simulator = ExecutionSimulator(config=SimulationConfig(max_volume_participation=0.1))
    order = simulator.orders_from_signal(signal, created_at=timestamp_one)[0]
    contract = order.contract
    candle = Candle(
        tradingsymbol=contract.tradingsymbol,
        timeframe=TimeFrame.MINUTE,
        timestamp=timestamp_one,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("100"),
        volume=10,
    )

    assert simulator._available_quantity(None, 25, contract.lot_size) == 25
    assert (
        simulator._available_quantity(
            Quote(
                tradingsymbol=contract.tradingsymbol,
                timestamp=timestamp_one,
                bid=Decimal("99"),
                ask=Decimal("101"),
                last_price=Decimal("100"),
                volume=0,
            ),
            25,
            contract.lot_size,
        )
        == 25
    )
    assert (
        simulator._available_quantity(
            Quote(
                tradingsymbol=contract.tradingsymbol,
                timestamp=timestamp_one,
                bid=Decimal("99"),
                ask=Decimal("101"),
                last_price=Decimal("100"),
                volume=1,
            ),
            25,
            contract.lot_size,
        )
        == 0
    )
    # Regression: a real broker never partially fills below one lot's granularity.
    # `max_volume_participation=1.0` (the default) against a volume that isn't a
    # clean multiple of `lot_size` must round DOWN to the nearest lot boundary,
    # not return the raw, lot-misaligned volume -- the bug this guards against
    # left positions holding quantities like 59 units of a 25-lot contract, and a
    # later full-exit's `lots = quantity // lot_size` silently floored to 0.
    full_participation_simulator = ExecutionSimulator()
    assert contract.lot_size == 25
    assert (
        full_participation_simulator._available_quantity(
            Quote(
                tradingsymbol=contract.tradingsymbol,
                timestamp=timestamp_one,
                bid=Decimal("99"),
                ask=Decimal("101"),
                last_price=Decimal("100"),
                volume=59,
            ),
            100,
            contract.lot_size,
        )
        == 50
    )

    no_limit_order = order.model_copy(update={"limit_price": None})
    assert simulator._limit_fill(no_limit_order, None, candle) is False
    assert simulator._limit_price(no_limit_order, None) is None

    stop_sell_order = order.model_copy(update={"side": Side.SELL, "trigger_price": Decimal("100")})
    sell_quote = Quote(
        tradingsymbol=contract.tradingsymbol,
        timestamp=timestamp_one,
        bid=Decimal("99"),
        ask=Decimal("101"),
        last_price=Decimal("100"),
        volume=10,
    )
    assert simulator._stop_triggered(stop_sell_order, sell_quote, None) is True

    stop_buy_order = order.model_copy(update={"trigger_price": Decimal("104")})
    assert simulator._stop_triggered(stop_buy_order, None, candle) is True
    assert simulator._evaluate_fillability(
        order=stop_buy_order.model_copy(update={"order_type": OrderType.SL_MARKET}),
        quote=None,
        candle=Candle(
            tradingsymbol=contract.tradingsymbol,
            timeframe=TimeFrame.MINUTE,
            timestamp=timestamp_one,
            open=Decimal("100"),
            high=Decimal("103"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=10,
        ),
        triggered=False,
    ) == (False, None, False)
    assert (
        simulator._stop_triggered(
            stop_buy_order.model_copy(update={"trigger_price": Decimal("106")}),
            None,
            candle,
        )
        is False
    )

    unsupported_order = SimpleNamespace(
        order_type="unsupported",
        side=Side.BUY,
        limit_price=None,
        trigger_price=None,
    )
    assert simulator._evaluate_fillability(
        order=cast(Order, unsupported_order),
        quote=None,
        candle=None,
        triggered=True,
    ) == (False, None, True)
