"""Execution layer: the real Kite broker, the triple-gate, and the wrapper that ties them
to OMS. Nothing outside this package (and its composition-root wiring) knows the gates or
the concrete broker exist.
"""

from ceremyn.execution.gate import GateEvent, LiveTradingGate
from ceremyn.execution.gated_broker import GatedBrokerAdapter
from ceremyn.execution.kite_broker import KiteBroker

__all__ = ["GateEvent", "GatedBrokerAdapter", "KiteBroker", "LiveTradingGate"]
