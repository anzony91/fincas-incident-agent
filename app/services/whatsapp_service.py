"""
WhatsApp Service - Twilio integration for WhatsApp messaging
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from twilio.rest import Client
from twilio.request_validator import RequestValidator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ticket import Ticket, TicketStatus, Category, Priority
from app.models.provider import Provider
from app.models.reporter import Reporter
from app.models.event import Event
from app.schemas import TicketCreate
from app.services.ticket_service import TicketService
from app.services.ai_agent_service import AIAgentService
from app.services.classifier_service import ClassifierService

logger = logging.getLogger(__name__)
settings = get_settings()


class WhatsAppService:
    """Service for handling WhatsApp messages via Twilio."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = None
        self.validator = None
        
        if settings.twilio_account_sid and settings.twilio_auth_token:
            self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            self.validator = RequestValidator(settings.twilio_auth_token)
        else:
            logger.warning("Twilio credentials not configured")
        
        self.ai_agent = AIAgentService()
        self.classifier = ClassifierService()
    
    def validate_request(self, url: str, params: dict, signature: str) -> bool:
        """Validate that the request comes from Twilio."""
        if not self.validator:
            logger.warning("Cannot validate - Twilio not configured")
            return False
        return self.validator.validate(url, params, signature)
    
    async def process_incoming_message(
        self,
        from_number: str,
        body: str,
        message_sid: str,
        profile_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Process an incoming WhatsApp message.
        Returns the response message to send back.
        """
        logger.info("Processing WhatsApp message from %s: %s", from_number, body[:100])
        
        # Normalize phone number (remove 'whatsapp:' prefix if present)
        phone = from_number.replace("whatsapp:", "").strip()
        
        # Check if this is a reply to an existing ticket
        ticket = await self._find_ticket_by_phone(phone)
        
        if ticket and ticket.status == TicketStatus.NEEDS_INFO:
            # This is a response to a follow-up question
            return await self._process_info_response(ticket, body, phone)
        
        # New incident - create ticket
        return await self._create_ticket_from_message(phone, body, profile_name)
    
    async def _find_ticket_by_phone(self, phone: str) -> Optional[Ticket]:
        """Find the most recent open ticket for this phone number."""
        result = await self.db.execute(
            select(Ticket)
            .where(
                Ticket.reporter_phone == phone,
                Ticket.status.in_([
                    TicketStatus.NEW,
                    TicketStatus.NEEDS_INFO,
                    TicketStatus.IN_PROGRESS,
                    TicketStatus.DISPATCHED,
                ])
            )
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def _find_or_create_reporter(
        self,
        phone: str,
        name: Optional[str] = None,
    ) -> Optional[Reporter]:
        """Find or create a reporter by phone number."""
        # Normalize phone
        phone_clean = phone.strip()
        
        # Check if this phone belongs to a provider
        provider_check = await self.db.execute(
            select(Provider).where(
                (Provider.phone == phone_clean) | 
                (Provider.phone_emergency == phone_clean)
            )
        )
        if provider_check.scalar_one_or_none():
            logger.info("Phone %s belongs to a provider, skipping reporter creation", phone_clean)
            return None
        
        # Try to find existing reporter by phone
        result = await self.db.execute(
            select(Reporter).where(Reporter.phone == phone_clean)
        )
        reporter = result.scalar_one_or_none()
        
        if reporter:
            logger.info("Found existing reporter by phone: %s", reporter.name)
            return reporter
        
        # Generate placeholder email from phone
        phone_for_email = phone_clean.replace("+", "").replace(" ", "").replace("-", "")
        placeholder_email = f"whatsapp_{phone_for_email}@wa.placeholder.com"
        
        # Create new reporter
        reporter = Reporter(
            name=name or f"WhatsApp {phone_clean[-4:]}",
            email=placeholder_email,
            phone=phone_clean,
            is_active=True,
            preferred_contact_method="whatsapp",
        )
        self.db.add(reporter)
        await self.db.commit()
        await self.db.refresh(reporter)
        
        logger.info("Created new reporter from WhatsApp: %s", phone_clean)
        return reporter
    
    async def _create_ticket_from_message(
        self,
        phone: str,
        message: str,
        profile_name: Optional[str] = None,
    ) -> str:
        """Create a new ticket from a WhatsApp message."""
        # Find or create reporter
        reporter = await self._find_or_create_reporter(phone, profile_name)
        
        # Use AI to analyze the incident
        analysis = await self.ai_agent.analyze_incident(
            subject="Incidencia vía WhatsApp",
            body=message,
            sender_email=None,
            sender_name=profile_name or reporter.name if reporter else None,
            conversation_history=[],
        )
        
        logger.info("AI Analysis - Complete: %s, Category: %s, Missing: %s",
                   analysis.has_complete_info, analysis.category, analysis.missing_fields)
        
        # Determine category and priority
        category = analysis.category or Category.OTHER
        priority = analysis.priority or Priority.MEDIUM
        
        # Pre-fill from reporter if available
        reporter_name = profile_name or (reporter.name if reporter else f"WhatsApp {phone[-4:]}")
        community = reporter.community_name if reporter else None
        address = reporter.address if reporter else None
        floor_door = reporter.floor_door if reporter else None
        reporter_email = reporter.email if reporter and reporter.email else None
        
        # Generate placeholder email if none available (required by schema)
        if not reporter_email:
            # Create email from phone: +34612345678 -> whatsapp_34612345678@wa.placeholder.com
            phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
            reporter_email = f"whatsapp_{phone_clean}@wa.placeholder.com"
        
        # Create ticket
        ticket_service = TicketService(self.db)
        
        # Generate a subject from the message
        subject = message[:50] + "..." if len(message) > 50 else message
        
        ticket = await ticket_service.create_ticket(TicketCreate(
            subject=f"[WhatsApp] {subject}",
            description=message,
            category=category,
            priority=priority,
            reporter_email=reporter_email,
            reporter_name=reporter_name,
            community_name=community,
        ))
        
        # Set additional fields not in schema
        ticket.reporter_phone = phone
        ticket.address = address
        ticket.location_detail = floor_door
        
        # Set status and AI context
        initial_status = TicketStatus.NEW if analysis.has_complete_info else TicketStatus.NEEDS_INFO
        ticket.status = initial_status
        ticket.ai_context = {
            "analysis": {
                "has_complete_info": analysis.has_complete_info,
                "category": analysis.category.value if analysis.category else None,
                "priority": analysis.priority.value if analysis.priority else None,
                "missing_fields": analysis.missing_fields,
                "extracted_info": analysis.extracted_info,
                "summary": analysis.summary,
            },
            "source": "whatsapp",
            "conversation_history": [
                {"role": "user", "content": message}
            ],
        }
        
        # Update reporter with extracted info
        if reporter:
            extracted = analysis.extracted_info
            if extracted.get("address") and not reporter.address:
                reporter.address = extracted["address"]
            if extracted.get("location_detail") and not reporter.floor_door:
                reporter.floor_door = extracted["location_detail"]
            if extracted.get("reporter_name") and reporter.name.startswith("WhatsApp"):
                reporter.name = extracted["reporter_name"]
        
        await self.db.commit()
        await self.db.refresh(ticket)
        
        logger.info("Created ticket %s from WhatsApp", ticket.ticket_code)
        
        # Create event
        event = Event(
            ticket_id=ticket.id,
            event_type="whatsapp_received",
            description=f"Incidencia recibida vía WhatsApp desde {phone}",
            metadata={"phone": phone, "message_preview": message[:100]},
        )
        self.db.add(event)
        await self.db.commit()
        
        # If complete, notify provider
        if analysis.has_complete_info:
            await self._notify_default_provider(ticket)
            return self._format_complete_response(ticket, analysis)
        else:
            return self._format_followup_response(ticket, analysis)
    
    async def _process_info_response(
        self,
        ticket: Ticket,
        message: str,
        phone: str,
    ) -> str:
        """Process a response to a follow-up question."""
        logger.info("Processing info response for ticket %s", ticket.ticket_code)
        
        # Get conversation history
        ai_context = ticket.ai_context or {}
        conversation_history = ai_context.get("conversation_history", [])
        conversation_history.append({"role": "user", "content": message})
        
        # Build context with existing ticket data so AI knows what we already have
        existing_info = []
        if ticket.reporter_name:
            existing_info.append(f"Nombre: {ticket.reporter_name}")
        if ticket.reporter_phone:
            existing_info.append(f"Teléfono: {ticket.reporter_phone}")
        if ticket.address:
            existing_info.append(f"Dirección: {ticket.address}")
        if ticket.location_detail:
            existing_info.append(f"Piso/Puerta: {ticket.location_detail}")
        if ticket.community_name:
            existing_info.append(f"Comunidad: {ticket.community_name}")
        
        # Build full context for AI
        full_body = ticket.description or ""
        if existing_info:
            full_body += f"\n\n[INFORMACIÓN YA RECOPILADA]\n" + "\n".join(existing_info)
        full_body += f"\n\n[NUEVA RESPUESTA DEL USUARIO]\n{message}"
        
        # Re-analyze with new info
        analysis = await self.ai_agent.analyze_incident(
            subject=ticket.subject,
            body=full_body,
            sender_email=ticket.reporter_email,
            sender_name=ticket.reporter_name,
            conversation_history=conversation_history,
        )
        
        # Update ticket with conversation history
        ai_context["conversation_history"] = conversation_history
        ai_context["analysis"] = {
            "has_complete_info": analysis.has_complete_info,
            "category": analysis.category.value if analysis.category else None,
            "priority": analysis.priority.value if analysis.priority else None,
            "missing_fields": analysis.missing_fields,
            "extracted_info": analysis.extracted_info,
            "summary": analysis.summary,
        }
        ticket.ai_context = ai_context
        
        # Update extracted info from the new response
        extracted = analysis.extracted_info
        if extracted.get("address") and not ticket.address:
            ticket.address = extracted["address"]
        if extracted.get("location_detail") and not ticket.location_detail:
            ticket.location_detail = extracted["location_detail"]
        if extracted.get("reporter_phone") and not ticket.reporter_phone:
            ticket.reporter_phone = extracted["reporter_phone"]
        if extracted.get("reporter_name") and (not ticket.reporter_name or ticket.reporter_name.startswith("WhatsApp")):
            ticket.reporter_name = extracted["reporter_name"]
        
        # Also update reporter record if available
        reporter = None
        phone_clean = phone.strip()
        result = await self.db.execute(
            select(Reporter).where(Reporter.phone == phone_clean)
        )
        reporter = result.scalar_one_or_none()
        
        if reporter:
            if extracted.get("address") and not reporter.address:
                reporter.address = extracted["address"]
            if extracted.get("location_detail") and not reporter.floor_door:
                reporter.floor_door = extracted["location_detail"]
            if extracted.get("reporter_name") and reporter.name.startswith("WhatsApp"):
                reporter.name = extracted["reporter_name"]
        
        # Create event
        event = Event(
            ticket_id=ticket.id,
            event_type="whatsapp_response",
            description=f"Respuesta recibida vía WhatsApp",
            metadata={"message_preview": message[:100]},
        )
        self.db.add(event)
        
        if analysis.has_complete_info:
            ticket.status = TicketStatus.NEW
            await self.db.commit()
            await self._notify_default_provider(ticket)
            return self._format_complete_response(ticket, analysis)
        else:
            await self.db.commit()
            return self._format_followup_response(ticket, analysis)
    
    async def _notify_default_provider(self, ticket: Ticket) -> None:
        """Notify the default provider for this ticket category."""
        try:
            from app.services.email_service import EmailService
            email_service = EmailService(self.db)
            await email_service._notify_default_provider(ticket)
        except Exception as e:
            logger.error("Failed to notify provider: %s", str(e))
    
    # Mapping from technical field names to user-friendly Spanish
    FIELD_NAMES_ES = {
        "reporter_name": "Su nombre",
        "reporter_phone": "Teléfono de contacto",
        "reporter_contact": "Teléfono de contacto",
        "address": "Dirección del edificio",
        "location_detail": "Piso y puerta",
        "community_name": "Nombre de la comunidad",
        "problem_description": "Descripción del problema",
        "urgency": "Nivel de urgencia",
        "category": "Tipo de incidencia",
    }
    
    def _format_complete_response(self, ticket: Ticket, analysis) -> str:
        """Format response when ticket has complete info."""
        return (
            f"✅ *Incidencia registrada*\n\n"
            f"📋 Código: *{ticket.ticket_code}*\n"
            f"📝 {analysis.summary}\n\n"
            f"Hemos notificado al técnico correspondiente. "
            f"Se pondrán en contacto con usted para coordinar la visita.\n\n"
            f"Guarde este código para seguimiento."
        )
    
    def _format_followup_response(self, ticket: Ticket, analysis) -> str:
        """Format response asking for more info."""
        # Convert technical field names to friendly Spanish
        friendly_fields = []
        for field in analysis.missing_fields:
            friendly_name = self.FIELD_NAMES_ES.get(field, field)
            friendly_fields.append(f"• {friendly_name}")
        
        missing = "\n".join(friendly_fields) if friendly_fields else ""
        
        # Use follow-up questions from AI (they should be in Spanish)
        questions = ""
        if analysis.follow_up_questions:
            questions = "\n".join(analysis.follow_up_questions)
        
        response = f"📋 *Incidencia recibida*\nCódigo: *{ticket.ticket_code}*\n\n"
        
        if missing:
            response += f"Para poder gestionar su incidencia, necesitamos:\n{missing}\n\n"
        
        if questions:
            response += f"{questions}\n\n"
        
        response += "Por favor, responda a este mensaje con la información solicitada."
        
        return response
    
    async def send_message(self, to_phone: str, message: str) -> bool:
        """Send a WhatsApp message."""
        if not self.client:
            logger.error("Twilio client not configured")
            return False
        
        try:
            # Ensure phone has whatsapp: prefix
            to_number = f"whatsapp:{to_phone}" if not to_phone.startswith("whatsapp:") else to_phone
            from_number = f"whatsapp:{settings.twilio_whatsapp_number}"
            
            message = self.client.messages.create(
                body=message,
                from_=from_number,
                to=to_number,
            )
            
            logger.info("Sent WhatsApp message to %s: %s", to_phone, message.sid)
            return True
            
        except Exception as e:
            logger.error("Failed to send WhatsApp message: %s", str(e))
            return False
