"""fact-check notes kept with each drafted day

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("days") as b:
        b.add_column(sa.Column("ai_flags", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("days") as b:
        b.drop_column("ai_flags")
