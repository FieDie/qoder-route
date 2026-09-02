from sqlalchemy import Column, String, Float
from app.core.database import Base


class PoolCounter(Base):
    """Lifetime pool-wide counters that survive account deletion.

    Credits burned by an account keep counting toward the pool total even
    after the account row is purged (exhausted PATs are deleted from pool).
    """
    __tablename__ = "pool_counters"

    key = Column(String(64), primary_key=True)
    value = Column(Float, default=0.0, nullable=False)


CREDITS_SPENT_KEY = "credits_spent"
