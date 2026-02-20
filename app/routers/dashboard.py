"""Dashboard router for serving HTML views."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, distinct
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.ticket import Ticket, TicketStatus, Category, Priority
from app.models.provider import Provider
from app.models.reporter import Reporter
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
        return RedirectResponse(url="/dashboard/tickets", status_code=303)
    
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
        select(Provider).where(Provider.is_active == True).order_by(Provider.name)
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
    
    # Clean up ai_context missing_fields - remove fields that already have values
    if ticket.ai_context and ticket.ai_context.get('analysis'):
        analysis = ticket.ai_context['analysis']
        if analysis.get('missing_fields'):
            # Mapping of common field name variations to ticket attributes
            field_mapping = {
                'address': lambda t: t.address,
                'dirección': lambda t: t.address,
                'direccion': lambda t: t.address,
                'location_detail': lambda t: t.location_detail,
                'ubicación': lambda t: t.location_detail,
                'ubicacion': lambda t: t.location_detail,
                'detalle de ubicación': lambda t: t.location_detail,
                'detalle ubicación': lambda t: t.location_detail,
                'piso/puerta': lambda t: t.location_detail,
                'reporter_name': lambda t: t.reporter_name,
                'nombre': lambda t: t.reporter_name,
                'nombre del reportante': lambda t: t.reporter_name,
                'reporter_contact': lambda t: t.reporter_email,
                'teléfono': lambda t: ticket.ai_context.get('analysis', {}).get('extracted_info', {}).get('reporter_contact'),
                'telefono': lambda t: ticket.ai_context.get('analysis', {}).get('extracted_info', {}).get('reporter_contact'),
                'contacto': lambda t: t.reporter_email,
                'comunidad': lambda t: t.community_name,
                'community_name': lambda t: t.community_name,
                'nombre de comunidad': lambda t: t.community_name,
            }
            
            # Filter out fields that already have values
            actual_missing = []
            extracted_info = analysis.get('extracted_info', {})
            
            for field in analysis['missing_fields']:
                field_lower = field.lower().strip()
                
                # Check if this field has a value in ticket or extracted_info
                has_value = False
                
                # Check direct mapping
                for key, getter in field_mapping.items():
                    if key in field_lower or field_lower in key:
                        value = getter(ticket)
                        if value:
                            has_value = True
                            break
                
                # Also check extracted_info for this field
                if not has_value:
                    for info_key, info_value in extracted_info.items():
                        if info_key.lower() in field_lower or field_lower in info_key.lower():
                            if info_value:
                                has_value = True
                                break
                
                if not has_value:
                    actual_missing.append(field)
            
            # Update the analysis with filtered missing_fields
            analysis['missing_fields'] = actual_missing
    
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
            
            if new_status == TicketStatus.CLOSED and not ticket.closed_at:
                ticket.closed_at = datetime.utcnow()
            
            # Create event
            event = Event(
                ticket_id=ticket_id,
                event_type="STATUS_CHANGED",
                description=f"Estado cambiado de {old_status.value} a {new_status.value}",
                created_by="Dashboard"
            )
            db.add(event)
            await db.commit()
        except ValueError:
            pass
    
    return RedirectResponse(url=f"/dashboard/tickets/{ticket_id}", status_code=303)


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
        # Handle empty string or invalid provider_id
        provider_id_int = None
        if provider_id and provider_id.strip():
            try:
                provider_id_int = int(provider_id)
            except ValueError:
                provider_id_int = None
        
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
            created_by="Dashboard"
        )
        db.add(event)
        await db.commit()
    
    return RedirectResponse(url=f"/dashboard/tickets/{ticket_id}", status_code=303)


# ============ PROVIDERS ROUTES ============

@router.get("/providers", response_class=HTMLResponse)
async def providers_list(
    request: Request,
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """List all providers with filters and stats."""
    query = select(Provider)
    
    # Apply filters
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            or_(
                Provider.name.ilike(search_filter),
                Provider.email.ilike(search_filter),
                Provider.phone.ilike(search_filter)
            )
        )
    if category:
        query = query.where(Provider.category == category)
    if is_active == 'true':
        query = query.where(Provider.is_active == True)
    elif is_active == 'false':
        query = query.where(Provider.is_active == False)
    
    query = query.order_by(Provider.category, Provider.name)
    result = await db.execute(query)
    providers = result.scalars().all()
    
    # Get stats
    total_result = await db.execute(select(func.count(Provider.id)))
    total = total_result.scalar() or 0
    
    active_result = await db.execute(
        select(func.count(Provider.id)).where(Provider.is_active == True)
    )
    active = active_result.scalar() or 0
    
    emergency_result = await db.execute(
        select(func.count(Provider.id)).where(Provider.has_emergency_service == True)
    )
    emergency = emergency_result.scalar() or 0
    
    categories_result = await db.execute(
        select(func.count(distinct(Provider.category)))
    )
    categories_count = categories_result.scalar() or 0
    
    return templates.TemplateResponse("providers.html", {
        "request": request,
        "providers": providers,
        "categories": [c.value for c in Category],
        "search": search,
        "category": category,
        "is_active": is_active,
        "stats": {
            "total": total,
            "active": active,
            "emergency": emergency,
            "categories": categories_count
        }
    })


@router.post("/providers/create", response_class=HTMLResponse)
async def create_provider(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    category: str = Form(...),
    company_name: Optional[str] = Form(None),
    cif_nif: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    phone_secondary: Optional[str] = Form(None),
    phone_emergency: Optional[str] = Form(None),
    contact_person: Optional[str] = Form(None),
    contact_position: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    postal_code: Optional[str] = Form(None),
    specialties: Optional[str] = Form(None),
    service_areas: Optional[str] = Form(None),
    availability_hours: Optional[str] = Form(None),
    has_emergency_service: Optional[str] = Form(None),
    is_default: Optional[str] = Form(None),
    hourly_rate: Optional[float] = Form(None),
    payment_terms: Optional[str] = Form(None),
    bank_account: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Create a new provider."""
    provider = Provider(
        name=name,
        email=email,
        category=category,
        company_name=company_name or None,
        cif_nif=cif_nif or None,
        phone=phone or None,
        phone_secondary=phone_secondary or None,
        phone_emergency=phone_emergency or None,
        contact_person=contact_person or None,
        contact_position=contact_position or None,
        address=address or None,
        city=city or None,
        postal_code=postal_code or None,
        specialties=specialties or None,
        service_areas=service_areas or None,
        availability_hours=availability_hours or None,
        has_emergency_service=has_emergency_service == 'true',
        is_default=is_default == 'true',
        hourly_rate=hourly_rate,
        payment_terms=payment_terms or None,
        bank_account=bank_account or None,
        notes=notes or None
    )
    db.add(provider)
    await db.commit()
    
    return RedirectResponse(url="/dashboard/providers", status_code=303)


