from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    from app.models.account import Account  # noqa
    from app.models.pool_counter import PoolCounter  # noqa
    from app.models.app_setting import AppSetting  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_account_quota_columns(conn)


async def _migrate_account_quota_columns(conn):
    """Add plan/quota columns to existing accounts table (idempotent)."""
    from sqlalchemy import text
    new_columns = {
        "plan_tier": "VARCHAR(64)",
        "plan_name": "VARCHAR(64)",
        "is_paid": "BOOLEAN DEFAULT 0",
        "plan_end_date": "FLOAT",
        "email": "VARCHAR(128)",
        "machine_id": "VARCHAR(128)",
        "machine_token": "TEXT",
        "machine_type": "VARCHAR(32)",
        "activity_id": "VARCHAR(128)",
        "activity_status": "VARCHAR(32)",
        "activity_label": "VARCHAR(256)",
        "activity_model": "VARCHAR(64)",
        "activity_limit": "INTEGER",
        "activity_used": "INTEGER NOT NULL DEFAULT 0",
        "activity_remaining": "INTEGER",
        "activity_expires_at": "FLOAT",
        "activity_checked_at": "FLOAT",
        "activity_claimed_at": "FLOAT",
        "quota_total": "FLOAT",
        "quota_used": "FLOAT",
        "quota_remaining": "FLOAT",
        "quota_percentage": "FLOAT",
        "quota_unit": "VARCHAR(16) DEFAULT 'credits'",
        "is_quota_exceeded": "BOOLEAN DEFAULT 0",
        "quota_expires_at": "FLOAT",
        "quota_fetched_at": "FLOAT",
    }
    result = await conn.execute(text("PRAGMA table_info(accounts)"))
    existing = {row[1] for row in result.fetchall()}
    for name, col_type in new_columns.items():
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {name} {col_type}"))
