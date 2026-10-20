"""Bar-driven execution through the existing OMS; never hands a broker to a strategy."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from ceremyn.oms.engine import OrderManagementEngine
from ceremyn.oms.orders import OMSOrder
from ceremyn.runtime.rest_poller import _strategy_positions
from ceremyn.strategies.bars import BarContext
from ceremyn.strategies.base import Strategy


class BarStrategyDriver:
    def __init__(self, strategy: Strategy[Any], oms: OrderManagementEngine) -> None:
        self.strategy = strategy
        self.oms = oms

    def on_bar(
        self,
        context: BarContext,
        *,
        now: datetime | None = None,
        reference_price: Decimal | None = None,
    ) -> tuple[OMSOrder, ...]:
        context = context.model_copy(
            update={
                "portfolio": self.oms.portfolio.snapshot(),
                "positions": _strategy_positions(self.oms, self.strategy.definition.id),
            }
        )
        signals = self.strategy.on_bar(context)
        if now is not None:
            if now < context.as_of or reference_price is None or reference_price <= 0:
                raise ValueError("runtime needs a current price and a completed bar")
            signals = [
                signal.model_copy(
                    update={
                        "created_at": now,
                        "market_timestamp": now,
                        "metadata": {
                            **signal.metadata,
                            "reference_prices": {
                                context.instrument.tradingsymbol: str(
                                    max(reference_price, context.candles[-1].close)
                                )
                            },
                        },
                    }
                )
                for signal in signals
            ]
        return self.oms.submit_correlated_signals(signals, now=now or context.as_of)
