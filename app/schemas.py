"""
Pydantic schemas for API validation
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.email import EmailDirection
from app.models.ticket import Category, Priority, TicketStatus


# ============ Ticket Schemas ============

class TicketBase(BaseModel):
    """Base schema for ticket"""
    subject: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    category: Category = Category.OTHER
    priority: Priority = Priority.MEDIUM
    reporter_email: EmailStr
    reporter_name: Optional[str] = Field(None, max_length=255)
    community_name: Optional[str] = Field(None, max_length=255)


class TicketCreate(TicketBase):
    """Schema for creating a ticket"""
    pass


class TicketUpdate(BaseModel):
    """Schema for updating a ticket"""
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[TicketStatus] = None
    category: Optional[Category] = None
    priority: Optional[Priority] = None
    assigned_provider_id: Optional[int] = None
    community_name: Optional[str] = Field(None, max_length=255)


class AttachmentResponse(BaseModel):
    """Schema for attachment response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    filename: str
    content_type: Optional[str]
    size_bytes: Optional[int]
    created_at: datetime


class EmailResponse(BaseModel):
    """Schema for email response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    message_id: str
    subject: str
    body_text: Optional[str]
    from_address: str
    from_name: Optional[str]
    to_address: str
    direction: EmailDirection
    received_at: datetime
    created_at: datetime
    attachments: List[AttachmentResponse] = []


class EventResponse(BaseModel):
    """Schema for event response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    event_type: str
    description: Optional[str]
    payload: Optional[dict]
    created_by: Optional[str]
    created_at: datetime


class TicketResponse(BaseModel):
    """Schema for ticket response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    ticket_code: str
    subject: str
    description: Optional[str]
    status: TicketStatus
    category: Category
    priority: Priority
    reporter_email: str
    reporter_name: Optional[str]
    assigned_provider_id: Optional[int]
    community_name: Optional[str]
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]


class TicketDetailResponse(TicketResponse):
    """Schema for detailed ticket response with emails and events"""
    emails: List[EmailResponse] = []
    events: List[EventResponse] = []


class TicketListResponse(BaseModel):
    """Schema for paginated ticket list"""
    items: List[TicketResponse]
    total: int
    page: int
    size: int
    pages: int


# ============ Provider Schemas ============

class ProviderBase(BaseModel):
    """Base schema for provider"""
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    category: Category
    is_default: bool = False
    notes: Optional[str] = Field(None, max_length=1000)


class ProviderCreate(ProviderBase):
    """Schema for creating a provider"""
    pass


class ProviderUpdate(BaseModel):
    """Schema for updating a provider"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    category: Optional[Category] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)


class ProviderResponse(BaseModel):
    """Schema for provider response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    email: str
    phone: Optional[str]
    category: Category
    is_default: bool
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProviderListResponse(BaseModel):
    """Schema for paginated provider list"""
    items: List[ProviderResponse]
    total: int
    page: int
    size: int
    pages: int


# ============ Email Schemas ============

class EmailListResponse(BaseModel):
    """Schema for paginated email list"""
    items: List[EmailResponse]
    total: int
    page: int
    size: int
    pages: int


# ============ Event Schemas ============

class EventCreate(BaseModel):
    """Schema for creating an event"""
    event_type: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    payload: Optional[dict] = None
    created_by: Optional[str] = Field(None, max_length=255)


class EventListResponse(BaseModel):
    """Schema for paginated event list"""
    items: List[EventResponse]
    total: int
    page: int
    size: int
    pages: int


# ============ Action Schemas ============

class AssignProviderRequest(BaseModel):
    """Schema for assigning a provider to a ticket"""
    provider_id: int


class ChangeStatusRequest(BaseModel):
    """Schema for changing ticket status"""
    status: TicketStatus
    comment: Optional[str] = None


class SendEmailRequest(BaseModel):
    """Schema for sending an email"""
    to: EmailStr
    subject: str
    body: str
    cc: Optional[List[EmailStr]] = None
