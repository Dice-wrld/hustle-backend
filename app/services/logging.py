"""
Logging service for comprehensive action tracking.
Used for dispute resolution and system monitoring.
"""

import json
from typing import Optional, Any, Dict
from uuid import UUID
from datetime import datetime

from app.database import SessionLocal
from app.models import ActionLog


def log_action(
    action_type: str,
    seller_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    interest_id: Optional[UUID] = None,
    action_data: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    whatsapp_message_id: Optional[str] = None
) -> ActionLog:
    """
    Log an action to the database.
    
    Args:
        action_type: Type of action (from ActionLog constants)
        seller_id: Optional seller UUID
        product_id: Optional product UUID
        interest_id: Optional interest UUID
        action_data: Optional dict of additional data (will be JSON serialized)
        ip_address: Optional IP address
        user_agent: Optional user agent string
        whatsapp_message_id: Optional WhatsApp message ID
    
    Returns:
        Created ActionLog instance
    """
    db = SessionLocal()
    try:
        log_entry = ActionLog(
            action_type=action_type,
            seller_id=seller_id,
            product_id=product_id,
            interest_id=interest_id,
            action_data=json.dumps(action_data) if action_data else None,
            ip_address=ip_address,
            user_agent=user_agent,
            whatsapp_message_id=whatsapp_message_id
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
    except Exception as e:
        db.rollback()
        # Don't raise - logging should not break main flow
        print(f"Failed to log action: {e}")
        return None
    finally:
        db.close()


def get_seller_logs(
    seller_id: UUID,
    action_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> list:
    """
    Get action logs for a specific seller.
    
    Args:
        seller_id: Seller UUID
        action_type: Optional filter by action type
        limit: Maximum number of results
        offset: Pagination offset
    
    Returns:
        List of ActionLog instances
    """
    db = SessionLocal()
    try:
        query = db.query(ActionLog).filter(ActionLog.seller_id == seller_id)
        
        if action_type:
            query = query.filter(ActionLog.action_type == action_type)
        
        return query.order_by(ActionLog.created_at.desc()).offset(offset).limit(limit).all()
    finally:
        db.close()


def get_product_logs(product_id: UUID, limit: int = 50) -> list:
    """
    Get action logs for a specific product.
    
    Args:
        product_id: Product UUID
        limit: Maximum number of results
    
    Returns:
        List of ActionLog instances
    """
    db = SessionLocal()
    try:
        return db.query(ActionLog).filter(
            ActionLog.product_id == product_id
        ).order_by(ActionLog.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def get_recent_logs(hours: int = 24, action_type: Optional[str] = None) -> list:
    """
    Get recent action logs.
    
    Args:
        hours: Number of hours to look back
        action_type: Optional filter by action type
    
    Returns:
        List of ActionLog instances
    """
    db = SessionLocal()
    try:
        from datetime import timedelta
        
        since = datetime.utcnow() - timedelta(hours=hours)
        query = db.query(ActionLog).filter(ActionLog.created_at >= since)
        
        if action_type:
            query = query.filter(ActionLog.action_type == action_type)
        
        return query.order_by(ActionLog.created_at.desc()).all()
    finally:
        db.close()


def log_error(
    error_message: str,
    seller_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    details: Optional[Dict[str, Any]] = None
) -> ActionLog:
    """
    Log an error occurrence.
    
    Args:
        error_message: Description of the error
        seller_id: Optional seller UUID
        product_id: Optional product UUID
        details: Optional error details
    
    Returns:
        Created ActionLog instance
    """
    action_data = {"error": error_message}
    if details:
        action_data.update(details)
    
    return log_action(
        action_type=ActionLog.ERROR_OCCURRED,
        seller_id=seller_id,
        product_id=product_id,
        action_data=action_data
    )
