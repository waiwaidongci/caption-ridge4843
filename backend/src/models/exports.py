from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now

class Publication(Base):
    __tablename__ = 'publications'

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    granularity: Mapped[str] = mapped_column(String(10))
    start: Mapped[str | None] = mapped_column(String(10))
    end: Mapped[str | None] = mapped_column(String(10))
    order_count: Mapped[int]
    hidden_count: Mapped[int]
    snapshot: Mapped[dict] = mapped_column(JSON)
    export_file: Mapped[str | None] = mapped_column(String(100))
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
