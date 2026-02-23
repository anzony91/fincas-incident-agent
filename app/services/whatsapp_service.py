"""
WhatsApp Service - Twilio integration for WhatsApp messaging
"""
import json
import logging
import re
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta

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

# Commands that indicate user wants to start a new incident (exact match or at start)
NEW_INCIDENT_COMMANDS_EXACT = [
    "nueva", "nuevo", "reportar", "incidencia",
]

# Phrases that indicate new incident (can appear anywhere in message)
NEW_INCIDENT_PHRASES = [
    "nueva incidencia", "nuevo problema", "otra incidencia", "otro problema",
    "reportar nueva", "tengo otro problema", "quiero reportar", "nueva consulta",
    "tengo una nueva", "tengo un nuevo", "hay una nueva", "hay un nuevo",
    "reportar incidencia", "nueva averia", "nueva avería", "otra averia", "otra avería",
]

# Time threshold after which we consider it a new incident (24 hours)
NEW_INCIDENT_TIME_THRESHOLD = timedelta(hours=24)


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
    
    @staticmethod
    def _is_valid_floor_door(value: str) -> bool:
        """Check if a value is a valid floor/door (not a room name)."""
        if not value:
            return False
        value_lower = value.lower()
        # Room names that should NOT be saved as floor/door
        invalid_values = [
            "baño", "bano", "cocina", "salon", "salón", "dormitorio", 
            "habitacion", "habitación", "terraza", "balcon", "balcón", 
            "pasillo", "comedor", "aseo", "lavabo", "despensa", "trastero"
        ]
        return not any(room in value_lower for room in invalid_values)
    
    async def process_incoming_message(
        self,
        from_number: str,
        body: str,
        message_sid: str,
        profile_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Process an incoming WhatsApp message using AI to understand intent.
        Returns the response message to send back.
        """
        logger.info("Processing WhatsApp message from %s: %s", from_number, body[:100])
        
        # Normalize phone number (remove 'whatsapp:' prefix if present)
        phone = from_number.replace("whatsapp:", "").strip()
        
        # Find existing ticket that needs info (priority handling)
        pending_ticket = await self._find_ticket_needing_info(phone)
        
        # Get all open tickets for this user
        open_tickets = await self._find_all_open_tickets(phone)
        
        # Use AI to understand the user's intent
        intent, intent_data = await self._detect_user_intent(body, pending_ticket, open_tickets)
        
        logger.info("Detected intent: %s, data: %s", intent, intent_data)
        
        # Handle based on intent
        if intent == "GREETING":
            return await self._handle_greeting(phone, profile_name, open_tickets, pending_ticket)
        
        elif intent == "NEW_INCIDENT":
            # User wants to report a new incident
            problem_description = intent_data.get("problem_description", body)
            return await self._create_ticket_from_message(phone, problem_description, profile_name)
        
        elif intent == "CHECK_STATUS":
            return await self._handle_status_check(phone, open_tickets, intent_data)
        
        elif intent == "PROVIDE_INFO":
            # User is providing info for a pending ticket
            if pending_ticket:
                return await self._process_info_response(pending_ticket, body, phone)
            else:
                # No pending ticket, maybe they want to create one
                return await self._create_ticket_from_message(phone, body, profile_name)
        
        elif intent == "CONFIRM_DATA":
            # User confirmed their data is correct
            if pending_ticket:
                return await self._process_info_response(pending_ticket, body, phone)
            return self._format_welcome_message(profile_name, open_tickets)
        
        elif intent == "OFF_TOPIC":
            return self._format_off_topic_response()
        
        else:  # UNCLEAR or unknown
            return self._format_help_message(profile_name, open_tickets, pending_ticket)
    
    async def _detect_user_intent(
        self, 
        message: str, 
        pending_ticket: Optional[Ticket],
        open_tickets: List[Ticket]
    ) -> Tuple[str, dict]:
        """
        Use AI to detect user's intent from their message.
        Returns (intent, additional_data).
        
        Intents:
        - GREETING: Simple greeting (hola, buenos días, etc.)
        - NEW_INCIDENT: User is reporting a problem
        - CHECK_STATUS: User wants to know status of their incidents
        - PROVIDE_INFO: User is providing requested information
        - CONFIRM_DATA: User is confirming their data is correct
        - OFF_TOPIC: Question unrelated to incident management
        - UNCLEAR: Can't determine intent
        """
        try:
            # Build context about user's situation
            context_parts = []
            if pending_ticket:
                context_parts.append(f"- Tiene una incidencia pendiente ({pending_ticket.ticket_code}) esperando información")
            if open_tickets:
                tickets_summary = ", ".join([f"{t.ticket_code} ({t.status.value})" for t in open_tickets[:5]])
                context_parts.append(f"- Tiene {len(open_tickets)} incidencia(s) abierta(s): {tickets_summary}")
            
            context = "\n".join(context_parts) if context_parts else "- No tiene incidencias abiertas"
            
            prompt = f"""Analiza el siguiente mensaje de WhatsApp de un vecino/propietario y determina su intención.

CONTEXTO DEL USUARIO:
{context}

MENSAJE DEL USUARIO:
"{message}"

POSIBLES INTENCIONES:
1. GREETING - Saludo simple (hola, buenos días, buenas tardes, etc.) sin más contenido
2. NEW_INCIDENT - Está reportando un problema o avería (agua, luz, ascensor, limpieza, ruidos, etc.)
3. CHECK_STATUS - Quiere saber el estado de sus incidencias abiertas
4. PROVIDE_INFO - Está proporcionando información solicitada (nombre, dirección, datos, etc.)
5. CONFIRM_DATA - Está confirmando que sus datos son correctos (sí, correcto, ok, vale, etc.)
6. OFF_TOPIC - Pregunta sobre algo NO relacionado con incidencias del edificio (clima, política, recetas, chistes, etc.)
7. UNCLEAR - No se puede determinar la intención

Si la intención es NEW_INCIDENT, extrae la descripción del problema.
Si es CHECK_STATUS y menciona un código específico, extráelo.

Responde SOLO en JSON: {{"intent": "INTENT_NAME", "problem_description": "si aplica", "ticket_code": "si menciona uno"}}"""

            if self.ai_agent.client:
                response = await self.ai_agent.client.chat.completions.create(
                    model=self.ai_agent.model,
                    messages=[
                        {"role": "system", "content": "Eres un asistente que clasifica intenciones de mensajes. Solo gestionamos incidencias de edificios (fontanería, electricidad, ascensores, limpieza, seguridad). Responde solo en JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                
                result = json.loads(response.choices[0].message.content)
                intent = result.get("intent", "UNCLEAR")
                return intent, result
            
            # Fallback to simple detection
            return self._simple_intent_detection(message, pending_ticket)
            
        except Exception as e:
            logger.error("Error detecting intent: %s", str(e))
            return self._simple_intent_detection(message, pending_ticket)
    
    def _simple_intent_detection(self, message: str, pending_ticket: Optional[Ticket]) -> Tuple[str, dict]:
        """Simple keyword-based intent detection as fallback."""
        msg_lower = message.lower().strip()
        
        # Greetings
        greetings = ["hola", "buenos días", "buenos dias", "buenas tardes", "buenas noches", "hey", "hi", "buenas"]
        if msg_lower in greetings or any(msg_lower.startswith(g + " ") for g in greetings[:3]) and len(msg_lower) < 20:
            return "GREETING", {}
        
        # New incident keywords (anywhere in message)
        for phrase in NEW_INCIDENT_PHRASES:
            if phrase in msg_lower:
                return "NEW_INCIDENT", {"problem_description": message}
        
        # Status check
        status_keywords = ["estado", "cómo va", "como va", "qué pasó", "que paso", "novedades", "actualización", "actualizacion", "mis incidencias"]
        if any(kw in msg_lower for kw in status_keywords):
            return "CHECK_STATUS", {}
        
        # Confirmation
        confirmations = ["sí", "si", "correcto", "ok", "vale", "de acuerdo", "está bien", "esta bien", "afirmativo", "confirmo"]
        if msg_lower in confirmations or any(msg_lower.startswith(c) for c in confirmations):
            return "CONFIRM_DATA", {}
        
        # If there's a pending ticket and message has useful info, assume PROVIDE_INFO
        if pending_ticket:
            return "PROVIDE_INFO", {}
        
        # Check for problem indicators (might be new incident)
        problem_keywords = ["no funciona", "avería", "averia", "roto", "rota", "fuga", "gotea", "ruido", 
                          "luz", "agua", "ascensor", "puerta", "cerradura", "suciedad", "basura"]
        if any(kw in msg_lower for kw in problem_keywords):
            return "NEW_INCIDENT", {"problem_description": message}
        
        return "UNCLEAR", {}
    
    async def _find_ticket_needing_info(self, phone: str) -> Optional[Ticket]:
        """Find a ticket that is waiting for information from this user."""
        # Try multiple phone formats
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        phone_variants = [
            phone_clean,
            phone_clean.replace("+", ""),
            f"+{phone_clean}" if not phone_clean.startswith("+") else phone_clean,
        ]
        
        for variant in phone_variants:
            result = await self.db.execute(
                select(Ticket)
                .where(
                    Ticket.reporter_phone == variant,
                    Ticket.status == TicketStatus.NEEDS_INFO,
                )
                .order_by(Ticket.created_at.desc())
                .limit(1)
            )
            ticket = result.scalar_one_or_none()
            if ticket:
                return ticket
        
        return None
    
    async def _find_all_open_tickets(self, phone: str) -> List[Ticket]:
        """Find all open tickets for this phone number."""
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        phone_variants = [
            phone_clean,
            phone_clean.replace("+", ""),
            f"+{phone_clean}" if not phone_clean.startswith("+") else phone_clean,
        ]
        
        tickets = []
        for variant in phone_variants:
            result = await self.db.execute(
                select(Ticket)
                .where(
                    Ticket.reporter_phone == variant,
                    Ticket.status.in_([
                        TicketStatus.NEW,
                        TicketStatus.NEEDS_INFO,
                        TicketStatus.IN_PROGRESS,
                        TicketStatus.DISPATCHED,
                    ])
                )
                .order_by(Ticket.created_at.desc())
            )
            found = result.scalars().all()
            for t in found:
                if t not in tickets:
                    tickets.append(t)
        
        return tickets
    
    async def _handle_greeting(
        self, 
        phone: str, 
        profile_name: Optional[str],
        open_tickets: List[Ticket],
        pending_ticket: Optional[Ticket]
    ) -> str:
        """Handle a greeting message."""
        return self._format_welcome_message(profile_name, open_tickets, pending_ticket)
    
    def _format_welcome_message(
        self, 
        profile_name: Optional[str], 
        open_tickets: List[Ticket] = None,
        pending_ticket: Optional[Ticket] = None
    ) -> str:
        """Format a welcome message with available options."""
        name = profile_name or "vecino/a"
        
        response = f"""👋 *¡Hola {name}!*

Soy el asistente de *Administración de Fincas*. Puedo ayudarte con:

"""
        
        # If there's a pending ticket, mention it first
        if pending_ticket:
            response += f"""⚠️ *Tienes una incidencia pendiente de información:*
📋 {pending_ticket.ticket_code}: {pending_ticket.subject[:50]}...
_Responde con los datos que te pedimos para procesarla._

"""
        
        response += """📝 *Reportar una incidencia*
   Cuéntame el problema (ej: "no funciona la luz del portal")

"""
        
        if open_tickets and len(open_tickets) > 0:
            response += f"""📊 *Consultar estado* de tus {len(open_tickets)} incidencia(s) abierta(s)
   Escribe "estado" o "mis incidencias"

"""
        
        response += """❓ *Ayuda*
   Escribe "ayuda" para ver más opciones

¿En qué puedo ayudarte?"""
        
        return response
    
    async def _handle_status_check(
        self, 
        phone: str, 
        open_tickets: List[Ticket],
        intent_data: dict
    ) -> str:
        """Handle a request to check ticket status."""
        specific_code = intent_data.get("ticket_code")
        
        if specific_code:
            # Look for specific ticket
            for ticket in open_tickets:
                if ticket.ticket_code.lower() == specific_code.lower():
                    return self._format_ticket_status(ticket)
            return f"No encontré ninguna incidencia con código *{specific_code}* asociada a tu número."
        
        if not open_tickets:
            return """📭 *No tienes incidencias abiertas*

Si quieres reportar un problema, simplemente cuéntame qué ocurre."""
        
        response = f"""📊 *Tus incidencias abiertas ({len(open_tickets)}):*

"""
        
        status_emoji = {
            TicketStatus.NEW: "🆕",
            TicketStatus.NEEDS_INFO: "⏳",
            TicketStatus.IN_PROGRESS: "🔧",
            TicketStatus.DISPATCHED: "🚗",
        }
        
        status_text = {
            TicketStatus.NEW: "Pendiente",
            TicketStatus.NEEDS_INFO: "Esperando información",
            TicketStatus.IN_PROGRESS: "En proceso",
            TicketStatus.DISPATCHED: "Técnico asignado",
        }
        
        for i, ticket in enumerate(open_tickets[:5], 1):
            emoji = status_emoji.get(ticket.status, "📋")
            status = status_text.get(ticket.status, ticket.status.value)
            subject_short = ticket.subject[:40] + "..." if len(ticket.subject) > 40 else ticket.subject
            response += f"""{i}. {emoji} *{ticket.ticket_code}*
   {subject_short}
   Estado: _{status}_

"""
        
        if len(open_tickets) > 5:
            response += f"_...y {len(open_tickets) - 5} más_\n\n"
        
        response += "Para más detalles de una incidencia, escribe su código (ej: INC-XXXXX)"
        
        return response
    
    def _format_ticket_status(self, ticket: Ticket) -> str:
        """Format detailed status for a single ticket."""
        status_text = {
            TicketStatus.NEW: "📋 Pendiente de asignación",
            TicketStatus.NEEDS_INFO: "⏳ Esperando información adicional",
            TicketStatus.IN_PROGRESS: "🔧 En proceso de reparación",
            TicketStatus.DISPATCHED: "🚗 Técnico asignado",
            TicketStatus.RESOLVED: "✅ Resuelta",
            TicketStatus.CLOSED: "🔒 Cerrada",
        }
        
        response = f"""📋 *Incidencia {ticket.ticket_code}*

📝 *Problema:* {ticket.subject}

📊 *Estado:* {status_text.get(ticket.status, ticket.status.value)}
"""
        
        if ticket.address:
            response += f"📍 *Ubicación:* {ticket.address}"
            if ticket.location_detail:
                response += f" ({ticket.location_detail})"
            response += "\n"
        
        if ticket.created_at:
            created_str = ticket.created_at.strftime("%d/%m/%Y %H:%M")
            response += f"📅 *Reportada:* {created_str}\n"
        
        if ticket.status == TicketStatus.NEEDS_INFO:
            response += "\n⚠️ _Necesitamos más información para procesar esta incidencia. Por favor revisa los datos que te solicitamos._"
        
        return response
    
    def _format_off_topic_response(self) -> str:
        """Response for off-topic questions."""
        return """🤖 Lo siento, solo puedo ayudarte con temas relacionados con *incidencias del edificio*.

Puedo ayudarte a:
• 📝 Reportar averías o problemas (luz, agua, ascensor, limpieza, etc.)
• 📊 Consultar el estado de tus incidencias

¿Tienes algún problema en el edificio que quieras reportar?"""
    
    def _format_help_message(
        self, 
        profile_name: Optional[str], 
        open_tickets: List[Ticket],
        pending_ticket: Optional[Ticket]
    ) -> str:
        """Format help message when intent is unclear."""
        response = """🤔 No estoy seguro de entenderte. 

*¿Qué quieres hacer?*

1️⃣ *Reportar un problema* → Describe qué ocurre
   _Ej: "La luz del portal no funciona"_

2️⃣ *Ver mis incidencias* → Escribe "estado"
"""
        
        if pending_ticket:
            response += f"""
⚠️ *Tienes información pendiente de proporcionar* para la incidencia {pending_ticket.ticket_code}.
"""
        
        response += """
Solo puedo ayudarte con incidencias del edificio (fontanería, electricidad, ascensores, limpieza, seguridad, etc.)"""
        
        return response
    
    def _is_new_incident_command(self, message: str) -> bool:
        """Check if the message indicates a new incident should be created."""
        message_lower = message.lower().strip()
        
        # Check exact matches or starts with (for short commands)
        for cmd in NEW_INCIDENT_COMMANDS_EXACT:
            if message_lower == cmd or message_lower.startswith(f"{cmd} ") or message_lower.startswith(f"{cmd}:"):
                logger.info("New incident command detected (exact/start): '%s'", cmd)
                return True
        
        # Check if any new incident phrase appears ANYWHERE in the message
        for phrase in NEW_INCIDENT_PHRASES:
            if phrase in message_lower:
                logger.info("New incident phrase detected: '%s' in message", phrase)
                return True
        
        return False
    
    async def _detect_if_new_incident(self, existing_ticket: Ticket, new_message: str) -> Tuple[bool, str]:
        """
        Use AI to determine if the message is about a NEW incident or the same one.
        Returns (is_new_incident, reason).
        """
        try:
            # Build context about the existing ticket
            existing_context = f"""
INCIDENCIA EXISTENTE ({existing_ticket.ticket_code}):
- Categoría: {existing_ticket.category.value if existing_ticket.category else 'No definida'}
- Asunto: {existing_ticket.subject}
- Descripción: {existing_ticket.description[:500] if existing_ticket.description else 'Sin descripción'}
- Dirección: {existing_ticket.address or 'No especificada'}
- Estado: {existing_ticket.status.value}
"""
            
            # Get AI analysis
            prompt = f"""Analiza si este nuevo mensaje de WhatsApp es sobre la MISMA incidencia existente o es una NUEVA incidencia diferente.

{existing_context}

NUEVO MENSAJE DEL USUARIO:
"{new_message}"

Criterios para considerarlo NUEVA incidencia:
1. Habla de un problema DIFERENTE (ej: antes era fontanería, ahora electricidad)
2. Menciona una ubicación DIFERENTE (otro piso, otro edificio)
3. Describe algo claramente NO relacionado con lo anterior
4. Usa frases como "tengo otro problema", "además", "otra cosa"

Criterios para considerarlo la MISMA incidencia:
1. Proporciona información que se pidió (nombre, dirección, detalles)
2. Da más detalles sobre el MISMO problema
3. Pregunta sobre el estado de su incidencia
4. Responde a preguntas previas

Responde ÚNICAMENTE en formato JSON: {{"is_new": true/false, "reason": "explicación breve"}}"""

            if self.ai_agent.client:
                response = await self.ai_agent.client.chat.completions.create(
                    model=self.ai_agent.model,
                    messages=[
                        {"role": "system", "content": "Eres un asistente que analiza conversaciones de WhatsApp para determinar si un mensaje es sobre una nueva incidencia o la misma. Responde solo en JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                )
                
                result = json.loads(response.choices[0].message.content)
                is_new = result.get("is_new", False)
                reason = result.get("reason", "Sin razón especificada")
                
                logger.info("AI incident detection: is_new=%s, reason=%s", is_new, reason)
                return is_new, reason
            
            # Fallback: simple keyword detection
            return self._simple_new_incident_detection(existing_ticket, new_message)
            
        except Exception as e:
            logger.error("Error in AI incident detection: %s", str(e))
            return self._simple_new_incident_detection(existing_ticket, new_message)
    
    def _simple_new_incident_detection(self, existing_ticket: Ticket, new_message: str) -> Tuple[bool, str]:
        """Simple keyword-based detection as fallback."""
        message_lower = new_message.lower()
        
        # Keywords that suggest a new incident
        new_incident_keywords = [
            "otro problema", "otra incidencia", "además tengo", "también tengo",
            "nueva avería", "otra avería", "otro tema", "aparte de eso",
            "tengo otro", "hay otro", "también hay", "otro asunto",
        ]
        
        for keyword in new_incident_keywords:
            if keyword in message_lower:
                return True, f"Contiene '{keyword}'"
        
        # Check if message mentions a completely different category
        existing_category = existing_ticket.category.value if existing_ticket.category else ""
        category_keywords = {
            "plumbing": ["agua", "tubería", "fontanería", "grifo", "lavabo", "wc", "atasco", "fuga"],
            "electrical": ["luz", "electricidad", "enchufe", "interruptor", "corriente", "fusible"],
            "elevator": ["ascensor", "elevador"],
            "structural": ["grieta", "pared", "techo", "suelo", "estructura"],
            "cleaning": ["limpieza", "basura", "suciedad"],
            "security": ["seguridad", "puerta", "cerradura", "portal"],
        }
        
        # Find what category the new message might be about
        new_categories = set()
        for cat, keywords in category_keywords.items():
            for kw in keywords:
                if kw in message_lower:
                    new_categories.add(cat)
        
        # If new message is about a different category, it's likely a new incident
        if new_categories and existing_category not in new_categories:
            return True, f"Categoría diferente detectada: {new_categories}"
        
        return False, "Parece ser sobre la misma incidencia"
    
    async def _add_update_to_ticket(self, ticket: Ticket, message: str, phone: str) -> str:
        """Add a message as an update to an existing ticket."""
        # Create event
        event = Event(
            ticket_id=ticket.id,
            event_type="whatsapp_update",
            description=f"Mensaje adicional recibido vía WhatsApp: {message[:200]}",
            metadata={"phone": phone, "message": message},
        )
        self.db.add(event)
        await self.db.commit()
        
        response = f"""📝 *Mensaje recibido*

He añadido tu mensaje a la incidencia existente *{ticket.ticket_code}*.

Estado actual: *{self._get_status_text(ticket.status)}*

Si quieres reportar una *nueva incidencia diferente*, escribe: "nueva incidencia"

Si tienes dudas sobre esta incidencia, simplemente responde aquí."""
        
        return response
    
    def _get_status_text(self, status: TicketStatus) -> str:
        """Get user-friendly status text."""
        status_texts = {
            TicketStatus.NEW: "Nueva - Pendiente de asignación",
            TicketStatus.NEEDS_INFO: "Esperando información",
            TicketStatus.IN_PROGRESS: "En proceso",
            TicketStatus.DISPATCHED: "Asignada a proveedor",
            TicketStatus.RESOLVED: "Resuelta",
            TicketStatus.CLOSED: "Cerrada",
        }
        return status_texts.get(status, status.value)
    
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
        # Normalize phone - remove spaces, dashes, and ensure consistent format
        phone_clean = phone.strip().replace(" ", "").replace("-", "")
        
        # Also try variations without + or with different prefix
        phone_variants = [
            phone_clean,
            phone_clean.replace("+", ""),
            f"+{phone_clean}" if not phone_clean.startswith("+") else phone_clean,
        ]
        
        # Check if this phone belongs to a provider
        for variant in phone_variants:
            provider_check = await self.db.execute(
                select(Provider).where(
                    (Provider.phone == variant) | 
                    (Provider.phone_emergency == variant)
                )
            )
            if provider_check.scalar_one_or_none():
                logger.info("Phone %s belongs to a provider, skipping reporter creation", phone_clean)
                return None
        
        # Try to find existing reporter by phone (try all variants)
        reporter = None
        for variant in phone_variants:
            result = await self.db.execute(
                select(Reporter).where(Reporter.phone == variant)
            )
            reporter = result.scalar_one_or_none()
            if reporter:
                break
        
        if reporter:
            # Refresh to get latest data from database
            await self.db.refresh(reporter)
            logger.info("Found existing reporter by phone: %s (refreshed)", reporter.name)
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
        
        # Log reporter data for debugging
        if reporter:
            logger.info("Reporter found: name=%s, phone=%s, address=%s, floor_door=%s, community=%s",
                       reporter.name, reporter.phone, reporter.address, reporter.floor_door, reporter.community_name)
        
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
        logger.info("AI Extracted info: %s", analysis.extracted_info)
        
        # Determine category and priority
        category = analysis.category or Category.OTHER
        priority = analysis.priority or Priority.MEDIUM
        
        # Pre-fill from reporter if available - ONLY use clean data, not AI extractions on floor_door
        reporter_name = profile_name or (reporter.name if reporter else f"WhatsApp {phone[-4:]}")
        community = reporter.community_name if reporter else None
        address = reporter.address if reporter else None
        # Only use floor_door if it looks like a real floor/door (not a room name like "baño")
        floor_door = None
        if reporter and reporter.floor_door:
            fd_lower = reporter.floor_door.lower()
            # Filter out room names that got incorrectly saved as floor_door
            invalid_floor_door = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
            if not any(room in fd_lower for room in invalid_floor_door):
                floor_door = reporter.floor_door
            else:
                logger.warning("Skipping invalid floor_door value: %s", reporter.floor_door)
        
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
        
        # Update reporter with extracted info (but be careful with floor_door)
        if reporter:
            extracted = analysis.extracted_info
            if extracted.get("address") and not reporter.address:
                reporter.address = extracted["address"]
            # Only save location_detail as floor_door if it looks like actual floor/door info
            if extracted.get("location_detail") and not reporter.floor_door:
                location = extracted["location_detail"].lower()
                invalid_locations = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                    "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
                if not any(room in location for room in invalid_locations):
                    reporter.floor_door = extracted["location_detail"]
                    logger.info("Saved floor_door: %s", extracted["location_detail"])
                else:
                    logger.warning("Not saving room name as floor_door: %s", extracted["location_detail"])
            if extracted.get("reporter_name") and reporter.name.startswith("WhatsApp"):
                reporter.name = extracted["reporter_name"]
            
            # Clean up existing invalid floor_door value
            if reporter.floor_door:
                fd_lower = reporter.floor_door.lower()
                invalid_floor_door = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                     "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
                if any(room in fd_lower for room in invalid_floor_door):
                    logger.info("Clearing invalid floor_door value: %s", reporter.floor_door)
                    reporter.floor_door = None
        
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
            # Pass reporter info to format response with known data
            known_data = {
                "name": reporter_name if not reporter_name.startswith("WhatsApp") else None,
                "phone": phone,
                "community": community,
                "address": address,
                "floor_door": floor_door,
            }
            return self._format_followup_response(ticket, analysis, known_data)
    
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
        # Only save location_detail if it looks like actual floor/door info
        if extracted.get("location_detail") and not ticket.location_detail:
            location = extracted["location_detail"].lower()
            invalid_locations = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
            if not any(room in location for room in invalid_locations):
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
            # Only save location_detail as floor_door if it looks like actual floor/door info
            if extracted.get("location_detail") and not reporter.floor_door:
                location = extracted["location_detail"].lower()
                invalid_locations = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                    "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
                if not any(room in location for room in invalid_locations):
                    reporter.floor_door = extracted["location_detail"]
            if extracted.get("reporter_name") and reporter.name.startswith("WhatsApp"):
                reporter.name = extracted["reporter_name"]
            
            # Clean up existing invalid floor_door value
            if reporter.floor_door:
                fd_lower = reporter.floor_door.lower()
                invalid_floor_door = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                     "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
                if any(room in fd_lower for room in invalid_floor_door):
                    logger.info("Clearing invalid floor_door value in _process_info_response: %s", reporter.floor_door)
                    reporter.floor_door = None
        
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
            # Build known data from ticket (filter out invalid floor_door values)
            floor_door_value = ticket.location_detail
            if floor_door_value:
                fd_lower = floor_door_value.lower()
                invalid_values = ["baño", "bano", "cocina", "salon", "salón", "dormitorio", 
                                 "habitacion", "habitación", "terraza", "balcon", "balcón", "pasillo"]
                if any(room in fd_lower for room in invalid_values):
                    floor_door_value = None
            
            known_data = {
                "name": ticket.reporter_name if ticket.reporter_name and not ticket.reporter_name.startswith("WhatsApp") else None,
                "phone": ticket.reporter_phone,
                "community": ticket.community_name,
                "address": ticket.address,
                "floor_door": floor_door_value,
            }
            return self._format_followup_response(ticket, analysis, known_data)
    
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
        # Get category in Spanish
        category_names = {
            "plumbing": "Fontanería",
            "electrical": "Electricidad",
            "elevator": "Ascensor",
            "structural": "Estructura/Albañilería",
            "cleaning": "Limpieza",
            "security": "Seguridad",
            "hvac": "Climatización",
            "other": "General",
        }
        category_es = category_names.get(ticket.category.value, ticket.category.value) if ticket.category else "General"
        
        response = f"""✅ *INCIDENCIA REGISTRADA CORRECTAMENTE*

📋 *Código de seguimiento:* {ticket.ticket_code}

📝 *Resumen del problema:*
{analysis.summary}

🏷️ *Categoría:* {category_es}
"""
        
        # Add location info if available
        if ticket.address:
            response += f"📍 *Ubicación:* {ticket.address}"
            if ticket.location_detail:
                response += f" ({ticket.location_detail})"
            response += "\n"
        
        response += f"""
━━━━━━━━━━━━━━━━━━━━━━
✔️ Hemos notificado al técnico especializado.

� *Le informaremos cuando la incidencia esté solucionada.*

💾 *Guarde el código {ticket.ticket_code}* para consultar el estado de su incidencia.

Si tiene alguna duda, responda a este mensaje."""
        
        return response
    
    def _format_followup_response(self, ticket: Ticket, analysis, known_data: dict = None) -> str:
        """Format response asking for more info, showing known data first."""
        known_data = known_data or {}
        
        response = f"""📋 *INCIDENCIA RECIBIDA*
Código: *{ticket.ticket_code}*

"""
        
        # Show summary of what we understood about the problem
        if analysis.summary:
            response += f"""📝 *Hemos entendido que su problema es:*
"{analysis.summary}"

_¿Es correcto? Si no es así, por favor descríbalo nuevamente._

"""
        
        # Show known data for confirmation
        known_items = []
        if known_data.get("name"):
            known_items.append(f"👤 Nombre: {known_data['name']}")
        if known_data.get("phone"):
            known_items.append(f"📱 Teléfono: {known_data['phone']}")
        if known_data.get("community"):
            known_items.append(f"🏢 Comunidad: {known_data['community']}")
        if known_data.get("address"):
            known_items.append(f"📍 Dirección: {known_data['address']}")
        if known_data.get("floor_door"):
            known_items.append(f"🚪 Piso/Puerta: {known_data['floor_door']}")
        
        if known_items:
            response += "*✅ Sus datos registrados:*\n"
            response += "\n".join(known_items)
            response += "\n\n"
        
        # Filter out fields we already have
        fields_we_have = set()
        if known_data.get("phone"):
            fields_we_have.add("reporter_phone")
            fields_we_have.add("reporter_contact")
        if known_data.get("name"):
            fields_we_have.add("reporter_name")
        if known_data.get("address"):
            fields_we_have.add("address")
        if known_data.get("floor_door"):
            fields_we_have.add("location_detail")
        if known_data.get("community"):
            fields_we_have.add("community_name")
        
        # Get missing fields that we don't already have
        truly_missing = [f for f in analysis.missing_fields if f not in fields_we_have]
        
        if truly_missing:
            response += "━━━━━━━━━━━━━━━━━━━━━━\n"
            response += "⚠️ *NECESITAMOS ESTA INFORMACIÓN:*\n\n"
            
            # Convert technical field names to friendly Spanish with examples
            field_examples = {
                "reporter_name": ("Su nombre completo", "Ej: Juan García"),
                "reporter_phone": ("Teléfono de contacto", "Ej: 612345678"),
                "reporter_contact": ("Teléfono de contacto", "Ej: 612345678"),
                "address": ("Dirección del edificio", "Ej: Calle Mayor 15"),
                "location_detail": ("Piso y puerta", "Ej: 3º A"),
                "community_name": ("Nombre de la comunidad", "Ej: Comunidad Jardines del Sur"),
                "problem_description": ("Descripción detallada del problema", ""),
                "urgency": ("¿Es urgente?", "Ej: Sí/No"),
            }
            
            for i, field in enumerate(truly_missing, 1):
                field_info = field_examples.get(field, (self.FIELD_NAMES_ES.get(field, field), ""))
                name, example = field_info
                if example:
                    response += f"{i}️⃣ *{name}*\n   _{example}_\n"
                else:
                    response += f"{i}️⃣ *{name}*\n"
            
            response += "\n"
        
        response += """📩 *Responda con los datos que faltan* para que podamos gestionar su incidencia lo antes posible.

_Una vez tengamos toda la información, le confirmaremos el registro y le avisaremos cuando esté solucionada._"""
        
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
