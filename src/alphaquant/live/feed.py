"""Feed-side catalog and subscription management."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from alphaquant.domain import OptionContract
from alphaquant.live.exceptions import LiveConfigurationError
from alphaquant.live.snapshot import InstrumentKind


class SubscriptionMode(StrEnum):
    FULL = "full"
    LTP = "ltp"
    QUOTE = "quote"


@dataclass(frozen=True)
class UnderlyingDefinition:
    name: str
    index_symbol: str
    index_token: int


@dataclass(frozen=True)
class InstrumentDescriptor:
    instrument_token: int
    tradingsymbol: str
    underlying: str
    instrument_kind: InstrumentKind
    subscription_mode: SubscriptionMode
    expiry: date | None = None
    contract: OptionContract | None = None


@dataclass(frozen=True)
class SubscriptionPlan:
    instruments: tuple[InstrumentDescriptor, ...]

    @property
    def all_tokens(self) -> tuple[int, ...]:
        return tuple(instrument.instrument_token for instrument in self.instruments)

    def tokens_for_mode(self, mode: SubscriptionMode) -> tuple[int, ...]:
        return tuple(
            instrument.instrument_token
            for instrument in self.instruments
            if instrument.subscription_mode is mode
        )


class StreamingClient(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def subscribe(self, instrument_tokens: Sequence[int]) -> None: ...

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None: ...

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None: ...


class SubscriptionManager:
    def __init__(self, client: StreamingClient) -> None:
        self._client = client
        self._active = SubscriptionPlan(())

    @property
    def active(self) -> SubscriptionPlan:
        return self._active

    def connect(self) -> None:
        self._client.connect()

    def close(self) -> None:
        self._client.close()

    def apply(self, plan: SubscriptionPlan) -> None:
        current = set(self._active.all_tokens)
        target = set(plan.all_tokens)
        to_unsubscribe = [token for token in self._active.all_tokens if token not in target]
        to_subscribe = [token for token in plan.all_tokens if token not in current]
        if to_unsubscribe:
            self._client.unsubscribe(to_unsubscribe)
        if to_subscribe:
            self._client.subscribe(to_subscribe)
        for mode in SubscriptionMode:
            tokens = plan.tokens_for_mode(mode)
            if tokens:
                self._client.set_mode(mode.value, tokens)
        self._active = plan

    def restore(self) -> None:
        if not self._active.instruments:
            return
        self._client.subscribe(self._active.all_tokens)
        for mode in SubscriptionMode:
            tokens = self._active.tokens_for_mode(mode)
            if tokens:
                self._client.set_mode(mode.value, tokens)


def build_subscription_plan(
    *,
    underlyings: Iterable[UnderlyingDefinition],
    contracts: Iterable[OptionContract],
) -> SubscriptionPlan:
    descriptors: list[InstrumentDescriptor] = []
    for underlying in underlyings:
        descriptors.append(
            InstrumentDescriptor(
                instrument_token=underlying.index_token,
                tradingsymbol=underlying.index_symbol,
                underlying=underlying.name,
                instrument_kind=InstrumentKind.INDEX,
                subscription_mode=SubscriptionMode.QUOTE,
            )
        )
    for contract in contracts:
        if contract.broker_token is None:
            raise LiveConfigurationError(
                f"contract {contract.tradingsymbol} is missing broker_token"
            )
        descriptors.append(
            InstrumentDescriptor(
                instrument_token=contract.broker_token,
                tradingsymbol=contract.tradingsymbol,
                underlying=contract.underlying,
                instrument_kind=InstrumentKind.OPTION,
                subscription_mode=SubscriptionMode.FULL,
                expiry=contract.expiry,
                contract=contract,
            )
        )
    if not descriptors:
        raise LiveConfigurationError("subscription plan cannot be empty")
    return SubscriptionPlan(instruments=tuple(descriptors))
