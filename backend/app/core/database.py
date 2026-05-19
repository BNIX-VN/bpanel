from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Lightweight schema migrations for additive columns. Replace with Alembic when
# the project grows beyond a handful of changes.
_PENDING_COLUMNS = [
    ("websites", "nginx_custom", "TEXT NOT NULL DEFAULT ''"),
    ("websites", "app_type", "VARCHAR(32) NOT NULL DEFAULT 'wordpress'"),
    ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
]


def apply_simple_migrations() -> None:
    inspector = inspect(engine)
    for table, column, ddl in _PENDING_COLUMNS:
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        if column in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
