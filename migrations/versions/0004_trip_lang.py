"""report language per trip

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trips") as b:
        b.add_column(sa.Column("lang", sa.String(length=2), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("trips") as b:
        b.drop_column("lang")