@router.post("/providers/{provider_id}/update", response_class=HTMLResponse)
async def update_provider(
    provider_id: int,
    name: str = Form(...),
    email: str = Form(...),
    category: str = Form(...),
    company_name: Optional[str] = Form(None),
    cif_nif: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    phone_secondary: Optional[str] = Form(None),
    phone_emergency: Optional[str] = Form(None),
    contact_person: Optional[str] = Form(None),
    contact_position: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    postal_code: Optional[str] = Form(None),
    specialties: Optional[str] = Form(None),
    service_areas: Optional[str] = Form(None),
    availability_hours: Optional[str] = Form(None),
    has_emergency_service: Optional[str] = Form(None),
    is_default: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    rating: Optional[float] = Form(None),
    hourly_rate: Optional[float] = Form(None),
    payment_terms: Optional[str] = Form(None),
    bank_account: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Update a provider."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if provider:
        provider.name = name
        provider.email = email
        provider.category = category
        provider.company_name = company_name or None
        provider.cif_nif = cif_nif or None
        provider.phone = phone or None
        provider.phone_secondary = phone_secondary or None
        provider.phone_emergency = phone_emergency or None
        provider.contact_person = contact_person or None
        provider.contact_position = contact_position or None
        provider.address = address or None
        provider.city = city or None
        provider.postal_code = postal_code or None
        provider.specialties = specialties or None
        provider.service_areas = service_areas or None
        provider.availability_hours = availability_hours or None
        provider.has_emergency_service = has_emergency_service == 'true'
        provider.is_default = is_default == 'true'
        provider.is_active = is_active == 'true'
        provider.rating = rating
        provider.hourly_rate = hourly_rate
        provider.payment_terms = payment_terms or None
        provider.bank_account = bank_account or None
        provider.notes = notes or None
        await db.commit()
    
    return RedirectResponse(url="/dashboard/providers", status_code=303)


@router.post("/providers/{provider_id}/delete", response_class=HTMLResponse)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a provider."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if provider:
        await db.delete(provider)
        await db.commit()
    
    return RedirectResponse(url="/dashboard/providers", status_code=303)


# ============ REPORTERS ROUTES ============

@router.get("/reporters", response_class=HTMLResponse)
async def reporters_list(
    request: Request,
    search: Optional[str] = Query(None),
    community: Optional[str] = Query(None),
    is_active: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db)
):
    """List all reporters with filters and stats."""
    query = select(Reporter)
    
    # Apply filters
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            or_(
                Reporter.name.ilike(search_filter),
                Reporter.email.ilike(search_filter),
                Reporter.phone.ilike(search_filter)
            )
        )
    if community:
        query = query.where(Reporter.community_name.ilike(f"%{community}%"))
    if is_active == 'true':
        query = query.where(Reporter.is_active == True)
    elif is_active == 'false':
        query = query.where(Reporter.is_active == False)
    
    # Pagination
    page_size = 20
    offset = (page - 1) * page_size
    query = query.order_by(Reporter.name).offset(offset).limit(page_size)
    
    result = await db.execute(query)
    reporters = result.scalars().all()
    
    # Get total count for pagination
    count_query = select(func.count(Reporter.id))
    if search:
        count_query = count_query.where(
            or_(
                Reporter.name.ilike(f"%{search}%"),
                Reporter.email.ilike(f"%{search}%"),
                Reporter.phone.ilike(f"%{search}%")
            )
        )
    if community:
        count_query = count_query.where(Reporter.community_name.ilike(f"%{community}%"))
    if is_active == 'true':
        count_query = count_query.where(Reporter.is_active == True)
    elif is_active == 'false':
        count_query = count_query.where(Reporter.is_active == False)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    pages = (total + page_size - 1) // page_size
    
    # Get stats
    total_all = await db.scalar(select(func.count(Reporter.id)))
    active = await db.scalar(select(func.count(Reporter.id)).where(Reporter.is_active == True))
    inactive = (total_all or 0) - (active or 0)
    communities_count = await db.scalar(
        select(func.count(distinct(Reporter.community_name))).where(Reporter.community_name.isnot(None))
    )
    
    # Get unique communities for filter
    communities_result = await db.execute(
        select(distinct(Reporter.community_name)).where(Reporter.community_name.isnot(None)).order_by(Reporter.community_name)
    )
    communities = [c[0] for c in communities_result.all()]
    
    return templates.TemplateResponse("reporters.html", {
        "request": request,
        "reporters": reporters,
        "communities": communities,
        "search": search,
        "community": community,
        "is_active": is_active,
        "page": page,
        "pages": pages,
        "stats": {
            "total": total_all or 0,
            "active": active or 0,
            "inactive": inactive,
            "communities": communities_count or 0
        }
    })


