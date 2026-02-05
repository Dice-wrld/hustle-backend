"""
WhatsApp webhook endpoints for receiving messages and events.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy.orm import Session
import json
import hmac
import hashlib
import os

from app.database import get_db
from app.models import Seller, Product, ActionLog
from app.services.whatsapp import whatsapp_service
from app.services.logging import log_action

router = APIRouter(prefix="/webhook", tags=["Webhook"])

# Webhook verification token
VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "hustle-webhook-token")


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Verify WhatsApp webhook subscription.
    Meta calls this endpoint to verify the webhook.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        # Return the challenge to confirm verification
        return int(hub_challenge)
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification failed"
    )


@router.post("/whatsapp")
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Receive WhatsApp webhook events.
    Handles incoming messages, button clicks, and status updates.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Parse the incoming message
    parsed = whatsapp_service.parse_incoming_message(payload)
    
    if not parsed:
        # Not a message event (could be status update)
        return {"status": "ignored"}
    
    phone_number = parsed.get("from")
    message_type = parsed.get("type")
    
    # Handle different message types
    if message_type == "text":
        await handle_text_message(phone_number, parsed.get("text", ""), db)
    
    elif message_type == "image":
        await handle_image_message(
            phone_number,
            parsed.get("image", {}),
            parsed.get("caption", ""),
            db
        )
    
    elif message_type == "interactive":
        await handle_interactive_message(phone_number, parsed, db)
    
    return {"status": "processed"}


async def handle_text_message(
    phone_number: str,
    text: str,
    db: Session
):
    """Handle incoming text message."""
    text_lower = text.lower().strip()
    
    # Check for registration command
    if text_lower in ["start", "hello", "hi", "register", "signup"]:
        await handle_registration(phone_number, db)
        return
    
    # Check for help command
    if text_lower in ["help", "?", "how", "guide"]:
        await send_help_message(phone_number)
        return
    
    # Check for catalog link request
    if any(word in text_lower for word in ["link", "catalog", "my shop", "my store"]):
        await send_catalog_link(phone_number, db)
        return
    
    # Default response
    await whatsapp_service.send_text_message(
        to=phone_number,
        message="""👋 I didn't understand that.

Send me a *photo* to add a product to your catalog.

Or type:
• *help* - for instructions
• *link* - to get your catalog link
• *start* - to see the welcome message"""
    )


async def handle_image_message(
    phone_number: str,
    image_data: dict,
    caption: str,
    db: Session
):
    """Handle incoming image message (product upload)."""
    # Find or create seller
    seller = db.query(Seller).filter(Seller.phone_number == phone_number).first()
    
    if not seller:
        # Auto-register if not exists
        seller = await auto_register_seller(phone_number, db)
    
    # Get image URL from WhatsApp
    image_id = image_data.get("id")
    if not image_id:
        await whatsapp_service.send_text_message(
            to=phone_number,
            message="❌ Sorry, I couldn't process that image. Please try again."
        )
        return
    
    # Download image URL from WhatsApp API
    image_url = await get_media_url(image_id)
    
    if not image_url:
        await whatsapp_service.send_text_message(
            to=phone_number,
            message="❌ Sorry, I couldn't download that image. Please try again."
        )
        return
    
    # Create product (inactive until confirmed)
    from app.routers.products import UPLOAD_DIR, MAX_UPLOAD_SIZE
    import uuid as uuid_module
    import httpx
    import os
    
    # Parse caption for product details
    import re
    name = "Untitled Product"
    price = None
    
    if caption:
        price_match = re.search(r'[\$£€]?(\d+(?:\.\d{2})?)', caption)
        if price_match:
            price = float(price_match.group(1))
            name = caption[:price_match.start()].strip() or "Untitled Product"
            name = re.sub(r'[-–—:]$', '', name).strip()
        else:
            name = caption[:50]
    
    # Download and save image
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30.0)
            response.raise_for_status()
            
            file_ext = ".jpg"
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
        await whatsapp_service.send_text_message(
            to=phone_number,
            message=f"❌ Failed to process image: {str(e)}"
        )
        return
    
    # Create product
    product = Product(
        seller_id=seller.id,
        name=name,
        description=caption,
        price=price,
        currency="USD",
        image_url=local_image_url,
        image_path=file_path,
        is_active=False  # Inactive until confirmed
    )
    
    db.add(product)
    db.commit()
    db.refresh(product)
    
    # Log upload
    log_action(
        action_type=ActionLog.PRODUCT_UPLOADED,
        seller_id=seller.id,
        product_id=product.id,
        action_data={"product_name": name, "price": price}
    )
    
    # Send confirmation
    price_str = f"${price:.2f}" if price else None
    await whatsapp_service.send_upload_confirmation(
        to=phone_number,
        product_name=name,
        product_id=product.id,
        image_url=local_image_url,
        price=price_str
    )


async def handle_interactive_message(
    phone_number: str,
    parsed: dict,
    db: Session
):
    """Handle interactive message (button clicks)."""
    button_reply = parsed.get("button_reply", {})
    button_id = button_reply.get("id", "")
    
    # Handle product confirmation buttons
    if button_id.startswith("confirm_add_"):
        product_id = button_id.replace("confirm_add_", "")
        await confirm_product(product_id, phone_number, True, db)
    
    elif button_id.startswith("cancel_add_"):
        product_id = button_id.replace("cancel_add_", "")
        await confirm_product(product_id, phone_number, False, db)


async def confirm_product(
    product_id: str,
    phone_number: str,
    confirmed: bool,
    db: Session
):
    """Handle product confirmation button click."""
    from uuid import UUID
    from app.services.whatsapp import CATALOG_BASE_URL
    
    try:
        product_uuid = UUID(product_id)
    except ValueError:
        await whatsapp_service.send_text_message(
            to=phone_number,
            message="❌ Invalid product ID."
        )
        return
    
    product = db.query(Product).filter(Product.id == product_uuid).first()
    
    if not product:
        await whatsapp_service.send_text_message(
            to=phone_number,
            message="❌ Product not found. It may have been deleted."
        )
        return
    
    seller = db.query(Seller).filter(Seller.id == product.seller_id).first()
    
    if confirmed:
        # Activate product
        product.is_active = True
        db.commit()
        
        log_action(
            action_type=ActionLog.PRODUCT_CONFIRMED,
            seller_id=product.seller_id,
            product_id=product.id,
            action_data={"product_name": product.name}
        )
        
        # Send confirmation
        catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
        await whatsapp_service.send_product_added_confirmation(
            to=phone_number,
            product_name=product.name,
            catalog_url=catalog_url
        )
    else:
        # Cancel - delete product
        import os
        try:
            if os.path.exists(product.image_path):
                os.remove(product.image_path)
        except Exception:
            pass
        
        db.delete(product)
        db.commit()
        
        log_action(
            action_type=ActionLog.PRODUCT_CANCELLED,
            seller_id=seller.id if seller else None,
            action_data={"product_name": product.name}
        )
        
        await whatsapp_service.send_text_message(
            to=phone_number,
            message=f"❌ *{product.name}* was not added to your catalog.\n\nSend another photo to try again!"
        )


async def handle_registration(phone_number: str, db: Session):
    """Handle seller registration."""
    seller = db.query(Seller).filter(Seller.phone_number == phone_number).first()
    
    if seller:
        # Already registered
        from app.services.whatsapp import CATALOG_BASE_URL
        catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
        
        await whatsapp_service.send_text_message(
            to=phone_number,
            message=f"""👋 Welcome back to Hustle!

