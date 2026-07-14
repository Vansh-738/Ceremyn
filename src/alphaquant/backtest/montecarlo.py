"""Monte Carlo analysis for equity outcomes."""

from decimal import Decimal

import numpy as np
from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.statistics import EquityPoint


class MonteCarloResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    simulations: tuple[tuple[float, ...], ...] = ()
    probability_of_ruin: float = 0.0
    expected_drawdown: float = 0.0
    confidence_interval_low: float = 0.0
    confidence_interval_high: float = 0.0


class MonteCarloSimulator:
    def run(
        self,
        *,
        equity_curve: tuple[EquityPoint, ...],
        iterations: int = 1000,
        ruin_threshold: Decimal = Decimal("0"),
        seed: int = 7,
    ) -> MonteCarloResult:
        if len(equity_curve) < 2:
            return MonteCarloResult()
        rng = np.random.default_rng(seed)
        returns = np.diff(np.array([float(point.equity) for point in equity_curve])) / np.array(
            [float(point.equity) for point in equity_curve[:-1]]
        )
        start_equity = float(equity_curve[0].equity)
        paths: list[tuple[float, ...]] = []
        ruin_count = 0
        drawdowns = []
        finals = []
        for _ in range(iterations):
            sampled = rng.choice(returns, size=len(returns), replace=True)
            equity = start_equity
            peak = equity
            path = [equity]
            max_drawdown = 0.0
            ruined = False
            for ret in sampled:
                equity *= 1.0 + float(ret)
                peak = max(peak, equity)
                max_drawdown = max(max_drawdown, peak - equity)
                if equity <= float(ruin_threshold):
                    ruined = True
                path.append(equity)
            paths.append(tuple(path))
            finals.append(equity)
            drawdowns.append(max_drawdown)
            if ruined:
                ruin_count += 1
        low, high = np.percentile(finals, [5, 95])
        return MonteCarloResult(
            simulations=tuple(paths),
            probability_of_ruin=ruin_count / iterations,
            expected_drawdown=float(np.mean(drawdowns)),
            confidence_interval_low=float(low),
            confidence_interval_high=float(high),
        )
