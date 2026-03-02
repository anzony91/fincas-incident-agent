"""
Resend Inbound Email Webhook Router
Receives emails sent to incidencias@adminsavia.com via Resend's inbound feature
"""
import hashlib
import hmac
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.models.email import Email, EmailDirection
from app.models.ticket import Ticket, TicketStatus
from app.models.event import Event
from app.models.provider import Provider
from app.models.reporter import Reporter
from app.schemas import TicketCreate
from app.services.ticket_service import TicketService
from app.services.ai_agent_service import AIAgentService
from app.services.classifier_service import ClassifierService

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


class ResendEmailHeader(BaseModel):
    name: str
    value: str


class ResendEmailData(BaseModel):
    """Resend inbound email data structure"""
    id: str
    to: List[str]
    from_: str = None  # 'from' is reserved keyword
    subject: str = ""
    text: str = ""
    html: str = ""
    created_at: str = ""
    headers: List[Dict[str, str]] = []
    attachments: List[Dict[str, Any]] = []
    
    class Config:
        populate_by_name = True
        
    def __init__(self, **data):
        # Handle 'from' field which is a reserved keyword
        if 'from' in data:
            data['from_'] = data.pop('from')
        super().__init__(**data)


class ResendWebhookPayload(BaseModel):
    """Resend webhook payload structure"""
    type: str
    created_at: str = ""
    data: Dict[str, Any]


