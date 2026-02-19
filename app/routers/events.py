"""
Events API Router
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.event import Event
from app.schemas import EventCreate, EventListResponse, EventResponse

router = APIRouter()


@router.get("", response_model=EventListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    ticket_id: Optional[int] = None,
    event_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List events with pagination and filters"""
    query = select(Event)
    count_query = select(func.count(Event.id))
    
    # Apply filters
    if ticket_id:
        query = query.where(Event.ticket_id == ticket_id)
        count_query = count_query.where(Event.ticket_id == ticket_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
        count_query = count_query.where(Event.event_type == event_type)
    
    # Get total count
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Event.created_at.desc()).offset(offset).limit(size)
    
    result = await db.execute(query)
    events = result.scalars().all()
    
    return EventListResponse(
        items=[EventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single event"""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return EventResponse.model_validate(event)


@router.get("/ticket/{ticket_id}", response_model=list[EventResponse])
async def get_events_by_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    """Get all events for a specific ticket"""
    query = (
        select(Event)
        .where(Event.ticket_id == ticket_id)
        .order_by(Event.created_at.asc())
    )
    
    result = await db.execute(query)
    events = result.scalars().all()
    
    return [EventResponse.model_validate(e) for e in events]


@router.post("/ticket/{ticket_id}", response_model=EventResponse, status_code=201)
async def create_event(
    ticket_id: int,
    event_data: EventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new event for a ticket"""
    event = Event(
        ticket_id=ticket_id,
        event_type=event_data.event_type,
        description=event_data.description,
        payload=event_data.payload,
        created_by=event_data.created_by,
    )
    
    db.add(event)
    await db.commit()
    await db.refresh(event)
    
    return EventResponse.model_validate(event)
