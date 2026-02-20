"""
Public routes for incident reporting form.
These routes are accessible without authentication.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.ticket import Ticket, TicketStatus, Category, Priority
from app.models.provider import Provider
from app.models.reporter import Reporter
from app.schemas import TicketCreate
from app.services.ticket_service import TicketService
from app.services.ai_agent_service import AIAgentService
from app.services.classifier_service import ClassifierService

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)


@router.get("/reportar", response_class=HTMLResponse)
async def incident_form(request: Request):
    """Display the public incident reporting form."""
    return templates.TemplateResponse("incident_form.html", {
        "request": request,
    })


@router.post("/reportar", response_class=HTMLResponse)
async def submit_incident(
    request: Request,
    db: AsyncSession = Depends(get_db),
    # Reporter info
    reporter_name: str = Form(...),
    reporter_email: str = Form(...),
    reporter_phone: str = Form(...),
    # Location info
    community_name: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    floor_door: Optional[str] = Form(None),
    # Incident info
    subject: str = Form(...),
    description: str = Form(...),
    category: Optional[str] = Form(None),
    urgency: Optional[str] = Form(None),
):
    """Process the incident form submission."""
    try:
        # Normalize email
        email_lower = reporter_email.lower().strip()
        
        # Check if this email belongs to a provider - don't create reporter in that case
        provider_check = await db.execute(
            select(Provider).where(Provider.email == email_lower)
        )
        is_provider = provider_check.scalar_one_or_none() is not None
        
        reporter = None
        if not is_provider:
            # Find or create reporter
            result = await db.execute(
                select(Reporter).where(Reporter.email == email_lower)
            )
            reporter = result.scalar_one_or_none()
            
            if not reporter:
                # Create new reporter
                reporter = Reporter(
                    name=reporter_name,
                    email=email_lower,
                    phone=reporter_phone,
                    community_name=community_name,
                    address=address,
                    floor_door=floor_door,
                    is_active=True,
                )
                db.add(reporter)
                await db.commit()
                await db.refresh(reporter)
                logger.info("Created new reporter from form: %s", email_lower)
            else:
                # Update reporter with any new info
                if reporter_phone and not reporter.phone:
                    reporter.phone = reporter_phone
                if community_name and not reporter.community_name:
                    reporter.community_name = community_name
                if address and not reporter.address:
                    reporter.address = address
                if floor_door and not reporter.floor_door:
                    reporter.floor_door = floor_door
                await db.commit()
        
        # Determine category
        ticket_category = Category.OTHER
        if category:
            try:
                ticket_category = Category(category)
            except ValueError:
                pass
        else:
            # Use classifier to auto-detect
            classifier = ClassifierService()
            detected_category, _ = classifier.classify_email(subject, description)
            ticket_category = detected_category
        
        # Determine priority based on urgency selection
        ticket_priority = Priority.MEDIUM
        if urgency == "urgent":
            ticket_priority = Priority.URGENT
        elif urgency == "high":
            ticket_priority = Priority.HIGH
        elif urgency == "low":
            ticket_priority = Priority.LOW
        
        # Use AI to analyze the incident (same as email flow)
        ai_agent = AIAgentService()
        analysis = await ai_agent.analyze_incident(
            subject=subject,
            body=description,
            sender_email=email_lower,
            sender_name=reporter_name,
            conversation_history=[],
        )
        
        # Create the ticket
        ticket_service = TicketService(db)
        ticket = await ticket_service.create_ticket(TicketCreate(
            subject=subject,
            description=description[:2000] if description else None,
            category=ticket_category,
            priority=ticket_priority,
            reporter_email=email_lower,
            reporter_name=reporter_name,
            reporter_phone=reporter_phone,
            community_name=community_name,
            address=address,
            location_detail=floor_door,
        ))
        
        # Set status based on completeness
        initial_status = TicketStatus.NEW if analysis.has_complete_info else TicketStatus.NEEDS_INFO
        ticket.status = initial_status
        
        # Store AI context
        ticket.ai_context = {
            "analysis": {
                "has_complete_info": analysis.has_complete_info,
                "category": analysis.category.value if analysis.category else None,
                "priority": analysis.priority.value if analysis.priority else None,
                "missing_fields": analysis.missing_fields,
                "extracted_info": analysis.extracted_info,
                "summary": analysis.summary,
            },
            "source": "web_form",
        }
        
        await db.commit()
        await db.refresh(ticket)
        
        logger.info("Created ticket %s from web form", ticket.ticket_code)
        
        # If info is complete, notify default provider
        if analysis.has_complete_info:
            from app.services.email_service import EmailService
            email_service = EmailService(db)
            await email_service._notify_default_provider(ticket)
        
        # Show success page
        return templates.TemplateResponse("incident_success.html", {
            "request": request,
            "ticket": ticket,
            "analysis": analysis,
        })
        
    except Exception as e:
        logger.error("Error processing incident form: %s", str(e))
        return templates.TemplateResponse("incident_form.html", {
            "request": request,
            "error": "Ha ocurrido un error al procesar su solicitud. Por favor, inténtelo de nuevo.",
            # Preserve form data
            "form_data": {
                "reporter_name": reporter_name,
                "reporter_email": reporter_email,
                "reporter_phone": reporter_phone,
                "community_name": community_name,
                "address": address,
                "floor_door": floor_door,
                "subject": subject,
                "description": description,
                "category": category,
                "urgency": urgency,
            }
        })
