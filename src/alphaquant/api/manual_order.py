"""Manual order ticket — lets the operator place a real order by hand: pick an option
contract (underlying + expiry + strike + CE/PE), see its live premium, choose quantity
(lots) and buy/sell, submit. Structurally separate from `/dashboard` (never imported by
it — the "dashboard never places orders" import-linter contract stays untouched) and from
`/execution`, mirroring both routers' shape (`api/execution.py`, `api/llm.py`).

Hard invariant: a manual order is built into exactly the `Signal` shape a strategy would
emit and flows through the identical `RiskEngine.validate() -> OMSEngine.submit_signal() ->
GatedBrokerAdapter` path (`oms/engine.py::OrderManagementEngine.submit_signal`) — there is
no separate, shortcut path to a broker here. The three live-trading gates and every risk
rule apply exactly as they do to an algorithmic signal.

v1 scope: opening positions only (`SignalAction.ENTER`), market orders only (leaving
`Signal.metadata` empty is what makes `OrderPlanner.intent_from_signal` default to
`ExecutionStyle.MARKET`). Closing an existing position via the ticket, and limit-price
support, are natural fast-follows, not built here.

Auth: read endpoints (underlyings/expiries/chain) use the existing `Permission.
VIEW_DASHBOARD` — same trust level as viewing the dashboard. `POST /submit` requires
`Permission.SUBMIT_ORDER`, granted only to `Role.ADMIN` — and since `resolve_role` always
returns VIEWER when `auth_enabled` is False (the out-of-the-box default), submitting an
order is unreachable until the operator deliberately enables auth and configures a real
admin token. No order — not even a simulated one — is placeable on an unconfigured instance.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from alphaquant.api.auth import require_permission
from alphaquant.core.exceptions import BrokerError
from alphaquant.core.timeutils import now_ist
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import Permission
from alphaquant.data.repositories.instruments import InstrumentRepository
from alphaquant.data.services.snapshots import ChainService
from alphaquant.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from alphaquant.oms.engine import OrderManagementEngine
from alphaquant.oms.exceptions import (
    OMSDuplicateRequestError,
    OMSKillSwitchActiveError,
    OMSRiskRejectedError,
)
from alphaquant.oms.orders import OMSOrder


class UnderlyingsResponse(BaseModel):
    underlyings: tuple[str, ...]


class ExpiriesResponse(BaseModel):
    expiries: list[date]


class ChainEntryDTO(BaseModel):
    strike: Decimal
    option_type: Literal["CE", "PE"]
    tradingsymbol: str
    lot_size: int
    last_price: Decimal | None = None


class ChainResponse(BaseModel):
    underlying: str
    expiry: date
    spot: Decimal
    atm_strike: Decimal
    entries: list[ChainEntryDTO]


class SubmitOrderRequest(BaseModel):
    underlying: str = Field(min_length=1)
    expiry: date
    strike: Decimal = Field(gt=0)
    option_type: Literal["CE", "PE"]
    side: Literal["BUY", "SELL"]
    lots: int = Field(gt=0)
    reason: str = ""


class OMSOrderSummary(BaseModel):
    oms_order_id: UUID
    tradingsymbol: str
    side: str
    quantity: int
    execution_state: str
    broker_name: str | None
    last_error: str


class SubmitOrderResponse(BaseModel):
    orders: list[OMSOrderSummary]


def _order_summary(order: OMSOrder) -> OMSOrderSummary:
    return OMSOrderSummary(
        oms_order_id=order.oms_order_id,
        tradingsymbol=order.order.contract.tradingsymbol,
        side=order.order.side.value,
        quantity=order.order.quantity,
        execution_state=order.execution_state.value,
        broker_name=order.broker_name,
        last_error=order.last_error,
    )


def build_manual_order_router(
    *,
    chain_service_factory: Callable[[], ChainService],
    instruments: InstrumentRepository,
    oms_engine: OrderManagementEngine,
    underlyings: tuple[str, ...],
    settings: DashboardSettings,
) -> APIRouter:
    """`chain_service_factory` is a lazy factory, not a resolved instance: `ChainService`
    transitively constructs a `KiteProvider`, which raises `BrokerError` without
    `ALPHAQUANT_KITE__API_KEY` configured (see `data/providers/kite.py::from_settings`).
    Passing the resolved `Container.chain_service` here would raise at *mount* time on
    every credential-less dev/test instance; calling the factory only inside `/chain`
    (already wrapped in `except BrokerError`) defers that failure to first real use,
    matching the `kite_broker`/`llm_client` lazy-construction pattern used everywhere
    else credentials are involved.
    """
    router = APIRouter()
    view = Depends(require_permission(Permission.VIEW_DASHBOARD, settings))
    submit_order = Depends(require_permission(Permission.SUBMIT_ORDER, settings))

    @router.get("/underlyings", response_model=UnderlyingsResponse, dependencies=[view])
    def list_underlyings() -> UnderlyingsResponse:
        return UnderlyingsResponse(underlyings=underlyings)

    @router.get("/expiries", response_model=ExpiriesResponse, dependencies=[view])
    async def list_expiries(underlying: str) -> ExpiriesResponse:
        if underlying not in underlyings:
            raise HTTPException(status_code=400, detail=f"unknown underlying {underlying!r}")
        expiries = await instruments.expiries(underlying, now_ist().date())
        return ExpiriesResponse(expiries=expiries)

    @router.get("/chain", response_model=ChainResponse, dependencies=[view])
    async def get_chain(underlying: str, expiry: date) -> ChainResponse:
        if underlying not in underlyings:
            raise HTTPException(status_code=400, detail=f"unknown underlying {underlying!r}")
        try:
            snapshot = await chain_service_factory().build(underlying, expiry)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except BrokerError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        entries = [
            ChainEntryDTO(
                strike=entry.contract.strike,
                option_type=entry.contract.option_type.value,
                tradingsymbol=entry.contract.tradingsymbol,
                lot_size=entry.contract.lot_size,
                last_price=entry.quote.last_price if entry.quote is not None else None,
            )
            for entry in snapshot.entries
        ]
        return ChainResponse(
            underlying=snapshot.underlying,
            expiry=snapshot.expiry,
            spot=snapshot.spot,
            atm_strike=snapshot.atm_strike,
            entries=entries,
        )

    @router.post("/submit", response_model=SubmitOrderResponse, dependencies=[submit_order])
    async def submit(request: SubmitOrderRequest) -> SubmitOrderResponse:
        if request.underlying not in underlyings:
            raise HTTPException(
                status_code=400, detail=f"unknown underlying {request.underlying!r}"
            )
        option_type = OptionType(request.option_type)
        contracts = await instruments.list_contracts(request.underlying, request.expiry)
        contract = next(
            (c for c in contracts if c.strike == request.strike and c.option_type is option_type),
            None,
        )
        if contract is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"no such contract for {request.underlying} {request.expiry} "
                    f"{request.strike} {request.option_type}"
                ),
            )
        signal = Signal(
            strategy_id="manual",
            signal_type=SignalAction.ENTER,
            reason=request.reason or "manual order ticket",
            legs=(SignalLeg(contract=contract, side=Side(request.side), lots=request.lots),),
        )
        try:
            orders = oms_engine.submit_signal(signal)
        except OMSRiskRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OMSDuplicateRequestError as exc:
            raise HTTPException(status_code=409, detail=f"duplicate order: {exc}") from exc
        except OMSKillSwitchActiveError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BrokerError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SubmitOrderResponse(orders=[_order_summary(order) for order in orders])

    return router
