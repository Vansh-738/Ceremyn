"""O(1) in-memory caches for live market state."""

from decimal import Decimal

from alphaquant.domain import OptionChainSnapshot
from alphaquant.features.models import FeatureSet
from alphaquant.live.snapshot import MarketSnapshot


class LiveDataCache:
    def __init__(self) -> None:
        self._snapshots: dict[str, MarketSnapshot] = {}
        self._chains: dict[str, OptionChainSnapshot] = {}
        self._spots: dict[str, Decimal] = {}
        self._features: dict[str, FeatureSet] = {}

    def set_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._snapshots[snapshot.underlying] = snapshot
        self._chains[snapshot.underlying] = snapshot.option_chain
        self._spots[snapshot.underlying] = snapshot.spot
        if snapshot.features is not None:
            self._features[snapshot.underlying] = snapshot.features

    def set_chain(self, chain: OptionChainSnapshot) -> None:
        self._chains[chain.underlying] = chain
        self._spots[chain.underlying] = chain.spot

    def latest_snapshot(self, underlying: str) -> MarketSnapshot | None:
        return self._snapshots.get(underlying)

    def latest_chain(self, underlying: str) -> OptionChainSnapshot | None:
        return self._chains.get(underlying)

    def latest_spot(self, underlying: str) -> Decimal | None:
        return self._spots.get(underlying)

    def latest_features(self, underlying: str) -> FeatureSet | None:
        return self._features.get(underlying)