@router.post("/reporters/create", response_class=HTMLResponse)
async def create_reporter(
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    phone_secondary: Optional[str] = Form(None),
    community_name: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    floor_door: Optional[str] = Form(None),
    dni_nif: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    preferred_contact_method: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Create a new reporter."""
    reporter = Reporter(
        name=name,
        email=email,
        phone=phone or None,
        phone_secondary=phone_secondary or None,
        community_name=community_name or None,
        address=address or None,
        floor_door=floor_door or None,
        dni_nif=dni_nif or None,
        role=role or None,
        preferred_contact_method=preferred_contact_method or None,
        notes=notes or None
    )
    db.add(reporter)
    await db.commit()
    
    return RedirectResponse(url="/dashboard/reporters", status_code=303)


@router.post("/reporters/{reporter_id}/update", response_class=HTMLResponse)
async def update_reporter(
    reporter_id: int,
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    phone_secondary: Optional[str] = Form(None),
    community_name: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    floor_door: Optional[str] = Form(None),
    dni_nif: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    preferred_contact_method: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Update a reporter."""
    result = await db.execute(select(Reporter).where(Reporter.id == reporter_id))
    reporter = result.scalar_one_or_none()
    
    if reporter:
        reporter.name = name
        reporter.email = email
        reporter.phone = phone or None
        reporter.phone_secondary = phone_secondary or None
        reporter.community_name = community_name or None
        reporter.address = address or None
        reporter.floor_door = floor_door or None
        reporter.dni_nif = dni_nif or None
        reporter.role = role or None
        reporter.preferred_contact_method = preferred_contact_method or None
        reporter.is_active = is_active == 'true'
        reporter.notes = notes or None
        await db.commit()
    
    return RedirectResponse(url="/dashboard/reporters", status_code=303)


@router.post("/reporters/{reporter_id}/delete", response_class=HTMLResponse)
async def delete_reporter(reporter_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a reporter."""
    result = await db.execute(select(Reporter).where(Reporter.id == reporter_id))
    reporter = result.scalar_one_or_none()
    
    if reporter:
        await db.delete(reporter)
        await db.commit()
    
    return RedirectResponse(url="/dashboard/reporters", status_code=303)


@router.post("/tickets/{ticket_id}/delete", response_class=HTMLResponse)
async def delete_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a ticket."""
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if ticket:
        # Delete related events first
        await db.execute(
            select(Event).where(Event.ticket_id == ticket_id)
        )
        from sqlalchemy import delete as sql_delete
        await db.execute(sql_delete(Event).where(Event.ticket_id == ticket_id))
        await db.execute(sql_delete(Email).where(Email.ticket_id == ticket_id))
        await db.delete(ticket)
        await db.commit()
    
    return RedirectResponse(url="/dashboard/tickets", status_code=303)
