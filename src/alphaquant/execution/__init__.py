"""Execution layer: the real Kite broker, the triple-gate, and the wrapper that ties them
to OMS. Nothing outside this package (and its composition-root wiring) knows the gates or
the concrete broker exist.
"""

from alphaquant.execution.gate import GateEvent, LiveTradingGate
from alphaquant.execution.gated_broker import GatedBrokerAdapter
from alphaquant.execution.kite_broker import KiteBroker

__all__ = ["GateEvent", "GatedBrokerAdapter", "KiteBroker", "LiveTradingGate"]
