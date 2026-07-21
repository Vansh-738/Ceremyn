"""Virtual execution simulator."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.commission import IndianCostModel
from ceremyn.backtest.fills import (
    ExecutionContext,
    PendingOrderState,
    VirtualFill,
    terminal_status,
)
from ceremyn.backtest.slippage import NoSlippageModel, SlippageModel
from ceremyn.domain import Candle, Fill, Order, Quote, Signal
from ceremyn.domain.enums import OrderStatus, OrderType, ProductType, Side


class SimulationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    default_order_type: OrderType = OrderType.MARKET
    max_volume_participation: float = Field(default=1.0, gt=0, le=1.0)


class ExecutionSimulator:
    def __init__(
        self,
        *,
        config: SimulationConfig | None = None,
        slippage_model: SlippageModel | None = None,
        commission_model: IndianCostModel | None = None,
    ) -> None:
        self.config = config or SimulationConfig()
        self.slippage_model = slippage_model or NoSlippageModel()
        self.commission_model = commission_model or IndianCostModel()

    def orders_from_signal(
        self,
        signal: Signal,
        *,
        created_at: datetime | None = None,
    ) -> tuple[Order, ...]:
        timestamp = created_at or signal.created_at
        execution = signal.metadata.get("execution", {})
        orders: list[Order] = []
        for leg in signal.legs:
            symbol = leg.contract.tradingsymbol
            order_type = self._order_type(execution, symbol)
            limit_price = self._decimal_value(execution.get("limit_prices"), symbol)
            trigger_price = self._decimal_value(execution.get("trigger_prices"), symbol)
            product = self._product(execution, symbol)
            orders.append(
                Order(
                    signal_id=signal.signal_id,
                    contract=leg.contract,
                    side=leg.side,
                    quantity=leg.quantity,
                    order_type=order_type,
                    product=product,
                    limit_price=limit_price,
                    trigger_price=trigger_price,
                    status=OrderStatus.VALIDATED,
                    created_at=timestamp,
                )
            )
        return tuple(orders)

    def simulate_pending(
        self,
        pending_orders: tuple[PendingOrderState, ...],
        *,
        context: ExecutionContext,
        strategy_id: str,
    ) -> tuple[tuple[PendingOrderState, ...], tuple[VirtualFill, ...]]:
        remaining: list[PendingOrderState] = []
        fills: list[VirtualFill] = []
        for pending in pending_orders:
            next_pending, pending_fills = self._process_order(
                pending=pending,
                context=context,
                strategy_id=strategy_id,
            )
            if next_pending is not None:
                remaining.append(next_pending)
            fills.extend(pending_fills)
        return tuple(remaining), tuple(fills)

    def _process_order(
        self,
        *,
        pending: PendingOrderState,
        context: ExecutionContext,
        strategy_id: str,
    ) -> tuple[PendingOrderState | None, tuple[VirtualFill, ...]]:
        quote = context.quote_for(pending.order.contract.tradingsymbol)
        candle = context.candle_for(pending.order.contract.tradingsymbol)
        fillable, reference_price, triggered = self._evaluate_fillability(
            order=pending.order,
            quote=quote,
            candle=candle,
            triggered=pending.triggered,
        )
        if not fillable or reference_price is None:
            updated_order = pending.order.model_copy(update={"status": OrderStatus.OPEN})
            return (
                pending.model_copy(update={"triggered": triggered, "order": updated_order}),
                (),
            )

        available_quantity = self._available_quantity(
            quote, pending.remaining_quantity, pending.order.contract.lot_size
        )
        if available_quantity <= 0:
            return (pending, ())
        slipped = self.slippage_model.apply(
            side=pending.order.side,
            reference_price=reference_price,
            spread=quote.spread if quote is not None else None,
        )
        costs = self.commission_model.calculate(
            side=pending.order.side,
            quantity=available_quantity,
            price=slipped,
        )
        fill = Fill(
            order_id=pending.order.id,
            quantity=available_quantity,
            price=slipped,
            timestamp=context.timestamp,
        )
        remaining_quantity = pending.remaining_quantity - available_quantity
        updated_order = pending.order.model_copy(
            update={"status": terminal_status(remaining_quantity)}
        )
        virtual_fill = VirtualFill(
            order=pending.order,
            fill=fill,
            updated_order=updated_order,
            cost_breakdown=costs,
            signal_id=pending.order.signal_id,
            strategy_id=strategy_id,
        )
        if remaining_quantity == 0:
            return None, (virtual_fill,)
        return (
            PendingOrderState(
                order=updated_order,
                remaining_quantity=remaining_quantity,
                triggered=triggered,
            ),
            (virtual_fill,),
        )

    def _available_quantity(
        self, quote: Quote | None, remaining_quantity: int, lot_size: int
    ) -> int:
        if quote is None or quote.volume <= 0:
            return remaining_quantity
        raw = int(quote.volume * self.config.max_volume_participation)
        if raw <= 0:
            return 0
        # Round down to a whole-lot boundary -- a real broker can never partially
        # fill you below one lot's granularity. Without this, a volume-capped
        # partial fill can leave a position holding a quantity that isn't a
        # multiple of its own contract's lot size (e.g. 59 units of a 65-lot
        # contract), and a later full-exit signal's `lots = quantity // lot_size`
        # silently floors to 0 -- rejected by `SignalLeg`'s own validation.
        # `available` can legitimately be 0 here (today's volume doesn't clear
        # even one lot) -- the caller already treats `<= 0` as "no fill this
        # tick, stay pending," which is the correct outcome, not "ignore the
        # volume cap and fill everything."
        available = raw - (raw % lot_size)
        return min(remaining_quantity, available)

    def _evaluate_fillability(
        self,
        *,
        order: Order,
        quote: Quote | None,
        candle: Candle | None,
        triggered: bool,
    ) -> tuple[bool, Decimal | None, bool]:
        market_price = self._market_price(order.side, quote)
        if order.order_type is OrderType.MARKET:
            return market_price is not None, market_price, triggered
        if order.order_type is OrderType.LIMIT:
            return (
                self._limit_fill(order, quote, candle),
                self._limit_price(order, quote),
                triggered,
            )
        if order.order_type in (OrderType.SL_LIMIT, OrderType.SL_MARKET):
            triggered_now = triggered or self._stop_triggered(order, quote, candle)
            if not triggered_now:
                return False, None, False
            if order.order_type is OrderType.SL_MARKET:
                return market_price is not None, market_price, True
            return self._limit_fill(order, quote, candle), self._limit_price(order, quote), True
        return False, None, triggered

    def _market_price(self, side: Side, quote: Quote | None) -> Decimal | None:
        if quote is None:
            return None
        if side is Side.BUY:
            return quote.ask if quote.ask is not None else quote.last_price
        return quote.bid if quote.bid is not None else quote.last_price

    def _limit_fill(self, order: Order, quote: Quote | None, candle: Candle | None) -> bool:
        if order.limit_price is None:
            return False
        if quote is not None:
            if order.side is Side.BUY and quote.ask is not None and quote.ask <= order.limit_price:
                return True
            if order.side is Side.SELL and quote.bid is not None and quote.bid >= order.limit_price:
                return True
        if candle is not None:
            if order.side is Side.BUY and candle.low <= order.limit_price:
                return True
            if order.side is Side.SELL and candle.high >= order.limit_price:
                return True
        return False

    def _limit_price(self, order: Order, quote: Quote | None) -> Decimal | None:
        if order.limit_price is None:
            return None
        market_price = self._market_price(order.side, quote)
        if market_price is None:
            return order.limit_price
        if order.side is Side.BUY:
            return min(order.limit_price, market_price)
        return max(order.limit_price, market_price)

    def _stop_triggered(
        self,
        order: Order,
        quote: Quote | None,
        candle: Candle | None,
    ) -> bool:
        trigger = order.trigger_price
        if trigger is None:
            return False
        if quote is not None:
            market_price = self._market_price(order.side, quote)
            if market_price is not None:
                if order.side is Side.BUY and market_price >= trigger:
                    return True
                if order.side is Side.SELL and market_price <= trigger:
                    return True
        if candle is not None:
            if order.side is Side.BUY and candle.high >= trigger:
                return True
            if order.side is Side.SELL and candle.low <= trigger:
                return True
        return False

    def _order_type(self, execution: Any, symbol: str) -> OrderType:
        raw = self._value_for_symbol(execution.get("order_types"), symbol)
        if raw is None:
            return self.config.default_order_type
        return OrderType(str(raw))

    def _product(self, execution: Any, symbol: str) -> ProductType:
        raw = self._value_for_symbol(execution.get("products"), symbol)
        if raw is None:
            return ProductType.NRML
        return ProductType(str(raw))

    def _decimal_value(self, raw: Any, symbol: str) -> Decimal | None:
        value = self._value_for_symbol(raw, symbol)
        if value is None:
            return None
        return Decimal(str(value))

    def _value_for_symbol(self, raw: Any, symbol: str) -> Any:
        if isinstance(raw, dict):
            return raw.get(symbol)
        return raw
