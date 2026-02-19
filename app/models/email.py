"""
Email model for storing email communications
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ticket import Ticket
    from app.models.attachment import Attachment


class EmailDirection(str, enum.Enum):
    """Email direction enum"""
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class Email(Base):
    """Email model for tracking all email communications"""
    
    __tablename__ = "emails"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_address: Mapped[str] = mapped_column(String(255), nullable=False)
    cc_addresses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    direction: Mapped[EmailDirection] = mapped_column(
        Enum(EmailDirection), nullable=False
    )
    in_reply_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    references_header: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="emails")
    attachments: Mapped[List["Attachment"]] = relationship(
        "Attachment", back_populates="email", lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<Email {self.message_id} - {self.direction.value}>"
