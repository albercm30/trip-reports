"""keep the guide's own words for each species row

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sightings") as b:
        b.add_column(sa.Column("source", sa.String(length=200), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("sightings") as b:
        b.drop_column("source")
