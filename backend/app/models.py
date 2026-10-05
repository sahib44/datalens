from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    String,
    DateTime,
    Integer,
    ForeignKey,
    JSON,
    Text,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Version(Base):
    __tablename__ = "versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_count: Mapped[int | None] = mapped_column(Integer)


class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status in ('queued','running','completed','failed')"),
        CheckConstraint("kind in ('profile','compare')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    comparison_id: Mapped[str | None] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    engine_version: Mapped[str] = mapped_column(String(40))
    configuration: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    limitations: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ColumnProfile(Base):
    __tablename__ = "column_profiles"
    __table_args__ = (UniqueConstraint("analysis_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    column_name: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)


class Cleanup(Base):
    __tablename__ = "file_cleanup"
    storage_key: Mapped[str] = mapped_column(String(64), primary_key=True)
