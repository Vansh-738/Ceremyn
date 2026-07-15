from decimal import Decimal

from alphaquant.strategies.common import exit_reason_from_pnl_pct, net_pnl_pct


class TestNetPnlPct:
    def test_credit_position_profit(self) -> None:
        assert net_pnl_pct(Decimal("7500"), Decimal("-3000")) == 60.0

    def test_debit_position_profit(self) -> None:
        assert net_pnl_pct(Decimal("-7500"), Decimal("12000")) == 60.0

    def test_zero_entry_cashflow_is_zero(self) -> None:
        assert net_pnl_pct(Decimal("0"), Decimal("500")) == 0.0


class TestExitReasonFromPnlPct:
    def test_profit_target(self) -> None:
        reason = exit_reason_from_pnl_pct(60.0, profit_target_pct=50.0, stop_loss_pct=100.0)
        assert reason is not None
        assert "profit target" in reason

    def test_stop_loss(self) -> None:
        reason = exit_reason_from_pnl_pct(-60.0, profit_target_pct=50.0, stop_loss_pct=50.0)
        assert reason is not None
        assert "stop loss" in reason

    def test_none_within_bands(self) -> None:
        assert exit_reason_from_pnl_pct(10.0, profit_target_pct=50.0, stop_loss_pct=100.0) is None
