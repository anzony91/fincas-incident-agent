"""
Tickets API Router
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ticket import Category, Priority, Ticket, TicketStatus
from app.schemas import (
    AssignProviderRequest,
    ChangeStatusRequest,
    TicketCreate,
    TicketDetailResponse,
    TicketListResponse,
    TicketResponse,
    TicketUpdate,
)
from app.services.ticket_service import TicketService

router = APIRouter()


@router.get("", response_model=TicketListResponse)
async def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Optional[TicketStatus] = None,
    category: Optional[Category] = None,
    priority: Optional[Priority] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List tickets with pagination and filters"""
    query = select(Ticket)
    count_query = select(func.count(Ticket.id))
    
    # Apply filters
    if status:
        query = query.where(Ticket.status == status)
        count_query = count_query.where(Ticket.status == status)
    if category:
        query = query.where(Ticket.category == category)
        count_query = count_query.where(Ticket.category == category)
    if priority:
        query = query.where(Ticket.priority == priority)
        count_query = count_query.where(Ticket.priority == priority)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Ticket.subject.ilike(search_filter)) |
            (Ticket.ticket_code.ilike(search_filter)) |
            (Ticket.reporter_email.ilike(search_filter))
        )
        count_query = count_query.where(
            (Ticket.subject.ilike(search_filter)) |
            (Ticket.ticket_code.ilike(search_filter)) |
            (Ticket.reporter_email.ilike(search_filter))
        )
    
    # Get total count
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Ticket.created_at.desc()).offset(offset).limit(size)
    
    result = await db.execute(query)
    tickets = result.scalars().all()
    
    return TicketListResponse(
        items=[TicketResponse.model_validate(t) for t in tickets],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single ticket with all details"""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return TicketDetailResponse.model_validate(ticket)


@router.get("/code/{ticket_code}", response_model=TicketDetailResponse)
async def get_ticket_by_code(ticket_code: str, db: AsyncSession = Depends(get_db)):
    """Get a single ticket by code with all details"""
    result = await db.execute(select(Ticket).where(Ticket.ticket_code == ticket_code))
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return TicketDetailResponse.model_validate(ticket)


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket_data: TicketCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new ticket"""
    service = TicketService(db)
    ticket = await service.create_ticket(ticket_data)
    return TicketResponse.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a ticket"""
    service = TicketService(db)
    ticket = await service.update_ticket(ticket_id, ticket_data)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return TicketResponse.model_validate(ticket)


@router.post("/{ticket_id}/assign", response_model=TicketResponse)
async def assign_provider(
    ticket_id: int,
    request: AssignProviderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Assign a provider to a ticket"""
    service = TicketService(db)
    ticket = await service.assign_provider(ticket_id, request.provider_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return TicketResponse.model_validate(ticket)


@router.post("/{ticket_id}/status", response_model=TicketResponse)
async def change_status(
    ticket_id: int,
    request: ChangeStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    """Change ticket status"""
    service = TicketService(db)
    ticket = await service.change_status(ticket_id, request.status, request.comment)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return TicketResponse.model_validate(ticket)


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a ticket"""
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    await db.delete(ticket)
    await db.commit()
