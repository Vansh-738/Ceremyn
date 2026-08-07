"""Manual trade submission — a human placing one specific, deliberate order.

Structurally separate from `/dashboard` (read-only, never touches the OMS) and from
`/execution` (only arms/disarms the live-trading gate). This router is the one place
outside a `Strategy` that may construct a `Signal` and call `OrderManagementEngine.
submit_signal` -- every order still passes through the exact same `RiskEngine.
validate()` gate and `GatedBrokerAdapter` (paper unless all three live-trading gates
are open) that strategy-emitted signals do. Nothing here decides whether a trade is a
good idea; it only submits the one the caller explicitly asked for.

Equities have no static price of their own (unlike an option's strike), so the caller
must supply `reference_price` -- the risk engine has no safe silent default for it
(see `risk.context.RiskContext._reference_price`). In paper/simulated mode, note that
fills are currently only simulated against the live option-chain cache (see
`broker.simulated.SimulatedBroker._build_context`): an equity order will be risk-
validated and submitted correctly, but may sit open rather than auto-filling until a
live equity quote feed is wired into the simulator -- a known, documented gap, not a
silent failure.
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ceremyn.core.container import Container
from ceremyn.domain import EquityInstrument, Exchange, Signal, SignalAction, SignalLeg
from ceremyn.domain.enums import ProductType, Side
from ceremyn.oms.exceptions import OMSRiskRejectedError


class PlaceEquityTradeRequest(BaseModel):
    tradingsymbol: str = Field(min_length=1)
    side: Side
    quantity: int = Field(gt=0)
    reference_price: Decimal = Field(gt=0)
    product: ProductType = ProductType.CNC
    signal_type: SignalAction = SignalAction.ENTER


class PlacedOrderView(BaseModel):
    oms_order_id: str
    tradingsymbol: str
    side: str
    quantity: int
    product: str
    execution_state: str
    broker_name: str | None


def build_trading_router(container: Container) -> APIRouter:
    router = APIRouter()

    @router.post("/equity", response_model=list[PlacedOrderView], status_code=201)
    def place_equity_trade(request: PlaceEquityTradeRequest) -> list[PlacedOrderView]:
        contract = EquityInstrument(
            tradingsymbol=request.tradingsymbol,
            exchange=Exchange.NSE,
            underlying=request.tradingsymbol,
        )
        signal = Signal(
            strategy_id="manual",
            signal_type=request.signal_type,
            reason=(
                f"manual trade: {request.side.value} {request.quantity} "
                f"{request.tradingsymbol} @ {request.reference_price}"
            ),
            legs=(SignalLeg(contract=contract, side=request.side, lots=request.quantity),),
            metadata={
                "reference_prices": {request.tradingsymbol: str(request.reference_price)},
                "execution": {"products": {request.tradingsymbol: request.product.value}},
            },
        )
        try:
            orders = container.oms_engine.submit_signal(signal)
        except OMSRiskRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return [
            PlacedOrderView(
                oms_order_id=str(order.oms_order_id),
                tradingsymbol=order.order.contract.tradingsymbol,
                side=order.order.side.value,
                quantity=order.order.quantity,
                product=order.order.product.value,
                execution_state=order.execution_state.value,
                broker_name=order.broker_name,
            )
            for order in orders
        ]

    return router
