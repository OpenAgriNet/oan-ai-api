"""
Market Data SQLAlchemy Models

Defines database models for marketplaces, crops, livestock, prices, and conversation context.
"""

from sqlalchemy import Column, Integer, String, Boolean, DECIMAL, Date, TIMESTAMP, ForeignKey, CheckConstraint, UniqueConstraint, Index, TEXT
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid as uuid_lib

from app.database import Base


class Marketplace(Base):
    """Ethiopian marketplace locations from NMIS"""
    __tablename__ = "marketplaces"

    marketplace_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    name_amharic = Column(String(255))
    marketplace_type = Column(String(20), nullable=False)  # 'crop' or 'livestock'
    region = Column(String(100))
    region_amharic = Column(String(100))
    latitude = Column(DECIMAL(10, 7))  # For weather queries
    longitude = Column(DECIMAL(10, 7))  # For weather queries
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSONB, default={})

    # Relationships
    prices = relationship("MarketPrice", back_populates="marketplace", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("marketplace_type IN ('crop', 'livestock')", name='ck_marketplace_type'),
        Index('idx_marketplace_name', 'name'),
        Index('idx_marketplace_type', 'marketplace_type'),
        Index('idx_marketplace_region', 'region'),
        Index('idx_marketplace_name_lower', func.lower(name)),
        Index('idx_marketplace_name_amharic', 'name_amharic'),
        Index('idx_marketplace_coords', 'latitude', 'longitude'),
    )


class Crop(Base):
    """Agricultural crop types (NOT livestock)"""
    __tablename__ = "crops"

    crop_id = Column(Integer, primary_key=True, autoincrement=True)
    nmis_crop_id = Column(Integer)
    name = Column(String(255), nullable=False, unique=True)
    name_amharic = Column(String(255))
    category = Column(String(100), default='agricultural')  # Only agricultural
    unit = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSONB, default={})

    # Relationships
    varieties = relationship("CropVariety", back_populates="crop", cascade="all, delete-orphan")
    prices = relationship("MarketPrice", back_populates="crop", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_crop_name', 'name'),
        Index('idx_crop_name_lower', func.lower(name)),
        Index('idx_crop_name_amharic', 'name_amharic'),
        Index('idx_crop_category', 'category'),
    )


class CropVariety(Base):
    """Crop varieties"""
    __tablename__ = "crop_varieties"

    variety_id = Column(Integer, primary_key=True, autoincrement=True)
    crop_id = Column(Integer, ForeignKey("crops.crop_id", ondelete="CASCADE"), nullable=False)
    nmis_variety_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    name_amharic = Column(String(255))
    description = Column(TEXT)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSONB, default={})

    # Relationships
    crop = relationship("Crop", back_populates="varieties")
    prices = relationship("MarketPrice", back_populates="variety")

    __table_args__ = (
        UniqueConstraint('crop_id', 'name', name='uq_crop_variety'),
        Index('idx_variety_crop', 'crop_id'),
        Index('idx_variety_name', 'name'),
        Index('idx_variety_nmis_id', 'nmis_variety_id'),
    )


class Livestock(Base):
    """Livestock types (separate from crops per user requirement)"""
    __tablename__ = "livestock"

    livestock_id = Column(Integer, primary_key=True, autoincrement=True)
    nmis_livestock_id = Column(Integer)
    name = Column(String(255), nullable=False, unique=True)
    name_amharic = Column(String(255))
    category = Column(String(100))  # e.g., "cattle", "sheep", "goat"
    unit = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSONB, default={})

    # Relationships
    breeds = relationship("LivestockBreed", back_populates="livestock", cascade="all, delete-orphan")
    prices = relationship("MarketPrice", back_populates="livestock", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_livestock_name', 'name'),
        Index('idx_livestock_name_lower', func.lower(name)),
        Index('idx_livestock_name_amharic', 'name_amharic'),
        Index('idx_livestock_category', 'category'),
    )


