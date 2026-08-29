from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_on_connect(dbapi_conn, _connection_record):
    """WAL + busy_timeout so concurrent mark_success / routing writes don't stall."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

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
    from app.models.api_key import ApiKey  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_account_quota_columns(conn)
        await _migrate_api_key_plain_column(conn)
        await _ensure_pat_unique_index(conn)
        await _drop_legacy_activity_state(conn)
        await _reactivate_all_accounts(conn)


async def _migrate_account_quota_columns(conn):
    """Add plan/quota columns to existing accounts table (idempotent)."""
    from sqlalchemy import text
    new_columns = {
        "plan_tier": "VARCHAR(64)",
        "plan_name": "VARCHAR(64)",
        "is_paid": "BOOLEAN DEFAULT 0",
        "plan_end_date": "FLOAT",
        "email": "VARCHAR(128)",
        "quota_total": "FLOAT",
        "quota_used": "FLOAT",
        "quota_remaining": "FLOAT",
        "quota_percentage": "FLOAT",
        "quota_unit": "VARCHAR(16) DEFAULT 'credits'",
        "is_quota_exceeded": "BOOLEAN DEFAULT 0",
        "quota_expires_at": "FLOAT",
        "quota_fetched_at": "FLOAT",
        "machine_id": "VARCHAR(36)",
    }
    result = await conn.execute(text("PRAGMA table_info(accounts)"))
    existing = {row[1] for row in result.fetchall()}
    for name, col_type in new_columns.items():
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {name} {col_type}"))
    # Backfill machine_id for accounts created before the column existed.
    await _backfill_machine_ids(conn)


async def _backfill_machine_ids(conn):
    """Assign a random UUID machine_id to accounts that predate the column.

    Each account must present as a unique device to Qoder's anti-fraud, so a
    shared/empty machine_id is unacceptable."""
    import uuid
    from sqlalchemy import text

    result = await conn.execute(text(
        "SELECT id FROM accounts WHERE machine_id IS NULL OR machine_id = ''"))
    rows = result.fetchall()
    for (account_id,) in rows:
        await conn.execute(text(
            "UPDATE accounts SET machine_id = :mid WHERE id = :aid"),
            {"mid": str(uuid.uuid4()), "aid": account_id})


async def _reactivate_all_accounts(conn):
    """Account disable was removed — wake any rows left inactive in the DB."""
    from sqlalchemy import text

    await conn.execute(text("UPDATE accounts SET is_active = 1 WHERE is_active = 0"))


async def _drop_legacy_activity_state(conn):
    """Remove the retired Qoder campaign identity/counter storage."""
    from sqlalchemy import text

    legacy_columns = (
        "machine_token",
        "machine_type",
        "activity_id",
        "activity_status",
        "activity_label",
        "activity_model",
        "activity_limit",
        "activity_used",
        "activity_remaining",
        "activity_expires_at",
        "activity_checked_at",
        "activity_claimed_at",
    )
    result = await conn.execute(text("PRAGMA table_info(accounts)"))
    existing = {row[1] for row in result.fetchall()}
    for name in legacy_columns:
        if name in existing:
            await conn.execute(text(f'ALTER TABLE accounts DROP COLUMN "{name}"'))

    await conn.execute(text(
        "DELETE FROM app_settings "
        "WHERE key IN ('accounts_auto_delete_keep_activity', "
        "'account_activity_checks_enabled')"
    ))


async def _ensure_pat_unique_index(conn):
    """Unique PAT so the same token cannot enter the pool twice.

    create_all will not add the index to an existing table; do it here.
    Duplicate rows leftover from before this constraint are left as-is —
    the index create fails and we log rather than wiping accounts.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError, OperationalError

    try:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_pat_token "
            "ON accounts (pat_token)"
        ))
    except (OperationalError, IntegrityError):
        import logging
        logging.getLogger("qoderroute.db").warning(
            "Could not create unique PAT index — duplicate tokens already exist"
        )


async def _migrate_api_key_plain_column(conn):
    """Keep the generated key so the panel can copy it later."""
    from sqlalchemy import text

    result = await conn.execute(text("PRAGMA table_info(api_keys)"))
    existing = {row[1] for row in result.fetchall()}
    if existing and "key_plain" not in existing:
        await conn.execute(text("ALTER TABLE api_keys ADD COLUMN key_plain TEXT"))
