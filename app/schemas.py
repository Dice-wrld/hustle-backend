"""
Pydantic schemas for request/response validation.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from uuid import UUID


# ============== Seller Schemas ==============

class SellerBase(BaseModel):
    """Base seller schema."""
    phone_number: str = Field(..., min_length=10, max_length=20)
    name: Optional[str] = Field(None, max_length=100)


class SellerCreate(SellerBase):
    """Schema for creating a seller."""
    pass


class SellerUpdate(BaseModel):
    """Schema for updating seller info."""
    name: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class SellerResponse(BaseModel):
    """Schema for seller response."""
    id: UUID
    phone_number: str
    name: Optional[str]
    catalog_slug: str
    catalog_url: str
    is_active: bool
    created_at: datetime
    product_count: int

    class Config:
        from_attributes = True


class SellerRegisterRequest(BaseModel):
    """Schema for seller registration via WhatsApp."""
    phone_number: str = Field(..., min_length=10, max_length=20)
    name: Optional[str] = None
    whatsapp_chat_id: Optional[str] = None


# ============== Product Schemas ==============

class ProductBase(BaseModel):
    """Base product schema."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    currency: str = Field(default="USD", max_length=3)
    
    @field_validator('price')
    @classmethod
    def round_price(cls, v):
        if v is not None:
            return round(v, 2)
        return v


class ProductCreate(ProductBase):
    """Schema for creating a product."""
    seller_id: UUID
    image_url: str
    image_path: str


class ProductUpdate(BaseModel):
    """Schema for updating product info."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=3)
    
    @field_validator('price')
    @classmethod
    def round_price(cls, v):
        if v is not None:
            return round(v, 2)
        return v


class ProductResponse(BaseModel):
    """Schema for product response."""
    id: UUID
    name: str
    description: Optional[str]
    price: Optional[float]
    currency: str
    image_url: str
    is_active: bool
    created_at: datetime
    can_undo: bool
    seller: Optional[dict] = None

    class Config:
        from_attributes = True


class ProductUploadConfirmation(BaseModel):
    """Schema for confirming product upload via WhatsApp."""
    product_id: UUID
    confirmed: bool  # True to add, False to cancel


class ProductRemoveRequest(BaseModel):
    """Schema for removing a product."""
    product_ids: List[UUID]


class ProductRestoreRequest(BaseModel):
    """Schema for restoring a removed product."""
    product_id: UUID


class ProductListResponse(BaseModel):
    """Schema for product list response."""
    items: List[ProductResponse]
    total: int
    active_count: int
    removed_count: int


# ============== Interest Schemas ==============

class InterestBase(BaseModel):
    """Base interest schema."""
    buyer_name: Optional[str] = Field(None, max_length=100)
    buyer_phone: Optional[str] = Field(None, max_length=20)


class InterestCreate(InterestBase):
    """Schema for creating buyer interest."""
    product_id: UUID


class InterestResponse(BaseModel):
    """Schema for interest response."""
    id: UUID
    product_id: UUID
    buyer_phone: Optional[str]
    buyer_name: Optional[str]
    message_sent: bool
    created_at: datetime
    whatsapp_link: Optional[str] = None

    class Config:
        from_attributes = True


# ============== Catalog Schemas ==============

class CatalogProductResponse(BaseModel):
    """Schema for catalog product (buyer view)."""
    id: UUID
    name: str
    description: Optional[str]
    price: Optional[float]
    currency: str
    image_url: str
    seller_name: Optional[str]
    whatsapp_link: str

    class Config:
        from_attributes = True


class CatalogResponse(BaseModel):
    """Schema for seller catalog (buyer view)."""
    seller_name: Optional[str]
    seller_phone: str
    products: List[CatalogProductResponse]
    total_products: int


# ============== Action Log Schemas ==============

class ActionLogResponse(BaseModel):
    """Schema for action log response."""
    id: UUID
    action_type: str
    seller_id: Optional[UUID]
    product_id: Optional[UUID]
    interest_id: Optional[UUID]
    action_data: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ActionLogListResponse(BaseModel):
    """Schema for action log list response."""
    items: List[ActionLogResponse]
    total: int


# ============== WhatsApp Schemas ==============

class WhatsAppWebhookPayload(BaseModel):
    """Schema for WhatsApp webhook payload."""
    object: str
    entry: List[dict]


class WhatsAppMessageRequest(BaseModel):
    """Schema for sending WhatsApp message."""
    to: str
    message: str
    media_url: Optional[str] = None


class WhatsAppUploadRequest(BaseModel):
    """Schema for product upload via WhatsApp."""
    phone_number: str
    image_url: str
    caption: Optional[str] = None
    media_id: Optional[str] = None


class WhatsAppConfirmationRequest(BaseModel):
    """Schema for WhatsApp confirmation message."""
    phone_number: str
    product_name: str
    product_id: UUID


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Schema for error responses."""
    error: str
    message: str
    details: Optional[dict] = None


class SuccessResponse(BaseModel):
    """Schema for success responses."""
    success: bool
    message: str
    data: Optional[dict] = None


# ============== Stats Schemas ==============

class SellerStatsResponse(BaseModel):
    """Schema for seller statistics."""
    total_products: int
    active_products: int
    removed_products: int
    total_interests: int
    recent_interests: int  # Last 7 days
    catalog_views: int