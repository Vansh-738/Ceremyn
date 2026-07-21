"""option_chain_eod: add lot_size

NSE revises index-option lot sizes periodically (NIFTY alone was 25, then 75, then
65 across 2024-2026) -- backtests were silently using a single hardcoded value for
the whole history. Bhavcopy's own `NewBrdLotQty` column carries the real per-row
value; this column lets that flow through instead.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "option_chain_eod",
        sa.Column("lot_size", sa.BigInteger, nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("option_chain_eod", "lot_size")
