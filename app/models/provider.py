"""
Provider model for service providers
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.ticket import Category


class Provider(Base):
    """Provider model for service providers (plumbers, electricians, etc.)"""
    
    __tablename__ = "providers"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Razón social
    cif_nif: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Contact info
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phone_secondary: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    phone_emergency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Para urgencias
    
    # Contact person
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_position: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Cargo
    
    # Address
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    
    # Service info
    category: Mapped[Category] = mapped_column(Enum(Category), nullable=False, index=True)
    specialties: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Especialidades específicas
    service_areas: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Zonas que cubre
    
    # Availability
    availability_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # "L-V 8:00-18:00"
    has_emergency_service: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Rating and preferences
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 1-5
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Financial
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # "30 días", "contado"
    bank_account: Mapped[Optional[str]] = mapped_column(String(34), nullable=True)  # IBAN
    
    # Additional info
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<Provider {self.name} - {self.category.value}>"

