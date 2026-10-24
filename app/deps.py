"""Request dependencies: who is signed in, which organization, and what they may do."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from . import plans
from .db import get_db
from .models import Day, Trip, User
from .security import user_from_request


class LoginRequired(Exception):
    pass


class OwnerRequired(Exception):
    pass


class ReadOnly(Exception):
    pass


class NotFound(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(db, request)
    if user is None:
        raise LoginRequired()
    request.state.user = user
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return user_from_request(db, request)


def owner(user: User = Depends(current_user)) -> User:
    if not user.is_owner:
        raise OwnerRequired()
    return user


def writer(user: User = Depends(current_user)) -> User:
    """Signed-in user whose organization can create and edit (trial or paid)."""
    if not plans.can_write(user.org):
        raise ReadOnly()
    return user


def get_trip(db: Session, user: User, trip_id: str) -> Trip:
    t = db.get(Trip, trip_id)
    if t is None or t.org_id != user.org_id:
        raise NotFound()
    return t


def get_day(db: Session, trip: Trip, day_id: str) -> Day:
    d = db.get(Day, day_id)
    if d is None or d.trip_id != trip.id:
        raise NotFound()
    return d
