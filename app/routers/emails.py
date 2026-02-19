"""
Emails API Router
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.email import Email, EmailDirection
from app.schemas import EmailListResponse, EmailResponse

router = APIRouter()


@router.get("", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    ticket_id: Optional[int] = None,
    direction: Optional[EmailDirection] = None,
    db: AsyncSession = Depends(get_db),
):
    """List emails with pagination and filters"""
    query = select(Email)
    count_query = select(func.count(Email.id))
    
    # Apply filters
    if ticket_id:
        query = query.where(Email.ticket_id == ticket_id)
        count_query = count_query.where(Email.ticket_id == ticket_id)
    if direction:
        query = query.where(Email.direction == direction)
        count_query = count_query.where(Email.direction == direction)
    
    # Get total count
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Email.received_at.desc()).offset(offset).limit(size)
    
    result = await db.execute(query)
    emails = result.scalars().all()
    
    return EmailListResponse(
        items=[EmailResponse.model_validate(e) for e in emails],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/{email_id}", response_model=EmailResponse)
async def get_email(email_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single email"""
    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return EmailResponse.model_validate(email)


@router.get("/ticket/{ticket_id}", response_model=list[EmailResponse])
async def get_emails_by_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    """Get all emails for a specific ticket"""
    query = (
        select(Email)
        .where(Email.ticket_id == ticket_id)
        .order_by(Email.received_at.asc())
    )
    
    result = await db.execute(query)
    emails = result.scalars().all()
    
    return [EmailResponse.model_validate(e) for e in emails]
