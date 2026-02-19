"""Dashboard router for serving HTML views."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.ticket import Ticket, TicketStatus, Category, Priority
from app.models.provider import Provider
from app.models.event import Event
from app.models.email import Email

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard with overview statistics."""
    # Get ticket counts
    total_result = await db.execute(select(func.count(Ticket.id)))
    total = total_result.scalar() or 0
    
    open_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.NEW)
    )
    open_count = open_result.scalar() or 0
    
    in_progress_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.IN_PROGRESS)
    )
    in_progress = in_progress_result.scalar() or 0
    
    pending_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.NEEDS_INFO)
    )
    pending = pending_result.scalar() or 0
    
    dispatched_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.DISPATCHED)
    )
    dispatched = dispatched_result.scalar() or 0
    
    closed_result = await db.execute(
        select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.CLOSED)
    )
    closed = closed_result.scalar() or 0
    
    urgent_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.priority == Priority.URGENT,
            Ticket.status != TicketStatus.CLOSED
        )
    )
    urgent = urgent_result.scalar() or 0
    
    # Get counts by category
    categories_data = {}
    for cat in Category:
        cat_result = await db.execute(
            select(func.count(Ticket.id)).where(Ticket.category == cat)
        )
        count = cat_result.scalar() or 0
        if count > 0:
            categories_data[cat.value] = count
    
    # Get recent tickets
    recent_result = await db.execute(
        select(Ticket).order_by(Ticket.created_at.desc()).limit(10)
    )
    recent_tickets = recent_result.scalars().all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "now": datetime.utcnow(),
        "stats": {
            "total": total,
            "new": open_count,
            "in_progress": in_progress,
            "pending": pending,
            "dispatched": dispatched,
            "closed": closed,
            "urgent": urgent
        },
        "categories": categories_data,
        "recent_tickets": recent_tickets
    })


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_list(
    request: Request,
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List all tickets with filtering and pagination."""
    query = select(Ticket)
    
    # Apply filters
    if status:
        try:
            query = query.where(Ticket.status == TicketStatus(status))
        except ValueError:
            pass
    
    if category:
        try:
            query = query.where(Ticket.category == Category(category))
        except ValueError:
            pass
    
    if priority:
        try:
            query = query.where(Ticket.priority == Priority(priority))
        except ValueError:
            pass
    
    if search:
        search_filter = or_(
            Ticket.ticket_code.ilike(f"%{search}%"),
            Ticket.subject.ilike(f"%{search}%"),
            Ticket.reporter_email.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.order_by(Ticket.created_at.desc()).offset(offset).limit(size)
    
    result = await db.execute(query)
    tickets = result.scalars().all()
    
    # Calculate pages
    pages = (total + size - 1) // size if total > 0 else 1
    
    return templates.TemplateResponse("tickets.html", {
        "request": request,
        "tickets": tickets,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "filters": {
            "status": status,
            "category": category,
            "priority": priority,
            "search": search
        },
        "statuses": [s.value for s in TicketStatus],
        "categories": [c.value for c in Category],
        "priorities": [p.value for p in Priority]
    })


@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Show ticket detail with events and emails."""
    # Get ticket
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        return RedirectResponse(url="/dashboard/tickets", status_code=302)
    
    # Get events
    events_result = await db.execute(
        select(Event).where(Event.ticket_id == ticket_id).order_by(Event.created_at.desc())
    )
    events = events_result.scalars().all()
    
    # Get emails
    emails_result = await db.execute(
        select(Email).where(Email.ticket_id == ticket_id).order_by(Email.received_at.desc())
    )
    emails = emails_result.scalars().all()
    
    # Get all providers for assignment
    providers_result = await db.execute(
        select(Provider).where(Provider.active == True).order_by(Provider.name)
    )
    providers = providers_result.scalars().all()
    
    # Load assigned provider if exists
    if ticket.assigned_provider_id:
        provider_result = await db.execute(
            select(Provider).where(Provider.id == ticket.assigned_provider_id)
        )
        ticket.assigned_provider = provider_result.scalar_one_or_none()
    else:
        ticket.assigned_provider = None
    
    return templates.TemplateResponse("ticket_detail.html", {
        "request": request,
        "ticket": ticket,
        "events": events,
        "emails": emails,
        "providers": providers,
        "statuses": [s.value for s in TicketStatus]
    })


@router.post("/tickets/{ticket_id}/status", response_class=HTMLResponse)
async def update_ticket_status(
    ticket_id: int,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Update ticket status."""
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if ticket:
        old_status = ticket.status
        try:
            new_status = TicketStatus(status)
            ticket.status = new_status
            ticket.updated_at = datetime.utcnow()
            
            if new_status == TicketStatus.CLOSED and not ticket.resolved_at:
                ticket.resolved_at = datetime.utcnow()
            
            # Create event
            event = Event(
                ticket_id=ticket_id,
                event_type="STATUS_CHANGED",
                description=f"Estado cambiado de {old_status.value} a {new_status.value}",
                actor="Dashboard"
            )
            db.add(event)
            await db.commit()
        except ValueError:
            pass
    
    return RedirectResponse(url=f"/dashboard/tickets/{ticket_id}", status_code=302)


@router.post("/tickets/{ticket_id}/assign", response_class=HTMLResponse)
async def assign_provider(
    ticket_id: int,
    provider_id: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """Assign provider to ticket."""
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if ticket:
        provider_id_int = int(provider_id) if provider_id else None
        old_provider_id = ticket.assigned_provider_id
        ticket.assigned_provider_id = provider_id_int
        ticket.updated_at = datetime.utcnow()
        
        # Get provider name for event
        provider_name = "Ninguno"
        if provider_id_int:
            provider_result = await db.execute(
                select(Provider).where(Provider.id == provider_id_int)
            )
            provider = provider_result.scalar_one_or_none()
            if provider:
                provider_name = provider.name
        
        # Create event
        event = Event(
            ticket_id=ticket_id,
            event_type="PROVIDER_ASSIGNED",
            description=f"Proveedor asignado: {provider_name}",
            actor="Dashboard"
        )
        db.add(event)
        await db.commit()
    
    return RedirectResponse(url=f"/dashboard/tickets/{ticket_id}", status_code=302)


@router.get("/providers", response_class=HTMLResponse)
async def providers_list(request: Request, db: AsyncSession = Depends(get_db)):
    """List all providers."""
    result = await db.execute(
        select(Provider).order_by(Provider.category, Provider.name)
    )
    providers = result.scalars().all()
    
    return templates.TemplateResponse("providers.html", {
        "request": request,
        "providers": providers,
        "categories": [c.value for c in Category]
    })
