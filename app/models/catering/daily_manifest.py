from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, DateTime, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.models.base import Base
import uuid


class DailyManifest(Base):
    """A driver manifest for one top-level delivery route (e.g. "R1") on one service
    date — aggregates every stop (program) on that route. Built up from checked
    production-sheet items plus any one-off items the admin adds, then released as
    a whole for drivers to view."""
    __tablename__ = "catering_daily_manifests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    route_code = Column(String, nullable=False)  # top-level route group, e.g. "R1" (from program.route_code "R1-4")
    service_date = Column(Date, nullable=False)
    status = Column(String, default="draft", nullable=False)  # draft, released
    released_at = Column(DateTime, nullable=True)
    released_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stops = relationship(
        "DailyManifestStop",
        back_populates="manifest",
        cascade="all, delete-orphan",
        order_by="DailyManifestStop.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "route_code", "service_date", name="uq_daily_manifest_route_date"),
        Index("idx_daily_manifests_date", "tenant_id", "service_date"),
    )


class DailyManifestStop(Base):
    """One stop (program) within a route's manifest — e.g. "R1-1 Resurrection Academy"."""
    __tablename__ = "catering_daily_manifest_stops"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    manifest_id = Column(String, ForeignKey("catering_daily_manifests.id", ondelete="CASCADE"), nullable=False)
    program_id = Column(String, ForeignKey("catering_programs.id", ondelete="CASCADE"), nullable=False)
    special_instructions = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    manifest = relationship("DailyManifest", back_populates="stops")
    program = relationship("CateringProgram")
    items = relationship(
        "DailyManifestItem",
        back_populates="stop",
        cascade="all, delete-orphan",
        order_by="DailyManifestItem.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("manifest_id", "program_id", name="uq_daily_manifest_stop_program"),
        Index("idx_daily_manifest_stops_manifest", "manifest_id"),
        Index("idx_daily_manifest_stops_program", "program_id"),
    )


class DailyManifestItem(Base):
    """One packing line on a stop, e.g. '5 trays breakfast' or 'Yogurt'."""
    __tablename__ = "catering_daily_manifest_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    stop_id = Column(String, ForeignKey("catering_daily_manifest_stops.id", ondelete="CASCADE"), nullable=False)
    # 'breakfast', 'lunch', 'snack', 'am_snack', 'pm_snack', '<slot>_packnote', 'produce', 'beverage',
    # 'manual', or legacy 'milk'/'juice' (pre-Beverage)
    source = Column(String, nullable=False)
    label = Column(String, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    driver_confirmed = Column(Boolean, default=False, nullable=False)
    driver_confirmed_at = Column(DateTime, nullable=True)
    driver_confirmed_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stop = relationship("DailyManifestStop", back_populates="items")

    __table_args__ = (
        Index("idx_daily_manifest_items_stop", "stop_id"),
    )