def verify_resend_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify Resend webhook signature"""
    if not webhook_secret:
        logger.warning("RESEND_WEBHOOK_SECRET not configured, skipping signature verification")
        return True
    
    expected_signature = hmac.new(
        webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


def get_header_value(headers: List[Dict[str, str]], name: str) -> Optional[str]:
    """Extract a header value from the headers list"""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


@router.post("/webhook")
async def resend_inbound_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    svix_id: Optional[str] = Header(None, alias="svix-id"),
    svix_timestamp: Optional[str] = Header(None, alias="svix-timestamp"),
    svix_signature: Optional[str] = Header(None, alias="svix-signature"),
):
    """
    Webhook endpoint for receiving inbound emails from Resend.
    
    Resend sends a POST request with the email data when an email is received
    at any address @adminsavia.com
    """
    try:
        # Get raw body for signature verification
        body = await request.body()
        payload = await request.json()
        
        logger.info("Received Resend webhook: type=%s", payload.get("type"))
        
        # Note: Resend uses Svix for webhook signatures which has a complex format.
        # For now, we skip signature verification. In production, consider using
        # the svix library: pip install svix
        # webhook_secret = getattr(settings, 'resend_webhook_secret', '')
        # if webhook_secret and svix_signature:
        #     # Svix signature verification would go here
        #     pass
        
        # Only process email.received events
        event_type = payload.get("type", "")
        if event_type != "email.received":
            logger.info("Ignoring non-email event: %s", event_type)
            return JSONResponse({"status": "ignored", "reason": f"Event type {event_type} not handled"})
        
        # Extract email data
        data = payload.get("data", {})
        
        from_address = data.get("from", "")
        to_addresses = data.get("to", [])
        subject = data.get("subject", "(Sin asunto)")
        text_body = data.get("text", "")
        html_body = data.get("html", "")
        headers = data.get("headers", [])
        email_id = data.get("id", "")
        
        # Get Message-ID from headers - generate unique one if missing/invalid
        import uuid
        header_message_id = get_header_value(headers, "Message-ID")
        if header_message_id and len(header_message_id) > 10 and "@" in header_message_id:
            message_id = header_message_id
        elif email_id:
            message_id = f"<{email_id}@resend.dev>"
        else:
            # Generate unique message_id if Resend doesn't provide one
            message_id = f"<{uuid.uuid4()}@resend-inbound.adminsavia.com>"
        in_reply_to = get_header_value(headers, "In-Reply-To")
        references = get_header_value(headers, "References")
        
        logger.info("Processing inbound email: from=%s, to=%s, subject=%s", 
                   from_address, to_addresses, subject[:50])
        
        # Check if this email is from a provider (reply to ticket)
        provider = await _find_provider_by_email(db, from_address)
        
        if provider:
            # This is a reply from a provider
            logger.info("Email from provider: %s", provider.name)
            await _process_provider_reply(
                db, provider, from_address, subject, text_body, html_body,
                message_id, in_reply_to, references
            )
        else:
            # This is a new incident report from a resident
            logger.info("Email from resident/reporter: %s", from_address)
            await _process_incident_email(
                db, from_address, subject, text_body, html_body,
                message_id, in_reply_to, references
            )
        
        return JSONResponse({"status": "processed"})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing Resend webhook: %s", str(e), exc_info=True)
        # Return 200 to prevent Resend from retrying (we'll log the error)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=200)


async def _find_provider_by_email(db: AsyncSession, email_address: str) -> Optional[Provider]:
    """Find a provider by email address"""
    email_lower = email_address.lower().strip()
    # Extract just the email if it contains name: "Name <email@example.com>"
    if "<" in email_lower and ">" in email_lower:
        email_lower = email_lower.split("<")[1].split(">")[0]
    
    result = await db.execute(
        select(Provider).where(Provider.email == email_lower)
    )
    return result.scalar_one_or_none()


async def _process_provider_reply(
    db: AsyncSession,
    provider: Provider,
    from_address: str,
    subject: str,
    text_body: str,
    html_body: str,
    message_id: str,
    in_reply_to: Optional[str],
    references: Optional[str],
):
    """Process a reply from a provider"""
    # Try to find the ticket from In-Reply-To or References
    ticket = None
    
    if in_reply_to:
        # Find email with this message_id
        result = await db.execute(
            select(Email).where(Email.message_id == in_reply_to)
        )
        original_email = result.scalar_one_or_none()
        if original_email and original_email.ticket_id:
            result = await db.execute(
                select(Ticket).where(Ticket.id == original_email.ticket_id)
            )
            ticket = result.scalar_one_or_none()
    
    # Also try to extract ticket code from subject
    if not ticket:
        import re
        match = re.search(r'INC-[A-Z0-9]{6}', subject)
        if match:
            ticket_code = match.group()
            result = await db.execute(
                select(Ticket).where(Ticket.ticket_code == ticket_code)
            )
            ticket = result.scalar_one_or_none()
    
    if not ticket:
        logger.warning("Could not find ticket for provider reply: %s", subject)
        return
    
    # Store the email
    email_record = Email(
        ticket_id=ticket.id,
        message_id=message_id,
        subject=subject,
        body_text=text_body,
        body_html=html_body,
        from_address=from_address,
        to_address=settings.effective_from_email,
        direction=EmailDirection.INBOUND,
        in_reply_to=in_reply_to,
        references_header=references,
        received_at=datetime.now(timezone.utc),
    )
    db.add(email_record)
    
    # Create event
    event = Event(
        ticket_id=ticket.id,
        event_type="provider_reply",
        description=f"Respuesta recibida del proveedor {provider.name}",
        metadata={"provider_id": provider.id, "email_preview": text_body[:200] if text_body else ""},
    )
    db.add(event)
    
    await db.commit()
    logger.info("Processed provider reply for ticket %s", ticket.ticket_code)


async def _process_incident_email(
    db: AsyncSession,
    from_address: str,
    subject: str,
    text_body: str,
    html_body: str,
    message_id: str,
    in_reply_to: Optional[str],
    references: Optional[str],
):
    """Process a new incident email from a resident"""
    # Extract sender name and email
    sender_name = None
    sender_email = from_address.lower().strip()
    
    if "<" in from_address and ">" in from_address:
        parts = from_address.split("<")
        sender_name = parts[0].strip().strip('"')
        sender_email = parts[1].split(">")[0].lower().strip()
    
    # Check if this is a reply to an existing ticket
    existing_ticket = None
    
    # Method 1: Check In-Reply-To header
    if in_reply_to:
        result = await db.execute(
            select(Email).where(Email.message_id == in_reply_to)
        )
        original_email = result.scalar_one_or_none()
        if original_email and original_email.ticket_id:
            result = await db.execute(
                select(Ticket).where(Ticket.id == original_email.ticket_id)
            )
            existing_ticket = result.scalar_one_or_none()
            if existing_ticket:
                logger.info("Found existing ticket via In-Reply-To: %s", existing_ticket.ticket_code)
    
    # Method 2: Check for ticket code in subject
    if not existing_ticket:
        import re
        match = re.search(r'INC-[A-Z0-9]{6}', subject)
        if match:
            ticket_code = match.group()
            result = await db.execute(
                select(Ticket).where(Ticket.ticket_code == ticket_code)
            )
            existing_ticket = result.scalar_one_or_none()
            if existing_ticket:
                logger.info("Found existing ticket via subject code: %s", existing_ticket.ticket_code)
    
    # Method 3: Find recent ticket from same sender with similar subject (like WhatsApp)
    # This handles email threads where headers might be missing
    if not existing_ticket:
        from datetime import timedelta
        from sqlalchemy import and_, or_
        
        # Look for tickets from same reporter in last 48 hours
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=48)
        
        # Clean subject for comparison (remove Re:, Fwd:, etc.)
        clean_subject = re.sub(r'^(Re:|Fwd:|RV:|RE:|FW:)\s*', '', subject, flags=re.IGNORECASE).strip()
        
        result = await db.execute(
            select(Ticket)
            .where(
                and_(
                    Ticket.reporter_email == sender_email,
                    Ticket.created_at >= cutoff_time,
                    Ticket.status.notin_([TicketStatus.CLOSED])
                )
            )
            .order_by(Ticket.created_at.desc())
            .limit(5)
        )
        recent_tickets = result.scalars().all()
        
        # Check if any recent ticket has a similar subject
        for ticket in recent_tickets:
            ticket_subject_clean = re.sub(r'^(Re:|Fwd:|RV:|RE:|FW:)\s*', '', ticket.subject or '', flags=re.IGNORECASE).strip()
            # Check if subjects match (ignoring case and Re:/Fwd: prefixes)
            if clean_subject.lower() == ticket_subject_clean.lower():
                existing_ticket = ticket
                logger.info("Found existing ticket via same sender + subject: %s", existing_ticket.ticket_code)
                break
            # Also check if one subject contains the other (for partial matches)
            if len(clean_subject) > 10 and len(ticket_subject_clean) > 10:
                if clean_subject.lower() in ticket_subject_clean.lower() or ticket_subject_clean.lower() in clean_subject.lower():
                    existing_ticket = ticket
                    logger.info("Found existing ticket via subject similarity: %s", existing_ticket.ticket_code)
                    break
    
    if existing_ticket:
        # This is a reply to an existing ticket
        await _add_email_to_ticket(
            db, existing_ticket, from_address, sender_name, subject,
            text_body, html_body, message_id, in_reply_to, references
        )
    else:
        # Create new ticket
        await _create_ticket_from_email(
            db, sender_email, sender_name, subject, text_body, html_body,
            message_id
        )


async def _add_email_to_ticket(
    db: AsyncSession,
    ticket: Ticket,
    from_address: str,
    sender_name: Optional[str],
    subject: str,
    text_body: str,
    html_body: str,
    message_id: str,
    in_reply_to: Optional[str],
    references: Optional[str],
):
    """Add an email as a reply to an existing ticket and update ticket info"""
    logger.info("Adding email reply to existing ticket %s", ticket.ticket_code)
    
    # Store email
    email_record = Email(
        ticket_id=ticket.id,
        message_id=message_id,
        subject=subject,
        body_text=text_body,
        body_html=html_body,
        from_address=from_address,
        to_address=settings.effective_from_email,
        direction=EmailDirection.INBOUND,
        in_reply_to=in_reply_to,
        references_header=references,
        received_at=datetime.now(timezone.utc),
    )
    db.add(email_record)
    
    # Append new message to ticket description
    separator = "\n\n--- Respuesta del usuario ---\n"
    if ticket.description:
        ticket.description = f"{ticket.description}{separator}{text_body}"
    else:
        ticket.description = text_body
    
    # Analyze the combined information with AI
    ai_agent = AIAgentService()
    combined_text = f"{ticket.subject}\n\n{ticket.description}"
    
    analysis = await ai_agent.analyze_incident(
        subject=ticket.subject,
        body=combined_text,
        sender_email=ticket.reporter_email,
        sender_name=sender_name or ticket.reporter_name,
    )
    
    logger.info("AI analysis result - has_complete_info: %s, extracted_info: %s", 
                analysis.has_complete_info, analysis.extracted_info)
    
    # Update ticket fields from extracted info
    if analysis.extracted_info:
        extracted = analysis.extracted_info
        
        # Update reporter name if found and current is just email prefix
        if extracted.get('reporter_name') and (
            not ticket.reporter_name or 
            '@' in ticket.reporter_name or 
            ticket.reporter_name == ticket.reporter_email.split('@')[0]
        ):
            ticket.reporter_name = extracted['reporter_name']
            logger.info("Updated reporter_name: %s", ticket.reporter_name)
        
        # Update phone if found
        if extracted.get('reporter_phone') and not ticket.reporter_phone:
            ticket.reporter_phone = extracted['reporter_phone']
            logger.info("Updated reporter_phone: %s", ticket.reporter_phone)
        
        # Update address if found
        if extracted.get('address') and not ticket.address:
            ticket.address = extracted['address']
            logger.info("Updated address: %s", ticket.address)
        
        # Update location detail (floor/door/portal) if found
        if extracted.get('location_detail') and not ticket.location_detail:
            ticket.location_detail = extracted['location_detail']
            logger.info("Updated location_detail: %s", ticket.location_detail)
        
        # Update community name if found
        if extracted.get('community_name') and not ticket.community_name:
            ticket.community_name = extracted['community_name']
            logger.info("Updated community_name: %s", ticket.community_name)
    
    # Update AI context
    ticket.ai_context = ticket.ai_context or {}
    ticket.ai_context['last_analysis'] = {
        "has_complete_info": analysis.has_complete_info,
        "category": analysis.category.value if analysis.category else None,
        "priority": analysis.priority.value if analysis.priority else None,
        "missing_fields": analysis.missing_fields,
        "extracted_info": analysis.extracted_info,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Update status based on analysis
    if ticket.status == TicketStatus.NEEDS_INFO:
        if analysis.has_complete_info:
            ticket.status = TicketStatus.NEW
            logger.info("Ticket %s status changed to NEW (info complete)", ticket.ticket_code)
            
            # Create event for status change
            event = Event(
                ticket_id=ticket.id,
                event_type="info_provided",
                description="Información completa recibida por email. Ticket listo para procesar.",
            )
            db.add(event)
            
            # Notify provider since info is now complete
            await db.commit()
            await db.refresh(ticket)
            
            from app.services.email_service import EmailService
            email_service = EmailService(db)
            await email_service._notify_default_provider(ticket)
            return
        else:
            # Still missing info - create event
            missing = ", ".join(analysis.missing_fields[:3]) if analysis.missing_fields else "información adicional"
            event = Event(
                ticket_id=ticket.id,
                event_type="email_reply",
                description=f"Respuesta recibida. Aún falta: {missing}",
            )
            db.add(event)
    else:
        # Create event for the reply
        event = Event(
            ticket_id=ticket.id,
            event_type="email_reply",
            description="Respuesta recibida del reportante",
        )
        db.add(event)
    
    await db.commit()
    logger.info("Added email reply to ticket %s", ticket.ticket_code)


async def _create_ticket_from_email(
    db: AsyncSession,
    sender_email: str,
    sender_name: Optional[str],
    subject: str,
    text_body: str,
    html_body: str,
    message_id: str,
):
    """Create a new ticket from an inbound email"""
    # Find or create reporter
    result = await db.execute(
        select(Reporter).where(Reporter.email == sender_email)
    )
    reporter = result.scalar_one_or_none()
    
    if not reporter:
        reporter = Reporter(
            name=sender_name or sender_email.split("@")[0],
            email=sender_email,
            is_active=True,
        )
        db.add(reporter)
        await db.commit()
        await db.refresh(reporter)
        logger.info("Created new reporter from email: %s", sender_email)
    
    # Use AI to analyze the incident
    ai_agent = AIAgentService()
    classifier = ClassifierService()
    
    # Classify category
    category, confidence = classifier.classify_email(subject, text_body)
    
    # Analyze with AI
    analysis = await ai_agent.analyze_incident(
        subject=subject,
        body=text_body,
        sender_email=sender_email,
        sender_name=sender_name or reporter.name,
    )
    
    # Create ticket
    ticket_service = TicketService(db)
    ticket = await ticket_service.create_ticket(TicketCreate(
        subject=subject[:500],
        description=text_body[:5000] if text_body else None,
        category=analysis.category or category,
        priority=analysis.priority,
        reporter_email=sender_email,
        reporter_name=sender_name or reporter.name,
        community_name=reporter.community_name,
    ))
    
    # Set additional fields from reporter
    ticket.address = reporter.address
    ticket.location_detail = reporter.floor_door
    ticket.reporter_phone = reporter.phone
    
    # Set status based on analysis
    ticket.status = TicketStatus.NEW if analysis.has_complete_info else TicketStatus.NEEDS_INFO
    
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
        "source": "email_inbound",
    }
    
    await db.commit()
    await db.refresh(ticket)
    
    # Store the email
    email_record = Email(
        ticket_id=ticket.id,
        message_id=message_id,
        subject=subject,
        body_text=text_body,
        body_html=html_body,
        from_address=sender_email,
        to_address=settings.effective_from_email,
        direction=EmailDirection.INBOUND,
        received_at=datetime.now(timezone.utc),
    )
    db.add(email_record)
    
    # Create event
    event = Event(
        ticket_id=ticket.id,
        event_type="email_received",
        description=f"Incidencia recibida por email desde {sender_email}",
    )
    db.add(event)
    
    await db.commit()
    
    logger.info("Created ticket %s from inbound email", ticket.ticket_code)
    
    # Notify provider if complete
    if analysis.has_complete_info:
        from app.services.email_service import EmailService
        email_service = EmailService(db)
        await email_service._notify_default_provider(ticket)
    else:
        # Send follow-up email asking for more info
        from app.services.email_service import EmailService
        email_service = EmailService(db)
        await email_service._send_info_request(
            ticket=ticket,
            analysis=analysis,
            reply_to_message_id=message_id,
            known_data={
                "reporter_name": reporter.name,
                "reporter_email": reporter.email,
                "community_name": reporter.community_name,
                "address": reporter.address,
                "floor_door": reporter.floor_door,
            }
        )


@router.get("/webhook")
async def resend_webhook_verify():
    """GET endpoint for webhook verification"""
    return {"status": "ok", "service": "resend_inbound"}
