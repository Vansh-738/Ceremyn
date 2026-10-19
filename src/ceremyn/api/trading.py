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
(see `risk.context.RiskContext._reference_price`). In paper/simulated mode, an equity
can fill only from a real quote in `LiveDataCache`; an unavailable quote leaves the
order open rather than turning the caller's risk reference into fabricated market data.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ceremyn.config.modes import TradingMode
from ceremyn.core.container import Container
from ceremyn.dashboard.config import DashboardSettings
from ceremyn.dashboard.permissions import (
    AuthError,
    ForbiddenError,
    Permission,
    Role,
    authorize,
    bearer_token,
)
from ceremyn.domain import EquityInstrument, Exchange, Quote, Signal, SignalAction, SignalLeg
from ceremyn.domain.enums import ProductType, Side
from ceremyn.oms.exceptions import OMSRiskRejectedError

logger = structlog.get_logger(__name__)


class PlaceEquityTradeRequest(BaseModel):
    tradingsymbol: str = Field(min_length=1)
    side: Side
    quantity: int = Field(gt=0)
    reference_price: Decimal = Field(gt=0)
    product: Literal[ProductType.CNC] = ProductType.CNC
    signal_type: SignalAction = SignalAction.ENTER


class PlacedOrderView(BaseModel):
    oms_order_id: str
    tradingsymbol: str
    side: str
    quantity: int
    product: str
    execution_state: str
    broker_name: str | None


def _admin_dependency(settings: DashboardSettings) -> Callable[[str | None], Role]:
    def dependency(authorization: str | None = Header(default=None)) -> Role:
        try:
            return authorize(bearer_token(authorization), Permission.PLACE_TRADES, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return dependency


async def _cache_current_equity_quote(container: Container, tradingsymbol: str) -> None:
    """Best-effort quote refresh; failure must never manufacture a paper fill."""
    symbol = f"NSE:{tradingsymbol}"
    try:
        quote = (await container.kite_provider.quotes([symbol])).get(symbol)
    except Exception:
        logger.info("equity_quote_refresh_unavailable", tradingsymbol=tradingsymbol)
        return
    if quote is not None:
        container.live_engine.cache.set_quote(quote)


def _risk_reference_price(
    *, supplied_price: Decimal, cached_quote: Quote | None, max_deviation_ratio: Decimal
) -> Decimal:
    """Size a manual equity trade conservatively and catch fat-fingered prices."""
    if cached_quote is None or cached_quote.last_price <= 0:
        return supplied_price
    deviation_ratio = abs(supplied_price - cached_quote.last_price) / cached_quote.last_price
    if deviation_ratio > max_deviation_ratio:
        raise HTTPException(
            status_code=422,
            detail=(
                "reference_price differs from the current equity quote by more than "
                f"the configured {max_deviation_ratio:.2%} limit"
            ),
        )
    # The order must never look smaller to risk controls than the market price.
    return max(supplied_price, cached_quote.last_price)


def build_trading_router(container: Container, settings: DashboardSettings) -> APIRouter:
    router = APIRouter()
    place_trades = Depends(_admin_dependency(settings))

    @router.post(
        "/equity",
        response_model=list[PlacedOrderView],
        status_code=201,
        dependencies=[place_trades],
    )
    async def place_equity_trade(request: PlaceEquityTradeRequest) -> list[PlacedOrderView]:
        if not settings.auth_enabled and container.settings.effective_mode is TradingMode.LIVE:
            raise HTTPException(
                status_code=403,
                detail="manual equity orders require dashboard authentication in live mode",
            )
        await _cache_current_equity_quote(container, request.tradingsymbol)
        risk_reference_price = _risk_reference_price(
            supplied_price=request.reference_price,
            cached_quote=container.live_engine.cache.latest_quote(request.tradingsymbol),
            max_deviation_ratio=container.settings.risk.equity.max_reference_price_deviation_ratio,
        )
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
                f"{request.tradingsymbol} @ {risk_reference_price}"
            ),
            legs=(SignalLeg(contract=contract, side=request.side, lots=request.quantity),),
            metadata={
                "reference_prices": {request.tradingsymbol: str(risk_reference_price)},
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