class LivestockBreed(Base):
    """Livestock breed types"""
    __tablename__ = "livestock_breeds"

    breed_id = Column(Integer, primary_key=True, autoincrement=True)
    livestock_id = Column(Integer, ForeignKey("livestock.livestock_id", ondelete="CASCADE"), nullable=False)
    nmis_breed_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    name_amharic = Column(String(255))
    description = Column(TEXT)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSONB, default={})

    # Relationships
    livestock = relationship("Livestock", back_populates="breeds")
    prices = relationship("MarketPrice", back_populates="breed")

    __table_args__ = (
        UniqueConstraint('livestock_id', 'name', name='uq_livestock_breed'),
        Index('idx_breed_livestock', 'livestock_id'),
        Index('idx_breed_name', 'name'),
        Index('idx_breed_nmis_id', 'nmis_breed_id'),
    )


class MarketPrice(Base):
    """Price data for crops and livestock in marketplaces"""
    __tablename__ = "market_prices"

    price_id = Column(Integer, primary_key=True, autoincrement=True)
    marketplace_id = Column(Integer, ForeignKey("marketplaces.marketplace_id", ondelete="CASCADE"), nullable=False)

    # Support both crops and livestock
    crop_id = Column(Integer, ForeignKey("crops.crop_id", ondelete="CASCADE"))
    variety_id = Column(Integer, ForeignKey("crop_varieties.variety_id", ondelete="SET NULL"))
    livestock_id = Column(Integer, ForeignKey("livestock.livestock_id", ondelete="CASCADE"))
    breed_id = Column(Integer, ForeignKey("livestock_breeds.breed_id", ondelete="SET NULL"))

    # Price information
    min_price = Column(DECIMAL(10, 2))
    max_price = Column(DECIMAL(10, 2))
    avg_price = Column(DECIMAL(10, 2))
    modal_price = Column(DECIMAL(10, 2))
    currency = Column(String(10), default='ETB')
    unit = Column(String(50))

    # Temporal tracking
    price_date = Column(Date, nullable=False)
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Data quality
    source = Column(String(100), default='nmis.et')
    is_verified = Column(Boolean, default=False)
    confidence_score = Column(DECIMAL(3, 2))

    meta_data = Column(JSONB, default={})

    # Relationships
    marketplace = relationship("Marketplace", back_populates="prices")
    crop = relationship("Crop", back_populates="prices")
    variety = relationship("CropVariety", back_populates="prices")
    livestock = relationship("Livestock", back_populates="prices")
    breed = relationship("LivestockBreed", back_populates="prices")

    __table_args__ = (
        CheckConstraint(
            "(crop_id IS NOT NULL AND livestock_id IS NULL) OR (crop_id IS NULL AND livestock_id IS NOT NULL)",
            name='ck_price_crop_or_livestock'
        ),
        UniqueConstraint('marketplace_id', 'crop_id', 'variety_id', 'price_date', name='uq_crop_market_price'),
        UniqueConstraint('marketplace_id', 'livestock_id', 'breed_id', 'price_date', name='uq_livestock_market_price'),
        Index('idx_price_marketplace', 'marketplace_id'),
        Index('idx_price_crop', 'crop_id'),
        Index('idx_price_variety', 'variety_id'),
        Index('idx_price_livestock', 'livestock_id'),
        Index('idx_price_breed', 'breed_id'),
        Index('idx_price_date', price_date.desc()),
        Index('idx_price_fetched', fetched_at.desc()),
        Index('idx_price_crop_lookup', 'marketplace_id', 'crop_id', price_date.desc()),
        Index('idx_price_livestock_lookup', 'marketplace_id', 'livestock_id', price_date.desc()),
    )

class ScraperLog(Base):
    """Track scraper runs and health"""
    __tablename__ = "scraper_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    scraper_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    completed_at = Column(TIMESTAMP(timezone=True))
    duration_ms = Column(Integer)

    # Metrics
    records_fetched = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)

    error_message = Column(TEXT)
    error_details = Column(JSONB)
    meta_data = Column(JSONB, default={})

    __table_args__ = (
        CheckConstraint("status IN ('started', 'success', 'partial', 'failed')", name='ck_scraper_status'),
        Index('idx_scraper_type', 'scraper_type'),
        Index('idx_scraper_status', 'status'),
        Index('idx_scraper_started', started_at.desc()),
    )
