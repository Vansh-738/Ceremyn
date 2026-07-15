"""The flat M11 metric catalog, mapped from existing snapshots."""

from alphaquant.backtest.statistics import BacktestStatistics
from alphaquant.dashboard.models import GreeksView, MetricsView
from alphaquant.domain import PortfolioSnapshot
from alphaquant.live.metrics import LiveMetricsSnapshot
from alphaquant.oms.metrics import OMSMetricsSnapshot


def build_metrics(
    *,
    portfolio: PortfolioSnapshot | None = None,
    oms_metrics: OMSMetricsSnapshot | None = None,
    live_metrics: LiveMetricsSnapshot | None = None,
    open_orders: int = 0,
    statistics: BacktestStatistics | None = None,
    feature_cache_hit_rate: float = 0.0,
    experiment_count: int = 0,
) -> MetricsView:
    greeks = GreeksView()
    pnl = 0.0
    drawdown = 0.0
    gross_exposure = 0.0
    if portfolio is not None:
        pnl = float(portfolio.realized_pnl + portfolio.unrealized_pnl)
        drawdown = float(portfolio.drawdown)
        gross_exposure = float(portfolio.exposure.gross_notional)
        pg = portfolio.portfolio_greeks
        greeks = GreeksView(
            delta=pg.delta, gamma=pg.gamma, theta=pg.theta, vega=pg.vega, rho=pg.rho
        )
    return MetricsView(
        pnl=round(pnl, 6),
        drawdown=round(drawdown, 6),
        sharpe=statistics.sharpe if statistics is not None else 0.0,
        greeks=greeks,
        gross_exposure=round(gross_exposure, 6),
        open_orders=open_orders,
        filled_orders=oms_metrics.orders_filled if oms_metrics is not None else 0,
        rejected_orders=oms_metrics.rejections if oms_metrics is not None else 0,
        broker_latency_seconds=(
            oms_metrics.broker_latency_seconds if oms_metrics is not None else 0.0
        ),
        reconnect_count=live_metrics.reconnect_count if live_metrics is not None else 0,
        heartbeat_delay_seconds=(
            live_metrics.heartbeat_delay_seconds if live_metrics is not None else 0.0
        ),
        feature_cache_hit_rate=round(feature_cache_hit_rate, 6),
        experiment_count=experiment_count,
    )
