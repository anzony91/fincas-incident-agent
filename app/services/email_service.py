"""
Email Service - IMAP/SMTP handling for email operations
"""
import asyncio
import email
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from imapclient import IMAPClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.attachment import Attachment
from app.models.email import Email, EmailDirection
from app.models.event import Event
from app.models.provider import Provider
from app.models.reporter import Reporter
from app.models.ticket import Ticket, TicketStatus
from app.schemas import TicketCreate
from app.services.classifier_service import ClassifierService
from app.services.ticket_service import TicketService
from app.services.ai_agent_service import AIAgentService, IncidentAnalysis

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    """Service for email operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.classifier = ClassifierService()
        self.ai_agent = AIAgentService()
        logger.info("EmailService initialized - Provider: %s, From: %s", 
                   settings.email_provider, settings.effective_from_email)
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        cc: Optional[List[str]] = None,
        ticket: Optional[Ticket] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> Email:
        """Send an email via configured provider (Resend, SendGrid, or SMTP)"""
        
        # Generate message ID
        message_id = f"<{uuid.uuid4()}@fincas-agent>"
        
        # Log configuration for debugging
        logger.info("Preparing to send email: TO=%s, FROM=%s, PROVIDER=%s", 
                   to, settings.effective_from_email, settings.email_provider)
        logger.info("API Keys configured: RESEND=%s, SENDGRID=%s", 
                   bool(settings.resend_api_key), bool(settings.sendgrid_api_key))
        
        # Choose provider
        if settings.email_provider == "sendgrid" and settings.sendgrid_api_key:
            logger.info("Using SendGrid provider")
            await self._send_via_sendgrid(to, subject, body_text, body_html, cc, in_reply_to, references)
        elif settings.email_provider == "resend" and settings.resend_api_key:
            logger.info("Using Resend provider")
            await self._send_via_resend(to, subject, body_text, body_html, cc, in_reply_to, references)
        else:
            logger.info("Using SMTP provider (fallback)")
            await self._send_via_smtp(to, subject, body_text, body_html, cc, message_id, in_reply_to, references)
        
        logger.info("Email sent successfully to %s via %s from %s", to, settings.email_provider, settings.effective_from_email)
        
        # Store outbound email if ticket provided
        if ticket:
            email_record = Email(
                ticket_id=ticket.id,
                message_id=message_id,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                from_address=settings.effective_from_email,
                from_name=settings.from_name,
                to_address=to,
                cc_addresses=", ".join(cc) if cc else None,
                direction=EmailDirection.OUTBOUND,
                in_reply_to=in_reply_to,
                references_header=references,
                received_at=datetime.now(timezone.utc),
            )
            self.db.add(email_record)
            await self.db.commit()
            await self.db.refresh(email_record)
            return email_record
        
        return None
    
    async def _send_via_resend(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str],
        cc: Optional[List[str]],
        in_reply_to: Optional[str],
        references: Optional[str],
    ) -> None:
        """Send email via Resend API (HTTP-based, no port blocking issues)"""
        import httpx
        
        logger.info("Sending email to %s via Resend API", to)
        
        # Build email payload
        payload = {
            "from": f"{settings.from_name} <{settings.effective_from_email}>",
            "to": [to],
            "subject": subject,
            "text": body_text,
        }
        
        if body_html:
            payload["html"] = body_html
        
        if cc:
            payload["cc"] = cc
        
        # Add reply headers if available
        headers_dict = {}
        if in_reply_to:
            headers_dict["In-Reply-To"] = in_reply_to
        if references:
            headers_dict["References"] = references
        if headers_dict:
            payload["headers"] = headers_dict
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
            
            if response.status_code not in (200, 201):
                error_detail = response.text
                logger.error("Resend API error: %s - %s", response.status_code, error_detail)
                raise Exception(f"Resend API error: {response.status_code} - {error_detail}")
            
            result = response.json()
            logger.info("Email sent via Resend, ID: %s", result.get("id"))
    
    async def _send_via_sendgrid(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str],
        cc: Optional[List[str]],
        in_reply_to: Optional[str],
        references: Optional[str],
    ) -> None:
        """Send email via SendGrid API (HTTP-based, no port blocking issues)"""
        import httpx
        
        logger.info("Sending email to %s via SendGrid API", to)
        
        # Build email payload for SendGrid v3 API
        personalizations = {
            "to": [{"email": to}],
        }
        
        if cc:
            personalizations["cc"] = [{"email": addr} for addr in cc]
        
        payload = {
            "personalizations": [personalizations],
            "from": {
                "email": settings.effective_from_email,
                "name": settings.from_name,
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
            ],
        }
        
        if body_html:
            payload["content"].append({"type": "text/html", "value": body_html})
        
        # Add reply headers if available
        if in_reply_to or references:
            payload["headers"] = {}
            if in_reply_to:
                payload["headers"]["In-Reply-To"] = in_reply_to
            if references:
                payload["headers"]["References"] = references
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
            
            # SendGrid returns 202 Accepted on success
            if response.status_code not in (200, 201, 202):
                error_detail = response.text
                logger.error("SendGrid API error: %s - %s", response.status_code, error_detail)
                raise Exception(f"SendGrid API error: {response.status_code} - {error_detail}")
            
            logger.info("Email sent via SendGrid successfully")
    
    async def _send_via_smtp(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: Optional[str],
        cc: Optional[List[str]],
        message_id: str,
        in_reply_to: Optional[str],
        references: Optional[str],
    ) -> None:
        """Send email via SMTP"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.from_name} <{settings.effective_from_email}>"
        msg["To"] = to
        
        if cc:
            msg["Cc"] = ", ".join(cc)
        
        msg["Message-ID"] = message_id
        
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        
        # Add text body
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        
        # Add HTML body if provided
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))
        
        # Check SMTP credentials
        smtp_user = settings.effective_smtp_user
        smtp_password = settings.effective_smtp_password
        
        if not smtp_user or not smtp_password:
            logger.error("SMTP credentials not configured - cannot send email")
            raise ValueError("SMTP credentials not configured")
        
        logger.info("Sending email to %s via %s:%d (TLS=%s)", to, settings.smtp_host, settings.smtp_port, settings.smtp_use_tls)
        
        # Port 465 uses direct TLS, port 587 uses STARTTLS
        use_tls = settings.smtp_use_tls and settings.smtp_port == 465
        start_tls = not use_tls and settings.smtp_port == 587
        
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=smtp_user,
            password=smtp_password,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=settings.smtp_timeout,
        )
    
    async def process_inbound_email(
        self,
        message_id: str,
        subject: str,
        body_text: str,
        body_html: Optional[str],
        from_address: str,
        from_name: Optional[str],
        to_address: str,
        cc_addresses: Optional[str],
        received_at: datetime,
        in_reply_to: Optional[str],
        references: Optional[str],
        attachments_data: List[Tuple[str, bytes, str]],  # (filename, content, content_type)
    ) -> Tuple[Ticket, Email]:
        """Process an inbound email with AI-powered information gathering"""
        
        # Check if this is a reply to an existing ticket
        ticket = await self._find_existing_ticket(subject, in_reply_to, references, from_address)
        
        if ticket:
            logger.info("Found existing ticket %s for email", ticket.ticket_code)
            # Process reply to existing ticket
            email_record = await self._store_email(
                ticket, message_id, subject, body_text, body_html,
                from_address, from_name, to_address, cc_addresses,
                received_at, in_reply_to, references, EmailDirection.INBOUND
            )
            
            # Save attachments
            if attachments_data:
                await self._save_attachments(email_record, attachments_data, ticket.ticket_code)
            
            # If ticket is in NEEDS_INFO status, process with AI to check if info is now complete
            if ticket.status == TicketStatus.NEEDS_INFO:
                await self._process_info_response(ticket, body_text or "")
            
            return ticket, email_record
        
        # New ticket - first, find or create the reporter (None if email is a provider)
        reporter = await self._find_or_create_reporter(from_address, from_name)
        
        # Now analyze with AI
        reporter_name_log = reporter.name if reporter else "(provider email)"
        logger.info("Processing new incident email from %s (Reporter: %s)", from_address, reporter_name_log)
        
        # Get conversation history (empty for new ticket)
        conversation_history = []
        
        # Analyze with AI agent
        analysis = await self.ai_agent.analyze_incident(
            subject=subject,
            body=body_text or "",
            sender_email=from_address,
            sender_name=from_name,
            conversation_history=conversation_history,
        )
        
        logger.info("AI Analysis - Complete info: %s, Category: %s, Missing: %s",
                   analysis.has_complete_info, analysis.category, analysis.missing_fields)
        
        # Create ticket with AI-determined category/priority or fallback
        category = analysis.category or self.classifier.classify_email(subject, body_text or "")[0]
        priority = analysis.priority or self.classifier.classify_email(subject, body_text or "")[1]
        community = self.classifier.extract_community_name(from_address, body_text or "")
        
        # Pre-fill from known reporter data (intelligent matching)
        # If reporter is None (email belongs to provider), use only email data
        if reporter:
            reporter_name_to_use = from_name or reporter.name
            reporter_phone_to_use = reporter.phone  # Use stored phone if available
            community_to_use = reporter.community_name or community
            address_to_use = reporter.address
            floor_door_to_use = reporter.floor_door
        else:
            reporter_name_to_use = from_name
            reporter_phone_to_use = None
            community_to_use = community
            address_to_use = None
            floor_door_to_use = None
        
        # Determine initial status based on info completeness
        initial_status = TicketStatus.NEW if analysis.has_complete_info else TicketStatus.NEEDS_INFO
        
        # Prepare AI context for storage
        ai_context = {
            "analysis": {
                "has_complete_info": analysis.has_complete_info,
                "category": analysis.category.value if analysis.category else None,
                "priority": analysis.priority.value if analysis.priority else None,
                "missing_fields": analysis.missing_fields,
                "extracted_info": analysis.extracted_info,
                "summary": analysis.summary,
            },
            "conversation_history": [
                {"role": "user", "content": f"Asunto: {subject}\n\nMensaje:\n{body_text or ''}"}
            ],
        }
        
        # Create ticket with pre-filled reporter data
        ticket_service = TicketService(self.db)
        ticket = await ticket_service.create_ticket(TicketCreate(
            subject=subject,
            description=body_text[:2000] if body_text else None,
            category=category,
            priority=priority,
            reporter_email=from_address,
            reporter_name=reporter_name_to_use,
            reporter_phone=reporter_phone_to_use,
            community_name=community_to_use,
            address=address_to_use,
            location_detail=floor_door_to_use,
        ))
        
        # Update ticket with AI context and status
        ticket.status = initial_status
        ticket.ai_context = ai_context
        
        # Update extracted location info if available (override pre-filled with fresh data)
        extracted = analysis.extracted_info
        if extracted.get("address"):
            ticket.address = extracted["address"]
        if extracted.get("location_detail"):
            ticket.location_detail = extracted["location_detail"]
        if extracted.get("reporter_phone"):
            ticket.reporter_phone = extracted["reporter_phone"]
        if extracted.get("reporter_name") and not ticket.reporter_name:
            ticket.reporter_name = extracted["reporter_name"]
        
        # Update reporter with any new information extracted from this ticket
        await self._update_reporter_from_ticket(reporter, ticket, extracted)
        
        await self.db.commit()
        await self.db.refresh(ticket)
        
        logger.info("Created ticket %s with status %s", ticket.ticket_code, initial_status.value)
        
        # Store the email
        email_record = await self._store_email(
            ticket, message_id, subject, body_text, body_html,
            from_address, from_name, to_address, cc_addresses,
            received_at, in_reply_to, references, EmailDirection.INBOUND
        )
        
        # Save attachments
        if attachments_data:
            await self._save_attachments(email_record, attachments_data, ticket.ticket_code)
        
        # If info is complete, notify the default provider for this category
        if analysis.has_complete_info:
            await self._notify_default_provider(ticket)
        
        # If info is incomplete, send follow-up email asking for more info
        if not analysis.has_complete_info:
            # Ensure we have follow-up questions
            if not analysis.follow_up_questions and analysis.missing_fields:
                analysis.follow_up_questions = [f"¿Podría indicarnos {m.lower()}?" for m in analysis.missing_fields]
            
            if analysis.follow_up_questions or analysis.missing_fields:
                logger.info("Ticket %s needs more info, sending request email", ticket.ticket_code)
                # Build known_data from reporter for inclusion in follow-up email
                known_data = None
                if reporter:
                    known_data = {
                        "name": reporter.name if reporter.name and not reporter.name.startswith(reporter.email.split('@')[0]) else None,
                        "phone": reporter.phone,
                        "email": reporter.email if not reporter.email.endswith('.placeholder.com') else None,
                        "community": reporter.community_name,
                        "address": reporter.address,
                        "floor_door": reporter.floor_door,
                    }
                await self._send_info_request(ticket, analysis, email_record.message_id, known_data)
            else:
                logger.warning("Ticket %s marked incomplete but no questions/fields to ask", ticket.ticket_code)
        
        return ticket, email_record
    
    async def _find_or_create_reporter(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Optional[Reporter]:
        """Find an existing reporter by email or create a new one.
        
        This allows us to centralize reporter data and pre-fill ticket information
        for known reporters.
        
        Returns None if the email belongs to a provider (to avoid mixing data).
        """
        # Normalize email
        email_lower = email.lower().strip()
        
        # Check if this email belongs to a provider - don't create reporter in that case
        provider_check = await self.db.execute(
            select(Provider).where(Provider.email == email_lower)
        )
        if provider_check.scalar_one_or_none():
            logger.info("Email %s belongs to a provider, skipping reporter creation", email_lower)
            return None
        
        # Try to find existing reporter
        result = await self.db.execute(
            select(Reporter).where(Reporter.email == email_lower)
        )
        reporter = result.scalar_one_or_none()
        
        if reporter:
            # Refresh to ensure we have latest data from database
            await self.db.refresh(reporter)
            logger.info("Found existing reporter: %s (%s) (refreshed)", reporter.name, reporter.email)
            return reporter
        
        # Create new reporter with minimal info
        reporter = Reporter(
            name=name or email_lower.split('@')[0],  # Use email prefix as fallback name
            email=email_lower,
            is_active=True,
        )
        self.db.add(reporter)
        await self.db.commit()
        await self.db.refresh(reporter)
        
        logger.info("Created new reporter: %s (%s)", reporter.name, reporter.email)
        return reporter
    
    async def _update_reporter_from_ticket(
        self,
        reporter: Optional[Reporter],
        ticket: Ticket,
        extracted_info: dict,
    ) -> None:
        """Update reporter record with any new information from the ticket.
        
        This keeps reporter data up-to-date as we learn more about them
        from their incident reports.
        
        Does nothing if reporter is None (e.g., email belongs to a provider).
        """
        if reporter is None:
            return
        
        updated = False
        
        # Update name if we have a better one
        if ticket.reporter_name and (not reporter.name or reporter.name == reporter.email.split('@')[0]):
            reporter.name = ticket.reporter_name
            updated = True
        
        # Update phone from extracted info or ticket
        phone = extracted_info.get("reporter_phone") or ticket.reporter_phone
        if phone and not reporter.phone:
            reporter.phone = phone
            updated = True
        
        # Update community name
        if ticket.community_name and not reporter.community_name:
            reporter.community_name = ticket.community_name
            updated = True
        
        # Update address from extracted info or ticket
        address = extracted_info.get("address") or ticket.address
        if address and not reporter.address:
            reporter.address = address
            updated = True
        
        # Update floor/door from extracted location_detail
        location_detail = extracted_info.get("location_detail") or ticket.location_detail
        if location_detail and not reporter.floor_door:
            # Try to extract floor/door info from location_detail
            reporter.floor_door = location_detail
            updated = True
        
        if updated:
            await self.db.commit()
            logger.info("Updated reporter %s with new information", reporter.email)
    
    async def _store_email(
        self,
        ticket: Ticket,
        message_id: str,
        subject: str,
        body_text: Optional[str],
        body_html: Optional[str],
        from_address: str,
        from_name: Optional[str],
        to_address: str,
        cc_addresses: Optional[str],
        received_at: datetime,
        in_reply_to: Optional[str],
        references: Optional[str],
        direction: EmailDirection,
    ) -> Email:
        """Store email record in database"""
        email_record = Email(
            ticket_id=ticket.id,
            message_id=message_id,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_address=from_address,
            from_name=from_name,
            to_address=to_address,
            cc_addresses=cc_addresses,
            direction=direction,
            in_reply_to=in_reply_to,
            references_header=references,
            received_at=received_at,
        )
        self.db.add(email_record)
        await self.db.commit()
        await self.db.refresh(email_record)
        return email_record
    
    async def _send_info_request(
        self,
        ticket: Ticket,
        analysis: IncidentAnalysis,
        reply_to_message_id: str,
        known_data: Optional[dict] = None,
    ) -> None:
        """Send email requesting missing information, showing known data for confirmation"""
        logger.info("Preparing info request email for ticket %s", ticket.ticket_code)
        logger.info("Missing fields: %s", analysis.missing_fields)
        logger.info("Follow-up questions: %s", analysis.follow_up_questions)
        logger.info("Known data: %s", known_data)
        
        try:
            # Generate follow-up email content with known data
            subject, body = await self.ai_agent.generate_follow_up_email(
                analysis=analysis,
                ticket_code=ticket.ticket_code,
                reporter_name=ticket.reporter_name,
                known_data=known_data,
            )
            
            logger.info("Generated email - Subject: %s", subject)
            
            # Ensure subject includes ticket code
            if ticket.ticket_code not in subject:
                subject = f"[{ticket.ticket_code}] {subject}"
            
            # Send the email
            email_record = await self.send_email(
                to=ticket.reporter_email,
                subject=subject,
                body_text=body,
                ticket=ticket,
                in_reply_to=reply_to_message_id,
                references=reply_to_message_id,
            )
            
            # Create event for tracking
            event = Event(
                ticket_id=ticket.id,
                event_type="INFO_REQUESTED",
                description=f"Solicitud automática de información enviada. Campos faltantes: {', '.join(analysis.missing_fields[:3])}",
                created_by="AI Agent"
            )
            self.db.add(event)
            await self.db.commit()
            
            logger.info("Sent info request email for ticket %s to %s", ticket.ticket_code, ticket.reporter_email)
            
        except Exception as e:
            logger.error("Failed to send info request for ticket %s: %s", ticket.ticket_code, str(e), exc_info=True)
            
            # Create event noting the failure
            try:
                event = Event(
                    ticket_id=ticket.id,
                    event_type="EMAIL_FAILED",
                    description=f"Error al enviar solicitud de información: {str(e)[:200]}",
                    created_by="AI Agent"
                )
                self.db.add(event)
                await self.db.commit()
            except Exception:
                pass  # Don't fail if we can't create the event
    
    async def _notify_default_provider(
        self,
        ticket: Ticket,
    ) -> None:
        """Notify the default provider for the ticket's category about the new incident.
        
        This is called when a ticket has complete information and is in NEW status.
        It finds the default provider for the category and sends them an email
        requesting assistance with the incident.
        """
        try:
            # Find the default provider for this category
            result = await self.db.execute(
                select(Provider).where(
                    (Provider.category == ticket.category) &
                    (Provider.is_default == True) &  # noqa: E712
                    (Provider.is_active == True)  # noqa: E712
                )
            )
            provider = result.scalar_one_or_none()
            
            if not provider:
                logger.info("No default provider found for category %s, skipping notification", ticket.category.value)
                return
            
            logger.info("Notifying default provider %s (%s) for ticket %s",
                       provider.name, provider.email, ticket.ticket_code)
            
            # Auto-assign the provider to the ticket
            ticket.assigned_provider_id = provider.id
            
            # Build the email content
            category_name = ticket.category.value.replace('_', ' ').title()
            priority_name = ticket.priority.value.title()
            
            subject = f"[{ticket.ticket_code}] Nueva incidencia de {category_name} - {priority_name}"
            
            # Build contact info
            reporter_info = ticket.reporter_name or ticket.reporter_email
            contact_details = []
            if ticket.reporter_phone:
                contact_details.append(f"📞 Teléfono: {ticket.reporter_phone}")
            if ticket.reporter_email:
                contact_details.append(f"✉️ Email: {ticket.reporter_email}")
            contact_str = "\n".join(contact_details) if contact_details else "No disponible"
            
            body = f"""Estimado/a {provider.contact_person or provider.name},

Se ha registrado una nueva incidencia que requiere su atención:

📋 **Ticket:** {ticket.ticket_code}
📂 **Categoría:** {category_name}
⚠️ **Prioridad:** {priority_name}
👤 **Reportado por:** {reporter_info}
🏢 **Comunidad:** {ticket.community_name or 'No especificada'}

**Datos de contacto del solicitante:**
{contact_str}

**Asunto:**
{ticket.subject}

**Descripción del problema:**
{ticket.description or 'Sin descripción adicional'}
"""
            
            # Add location info if available
            if ticket.address or ticket.location_detail:
                body += "\n**Ubicación:**\n"
                if ticket.address:
                    body += f"📍 {ticket.address}\n"
                if ticket.location_detail:
                    body += f"📌 {ticket.location_detail}\n"
            
            body += f"""
---

Por favor, contacte con el solicitante para coordinar la visita y resolución del problema.

Puede responder directamente a este correo para comunicarse con el sistema de gestión.

Gracias por su colaboración.

Atentamente,
Sistema de Gestión de Incidencias
"""
            
            # Send the email
            await self.send_email(
                to=provider.email,
                subject=subject,
                body_text=body,
                ticket=ticket,
            )
            
            # Create event for tracking
            event = Event(
                ticket_id=ticket.id,
                event_type="PROVIDER_NOTIFIED",
                description=f"Proveedor por defecto notificado: {provider.name} ({provider.email})",
                payload={"provider_id": provider.id, "provider_name": provider.name, "provider_email": provider.email},
                created_by="AI Agent"
            )
            self.db.add(event)
            
            # Update ticket status to DISPATCHED since we assigned and notified a provider
            ticket.status = TicketStatus.DISPATCHED
            
            await self.db.commit()
            
            logger.info("Successfully notified provider %s for ticket %s, status changed to DISPATCHED",
                       provider.name, ticket.ticket_code)
            
        except Exception as e:
            logger.error("Failed to notify provider for ticket %s: %s", ticket.ticket_code, str(e), exc_info=True)
            
            # Create event noting the failure
            try:
                event = Event(
                    ticket_id=ticket.id,
                    event_type="PROVIDER_NOTIFICATION_FAILED",
                    description=f"Error al notificar proveedor: {str(e)[:200]}",
                    created_by="AI Agent"
                )
                self.db.add(event)
                await self.db.commit()
            except Exception:
                pass  # Don't fail if we can't create the event
    
    async def _process_info_response(
        self,
        ticket: Ticket,
        new_message: str,
    ) -> None:
        """Process a response to an info request and update ticket status"""
        try:
            # Get existing AI context
            ai_context = ticket.ai_context or {}
            conversation_history = ai_context.get("conversation_history", [])
            
            # Build previous analysis from context
            prev_analysis_data = ai_context.get("analysis", {})
            from app.models.ticket import Category, Priority
            
            prev_analysis = IncidentAnalysis(
                has_complete_info=prev_analysis_data.get("has_complete_info", False),
                category=Category[prev_analysis_data["category"]] if prev_analysis_data.get("category") else ticket.category,
                priority=Priority[prev_analysis_data["priority"]] if prev_analysis_data.get("priority") else ticket.priority,
                missing_fields=prev_analysis_data.get("missing_fields", []),
                extracted_info=prev_analysis_data.get("extracted_info", {}),
                follow_up_questions=[],
                summary=prev_analysis_data.get("summary", ""),
            )
            
            # Add new message to conversation history
            conversation_history.append({"role": "user", "content": new_message})
            
            # Process with AI
            updated_analysis = await self.ai_agent.process_follow_up_response(
                original_analysis=prev_analysis,
                new_message=new_message,
                conversation_history=conversation_history,
            )
            
            logger.info("Updated analysis - Complete info: %s, Missing: %s",
                       updated_analysis.has_complete_info, updated_analysis.missing_fields)
            
            # Update AI context
            ai_context["analysis"] = {
                "has_complete_info": updated_analysis.has_complete_info,
                "category": updated_analysis.category.value if updated_analysis.category else None,
                "priority": updated_analysis.priority.value if updated_analysis.priority else None,
                "missing_fields": updated_analysis.missing_fields,
                "extracted_info": updated_analysis.extracted_info,
                "summary": updated_analysis.summary,
            }
            ai_context["conversation_history"] = conversation_history
            ticket.ai_context = ai_context
            
            # Update ticket fields from extracted info
            extracted = updated_analysis.extracted_info
            if extracted.get("address") and not ticket.address:
                ticket.address = extracted["address"]
            if extracted.get("location_detail") and not ticket.location_detail:
                ticket.location_detail = extracted["location_detail"]
            if extracted.get("reporter_name") and not ticket.reporter_name:
                ticket.reporter_name = extracted["reporter_name"]
            if extracted.get("reporter_phone") and not ticket.reporter_phone:
                ticket.reporter_phone = extracted["reporter_phone"]
            
            # Update category/priority if AI determined better values
            if updated_analysis.category:
                ticket.category = updated_analysis.category
            if updated_analysis.priority:
                ticket.priority = updated_analysis.priority
            
            # If info is now complete, update status to NEW for processing
            if updated_analysis.has_complete_info:
                ticket.status = TicketStatus.NEW
                logger.info("Ticket %s now has complete info, status changed to NEW", ticket.ticket_code)
                
                # Notify the default provider for this category
                await self._notify_default_provider(ticket)
            else:
                # Still missing info, send another request
                # Get the last outbound email for reply reference
                result = await self.db.execute(
                    select(Email)
                    .where(Email.ticket_id == ticket.id)
                    .where(Email.direction == EmailDirection.OUTBOUND)
                    .order_by(Email.received_at.desc())
                )
                last_outbound = result.scalar_one_or_none()
                reply_to = last_outbound.message_id if last_outbound else None
                
                # Get reporter for known data
                known_data = None
                if ticket.reporter_email:
                    reporter_result = await self.db.execute(
                        select(Reporter).where(Reporter.email == ticket.reporter_email.lower())
                    )
                    reporter = reporter_result.scalar_one_or_none()
                    if reporter:
                        await self.db.refresh(reporter)
                        known_data = {
                            "name": reporter.name if reporter.name and not reporter.name.startswith(reporter.email.split('@')[0]) else None,
                            "phone": reporter.phone,
                            "email": reporter.email if not reporter.email.endswith('.placeholder.com') else None,
                            "community": reporter.community_name,
                            "address": reporter.address,
                            "floor_door": reporter.floor_door,
                        }
                
                await self._send_info_request(ticket, updated_analysis, reply_to, known_data)
            
            await self.db.commit()
            
        except Exception as e:
            logger.error("Error processing info response for ticket %s: %s", ticket.ticket_code, str(e))
    
    async def _find_existing_ticket(
        self,
        subject: str,
        in_reply_to: Optional[str],
        references: Optional[str],
        from_address: str,
    ) -> Optional[Ticket]:
        """Find an existing ticket based on email threading or subject.
        
        Rules for ticket association:
        1. Only associate if ticket is NOT closed (closed tickets = new incident)
        2. Only associate if ticket is recent (< 30 days old)
        3. Prioritize ticket code in subject over email threading headers
        """
        from datetime import timedelta
        
        # First priority: Check for ticket code in subject (most reliable)
        # e.g., "Re: [INC-ABC123] Your issue" or just "INC-ABC123"
        ticket_code_match = re.search(r'\[?(INC-[A-Z0-9]{6})\]?', subject)
        if ticket_code_match:
            ticket_code = ticket_code_match.group(1)
            logger.info("Found ticket code %s in subject", ticket_code)
            result = await self.db.execute(
                select(Ticket).where(Ticket.ticket_code == ticket_code)
            )
            ticket = result.scalar_one_or_none()
            if ticket:
                # Only use this ticket if it's not closed
                if ticket.status != TicketStatus.CLOSED:
                    logger.info("Associating email with ticket %s (found by subject code)", ticket_code)
                    return ticket
                else:
                    logger.info("Ticket %s is CLOSED, will create new ticket", ticket_code)
                    return None
        
        # Second priority: Check by In-Reply-To header
        if in_reply_to:
            logger.debug("Checking In-Reply-To: %s", in_reply_to)
            result = await self.db.execute(
                select(Email).where(Email.message_id == in_reply_to)
            )
            original_email = result.scalar_one_or_none()
            if original_email:
                ticket_result = await self.db.execute(
                    select(Ticket).where(Ticket.id == original_email.ticket_id)
                )
                ticket = ticket_result.scalar_one_or_none()
                if ticket:
                    # Only use if not closed and recent
                    age = datetime.utcnow() - ticket.created_at.replace(tzinfo=None)
                    if ticket.status == TicketStatus.CLOSED:
                        logger.info("Ticket %s is CLOSED, creating new ticket", ticket.ticket_code)
                        return None
                    elif age > timedelta(days=30):
                        logger.info("Ticket %s is too old (%d days), creating new ticket", 
                                   ticket.ticket_code, age.days)
                        return None
                    else:
                        logger.info("Associating email with ticket %s (found by In-Reply-To)", 
                                   ticket.ticket_code)
                        return ticket
        
        # Third priority: Check references header
        if references:
            for ref in references.split():
                ref = ref.strip()
                if not ref:
                    continue
                    
                # Skip our own system-generated message IDs
                if "@fincas-agent>" in ref:
                    continue
                    
                result = await self.db.execute(
                    select(Email).where(Email.message_id == ref)
                )
                ref_email = result.scalar_one_or_none()
                if ref_email:
                    ticket_result = await self.db.execute(
                        select(Ticket).where(Ticket.id == ref_email.ticket_id)
                    )
                    ticket = ticket_result.scalar_one_or_none()
                    if ticket:
                        age = datetime.utcnow() - ticket.created_at.replace(tzinfo=None)
                        if ticket.status == TicketStatus.CLOSED:
                            logger.info("Ticket %s (from References) is CLOSED, skipping", 
                                       ticket.ticket_code)
                            continue
                        elif age > timedelta(days=30):
                            logger.info("Ticket %s (from References) is too old, skipping", 
                                       ticket.ticket_code)
                            continue
                        else:
                            logger.info("Associating email with ticket %s (found by References)", 
                                       ticket.ticket_code)
                            return ticket
        
        logger.info("No existing ticket found for email from %s, will create new", from_address)
        return None
    
    async def _save_attachments(
        self,
        email_record: Email,
        attachments_data: List[Tuple[str, bytes, str]],
        ticket_code: str,
    ) -> List[Attachment]:
        """Save email attachments to disk and database"""
        saved = []
        
        # Create directory for ticket attachments
        ticket_dir = Path(settings.attachments_path) / ticket_code
        ticket_dir.mkdir(parents=True, exist_ok=True)
        
        for filename, content, content_type in attachments_data:
            # Generate unique filename
            safe_filename = re.sub(r'[^\w\-_\.]', '_', filename)
            unique_filename = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
            filepath = ticket_dir / unique_filename
            
            # Write file
            with open(filepath, 'wb') as f:
                f.write(content)
            
            # Create database record
            attachment = Attachment(
                email_id=email_record.id,
                filename=filename,
                filepath=str(filepath),
                content_type=content_type,
                size_bytes=len(content),
            )
            self.db.add(attachment)
            saved.append(attachment)
        
        await self.db.commit()
        return saved


class IMAPPoller:
    """IMAP email poller"""
    
    def __init__(self):
        self.host = settings.imap_host
        self.port = settings.imap_port
        self.user = settings.imap_user
        self.password = settings.imap_password
    
    def connect(self) -> IMAPClient:
        """Create IMAP connection"""
        client = IMAPClient(self.host, port=self.port, ssl=True)
        client.login(self.user, self.password)
        return client
    
    def fetch_unread_emails(self) -> List[dict]:
        """Fetch all unread emails from inbox"""
        emails = []
        
        try:
            client = self.connect()
            client.select_folder("INBOX")
            
            # Search for unread messages
            messages = client.search(["UNSEEN"])
            
            if messages:
                logger.info("Found %d unread messages", len(messages))
                
                for uid, message_data in client.fetch(messages, ["RFC822"]).items():
                    raw_email = message_data[b"RFC822"]
                    parsed = self._parse_email(raw_email)
                    if parsed:
                        parsed["uid"] = uid
                        emails.append(parsed)
                        
                        # Mark as seen
                        client.add_flags([uid], ["\\Seen"])
            
            client.logout()
            
        except Exception as e:
            logger.error("Error fetching emails: %s", str(e))
        
        return emails
    
    def _parse_email(self, raw_email: bytes) -> Optional[dict]:
        """Parse a raw email into a structured dict"""
        try:
            msg = email.message_from_bytes(raw_email)
            
            # Decode subject
            subject = self._decode_header(msg.get("Subject", ""))
            
            # Parse from
            from_name, from_address = parseaddr(msg.get("From", ""))
            from_name = self._decode_header(from_name)
            
            # Parse to
            to_address = parseaddr(msg.get("To", ""))[1]
            
            # Parse cc
            cc = msg.get("Cc", "")
            
            # Get message ID
            message_id = msg.get("Message-ID", f"<{uuid.uuid4()}@unknown>")
            
            # Get threading headers
            in_reply_to = msg.get("In-Reply-To")
            references = msg.get("References")
            
            # Get date
            date_str = msg.get("Date")
            try:
                received_at = parsedate_to_datetime(date_str) if date_str else datetime.now(timezone.utc)
            except Exception:
                received_at = datetime.now(timezone.utc)
            
            # Extract body and attachments
            body_text = None
            body_html = None
            attachments = []
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))
                    
                    if "attachment" in content_disposition:
                        # It's an attachment
                        filename = part.get_filename()
                        if filename:
                            filename = self._decode_header(filename)
                            content = part.get_payload(decode=True)
                            if content:
                                attachments.append((filename, content, content_type))
                    elif content_type == "text/plain" and not body_text:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode("utf-8", errors="replace")
                    elif content_type == "text/html" and not body_html:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_html = payload.decode("utf-8", errors="replace")
            else:
                # Not multipart
                payload = msg.get_payload(decode=True)
                if payload:
                    if msg.get_content_type() == "text/html":
                        body_html = payload.decode("utf-8", errors="replace")
                    else:
                        body_text = payload.decode("utf-8", errors="replace")
            
            return {
                "message_id": message_id,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "from_address": from_address,
                "from_name": from_name or None,
                "to_address": to_address,
                "cc_addresses": cc or None,
                "received_at": received_at,
                "in_reply_to": in_reply_to,
                "references": references,
                "attachments": attachments,
            }
            
        except Exception as e:
            logger.error("Error parsing email: %s", str(e))
            return None
    
    def _decode_header(self, header: str) -> str:
        """Decode an email header properly"""
        if not header:
            return ""
        
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(part)
        
        return "".join(decoded_parts)


