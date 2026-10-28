"""Plans, limits and what an organization is allowed to do right now."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AIUsage, Organization, User, aware

PLANS = {
    # Prices shown on the site; the real prices live in Stripe.
    "trial": {"seats": 2, "ai_per_month": 150, "month_eur": 0, "year_eur": 0},
    "starter": {"seats": 2, "ai_per_month": 400, "month_eur": 29, "year_eur": 290},
    "pro": {"seats": 8, "ai_per_month": 2000, "month_eur": 59, "year_eur": 590},
    # Pilot companies: free with no end date while the product is being built. Only an admin sets it.
    "pilot": {"seats": 8, "ai_per_month": 2000, "month_eur": 0, "year_eur": 0},
}

PAID_OK = {"active", "trialing", "past_due"}


def plan_of(org: Organization) -> dict:
    return PLANS.get(org.plan, PLANS["trial"])


def trial_active(org: Organization) -> bool:
    end = aware(org.trial_ends_at)
    return org.plan == "trial" and end is not None and end > datetime.now(timezone.utc)


def can_write(org: Organization) -> bool:
    """Paying (or in trial) organizations can create and edit. Others are read-only."""
    if org.plan == "pilot":
        return True
    if org.plan in ("starter", "pro") and org.billing_status in PAID_OK:
        return True
    return trial_active(org)


def trial_days_left(org: Organization) -> int:
    end = aware(org.trial_ends_at)
    if not end:
        return 0
    secs = (end - datetime.now(timezone.utc)).total_seconds()
    return max(0, -int(-secs // 86400))  # round up


def month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def ai_used_this_month(db: Session, org: Organization) -> int:
    return db.scalar(select(func.count(AIUsage.id)).where(
        AIUsage.org_id == org.id, AIUsage.created_at >= month_start())) or 0


def ai_left(db: Session, org: Organization) -> int:
    return max(0, plan_of(org)["ai_per_month"] - ai_used_this_month(db, org))


def seats_used(db: Session, org: Organization) -> int:
    return db.scalar(select(func.count(User.id)).where(User.org_id == org.id, User.is_active.is_(True))) or 0


def new_trial_end(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)
