"""Alembic migrations. The database URL comes from the app settings (DATABASE_URL)."""
from alembic import context

from app import models  # noqa: F401  (registers tables)
from app.config import settings
from app.db import Base, make_engine

target_metadata = Base.metadata


def run_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=settings.database_url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    engine = make_engine(settings.database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=settings.database_url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
