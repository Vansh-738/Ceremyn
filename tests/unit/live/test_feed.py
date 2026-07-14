from collections.abc import Sequence

import pytest

from alphaquant.live.exceptions import LiveConfigurationError
from alphaquant.live.feed import SubscriptionManager, SubscriptionMode, build_subscription_plan
from tests.unit.live.conftest import CALL_TOKEN, INDEX_TOKEN, PUT_TOKEN


class FakeClient:
    def __init__(self) -> None:
        self.subscribed: list[list[int]] = []
        self.unsubscribed: list[list[int]] = []
        self.modes: list[tuple[str, list[int]]] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.subscribed.append(list(instrument_tokens))

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.unsubscribed.append(list(instrument_tokens))

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.modes.append((mode, list(instrument_tokens)))


def test_build_subscription_plan_groups_tokens(underlyings, contracts) -> None:
    plan = build_subscription_plan(underlyings=underlyings, contracts=contracts)
    assert plan.all_tokens == (INDEX_TOKEN, CALL_TOKEN, PUT_TOKEN)
    assert plan.tokens_for_mode(SubscriptionMode.QUOTE) == (INDEX_TOKEN,)
    assert plan.tokens_for_mode(SubscriptionMode.FULL) == (CALL_TOKEN, PUT_TOKEN)


def test_build_subscription_plan_requires_broker_token(underlyings, contracts) -> None:
    missing = (contracts[0].model_copy(update={"broker_token": None}), contracts[1])
    with pytest.raises(LiveConfigurationError, match="missing broker_token"):
        build_subscription_plan(underlyings=underlyings, contracts=missing)


def test_subscription_manager_applies_and_restores(underlyings, contracts) -> None:
    client = FakeClient()
    manager = SubscriptionManager(client)
    plan = build_subscription_plan(underlyings=underlyings, contracts=contracts)

    manager.apply(plan)
    manager.restore()

    assert client.subscribed == [
        [INDEX_TOKEN, CALL_TOKEN, PUT_TOKEN],
        [INDEX_TOKEN, CALL_TOKEN, PUT_TOKEN],
    ]
    assert client.unsubscribed == []
    assert ("quote", [INDEX_TOKEN]) in client.modes
    assert ("full", [CALL_TOKEN, PUT_TOKEN]) in client.modes