You're already registered. 

🔗 Your catalog: {catalog_url}

Send me a photo to add a new product! 📸"""
        )
    else:
        # Register new seller
        seller = await auto_register_seller(phone_number, db)


async def auto_register_seller(phone_number: str, db: Session) -> Seller:
    """Auto-register a new seller."""
    import secrets
    import string
    from app.services.whatsapp import CATALOG_BASE_URL
    
    # Generate unique slug
    def generate_slug():
        return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    
    slug = generate_slug()
    while db.query(Seller).filter(Seller.catalog_slug == slug).first():
        slug = generate_slug()
    
    seller = Seller(
        phone_number=phone_number,
        catalog_slug=slug,
        whatsapp_chat_id=phone_number,
        is_active=True
    )
    
    db.add(seller)
    db.commit()
    db.refresh(seller)
    
    # Log registration
    log_action(
        action_type=ActionLog.SELLER_REGISTERED,
        seller_id=seller.id,
        action_data={"phone_number": phone_number, "catalog_slug": slug}
    )
    
    # Send welcome message
    catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
    await whatsapp_service.send_welcome_message(
        to=phone_number,
        seller_name=seller.name,
        catalog_url=catalog_url
    )
    
    return seller


async def send_help_message(phone_number: str):
    """Send help message."""
    await whatsapp_service.send_text_message(
        to=phone_number,
        message="""📚 *Hustle Quick Guide*

*Adding Products:*
1. Send me a product photo
2. Include name and price in caption (optional)
3. Tap ✅ to confirm

*Managing Products:*
• Use the app to view all products
• Check boxes to remove (30s undo available)
• Your catalog updates automatically

*Sharing:*
• Type "link" to get your catalog URL
• Share on WhatsApp Status
• Buyers tap "I'm Interested" to message you

*Tips:*
• Good photos sell better!
• Be responsive to buyer messages
• All actions are logged for protection

Need more help? Contact support@hustle.app"""
    )


async def send_catalog_link(phone_number: str, db: Session):
    """Send catalog link to seller."""
    seller = db.query(Seller).filter(Seller.phone_number == phone_number).first()
    
    if not seller:
        await whatsapp_service.send_text_message(
            to=phone_number,
            message="❌ You're not registered yet. Type 'start' to register."
        )
        return
    
    from app.services.whatsapp import CATALOG_BASE_URL
    catalog_url = f"{CATALOG_BASE_URL}/{seller.catalog_slug}"
    
    await whatsapp_service.send_text_message(
        to=phone_number,
        message=f"""🔗 *Your Catalog Link*

{catalog_url}

Share this link on WhatsApp Status to attract buyers!

*How to share:*
1. Copy the link above
2. Go to WhatsApp Status
3. Paste as a text status
4. Add "Shop my catalog! 👆" as caption

Your catalog updates automatically when you add/remove products."""
    )


async def get_media_url(media_id: str) -> str:
    """Get media URL from WhatsApp API."""
    import httpx
    import os
    
    api_token = os.getenv("WHATSAPP_API_TOKEN", "")
    api_version = "v18.0"
    base_url = f"https://graph.facebook.com/{api_version}"
    
    url = f"{base_url}/{media_id}"
    headers = {"Authorization": f"Bearer {api_token}"}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return data.get("url", "")
        except Exception:
            return ""
