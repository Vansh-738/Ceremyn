"""Broker abstraction placeholder package for architectural boundary checks."""

from alphaquant.broker.adapter import NullBrokerAdapter
from alphaquant.broker.simulated import SimulatedBroker

__all__ = ["NullBrokerAdapter", "SimulatedBroker"]
