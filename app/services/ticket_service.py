"""
Ticket Service - Business logic for ticket management
"""
import logging
import random
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.provider import Provider
from app.models.ticket import Ticket, TicketStatus, Channel
from app.schemas import TicketCreate, TicketUpdate

logger = logging.getLogger(__name__)


class TicketService:
    """Service for ticket operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def _generate_ticket_code(self) -> str:
        """Generate a unique ticket code like INC-XXXXXX"""
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=6))
        return f"INC-{random_part}"
    
    async def create_ticket(self, data: TicketCreate) -> Ticket:
        """Create a new ticket with a unique code"""
        # Generate unique ticket code
        while True:
            ticket_code = self._generate_ticket_code()
            existing = await self.db.execute(
                select(Ticket).where(Ticket.ticket_code == ticket_code)
            )
            if not existing.scalar_one_or_none():
                break
        
        ticket = Ticket(
            ticket_code=ticket_code,
            subject=data.subject,
            description=data.description,
            category=data.category,
            priority=data.priority,
            reporter_email=data.reporter_email,
            reporter_name=data.reporter_name,
            community_name=data.community_name,
            status=TicketStatus.NEW,
        )
        
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        
        # Create creation event
        await self._create_event(
            ticket.id,
            "TICKET_CREATED",
            f"Ticket {ticket_code} created",
            {"category": data.category.value, "priority": data.priority.value},
        )
        
        return ticket
    
    async def update_ticket(self, ticket_id: int, data: TicketUpdate) -> Optional[Ticket]:
        """Update an existing ticket"""
        result = await self.db.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        changes = {}
        
        for key, value in update_data.items():
            old_value = getattr(ticket, key)
            if old_value != value:
                changes[key] = {"from": str(old_value), "to": str(value)}
                setattr(ticket, key, value)
        
        if changes:
            await self.db.commit()
            await self.db.refresh(ticket)
            
            await self._create_event(
                ticket_id,
                "TICKET_UPDATED",
                f"Ticket updated: {', '.join(changes.keys())}",
                changes,
            )
        
        return ticket
    
    async def assign_provider(self, ticket_id: int, provider_id: int) -> Optional[Ticket]:
        """Assign a provider to a ticket"""
        result = await self.db.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            return None
        
        # Verify provider exists
        provider_result = await self.db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = provider_result.scalar_one_or_none()
        
        if not provider:
            raise ValueError(f"Provider {provider_id} not found")
        
        old_provider_id = ticket.assigned_provider_id
        ticket.assigned_provider_id = provider_id
        
        # Update status to DISPATCHED if NEW
        if ticket.status == TicketStatus.NEW:
            ticket.status = TicketStatus.DISPATCHED
        
        await self.db.commit()
        await self.db.refresh(ticket)
        
        await self._create_event(
            ticket_id,
            "PROVIDER_ASSIGNED",
            f"Provider {provider.name} assigned to ticket",
            {
                "provider_id": provider_id,
                "provider_name": provider.name,
                "provider_email": provider.email,
                "previous_provider_id": old_provider_id,
            },
        )
        
        return ticket
    
    async def change_status(
        self,
        ticket_id: int,
        new_status: TicketStatus,
        comment: Optional[str] = None,
    ) -> Optional[Ticket]:
        """Change the status of a ticket"""
        result = await self.db.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            return None
        
        old_status = ticket.status
        ticket.status = new_status
        
        # Set closed_at if closing
        if new_status == TicketStatus.CLOSED and not ticket.closed_at:
            ticket.closed_at = datetime.now(timezone.utc)
        elif new_status != TicketStatus.CLOSED:
            ticket.closed_at = None
        
        await self.db.commit()
        await self.db.refresh(ticket)
        
        await self._create_event(
            ticket_id,
            "STATUS_CHANGED",
            comment or f"Status changed from {old_status.value} to {new_status.value}",
            {"from": old_status.value, "to": new_status.value},
        )
        
        # Notify reporter when ticket is closed
        if new_status == TicketStatus.CLOSED:
            await self._notify_reporter_on_closure(ticket)
        
        return ticket
    
    async def _notify_reporter_on_closure(self, ticket: Ticket) -> None:
        """
        Notify the reporter that their ticket has been resolved.
        Uses the same channel they used to report the incident.
        """
        try:
            channel = ticket.channel or Channel.EMAIL
            
            if channel == Channel.WHATSAPP and ticket.reporter_phone:
                await self._send_whatsapp_closure_notification(ticket)
            elif channel == Channel.EMAIL and ticket.reporter_email:
                await self._send_email_closure_notification(ticket)
            else:
                # Fallback to email if available
                if ticket.reporter_email and not ticket.reporter_email.endswith("@wa.placeholder.com"):
                    await self._send_email_closure_notification(ticket)
                elif ticket.reporter_phone:
                    await self._send_whatsapp_closure_notification(ticket)
                    
            logger.info("Closure notification sent for ticket %s via %s", 
                       ticket.ticket_code, channel.value)
        except Exception as e:
            logger.error("Failed to send closure notification for ticket %s: %s", 
                        ticket.ticket_code, str(e))
    
    async def _send_whatsapp_closure_notification(self, ticket: Ticket) -> None:
        """Send WhatsApp notification when ticket is closed."""
        from app.services.whatsapp_service import WhatsAppService
        
        whatsapp = WhatsAppService(self.db)
        
        message = f"""✅ *INCIDENCIA RESUELTA*

📋 *Código:* {ticket.ticket_code}
📝 *Asunto:* {ticket.subject}

¡Su incidencia ha sido solucionada!

Si tiene alguna duda o el problema persiste, responda a este mensaje.

Gracias por su paciencia. 🙏"""
        
        await whatsapp.send_message(ticket.reporter_phone, message)
    
    async def _send_email_closure_notification(self, ticket: Ticket) -> None:
        """Send email notification when ticket is closed."""
        from app.services.email_service import EmailService
        
        email_service = EmailService(self.db)
        
        subject = f"✅ Incidencia resuelta: {ticket.ticket_code}"
        body = f"""Estimado/a {ticket.reporter_name or 'vecino/a'},

Nos complace informarle que su incidencia ha sido resuelta.

📋 Código: {ticket.ticket_code}
📝 Asunto: {ticket.subject}

Si tiene alguna duda o el problema persiste, puede responder a este correo.

Gracias por su paciencia.

Atentamente,
Administración de Fincas
"""
        
        await email_service.send_email(
            to=ticket.reporter_email,
            subject=subject,
            body_text=body,
            ticket=ticket,
        )
    
    async def get_default_provider_for_category(self, category) -> Optional[Provider]:
        """Get the default provider for a category"""
        result = await self.db.execute(
            select(Provider).where(
                (Provider.category == category) &
                (Provider.is_default == True) &  # noqa: E712
                (Provider.is_active == True)  # noqa: E712
            )
        )
        return result.scalar_one_or_none()
    
    async def _create_event(
        self,
        ticket_id: int,
        event_type: str,
        description: str,
        payload: dict,
        created_by: Optional[str] = None,
    ) -> Event:
        """Create an event for audit trail"""
        event = Event(
            ticket_id=ticket_id,
            event_type=event_type,
            description=description,
            payload=payload,
            created_by=created_by or "SYSTEM",
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event
