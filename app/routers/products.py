"""
API endpoints for product management.
Includes upload, removal with undo, and restoration.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import os
import uuid as uuid_module
import shutil

from app.database import get_db
from app.models import Seller, Product, ActionLog
from app.schemas import (
    ProductCreate, ProductUpdate, ProductResponse,
    ProductUploadConfirmation, ProductRemoveRequest,
    ProductRestoreRequest, ProductListResponse,
    SuccessResponse, ErrorResponse
)
from app.services.logging import log_action
from app.services.whatsapp import whatsapp_service

router = APIRouter(prefix="/products", tags=["Products"])

# Upload settings
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "10485760"))  # 10MB

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def upload_product(
    seller_id: UUID = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price: Optional[float] = Form(None),
    currency: str = Form("USD"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a new product with image.
    This is the primary method for adding products via the mobile app.
    """
    # Validate seller exists
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if image.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )
    
    # Validate file size
    image.file.seek(0, 2)  # Seek to end
    file_size = image.file.tell()
    image.file.seek(0)  # Reset to beginning
    
    if file_size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE / 1024 / 1024}MB"
        )
    
    # Generate unique filename
    file_ext = os.path.splitext(image.filename)[1].lower()
    if file_ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        file_ext = ".jpg"
    
    unique_filename = f"{uuid_module.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    # Save file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save image: {str(e)}"
        )
    
    # Generate image URL (relative path for now)
    image_url = f"/uploads/{unique_filename}"
    
    # Create product
    product = Product(
        seller_id=seller_id,
        name=name,
        description=description,
        price=price,
        currency=currency,
        image_url=image_url,
        image_path=file_path,
        is_active=True
    )
    
    db.add(product)
    db.commit()
    db.refresh(product)
    
    # Log product upload
    log_action(
        action_type=ActionLog.PRODUCT_UPLOADED,
        seller_id=seller_id,
        product_id=product.id,
        action_data={
            "product_name": name,
            "price": price,
            "currency": currency,
            "image_filename": unique_filename
        }
    )
    
    return product.to_dict()


