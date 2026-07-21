"""Runtime arming for gate #3 of live trading — a small, separate router, structurally
independent from the read-only `/dashboard` mount (which never imports `execution`/`broker`
at all — see the "Dashboard cannot place orders or bypass the OMS" import-linter contract).

Arming requires a pre-configured secret (`Settings.execution.arming_secret`) and gates #1-#2
already open; disarming requires nothing, since making the system safer is never gated.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ceremyn.config import Settings
from ceremyn.core.exceptions import LiveTradingLockedError
from ceremyn.execution.gate import LiveTradingGate


class ArmRequest(BaseModel):
    token: str
    reason: str = ""


class DisarmRequest(BaseModel):
    reason: str = ""


class ExecutionStatus(BaseModel):
    armed: bool
    live_trading_permitted: bool
    active_broker: str


def _status(gate: LiveTradingGate, settings: Settings) -> ExecutionStatus:
    permitted = gate.permits_live_trading(settings)
    return ExecutionStatus(
        armed=gate.is_armed,
        live_trading_permitted=permitted,
        active_broker="kite" if permitted else "simulated",
    )


def build_execution_router(gate: LiveTradingGate, settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/arm", response_model=ExecutionStatus)
    def arm(request: ArmRequest) -> ExecutionStatus:
        secret = settings.execution.arming_secret.get_secret_value()
        if not secret or request.token != secret:
            raise HTTPException(status_code=403, detail="invalid arming token")
        try:
            gate.arm(settings=settings, reason=request.reason)
        except LiveTradingLockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _status(gate, settings)

    @router.post("/disarm", response_model=ExecutionStatus)
    def disarm(request: DisarmRequest | None = None) -> ExecutionStatus:
        gate.disarm(reason=request.reason if request is not None else "")
        return _status(gate, settings)

    @router.get("/status", response_model=ExecutionStatus)
    def status() -> ExecutionStatus:
        return _status(gate, settings)

    return router
