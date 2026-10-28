"""Admin page for the people who run the service (ADMIN_EMAILS): see every company that signed
up and turn pilot accounts on or off. Everyone else gets a 404, as if the page didn't exist."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import plans
from ..config import settings
from ..db import get_db
from ..deps import NotFound, current_user
from ..models import Organization, Trip, User
from ..services import ai
from ..web import redirect, render

router = APIRouter(prefix="/app/admin")


def admin(user: User = Depends(current_user)) -> User:
    if not settings.is_admin(user.email):
        raise NotFound()
    return user


@router.get("")
def admin_page(request: Request, db: Session = Depends(get_db), user: User = Depends(admin)):
    orgs = list(db.scalars(select(Organization).order_by(Organization.created_at.desc())))
    owners = {u.org_id: u for u in db.scalars(select(User).where(User.role == "owner"))}
    members = dict(db.execute(select(User.org_id, func.count(User.id)).group_by(User.org_id)).all())
    trips = dict(db.execute(select(Trip.org_id, func.count(Trip.id)).where(Trip.is_demo.is_(False))
                            .group_by(Trip.org_id)).all())
    rows = [{"org": o, "owner": owners.get(o.id), "members": members.get(o.id, 0), "trips": trips.get(o.id, 0),
             "can_write": plans.can_write(o), "days_left": plans.trial_days_left(o)} for o in orgs]
    checked = ai.check() if request.query_params.get("check_ai") else None
    return render(request, "app/admin.html", {"rows": rows, "nav": "admin", "ai_chain": ai.model_chain(),
                                              "ai_checked": checked}, user=user)


@router.post("/{org_id}/pilot")
def make_pilot(org_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(admin)):
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound()
    if org.plan in ("starter", "pro") and org.billing_status in plans.PAID_OK:
        return redirect("/app/admin", "That company has a paid plan. Cancel it in Stripe first.")
    org.plan, org.billing_status = "pilot", "active"
    db.commit()
    return redirect("/app/admin", "Pilot account turned on.")


@router.post("/{org_id}/trial")
def back_to_trial(org_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(admin)):
    """End a pilot (or give an expired trial more time): a fresh free trial from today."""
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound()
    if org.plan in ("starter", "pro") and org.billing_status in plans.PAID_OK:
        return redirect("/app/admin", "That company has a paid plan. Cancel it in Stripe first.")
    org.plan, org.billing_status = "trial", "trialing"
    org.trial_ends_at = plans.new_trial_end(settings.trial_days)
    db.commit()
    return redirect("/app/admin", "Free trial restarted.")
