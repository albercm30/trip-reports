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
import time
from types import SimpleNamespace

from fastapi.responses import JSONResponse

from ..services import ai, evalcases, species as sp, verify
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


# ---------------------------------------------------------------- AI accuracy test
@router.get("/accuracy")
def accuracy_page(request: Request, user: User = Depends(admin)):
    return render(request, "app/accuracy.html", {"nav": "admin", "cases": evalcases.CASES,
                                                 "ai_on": settings.ai_enabled}, user=user)


@router.post("/accuracy/{case_id}")
def accuracy_run(case_id: str, request: Request, user: User = Depends(admin)):
    """Run one test case through the same steps the app uses: AI reading, then the code checks,
    then a day report from the result and its fact-check. Nothing is saved."""
    case = evalcases.by_id(case_id)
    if case is None:
        raise NotFound()
    lang, raw, notes = case["lang"], case["tally"], case["notes"]
    out = {"id": case_id, "title": case["title"]}
    free = sp.parse_tally(raw, sp.default_vocab(), lang)
    for r in free:
        r.pop("_entry", None)
    out["free"] = evalcases.score(case, free)
    t0 = time.time()
    rows = None
    if settings.ai_enabled:
        try:
            data, _, _ = ai.parse_species(raw, notes, lang, "Trip: test\nArea: (not given)\nOperator: test")
            rows = sp.clean_ai_rows(data, raw + "\n" + notes)
            out["ai_raw"] = evalcases.score(case, [dict(r) for r in rows])
            rows, changes = verify.check_species_rows(rows, raw + "\n" + notes, sp.default_vocab(), lang, tally=raw)
            out["ai"] = evalcases.score(case, rows)
            out["changes"] = changes
        except ai.AIError as e:
            out["ai_error"] = e.code
    final = rows if rows is not None else free
    out["rows"] = [{k: r.get(k) for k in ("name", "sci", "count", "sure", "star", "heard")} for r in final]
    if settings.ai_enabled and final and request.query_params.get("draft") == "1":
        species = [SimpleNamespace(name=r["name"], sci=r.get("sci", ""), count=r.get("count"), sure=r.get("sure", True),
                                   heard=r.get("heard", False), star=r.get("star", False)) for r in final]
        lines = "\n".join(f"- {s.name}{' (' + s.sci + ')' if s.sci else ''}{' x' + str(s.count) if s.count else ''}"
                          f"{'' if s.sure else ' [UNCONFIRMED]'}" for s in species)
        notes_all = (raw + "\n" + notes).strip()
        try:
            from ..services.drafting import checked_draft
            kw = dict(n=1, date_s="", place="", notes=notes_all, species_lines=lines, lang=lang, tone="warm", context="")

            def write(previous, problems):
                return ai.draft_day(**kw, previous=previous or "", problems=problems or "")[0].strip()

            def check(text):
                return verify.check_text(text, lang=lang, species=species, notes=notes_all, allowed_numbers={1})

            res = checked_draft(write, check, notes_all, lines, lang, species=species, allowed={1})
            out["draft"] = {"text": verify.tidy(res["result"]), "problems": res["problems"],
                            "first_try_problems": len(res["first_problems"]),
                            "fixed": [p["what"] for p in res["first_problems"]]}
        except ai.AIError as e:
            out["draft_error"] = e.code
    out["seconds"] = round(time.time() - t0, 1)
    return JSONResponse(out)
