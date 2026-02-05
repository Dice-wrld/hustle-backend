"""
API endpoints for the public catalog (buyer view).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.models import Seller, Product, Interest, ActionLog
from app.schemas import CatalogResponse, CatalogProductResponse, InterestCreate, InterestResponse
from app.services.logging import log_action
from app.services.whatsapp import whatsapp_service

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("/{catalog_slug}", response_model=CatalogResponse)
async def view_catalog(
    catalog_slug: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    View a seller's public catalog.
    This is the page buyers see when they click the catalog link.
    """
    # Find seller by catalog slug
    seller = db.query(Seller).filter(
        Seller.catalog_slug == catalog_slug,
        Seller.is_active == True
    ).first()
    
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found or unavailable"
        )
    
    # Get active products
    products = db.query(Product).filter(
        Product.seller_id == seller.id,
        Product.is_active == True
    ).order_by(Product.created_at.desc()).all()
    
    # Log catalog view
    log_action(
        action_type=ActionLog.CATALOG_VIEWED,
        seller_id=seller.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        action_data={
            "catalog_slug": catalog_slug,
            "product_count": len(products)
        }
    )
    
    # Build response with WhatsApp deep links
    catalog_products = []
    for product in products:
        # Generate pre-filled message
        message = f"Hi! I'm interested in your product: {product.name}"
        if product.price:
            message += f" (priced at ${product.price})"
        message += ". Is it still available?"
        
        whatsapp_link = whatsapp_service.generate_whatsapp_deep_link(
            phone_number=seller.phone_number,
            message=message
        )
        
        catalog_products.append(CatalogProductResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            price=float(product.price) if product.price else None,
            currency=product.currency,
            image_url=product.image_url,
            seller_name=seller.name,
            whatsapp_link=whatsapp_link
        ))
    
    return CatalogResponse(
        seller_name=seller.name,
        seller_phone=seller.phone_number,
        products=catalog_products,
        total_products=len(catalog_products)
    )


@router.post("/{catalog_slug}/interest", response_model=InterestResponse)
async def register_interest(
    catalog_slug: str,
    interest: InterestCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Register buyer interest in a product.
    Creates an interest record and returns WhatsApp deep link.
    """
    # Find seller
    seller = db.query(Seller).filter(
        Seller.catalog_slug == catalog_slug,
        Seller.is_active == True
    ).first()
    
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found"
        )
    
    # Find product
    product = db.query(Product).filter(
        Product.id == interest.product_id,
        Product.seller_id == seller.id,
        Product.is_active == True
    ).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or no longer available"
        )
    
    # Create interest record
    interest_record = Interest(
        product_id=interest.product_id,
        buyer_phone=interest.buyer_phone,
        buyer_name=interest.buyer_name,
        buyer_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        message_sent=False
    )
    
    db.add(interest_record)
    db.commit()
    db.refresh(interest_record)
    
    # Generate WhatsApp deep link
    message = f"Hi! I'm interested in your product: {product.name}"
    if product.price:
        message += f" (priced at ${product.price})"
    message += ". Is it still available?"
    
    whatsapp_link = whatsapp_service.generate_whatsapp_deep_link(
        phone_number=seller.phone_number,
        message=message
    )
    
    # Update interest as message sent
    interest_record.message_sent = True
    db.commit()
    
    # Log interest
    log_action(
        action_type=ActionLog.BUYER_INTEREST,
        seller_id=seller.id,
        product_id=product.id,
        interest_id=interest_record.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        action_data={
            "product_name": product.name,
            "buyer_name": interest.buyer_name,
            "buyer_phone": interest.buyer_phone
        }
    )
    
    # Notify seller via WhatsApp
    await whatsapp_service.send_interest_notification(
        to=seller.phone_number,
        buyer_name=interest.buyer_name,
        product_name=product.name
    )
    
    return InterestResponse(
        id=interest_record.id,
        product_id=interest_record.product_id,
        buyer_phone=interest_record.buyer_phone,
        buyer_name=interest_record.buyer_name,
        message_sent=interest_record.message_sent,
        created_at=interest_record.created_at,
        whatsapp_link=whatsapp_link
    )


@router.get("/{catalog_slug}/product/{product_id}")
async def view_product_detail(
    catalog_slug: str,
    product_id: UUID,
    db: Session = Depends(get_db)
):
    """View a single product detail (for sharing individual products)."""
    seller = db.query(Seller).filter(
        Seller.catalog_slug == catalog_slug,
        Seller.is_active == True
    ).first()
    
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog not found"
        )
    
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.seller_id == seller.id,
        Product.is_active == True
    ).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or no longer available"
        )
    
    # Generate WhatsApp link
    message = f"Hi! I'm interested in your product: {product.name}"
    if product.price:
        message += f" (priced at ${product.price})"
    message += ". Is it still available?"
    
    whatsapp_link = whatsapp_service.generate_whatsapp_deep_link(
        phone_number=seller.phone_number,
        message=message
    )
    
    return {
        "product": product.to_dict(),
        "seller": {
            "name": seller.name,
            "phone_number": seller.phone_number
        },
        "whatsapp_link": whatsapp_link
    }
