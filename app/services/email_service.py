"""
Email Service - IMAP/SMTP handling for email operations
"""
import asyncio
import email
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import List, Optional, Tuple

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
from app.models.ticket import Ticket
from app.schemas import TicketCreate
from app.services.classifier_service import ClassifierService
from app.services.ticket_service import TicketService

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    """Service for email operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.classifier = ClassifierService()
    
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
        """Send an email via SMTP"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.from_name} <{settings.from_email}>"
        msg["To"] = to
        
        if cc:
            msg["Cc"] = ", ".join(cc)
        
        # Generate message ID
        message_id = f"<{uuid.uuid4()}@fincas-agent>"
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
        
        # Send via SMTP
        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            logger.info("Email sent successfully to %s", to)
        except Exception as e:
            logger.error("Failed to send email: %s", str(e))
            raise
        
        # Store outbound email if ticket provided
        if ticket:
            email_record = Email(
                ticket_id=ticket.id,
                message_id=message_id,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                from_address=settings.from_email,
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
        """Process an inbound email - create or update ticket"""
        
        # Check if this is a reply to an existing ticket
        ticket = await self._find_existing_ticket(subject, in_reply_to, references, from_address)
        
        if ticket:
            logger.info("Found existing ticket %s for email", ticket.ticket_code)
        else:
            # Create new ticket
            category, priority = self.classifier.classify_email(subject, body_text or "")
            community = self.classifier.extract_community_name(from_address, body_text or "")
            
            ticket_service = TicketService(self.db)
            ticket = await ticket_service.create_ticket(TicketCreate(
                subject=subject,
                description=body_text[:2000] if body_text else None,
                category=category,
                priority=priority,
                reporter_email=from_address,
                reporter_name=from_name,
                community_name=community,
            ))
            logger.info("Created new ticket %s from email", ticket.ticket_code)
        
        # Store the email
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
            direction=EmailDirection.INBOUND,
            in_reply_to=in_reply_to,
            references_header=references,
            received_at=received_at,
        )
        self.db.add(email_record)
        await self.db.commit()
        await self.db.refresh(email_record)
        
        # Save attachments
        if attachments_data:
            await self._save_attachments(email_record, attachments_data, ticket.ticket_code)
        
        return ticket, email_record
    
    async def _find_existing_ticket(
        self,
        subject: str,
        in_reply_to: Optional[str],
        references: Optional[str],
        from_address: str,
    ) -> Optional[Ticket]:
        """Find an existing ticket based on email threading or subject"""
        
        # Check by In-Reply-To header
        if in_reply_to:
            result = await self.db.execute(
                select(Email).where(Email.message_id == in_reply_to)
            )
            original_email = result.scalar_one_or_none()
            if original_email:
                ticket_result = await self.db.execute(
                    select(Ticket).where(Ticket.id == original_email.ticket_id)
                )
                return ticket_result.scalar_one_or_none()
        
        # Check references header for any known message
        if references:
            for ref in references.split():
                result = await self.db.execute(
                    select(Email).where(Email.message_id == ref.strip())
                )
                ref_email = result.scalar_one_or_none()
                if ref_email:
                    ticket_result = await self.db.execute(
                        select(Ticket).where(Ticket.id == ref_email.ticket_id)
                    )
                    return ticket_result.scalar_one_or_none()
        
        # Check for ticket code in subject (e.g., "Re: [INC-ABC123] Your issue")
        ticket_code_match = re.search(r'\[?(INC-[A-Z0-9]{6})\]?', subject)
        if ticket_code_match:
            ticket_code = ticket_code_match.group(1)
            result = await self.db.execute(
                select(Ticket).where(Ticket.ticket_code == ticket_code)
            )
            return result.scalar_one_or_none()
        
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
    
    async with async_session_factory() as db:
        service = EmailService(db)
        
        for email_data in emails:
            try:
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
