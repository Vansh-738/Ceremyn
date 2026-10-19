"""O(1) in-memory caches for live market state."""

from decimal import Decimal

from ceremyn.domain import OptionChainSnapshot, Quote
from ceremyn.features.models import FeatureSet
from ceremyn.live.snapshot import MarketSnapshot


class LiveDataCache:
    def __init__(self) -> None:
        self._snapshots: dict[str, MarketSnapshot] = {}
        self._chains: dict[str, OptionChainSnapshot] = {}
        self._spots: dict[str, Decimal] = {}
        self._quotes: dict[str, Quote] = {}
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

    def set_quote(self, quote: Quote) -> None:
        """Store an externally sourced quote by its exact trading symbol.

        This supports cash-equity paper fills without treating a caller-provided
        reference price as market data.
        """
        self._quotes[quote.tradingsymbol] = quote

    def set_quotes(self, quotes: tuple[Quote, ...]) -> None:
        for quote in quotes:
            self.set_quote(quote)

    def latest_snapshot(self, underlying: str) -> MarketSnapshot | None:
        return self._snapshots.get(underlying)

    def latest_chain(self, underlying: str) -> OptionChainSnapshot | None:
        return self._chains.get(underlying)

    def latest_spot(self, underlying: str) -> Decimal | None:
        return self._spots.get(underlying)

    def latest_quote(self, tradingsymbol: str) -> Quote | None:
        return self._quotes.get(tradingsymbol)

    def latest_features(self, underlying: str) -> FeatureSet | None:
        return self._features.get(underlying)
