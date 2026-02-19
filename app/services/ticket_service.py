"""
Ticket Service - Business logic for ticket management
"""
import random
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.provider import Provider
from app.models.ticket import Ticket, TicketStatus
from app.schemas import TicketCreate, TicketUpdate


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
        
        return ticket
    
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
