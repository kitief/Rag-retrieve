"""
Database engine, session factory and schema bootstrap.

Works on both deployment shapes:

* **PostgreSQL** (Docker Compose): ``postgresql+asyncpg://…``
* **SQLite** (desktop build): ``sqlite+aiosqlite:///<data-dir>/ragvault.db``

SQLite needs a few extra knobs before it behaves well under concurrent async
requests — WAL lets a long PDF ingestion job write while the UI keeps reading,
``busy_timeout`` turns "database is locked" into a short wait instead of a 500,
and ``foreign_keys`` is OFF by default in SQLite while PostgreSQL enforces FKs.
"""
import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

_IS_SQLITE = settings.database_url.startswith("sqlite")

engine = create_async_engine(
    settings.database_url,
    echo=(settings.environment == "development"),
    # SQLite holds one writer at a time; let the pool hand out a single
    # connection so the PRAGMAs below always apply to the same handle.
    connect_args={"timeout": 30} if _IS_SQLITE else {},
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


if _IS_SQLITE:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
        """Apply the PRAGMAs on every new SQLite connection."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if _IS_SQLITE:
            # SQLite has no ALTER TABLE ... ADD COLUMN IF NOT EXISTS. ``create_all``
            # above already created every current column, so the only work left is
            # the historical ``is_deleted`` backfill for a database that predates it.
            columns = await conn.execute(text("PRAGMA table_info(chats)"))
            names = {row[1] for row in columns.fetchall()}
            if "is_deleted" not in names:
                await conn.execute(
                    text("ALTER TABLE chats ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0")
                )
        else:
            # Keep the existing Postgres deployments compatible with databases
            # created before ``is_deleted`` was added to the model.
            await conn.execute(
                text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;")
            )
