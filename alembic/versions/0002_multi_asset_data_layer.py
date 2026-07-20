"""multi-asset data layer: instruments.asset_class/isin, future_chain_eod, corporate_actions

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE = sa.Numeric(14, 4)


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("asset_class", sa.Text, nullable=False, server_default="OPTION"),
    )
    op.add_column("instruments", sa.Column("isin", sa.Text))

    op.create_table(
        "future_chain_eod",
        sa.Column("trade_date", sa.Date, primary_key=True),
        sa.Column("underlying", sa.Text, primary_key=True),
        sa.Column("expiry", sa.Date, primary_key=True),
        sa.Column("open", PRICE),
        sa.Column("high", PRICE),
        sa.Column("low", PRICE),
        sa.Column("close", PRICE),
        sa.Column("settle", PRICE),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("open_interest", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("oi_change", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("underlying_close", PRICE),
    )
    op.create_index(
        "ix_future_chain_eod_underlying_date", "future_chain_eod", ["underlying", "trade_date"]
    )

    op.create_table(
        "corporate_actions",
        sa.Column("tradingsymbol", sa.Text, primary_key=True),
        sa.Column("ex_date", sa.Date, primary_key=True),
        sa.Column("action_type", sa.Text, primary_key=True),
        sa.Column("ratio", sa.Numeric(12, 4)),
        sa.Column("dividend_amount", sa.Numeric(12, 4)),
    )


def downgrade() -> None:
    op.drop_table("corporate_actions")
    op.drop_index("ix_future_chain_eod_underlying_date", table_name="future_chain_eod")
    op.drop_table("future_chain_eod")
    op.drop_column("instruments", "isin")
    op.drop_column("instruments", "asset_class")
