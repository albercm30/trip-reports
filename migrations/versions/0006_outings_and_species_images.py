"""single-day outings mode, species reference photos

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("single_day", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("species_photos", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "species_images",
        sa.Column("sci", sa.String(length=160), primary_key=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("credit", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("license", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("page", sa.Text(), nullable=False, server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("species_images")
    with op.batch_alter_table("organizations") as b:
        b.drop_column("species_photos")
        b.drop_column("single_day")
