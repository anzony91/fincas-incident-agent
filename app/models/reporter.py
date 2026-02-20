"""
Reporter model for users who report incidents
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Reporter(Base):
    """Reporter model for users who create incident tickets.
    
    These are typically residents, property owners, or community administrators.
    """
    
    __tablename__ = "reporters"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phone_secondary: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Community/Property info
    community_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    floor_door: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "3ºA", "Bajo B"
    
    # Identification
    dni_nif: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Role/Type
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # propietario, inquilino, administrador
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Additional info
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferred_contact_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # email, phone, whatsapp
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<Reporter {self.name} - {self.email}>"
