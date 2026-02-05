"""
WhatsApp Business API service for Hustle.
Handles messaging, webhooks, and product upload flow.
"""

import os
import json
import re
import httpx
from typing import Optional, Dict, Any
from uuid import UUID

from app.services.logging import log_action
from app.models import ActionLog

# WhatsApp API Configuration
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = "v18.0"
WHATSAPP_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

# Catalog base URL
CATALOG_BASE_URL = os.getenv("CATALOG_BASE_URL", "https://hustle.app/catalog")


class WhatsAppService:
    """Service for interacting with WhatsApp Business API."""
    
    def __init__(self):
        self.api_token = WHATSAPP_API_TOKEN
        self.phone_number_id = WHATSAPP_PHONE_NUMBER_ID
        self.base_url = WHATSAPP_API_BASE
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
    
    async def send_text_message(
        self,
        to: str,
        message: str,
        preview_url: bool = True
    ) -> Dict[str, Any]:
        """
        Send a text message via WhatsApp.
        
        Args:
            to: Recipient phone number (with country code)
            message: Message text
            preview_url: Whether to show URL preview
        
        Returns:
            API response dict
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        
        # Format phone number (remove non-digits, ensure country code)
        formatted_phone = self._format_phone_number(to)
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_phone,
            "type": "text",
            "text": {
                "body": message,
                "preview_url": preview_url
            }
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                # Log the message sent
                log_action(
                    action_type=ActionLog.WHATSAPP_MESSAGE_SENT,
                    action_data={
                        "to": formatted_phone,
                        "message_type": "text",
                        "message_preview": message[:100]
                    },
                    whatsapp_message_id=result.get("messages", [{}])[0].get("id")
                )
                
                return {"success": True, "data": result}
            except httpx.HTTPError as e:
                error_msg = f"Failed to send WhatsApp message: {str(e)}"
                log_action(
                    action_type=ActionLog.ERROR_OCCURRED,
                    action_data={"error": error_msg, "phone": formatted_phone}
                )
                return {"success": False, "error": error_msg}
    
    async def send_image_message(
        self,
        to: str,
        image_url: str,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an image message via WhatsApp.
        
        Args:
            to: Recipient phone number
            image_url: URL of the image
            caption: Optional image caption
        
        Returns:
            API response dict
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        
        formatted_phone = self._format_phone_number(to)
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_phone,
            "type": "image",
            "image": {
                "link": image_url
            }
        }
        
        if caption:
            payload["image"]["caption"] = caption
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                log_action(
                    action_type=ActionLog.WHATSAPP_MESSAGE_SENT,
                    action_data={
                        "to": formatted_phone,
                        "message_type": "image",
                        "image_url": image_url
                    },
                    whatsapp_message_id=result.get("messages", [{}])[0].get("id")
                )
                
                return {"success": True, "data": result}
            except httpx.HTTPError as e:
                error_msg = f"Failed to send WhatsApp image: {str(e)}"
                return {"success": False, "error": error_msg}
    
    async def send_interactive_buttons(
        self,
        to: str,
        message: str,
        buttons: list
    ) -> Dict[str, Any]:
        """
        Send an interactive message with buttons.
        
        Args:
            to: Recipient phone number
            message: Message body
            buttons: List of button dicts with 'id' and 'title'
        
        Returns:
            API response dict
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        
        formatted_phone = self._format_phone_number(to)
        
        # Format buttons for WhatsApp API
        formatted_buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20]  # WhatsApp limit
                }
            }
            for btn in buttons[:3]  # Max 3 buttons
        ]
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": message[:1024]  # WhatsApp limit
                },
                "action": {
                    "buttons": formatted_buttons
                }
            }
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                log_action(
                    action_type=ActionLog.WHATSAPP_MESSAGE_SENT,
                    action_data={
                        "to": formatted_phone,
                        "message_type": "interactive_buttons",
                        "button_count": len(buttons)
                    },
                    whatsapp_message_id=result.get("messages", [{}])[0].get("id")
                )
                
                return {"success": True, "data": result}
            except httpx.HTTPError as e:
                error_msg = f"Failed to send interactive message: {str(e)}"
                return {"success": False, "error": error_msg}
    
    async def send_upload_confirmation(
        self,
        to: str,
        product_name: str,
        product_id: UUID,
        image_url: str,
        price: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send product upload confirmation message with ✅/❌ buttons.
        
        Args:
            to: Seller phone number
            product_name: Name of the product
            product_id: Product UUID
            image_url: Product image URL
            price: Optional price string
        
        Returns:
            API response dict
        """
        # First send the image
        caption = f"📦 *{product_name}*"
        if price:
            caption += f"\n💰 Price: {price}"
        caption += "\n\nAdd this product to your catalog?"
        
        image_result = await self.send_image_message(to, image_url, caption)
        
        if not image_result["success"]:
            return image_result
        
        # Then send confirmation buttons
        message = f"Tap ✅ to add *{product_name}* to your catalog, or ❌ to cancel."
        
        buttons = [
            {"id": f"confirm_add_{product_id}", "title": "✅ Add"},
            {"id": f"cancel_add_{product_id}", "title": "❌ Cancel"}
        ]
        
        return await self.send_interactive_buttons(to, message, buttons)
    
    async def send_welcome_message(
        self,
        to: str,
        seller_name: Optional[str] = None,
        catalog_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send welcome message to new seller.
        
        Args:
            to: Seller phone number
            seller_name: Optional seller name
            catalog_url: Optional catalog URL
        
        Returns:
            API response dict
        """
        name = seller_name or "there"
        
        message = f"""👋 Welcome to Hustle, {name}!

Your private catalog is ready. Here's how it works:

1️⃣ *Upload products*: Send me a photo with product details
2️⃣ *Confirm*: Tap ✅ to add to your catalog
3️⃣ *Manage*: Remove products anytime with checkboxes
4️⃣ *Share*: Copy your catalog link to WhatsApp Status
5️⃣ *Sell*: Buyers tap "I'm Interested" to message you

*Quick Tips:*
• Send product photos with name and price in caption
• You have 30 seconds to undo a removal
• All actions are logged for your protection

Ready to start selling? Send me your first product photo! 📸"""
        
        if catalog_url:
            message += f"\n\n🔗 Your catalog: {catalog_url}"
        
        return await self.send_text_message(to, message)
    
    async def send_product_added_confirmation(
        self,
        to: str,
        product_name: str,
        catalog_url: str
    ) -> Dict[str, Any]:
        """
        Send confirmation that product was added.
        
        Args:
            to: Seller phone number
            product_name: Name of the product
            catalog_url: Catalog URL
        
        Returns:
            API response dict
        """
        message = f"""✅ *{product_name}* added to your catalog!

Your catalog now has new items. Share your link on WhatsApp Status to attract buyers.

🔗 {catalog_url}

Send another photo to add more products! 📸"""
        
        return await self.send_text_message(to, message)
    
    async def send_interest_notification(
        self,
        to: str,
        buyer_name: Optional[str],
        product_name: str
    ) -> Dict[str, Any]:
        """
        Notify seller of buyer interest.
        
        Args:
            to: Seller phone number
            buyer_name: Name of interested buyer
            product_name: Name of the product
        
        Returns:
            API response dict
        """
        buyer = buyer_name or "Someone"
        
        message = f"""🛒 *New Interest!*

{buyer} is interested in *{product_name}*.

Check your WhatsApp messages to negotiate directly with the buyer.

Keep hustling! 💪"""
        
        return await self.send_text_message(to, message)
    
    def _format_phone_number(self, phone: str) -> str:
        """
        Format phone number for WhatsApp API.
        Removes non-digits and ensures country code.
        
        Args:
            phone: Raw phone number
        
        Returns:
            Formatted phone number
        """
        # Remove all non-digits
        digits = re.sub(r'\D', '', phone)
        
        # Ensure country code (assume +1 if starts with 1 and 11 digits)
        if len(digits) == 10:
            # Assume US number, add +1
            digits = "1" + digits
        
        return digits
    
    def generate_whatsapp_deep_link(
        self,
        phone_number: str,
        message: Optional[str] = None
    ) -> str:
        """
        Generate WhatsApp deep link for buyer to contact seller.
        
        Args:
            phone_number: Seller phone number
            message: Pre-filled message
        
        Returns:
            WhatsApp deep link
        """
        formatted_phone = self._format_phone_number(phone_number)
        
        if message:
            import urllib.parse
            encoded_message = urllib.parse.quote(message)
            return f"https://wa.me/{formatted_phone}?text={encoded_message}"
        
        return f"https://wa.me/{formatted_phone}"
    
    def parse_incoming_message(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse incoming webhook message from WhatsApp.
        
        Args:
            payload: Webhook payload
        
        Returns:
            Parsed message dict or None
        """
        try:
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            
            if "messages" not in value:
                return None
            
            message = value["messages"][0]
            
            parsed = {
                "message_id": message.get("id"),
                "from": message.get("from"),
                "timestamp": message.get("timestamp"),
                "type": message.get("type"),
                "profile": value.get("contacts", [{}])[0].get("profile", {})
            }
            
            # Extract message content based on type
            if message.get("type") == "text":
                parsed["text"] = message.get("text", {}).get("body", "")
            elif message.get("type") == "image":
                parsed["image"] = message.get("image", {})
                parsed["caption"] = message.get("image", {}).get("caption", "")
            elif message.get("type") == "interactive":
                interactive = message.get("interactive", {})
                if "button_reply" in interactive:
                    parsed["button_reply"] = interactive["button_reply"]
                elif "list_reply" in interactive:
                    parsed["list_reply"] = interactive["list_reply"]
            
            # Log received message
            log_action(
                action_type=ActionLog.WHATSAPP_MESSAGE_RECEIVED,
                action_data={
                    "from": parsed["from"],
                    "message_type": parsed["type"],
                    "message_id": parsed["message_id"]
                },
                whatsapp_message_id=parsed["message_id"]
            )
            
            return parsed
            
        except (KeyError, IndexError) as e:
            return None


# Singleton instance
whatsapp_service = WhatsAppService()