async def process_emails():
    """Process all unread emails from IMAP"""
    poller = IMAPPoller()
    emails = await asyncio.get_event_loop().run_in_executor(
        None, poller.fetch_unread_emails
    )
    
    if not emails:
        return
    
    # Get the system's own email address to filter out self-sent emails
    system_email = settings.effective_from_email.lower()
    logger.info("Processing %d emails. System email (for self-filter): %s, Provider: %s", 
               len(emails), system_email, settings.email_provider)
    
    async with async_session_factory() as db:
        service = EmailService(db)
        
        for email_data in emails:
            try:
                # Skip emails sent by the system itself (prevents loops)
                from_address = email_data.get("from_address", "").lower()
                message_id = email_data.get("message_id", "")
                
                # Check if email is from our own system
                if from_address == system_email:
                    logger.info("Skipping self-sent email from %s", from_address)
                    continue
                
                # Check if message ID indicates it's from our system
                if "@fincas-agent>" in message_id:
                    logger.info("Skipping system-generated email: %s", message_id)
                    continue
                
                # Check if already processed
                result = await db.execute(
                    select(Email).where(Email.message_id == email_data["message_id"])
                )
                if result.scalar_one_or_none():
                    logger.debug("Email %s already processed", email_data["message_id"])
                    continue
                
                ticket, email_record = await service.process_inbound_email(
                    message_id=email_data["message_id"],
                    subject=email_data["subject"],
                    body_text=email_data["body_text"],
                    body_html=email_data["body_html"],
                    from_address=email_data["from_address"],
                    from_name=email_data["from_name"],
                    to_address=email_data["to_address"],
                    cc_addresses=email_data["cc_addresses"],
                    received_at=email_data["received_at"],
                    in_reply_to=email_data["in_reply_to"],
                    references=email_data["references"],
                    attachments_data=email_data["attachments"],
                )
                
                logger.info(
                    "Processed email %s -> Ticket %s",
                    email_data["message_id"],
                    ticket.ticket_code,
                )
                
            except Exception as e:
                logger.error("Error processing email %s: %s", email_data.get("message_id"), str(e))
