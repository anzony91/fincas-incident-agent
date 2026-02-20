"""
Reporters API Router
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reporter import Reporter
from app.schemas import (
    ReporterCreate,
    ReporterListResponse,
    ReporterResponse,
    ReporterUpdate,
)

router = APIRouter()


@router.get("", response_model=ReporterListResponse)
async def list_reporters(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    community: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List reporters with pagination and filters"""
    query = select(Reporter)
    count_query = select(func.count(Reporter.id))
    
    # Apply filters
    if is_active is not None:
        query = query.where(Reporter.is_active == is_active)
        count_query = count_query.where(Reporter.is_active == is_active)
    if community:
        community_filter = f"%{community}%"
        query = query.where(Reporter.community_name.ilike(community_filter))
        count_query = count_query.where(Reporter.community_name.ilike(community_filter))
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Reporter.name.ilike(search_filter)) |
            (Reporter.email.ilike(search_filter)) |
            (Reporter.phone.ilike(search_filter))
        )
        count_query = count_query.where(
            (Reporter.name.ilike(search_filter)) |
            (Reporter.email.ilike(search_filter)) |
            (Reporter.phone.ilike(search_filter))
        )
    
    # Get total count
    total = await db.scalar(count_query)
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Reporter.name).offset(offset).limit(size)
    
    result = await db.execute(query)
    reporters = result.scalars().all()
    
    return ReporterListResponse(
        items=[ReporterResponse.model_validate(r) for r in reporters],
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/by-community/{community_name}", response_model=list[ReporterResponse])
async def get_reporters_by_community(
    community_name: str,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Get all reporters for a specific community"""
    query = select(Reporter).where(Reporter.community_name.ilike(f"%{community_name}%"))
    
    if active_only:
        query = query.where(Reporter.is_active == True)  # noqa: E712
    
    query = query.order_by(Reporter.name)
    
    result = await db.execute(query)
    reporters = result.scalars().all()
    
    return [ReporterResponse.model_validate(r) for r in reporters]


@router.get("/by-email/{email}", response_model=ReporterResponse)
async def get_reporter_by_email(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a reporter by their email address"""
    result = await db.execute(select(Reporter).where(Reporter.email == email))
    reporter = result.scalar_one_or_none()
    
    if not reporter:
        raise HTTPException(status_code=404, detail="Reporter not found")
    
    return ReporterResponse.model_validate(reporter)


@router.get("/{reporter_id}", response_model=ReporterResponse)
async def get_reporter(reporter_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single reporter"""
    result = await db.execute(select(Reporter).where(Reporter.id == reporter_id))
    reporter = result.scalar_one_or_none()
    
    if not reporter:
        raise HTTPException(status_code=404, detail="Reporter not found")
    
    return ReporterResponse.model_validate(reporter)


@router.post("", response_model=ReporterResponse, status_code=201)
async def create_reporter(
    reporter_data: ReporterCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new reporter"""
    # Check if email already exists
    existing = await db.execute(
        select(Reporter).where(Reporter.email == reporter_data.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    reporter = Reporter(**reporter_data.model_dump())
    db.add(reporter)
    await db.commit()
    await db.refresh(reporter)
    
    return ReporterResponse.model_validate(reporter)


@router.patch("/{reporter_id}", response_model=ReporterResponse)
async def update_reporter(
    reporter_id: int,
    reporter_data: ReporterUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a reporter"""
    result = await db.execute(select(Reporter).where(Reporter.id == reporter_id))
    reporter = result.scalar_one_or_none()
    
    if not reporter:
        raise HTTPException(status_code=404, detail="Reporter not found")
    
    # Check if email already exists (if changing email)
    if reporter_data.email and reporter_data.email != reporter.email:
        existing = await db.execute(
            select(Reporter).where(Reporter.email == reporter_data.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
    
    update_data = reporter_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(reporter, field, value)
    
    await db.commit()
    await db.refresh(reporter)
    
    return ReporterResponse.model_validate(reporter)


@router.delete("/{reporter_id}", status_code=204)
async def delete_reporter(
    reporter_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a reporter"""
    result = await db.execute(select(Reporter).where(Reporter.id == reporter_id))
    reporter = result.scalar_one_or_none()
    
    if not reporter:
        raise HTTPException(status_code=404, detail="Reporter not found")
    
    await db.delete(reporter)
    await db.commit()


@router.get("/stats/communities", response_model=list[dict])
async def get_community_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get statistics about reporters grouped by community"""
    query = select(
        Reporter.community_name,
        func.count(Reporter.id).label('count')
    ).where(
        Reporter.community_name.isnot(None)
    ).group_by(
        Reporter.community_name
    ).order_by(
        func.count(Reporter.id).desc()
    )
    
    result = await db.execute(query)
    stats = result.all()
    
    return [{"community": s[0], "count": s[1]} for s in stats]


@router.post("/seed-from-tickets")
async def seed_reporters_from_tickets(
    db: AsyncSession = Depends(get_db),
):
    """
    Create reporters from existing ticket data.
    Only creates reporters for emails that don't exist yet.
    """
    from app.models.ticket import Ticket
    
    # Get all tickets with reporter info
    tickets_result = await db.execute(
        select(Ticket).where(Ticket.reporter_email.isnot(None))
    )
    tickets = tickets_result.scalars().all()
    
    created = []
    skipped = []
    
    for ticket in tickets:
        email = ticket.reporter_email.lower().strip()
        
        # Check if reporter already exists
        existing = await db.execute(
            select(Reporter).where(Reporter.email == email)
        )
        if existing.scalar_one_or_none():
            skipped.append(email)
            continue
        
        # Create new reporter from ticket data
        reporter = Reporter(
            name=ticket.reporter_name or email.split('@')[0],
            email=email,
            phone=ticket.reporter_phone,
            community_name=ticket.community_name,
            address=ticket.address,
            floor_door=ticket.location_detail,
            is_active=True,
        )
        db.add(reporter)
        created.append({
            "email": email,
            "name": reporter.name,
            "phone": reporter.phone,
        })
    
    await db.commit()
    
    return {
        "created": len(created),
        "skipped": len(skipped),
        "details": created,
    }
