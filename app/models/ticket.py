"""
Ticket model and enums
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, String, Text, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.email import Email
    from app.models.event import Event


class TicketStatus(str, enum.Enum):
    """Ticket status enum"""
    NEW = "NEW"
    NEEDS_INFO = "NEEDS_INFO"
    VALIDATING = "VALIDATING"
    DISPATCHED = "DISPATCHED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    WAITING_INVOICE = "WAITING_INVOICE"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class Category(str, enum.Enum):
    """Incident category enum"""
    WATER = "WATER"
    ELEVATOR = "ELEVATOR"
    ELECTRICITY = "ELECTRICITY"
    GARAGE_DOOR = "GARAGE_DOOR"
    CLEANING = "CLEANING"
    SECURITY = "SECURITY"
    OTHER = "OTHER"


class Priority(str, enum.Enum):
    """Incident priority enum"""
    URGENT = "URGENT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Channel(str, enum.Enum):
    """Input channel enum"""
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    WEB = "WEB"
    PHONE = "PHONE"


class Ticket(Base):
    """Ticket model for incident tracking"""
    
    __tablename__ = "tickets"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_code: Mapped[str] = mapped_column(
        String(12), unique=True, nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus), default=TicketStatus.NEW, nullable=False
    )
    category: Mapped[Category] = mapped_column(
        Enum(Category), default=Category.OTHER, nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority), default=Priority.MEDIUM, nullable=False
    )
    reporter_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reporter_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reporter_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    assigned_provider_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    community_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel: Mapped[Channel] = mapped_column(
        Enum(Channel), default=Channel.EMAIL, nullable=False
    )
    
    # Location details
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    location_detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # AI analysis context (stores conversation state for info gathering)
    ai_context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    emails: Mapped[List["Email"]] = relationship(
        "Email", back_populates="ticket", lazy="selectin"
    )
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="ticket", lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<Ticket {self.ticket_code} - {self.status.value}>"