@router.post("/upload/whatsapp", response_model=ProductResponse)
async def upload_product_via_whatsapp(
    phone_number: str = Form(...),
    image_url: str = Form(...),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload a product via WhatsApp message.
    Parses caption for product name and price.
    """
    # Find or create seller
    seller = db.query(Seller).filter(Seller.phone_number == phone_number).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not registered. Please register first."
        )
    
    # Parse caption for product details
    # Expected format: "Product Name $50" or "Product Name - $50"
    name = "Untitled Product"
    price = None
    description = caption
    
    if caption:
        # Try to extract price
        import re
        price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', caption)
        if price_match:
            price = float(price_match.group(1))
            # Use text before price as name
            name = caption[:price_match.start()].strip() or "Untitled Product"
            # Remove common separators
            name = re.sub(r'[-–—:]$', '', name).strip()
        else:
            name = caption[:50]  # First 50 chars as name
    
    # Download image from WhatsApp
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30.0)
            response.raise_for_status()
            
            # Save image
            file_ext = ".jpg"  # Default
            content_type = response.headers.get("content-type", "")
            if "png" in content_type:
                file_ext = ".png"
            elif "webp" in content_type:
                file_ext = ".webp"
            
            unique_filename = f"{uuid_module.uuid4()}{file_ext}"
            file_path = os.path.join(UPLOAD_DIR, unique_filename)
            
            with open(file_path, "wb") as f:
                f.write(response.content)
            
            local_image_url = f"/uploads/{unique_filename}"
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download image: {str(e)}"
        )
    
    # Create product (inactive until confirmed)
    product = Product(
        seller_id=seller.id,
        name=name,
        description=description,
        price=price,
        currency="USD",
        image_url=local_image_url,
        image_path=file_path,
        is_active=False  # Inactive until confirmed
    )
    
    db.add(product)
    db.commit()
    db.refresh(product)
    
    # Send confirmation message via WhatsApp
    price_str = f"${price:.2f}" if price else None
    await whatsapp_service.send_upload_confirmation(
        to=phone_number,
        product_name=name,
        product_id=product.id,
        image_url=local_image_url,
        price=price_str
    )
    
    return product.to_dict(include_seller=True)


@router.post("/confirm", response_model=SuccessResponse)
async def confirm_product_upload(
    confirmation: ProductUploadConfirmation,
    db: Session = Depends(get_db)
):
    """
    Confirm or cancel a product upload via WhatsApp.
    ✅ to confirm, ❌ to cancel.
    """
    product = db.query(Product).filter(Product.id == confirmation.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    seller = db.query(Seller).filter(Seller.id == product.seller_id).first()
    
    if confirmation.confirmed:
        # Activate product
        product.is_active = True
        db.commit()
        
        # Log confirmation
        log_action(
            action_type=ActionLog.PRODUCT_CONFIRMED,
            seller_id=product.seller_id,
            product_id=product.id,
            action_data={"product_name": product.name}
        )
        
        # Send confirmation to seller
        from app.services.whatsapp import CATALOG_BASE_URL
        catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
        await whatsapp_service.send_product_added_confirmation(
            to=seller.phone_number,
            product_name=product.name,
            catalog_url=catalog_url
        )
        
        return SuccessResponse(
            success=True,
            message=f"Product '{product.name}' added to your catalog",
            data={"product_id": str(product.id), "catalog_url": catalog_url}
        )
    else:
        # Cancel - delete product and image
        try:
            if os.path.exists(product.image_path):
                os.remove(product.image_path)
        except Exception:
            pass  # Ignore cleanup errors
        
        db.delete(product)
        db.commit()
        
        # Log cancellation
        log_action(
            action_type=ActionLog.PRODUCT_CANCELLED,
            seller_id=seller.id if seller else None,
            action_data={"product_name": product.name}
        )
        
        return SuccessResponse(
            success=True,
            message="Product upload cancelled"
        )


@router.get("/seller/{seller_id}", response_model=ProductListResponse)
async def get_seller_products(
    seller_id: UUID,
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """Get all products for a seller."""
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller not found"
        )
    
    query = db.query(Product).filter(Product.seller_id == seller_id)
    
    if not include_inactive:
        query = query.filter(Product.is_active == True)
    
    products = query.order_by(Product.created_at.desc()).all()
    
    active_count = sum(1 for p in products if p.is_active)
    removed_count = len(products) - active_count
    
    return ProductListResponse(
        items=[p.to_dict() for p in products],
        total=len(products),
        active_count=active_count,
        removed_count=removed_count
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a single product by ID."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    return product.to_dict()


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    update: ProductUpdate,
    db: Session = Depends(get_db)
):
    """Update product information."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    if update.name is not None:
        product.name = update.name
    if update.description is not None:
        product.description = update.description
    if update.price is not None:
        product.price = update.price
    if update.currency is not None:
        product.currency = update.currency
    
    db.commit()
    db.refresh(product)
    
    return product.to_dict()


@router.post("/remove", response_model=SuccessResponse)
async def remove_products(
    request: ProductRemoveRequest,
    db: Session = Depends(get_db)
):
    """
    Remove products (soft delete with undo window).
    Products are marked inactive and can be restored within 30 seconds.
    """
    removed_count = 0
    undo_window = datetime.utcnow() + timedelta(seconds=30)
    
    for product_id in request.product_ids:
        product = db.query(Product).filter(
            Product.id == product_id,
            Product.is_active == True
        ).first()
        
        if product:
            product.is_active = False
            product.removed_at = datetime.utcnow()
            product.can_undo_until = undo_window
            removed_count += 1
            
            # Log removal
            log_action(
                action_type=ActionLog.PRODUCT_REMOVED,
                seller_id=product.seller_id,
                product_id=product.id,
                action_data={
                    "product_name": product.name,
                    "undo_until": undo_window.isoformat()
                }
            )
    
    db.commit()
    
    return SuccessResponse(
        success=True,
        message=f"{removed_count} product(s) removed. You have 30 seconds to undo.",
        data={
            "removed_count": removed_count,
            "undo_seconds": 30,
            "undo_until": undo_window.isoformat()
        }
    )


@router.post("/restore", response_model=ProductResponse)
async def restore_product(
    request: ProductRestoreRequest,
    db: Session = Depends(get_db)
):
    """
    Restore a removed product (within 30-second window).
    """
    product = db.query(Product).filter(
        Product.id == request.product_id,
        Product.is_active == False
    ).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or already active"
        )
    
    # Check if undo is still allowed
    if not product.can_undo():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Undo window has expired (30 seconds passed)"
        )
    
    # Restore product
    product.is_active = True
    product.removed_at = None
    product.can_undo_until = None
    
    db.commit()
    db.refresh(product)
    
    # Log restoration
    log_action(
        action_type=ActionLog.PRODUCT_RESTORED,
        seller_id=product.seller_id,
        product_id=product.id,
        action_data={"product_name": product.name}
    )
    
    return product.to_dict()


@router.delete("/{product_id}", response_model=SuccessResponse)
async def permanently_delete_product(
    product_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Permanently delete a product and its image.
    Use with caution - for admin purposes only.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    # Delete image file
    try:
        if os.path.exists(product.image_path):
            os.remove(product.image_path)
    except Exception:
        pass  # Ignore cleanup errors
    
    db.delete(product)
    db.commit()
    
    return SuccessResponse(
        success=True,
        message="Product permanently deleted"
    )
