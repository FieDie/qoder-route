from sqlalchemy import Column, Float, Integer, String
from app.core.database import Base


class RequestSummary(Base):
    """Last-day request outcomes for Usage charts and the Requests log view.

    Live events stay on the in-memory log bus. This table is the piece that
    survives a backend restart so the dashboard does not go blank.
    """

    __tablename__ = "request_summaries"

    request_id = Column(String(32), primary_key=True)
    ts = Column(Float, nullable=False, index=True)
    last_ts = Column(Float, nullable=False)
    dialect = Column(String(16), nullable=True)
    model = Column(String(64), nullable=True)
    account_id = Column(Integer, nullable=True)
    account_name = Column(String(128), nullable=True)
    phase = Column(String(16), nullable=True)
    outcome = Column(String(16), nullable=True)
    completion_tokens = Column(Integer, default=0, nullable=False)
    credits = Column(Float, default=0.0, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    first_token_ms = Column(Integer, nullable=True)
    message = Column(String(256), nullable=True)
    level = Column(String(16), nullable=True)
