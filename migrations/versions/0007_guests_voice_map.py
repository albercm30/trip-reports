"""guests' QR page (emails, photos, review links), sighting positions for the map

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("review_google", sa.String(length=400), nullable=False, server_default=""))
        b.add_column(sa.Column("review_tripadvisor", sa.String(length=400), nullable=False, server_default=""))
        b.add_column(sa.Column("guest_token", sa.String(length=32), nullable=True))
        b.create_unique_constraint("uq_organizations_guest_token", ["guest_token"])
    with op.batch_alter_table("trips") as b:
        b.add_column(sa.Column("guest_token", sa.String(length=32), nullable=True))
        b.add_column(sa.Column("guests_closed", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("report_sent_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("show_map", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.create_unique_constraint("uq_trips_guest_token", ["guest_token"])
    op.create_table(
        "points",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("day_id", sa.String(length=16), sa.ForeignKey("days.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("accuracy", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_id", sa.String(length=40), nullable=True),
    )
    op.create_index("ix_points_day_id", "points", ["day_id"])
    op.create_index("ix_points_client_id", "points", ["client_id"])
    op.create_table(
        "guests",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("trip_id", sa.String(length=16), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("news", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lang", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("trip_id", "email"),
    )
    op.create_index("ix_guests_trip_id", "guests", ["trip_id"])
    op.create_index("ix_guests_org_id", "guests", ["org_id"])
    op.create_table(
        "guest_photos",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("trip_id", sa.String(length=16), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("author", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_guest_photos_trip_id", "guest_photos", ["trip_id"])
    op.create_index("ix_guest_photos_org_id", "guest_photos", ["org_id"])


def downgrade() -> None:
    op.drop_table("guest_photos")
    op.drop_table("guests")
    op.drop_table("points")
    with op.batch_alter_table("trips") as b:
        b.drop_constraint("uq_trips_guest_token", type_="unique")
        for c in ("show_map", "report_sent_at", "guests_closed", "guest_token"):
            b.drop_column(c)
    with op.batch_alter_table("organizations") as b:
        b.drop_constraint("uq_organizations_guest_token", type_="unique")
        for c in ("guest_token", "review_tripadvisor", "review_google"):
            b.drop_column(c)
