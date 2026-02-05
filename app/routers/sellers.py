"""
API endpoints for seller management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import secrets
import string

from app.database import get_db
from app.models import Seller, Product, ActionLog
from app.schemas import (
    SellerCreate, SellerUpdate, SellerResponse,
    SellerRegisterRequest, SellerStatsResponse,
    SuccessResponse, ErrorResponse
)
from app.services.logging import log_action

router = APIRouter(prefix="/sellers", tags=["Sellers"])


def generate_catalog_slug() -> str:
    """Generate a unique catalog slug."""
    # Generate a random 8-character alphanumeric slug
    return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))


@router.post("/register", response_model=SellerResponse, status_code=status.HTTP_201_CREATED)
async def register_seller(
    request: SellerRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new seller via WhatsApp.
    Creates a dedicated Hustle chat for the seller.
    """
    # Check if seller already exists
    existing = db.query(Seller).filter(Seller.phone_number == request.phone_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seller already registered with this phone number"
        )
    
    # Generate unique catalog slug
    slug = generate_catalog_slug()
    while db.query(Seller).filter(Seller.catalog_slug == slug).first():
        slug = generate_catalog_slug()
    
    # Create seller
    seller = Seller(
        phone_number=request.phone_number,
        name=request.name,
        whatsapp_chat_id=request.whatsapp_chat_id,
        catalog_slug=slug,
        is_active=True
    )
    
    db.add(seller)
    db.commit()
    db.refresh(seller)
    
    # Log registration
    log_action(
        action_type=ActionLog.SELLER_REGISTERED,
        seller_id=seller.id,
        action_data={
            "phone_number": seller.phone_number,
            "name": seller.name,
            "catalog_slug": slug
        }
    )
    
    return seller.to_dict()


@router.get("/phone/{phone_number}", response_model=SellerResponse)
async def get_seller_by_phone(
    phone_number: str,
    db: Session = Depends(get_db)
):
    """Get seller by phone number."""
    seller = db.query(Seller).filter(Seller.phone_number == phone_number).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    return seller.to_dict()


@router.get("/{seller_id}", response_model=SellerResponse)
async def get_seller(
    seller_id: UUID,
    db: Session = Depends(get_db)
):
    """Get seller by ID."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    return seller.to_dict()


@router.patch("/{seller_id}", response_model=SellerResponse)
async def update_seller(
    seller_id: UUID,
    update: SellerUpdate,
    db: Session = Depends(get_db)
):
    """Update seller information."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    if update.name is not None:
        seller.name = update.name
    if update.is_active is not None:
        seller.is_active = update.is_active
    
    db.commit()
    db.refresh(seller)
    
    return seller.to_dict()


@router.delete("/{seller_id}", response_model=SuccessResponse)
async def delete_seller(
    seller_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a seller and all associated data."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    db.delete(seller)
    db.commit()
    
    return SuccessResponse(
        success=True,
        message="Seller deleted successfully"
    )


@router.get("/{seller_id}/stats", response_model=SellerStatsResponse)
async def get_seller_stats(
    seller_id: UUID,
    db: Session = Depends(get_db)
):
    """Get seller statistics."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    total_products = db.query(Product).filter(Product.seller_id == seller_id).count()
    active_products = db.query(Product).filter(
        Product.seller_id == seller_id,
        Product.is_active == True
    ).count()
    removed_products = total_products - active_products
    
    # Count total interests for seller's products
    from app.models import Interest
    total_interests = db.query(Interest).join(Product).filter(
        Product.seller_id == seller_id
    ).count()
    
    # Recent interests (last 7 days)
    from datetime import datetime, timedelta
    recent_date = datetime.utcnow() - timedelta(days=7)
    recent_interests = db.query(Interest).join(Product).filter(
        Product.seller_id == seller_id,
        Interest.created_at >= recent_date
    ).count()
    
    # Catalog views (from action logs)
    catalog_views = db.query(ActionLog).filter(
        ActionLog.seller_id == seller_id,
        ActionLog.action_type == ActionLog.CATALOG_VIEWED
    ).count()
    
    return SellerStatsResponse(
        total_products=total_products,
        active_products=active_products,
        removed_products=removed_products,
        total_interests=total_interests,
        recent_interests=recent_interests,
        catalog_views=catalog_views
    )


@router.get("/{seller_id}/catalog-link")
async def get_catalog_link(
    seller_id: UUID,
    db: Session = Depends(get_db)
):
    """Get the private catalog link for a seller."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    from app.services.whatsapp import CATALOG_BASE_URL
    
    catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
    
    return {
        "catalog_url": catalog_url,
        "catalog_slug": seller.catalog_slug
    }
