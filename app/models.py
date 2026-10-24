from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return secrets.token_hex(8)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes from the DB as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), default="")
    accent: Mapped[str] = mapped_column(String(7), default="#2E6A5C")
    tone: Mapped[str] = mapped_column(String(16), default="warm")
    report_lang: Mapped[str] = mapped_column(String(2), default="en")
    website: Mapped[str] = mapped_column(String(200), default="")
    signoff: Mapped[str] = mapped_column(Text, default="")
    show_credit: Mapped[bool] = mapped_column(Boolean, default=True)
    targets: Mapped[str] = mapped_column(Text, default="")
    logo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data_sharing: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[str] = mapped_column(String(16), default="trial")  # trial | starter | pro
    billing_status: Mapped[str] = mapped_column(String(24), default="trialing")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    users: Mapped[list[User]] = relationship(back_populates="org", cascade="all, delete-orphan")
    trips: Mapped[list[Trip]] = relationship(back_populates="org", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="owner")  # owner | guide
    ui_lang: Mapped[str] = mapped_column(String(2), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[Organization] = relationship(back_populates="users")

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(200), default="")


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254), default="")
    role: Mapped[str] = mapped_column(String(16), default="guide")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    guests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guides: Mapped[str] = mapped_column(String(200), default="")
    intro: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    share_token: Mapped[str | None] = mapped_column(String(48), unique=True, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    org: Mapped[Organization] = relationship(back_populates="trips")
    days: Mapped[list[Day]] = relationship(back_populates="trip", cascade="all, delete-orphan",
                                           order_by="Day.position")


class Day(Base):
    __tablename__ = "days"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    place: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    raw_tally: Mapped[str] = mapped_column(Text, default="")
    narrative: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trip: Mapped[Trip] = relationship(back_populates="days")
    sightings: Mapped[list[Sighting]] = relationship(back_populates="day", cascade="all, delete-orphan",
                                                     order_by="Sighting.position")
    photos: Mapped[list[Photo]] = relationship(back_populates="day", cascade="all, delete-orphan",
                                               order_by="Photo.position")


class Sighting(Base):
    __tablename__ = "sightings"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    day_id: Mapped[str] = mapped_column(ForeignKey("days.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120), default="")
    sci: Mapped[str] = mapped_column(String(120), default="")
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heard: Mapped[bool] = mapped_column(Boolean, default=False)
    sure: Mapped[bool] = mapped_column(Boolean, default=True)
    star: Mapped[bool] = mapped_column(Boolean, default=False)
    group: Mapped[str] = mapped_column(String(40), default="")
    taxon_key: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taxon_status: Mapped[str] = mapped_column(String(12), default="unchecked")  # matched|unmatched|unchecked

    day: Mapped[Day] = relationship(back_populates="sightings")


class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    day_id: Mapped[str] = mapped_column(ForeignKey("days.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str] = mapped_column(String(16), index=True)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    caption: Mapped[str] = mapped_column(String(300), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)

    day: Mapped[Day] = relationship(back_populates="photos")


class AIUsage(Base):
    __tablename__ = "ai_usage"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Blob(Base):
    """Image bytes when STORAGE=db (no separate file storage needed)."""
    __tablename__ = "blobs"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = ["Organization", "User", "AuthSession", "Invite", "PasswordReset", "Trip", "Day",
           "Sighting", "Photo", "AIUsage", "Blob", "StripeEvent", "new_id", "utcnow", "aware",
           "UniqueConstraint"]
