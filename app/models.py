"""
SQLAlchemy models for Hustle backend.
Defines Seller, Product, Interest, and ActionLog entities.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, 
    Text, ForeignKey, Numeric, Index, event
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timedelta

from app.database import Base


class Seller(Base):
    """Seller model - represents a Hustle user."""
    
    __tablename__ = "sellers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=True)
    whatsapp_chat_id = Column(String(100), unique=True, nullable=True)
    catalog_slug = Column(String(50), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    products = relationship("Product", back_populates="seller", cascade="all, delete-orphan")
    action_logs = relationship("ActionLog", back_populates="seller", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Seller(phone={self.phone_number}, slug={self.catalog_slug})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "phone_number": self.phone_number,
            "name": self.name,
            "catalog_slug": self.catalog_slug,
            "catalog_url": f"/catalog/{self.catalog_slug}",
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "product_count": len([p for p in self.products if p.is_active])
        }


class Product(Base):
    """Product model - represents a seller's product."""
    
    __tablename__ = "products"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), default="USD", nullable=False)
    image_url = Column(String(500), nullable=False)
    image_path = Column(String(500), nullable=False)  # Local storage path
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    removed_at = Column(DateTime(timezone=True), nullable=True)  # For undo functionality
    can_undo_until = Column(DateTime(timezone=True), nullable=True)  # 30-second undo window
    
    # Relationships
    seller = relationship("Seller", back_populates="products")
    interests = relationship("Interest", back_populates="product", cascade="all, delete-orphan")
    action_logs = relationship("ActionLog", back_populates="product", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_product_seller_active', 'seller_id', 'is_active'),
        Index('idx_product_created', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Product(name={self.name}, seller={self.seller_id})>"
    
    def to_dict(self, include_seller=False):
        data = {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "price": float(self.price) if self.price else None,
            "currency": self.currency,
            "image_url": self.image_url,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "can_undo": self.can_undo() if not self.is_active else False
        }
        if include_seller and self.seller:
            data["seller"] = {
                "id": str(self.seller.id),
                "name": self.seller.name,
                "phone_number": self.seller.phone_number
            }
        return data
    
    def can_undo(self) -> bool:
        """Check if product removal can be undone (within 30 seconds)."""
        if self.is_active or not self.can_undo_until:
            return False
        return datetime.utcnow() < self.can_undo_until


class Interest(Base):
    """Interest model - tracks buyer interest in products."""
    
    __tablename__ = "interests"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    buyer_phone = Column(String(20), nullable=True)  # Optional, if buyer is logged in
    buyer_name = Column(String(100), nullable=True)
    buyer_ip = Column(String(45), nullable=True)  # For tracking
    user_agent = Column(Text, nullable=True)
    message_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    product = relationship("Product", back_populates="interests")
    action_logs = relationship("ActionLog", back_populates="interest", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_interest_product', 'product_id', 'created_at'),
        Index('idx_interest_buyer', 'buyer_phone', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Interest(product={self.product_id}, buyer={self.buyer_phone})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "product_id": str(self.product_id),
            "buyer_phone": self.buyer_phone,
            "buyer_name": self.buyer_name,
            "message_sent": self.message_sent,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class ActionLog(Base):
    """
    ActionLog model - comprehensive logging for dispute resolution.
    Tracks all significant actions in the system.
    """
    
    __tablename__ = "action_logs"
    
    # Action types
    SELLER_REGISTERED = "seller_registered"
    PRODUCT_UPLOADED = "product_uploaded"
    PRODUCT_CONFIRMED = "product_confirmed"
    PRODUCT_CANCELLED = "product_cancelled"
    PRODUCT_REMOVED = "product_removed"
    PRODUCT_RESTORED = "product_restored"
    BUYER_INTEREST = "buyer_interest"
    CATALOG_VIEWED = "catalog_viewed"
    WHATSAPP_MESSAGE_SENT = "whatsapp_message_sent"
    WHATSAPP_MESSAGE_RECEIVED = "whatsapp_message_received"
    ERROR_OCCURRED = "error_occurred"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_type = Column(String(50), nullable=False, index=True)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    interest_id = Column(UUID(as_uuid=True), ForeignKey("interests.id", ondelete="SET NULL"), nullable=True)
    
    # Detailed action data (JSON-like storage)
    action_data = Column(Text, nullable=True)  # JSON string of action details
    
    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    whatsapp_message_id = Column(String(100), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    seller = relationship("Seller", back_populates="action_logs")
    product = relationship("Product", back_populates="action_logs")
    interest = relationship("Interest", back_populates="action_logs")
    
    # Indexes for querying
    __table_args__ = (
        Index('idx_action_log_seller_time', 'seller_id', 'created_at'),
        Index('idx_action_log_type_time', 'action_type', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ActionLog(type={self.action_type}, seller={self.seller_id})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "action_type": self.action_type,
            "seller_id": str(self.seller_id) if self.seller_id else None,
            "product_id": str(self.product_id) if self.product_id else None,
            "interest_id": str(self.interest_id) if self.interest_id else None,
            "action_data": self.action_data,
            "whatsapp_message_id": self.whatsapp_message_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# Event listeners for automatic logging
@event.listens_for(Product, 'after_insert')
def log_product_insert(mapper, connection, target):
    """Log when a new product is created."""
    from app.services.logging import log_action
    log_action(
        action_type=ActionLog.PRODUCT_UPLOADED,
        seller_id=target.seller_id,
        product_id=target.id,
        action_data={"product_name": target.name, "price": str(target.price) if target.price else None}
    )


@event.listens_for(Product, 'after_update')
def log_product_update(mapper, connection, target):
    """Log when a product is updated (removed/restored)."""
    from app.services.logging import log_action
    # Check if product was just removed
    if hasattr(target, '_was_removed') and target._was_removed:
        log_action(
            action_type=ActionLog.PRODUCT_REMOVED,
            seller_id=target.seller_id,
            product_id=target.id,
            action_data={"product_name": target.name, "removed_at": datetime.utcnow().isoformat()}
        )
    # Check if product was restored
    if hasattr(target, '_was_restored') and target._was_restored:
        log_action(
            action_type=ActionLog.PRODUCT_RESTORED,
            seller_id=target.seller_id,
            product_id=target.id,
            action_data={"product_name": target.name, "restored_at": datetime.utcnow().isoformat()}
        )
