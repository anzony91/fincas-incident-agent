"""
AI Agent Service - Intelligent incident analysis and information gathering using OpenAI
"""
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from app.config import get_settings
from app.models.ticket import Category, Priority

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class IncidentAnalysis:
    """Result of incident analysis"""
    has_complete_info: bool
    category: Optional[Category]
    priority: Optional[Priority]
    missing_fields: List[str]
    extracted_info: Dict[str, str]
    follow_up_questions: List[str]
    summary: str


REQUIRED_FIELDS = {
    "reporter_name": "Nombre de quien reporta",
    "reporter_contact": "Teléfono o email de contacto",
    "address": "Dirección completa (calle y número)",
    "location_detail": "Ubicación específica (portal, piso, planta, etc.)",
    "problem_description": "Descripción del problema",
}

CATEGORY_SPECIFIC_FIELDS = {
    Category.ELEVATOR: {
        "portal": "Número de portal donde está el ascensor",
        "floor_affected": "Planta donde se quedó parado (si aplica)",
        "people_trapped": "¿Hay personas atrapadas? (Sí/No)",
    },
    Category.WATER: {
        "location_in_building": "Ubicación exacta de la fuga/problema (cocina, baño, portal, etc.)",
        "severity": "¿Hay mucha agua? ¿Está afectando a otros vecinos?",
    },
    Category.ELECTRICITY: {
        "location_in_building": "Ubicación afectada (piso particular, zonas comunes, portal)",
        "scope": "¿Afecta a todo el edificio o solo a una zona?",
    },
    Category.GARAGE_DOOR: {
        "door_location": "Ubicación de la puerta (entrada principal, salida, etc.)",
        "can_enter_exit": "¿Se puede entrar/salir por otra vía?",
    },
    Category.CLEANING: {
        "area": "Zona que necesita limpieza",
    },
    Category.SECURITY: {
        "urgency_detail": "¿Es una emergencia actual o un problema ya ocurrido?",
    },
}

SYSTEM_PROMPT = """Eres un asistente de administración de fincas especializado en gestionar incidencias de comunidades de vecinos en España.

Tu tarea es analizar los reportes de incidencias que llegan y determinar:
1. Si tenemos toda la información necesaria para gestionar la incidencia
2. Qué información falta
3. Clasificar el tipo de incidencia
4. Determinar la prioridad

INFORMACIÓN REQUERIDA PARA CADA INCIDENCIA:
- Nombre de quien reporta
- Contacto (teléfono o email)
- Dirección completa del edificio
- Ubicación específica del problema (portal, piso, planta, zona común, etc.)
- Descripción clara del problema

INFORMACIÓN ADICIONAL SEGÚN TIPO:
- ASCENSOR: Portal específico, planta afectada, si hay personas atrapadas
- AGUA: Ubicación exacta (cocina, baño, etc.), gravedad de la fuga
- ELECTRICIDAD: Zona afectada, si es general o parcial
- GARAJE: Qué puerta, si hay acceso alternativo
- LIMPIEZA: Zona específica
- SEGURIDAD: Si es emergencia actual o incidente pasado

CATEGORÍAS DISPONIBLES: WATER, ELEVATOR, ELECTRICITY, GARAGE_DOOR, CLEANING, SECURITY, OTHER

PRIORIDADES:
- URGENT: Personas atrapadas, inundación activa, sin electricidad total, emergencia de seguridad
- HIGH: Problemas que afectan a varios vecinos, fugas de agua contenidas, ascensor averiado
- MEDIUM: Problemas que pueden esperar 24-48h
- LOW: Problemas menores, mantenimiento preventivo

Responde SIEMPRE en formato JSON con esta estructura exacta:
{
    "has_complete_info": boolean,
    "category": "WATER|ELEVATOR|ELECTRICITY|GARAGE_DOOR|CLEANING|SECURITY|OTHER",
    "priority": "URGENT|HIGH|MEDIUM|LOW",
    "missing_fields": ["lista de campos que faltan"],
    "extracted_info": {
        "reporter_name": "valor o null",
        "reporter_contact": "valor o null",
        "address": "valor o null",
        "location_detail": "valor o null",
        "problem_description": "valor o null",
        ...campos específicos del tipo
    },
    "follow_up_questions": ["preguntas a hacer al reportante"],
    "summary": "resumen breve del problema"
}

Sé amable y profesional. Las preguntas deben ser claras y en español."""


class AIAgentService:
    """Service for intelligent incident analysis using OpenAI"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.model = settings.openai_model
    
    async def analyze_incident(
        self,
        subject: str,
        body: str,
        sender_email: str,
        sender_name: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> IncidentAnalysis:
        """
        Analyze an incident report and determine if we have complete information.
        
        Args:
            subject: Email subject
            body: Email body text
            sender_email: Sender's email address
            sender_name: Sender's name if available
            conversation_history: Previous messages in the conversation
            
        Returns:
            IncidentAnalysis with extracted info and missing fields
        """
        if not self.client:
            logger.warning("OpenAI not configured, using fallback analysis")
            return self._fallback_analysis(subject, body, sender_email, sender_name)
        
        try:
            # Build the conversation context
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            
            # Add conversation history if this is a follow-up
            if conversation_history:
                for msg in conversation_history:
                    messages.append(msg)
            
            # Build the current message
            user_message = self._build_analysis_prompt(subject, body, sender_email, sender_name)
            messages.append({"role": "user", "content": user_message})
            
            # Call OpenAI
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            # Parse response
            result = json.loads(response.choices[0].message.content)
            
            return IncidentAnalysis(
                has_complete_info=result.get("has_complete_info", False),
                category=Category[result["category"]] if result.get("category") else None,
                priority=Priority[result["priority"]] if result.get("priority") else Priority.MEDIUM,
                missing_fields=result.get("missing_fields", []),
                extracted_info=result.get("extracted_info", {}),
                follow_up_questions=result.get("follow_up_questions", []),
                summary=result.get("summary", ""),
            )
            
        except Exception as e:
            logger.error("Error analyzing incident with OpenAI: %s", str(e))
            return self._fallback_analysis(subject, body, sender_email, sender_name)
    
    def _build_analysis_prompt(
        self,
        subject: str,
        body: str,
        sender_email: str,
        sender_name: Optional[str],
    ) -> str:
        """Build the prompt for incident analysis"""
        prompt = f"""Analiza el siguiente reporte de incidencia:

ASUNTO: {subject}

REMITENTE: {sender_name or 'No especificado'} <{sender_email}>

MENSAJE:
{body}

---
Determina si tenemos toda la información necesaria para gestionar esta incidencia.
Si falta información, genera las preguntas que debemos hacer al reportante.
"""
        return prompt
    
    async def generate_follow_up_email(
        self,
        analysis: IncidentAnalysis,
        ticket_code: str,
        reporter_name: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generate a follow-up email asking for missing information.
        
        Returns:
            Tuple of (subject, body_text)
        """
        if not self.client:
            return self._fallback_follow_up_email(analysis, ticket_code, reporter_name)
        
        try:
            questions_text = "\n".join(f"- {q}" for q in analysis.follow_up_questions)
            
            prompt = f"""Genera un email amable y profesional para solicitar más información sobre una incidencia.

CÓDIGO DE TICKET: {ticket_code}
NOMBRE DEL REPORTANTE: {reporter_name or 'Estimado/a vecino/a'}
RESUMEN DEL PROBLEMA: {analysis.summary}

INFORMACIÓN QUE NECESITAMOS:
{questions_text}

El email debe:
- Ser breve y claro
- Agradecer el reporte inicial
- Explicar que necesitamos más información para gestionar la incidencia
- Hacer las preguntas de forma numerada
- Pedir que respondan a este mismo email
- Firmar como "Administración de Fincas"

Responde en JSON con: {{"subject": "asunto", "body": "cuerpo del email"}}"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Eres un asistente de administración de fincas. Genera emails profesionales y amables en español."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get("subject", f"Re: Necesitamos más información - {ticket_code}"), result.get("body", "")
            
        except Exception as e:
            logger.error("Error generating follow-up email: %s", str(e))
            return self._fallback_follow_up_email(analysis, ticket_code, reporter_name)
    
    def _fallback_analysis(
        self,
        subject: str,
        body: str,
        sender_email: str,
        sender_name: Optional[str],
    ) -> IncidentAnalysis:
        """Fallback analysis when OpenAI is not available"""
        from app.services.classifier_service import ClassifierService
        
        classifier = ClassifierService()
        category, priority = classifier.classify_email(subject, body)
        
        # Basic extraction
        extracted = {
            "reporter_name": sender_name,
            "reporter_contact": sender_email,
            "problem_description": body[:500] if body else None,
        }
        
        # Determine missing fields (basic check)
        missing = []
        if not sender_name:
            missing.append("Nombre de quien reporta")
        if "dirección" not in body.lower() and "calle" not in body.lower():
            missing.append("Dirección del edificio")
        if "portal" not in body.lower() and "piso" not in body.lower() and "planta" not in body.lower():
            missing.append("Ubicación específica (portal, piso, planta)")
        
        has_complete = len(missing) == 0
        
        questions = [f"¿Podría indicarnos {m.lower()}?" for m in missing]
        
        return IncidentAnalysis(
            has_complete_info=has_complete,
            category=category,
            priority=priority,
            missing_fields=missing,
            extracted_info=extracted,
            follow_up_questions=questions,
            summary=subject,
        )
    
    def _fallback_follow_up_email(
        self,
        analysis: IncidentAnalysis,
        ticket_code: str,
        reporter_name: Optional[str],
    ) -> Tuple[str, str]:
        """Generate a basic follow-up email without OpenAI"""
        name = reporter_name or "Estimado/a vecino/a"
        questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(analysis.follow_up_questions))
        
        subject = f"Re: Necesitamos más información - {ticket_code}"
        body = f"""Hola {name},

Gracias por reportar la incidencia. Para poder gestionarla correctamente, necesitamos que nos proporcione la siguiente información:

{questions}

Por favor, responda a este email con los datos solicitados.

Gracias por su colaboración.

Atentamente,
Administración de Fincas

---
Referencia: {ticket_code}"""
        
        return subject, body
    
    async def process_follow_up_response(
        self,
        original_analysis: IncidentAnalysis,
        new_message: str,
        conversation_history: List[Dict[str, str]],
    ) -> IncidentAnalysis:
        """
        Process a follow-up response from the reporter and update the analysis.
        
        Args:
            original_analysis: Previous analysis state
            new_message: New message from reporter
            conversation_history: Full conversation history
            
        Returns:
            Updated IncidentAnalysis
        """
        if not self.client:
            # In fallback mode, assume info is now complete
            return IncidentAnalysis(
                has_complete_info=True,
                category=original_analysis.category,
                priority=original_analysis.priority,
                missing_fields=[],
                extracted_info=original_analysis.extracted_info,
                follow_up_questions=[],
                summary=original_analysis.summary,
            )
        
        try:
            # Build prompt with context
            prompt = f"""El reportante ha respondido con más información sobre la incidencia.

INFORMACIÓN PREVIA EXTRAÍDA:
{json.dumps(original_analysis.extracted_info, ensure_ascii=False, indent=2)}

CAMPOS QUE FALTABAN:
{', '.join(original_analysis.missing_fields)}

NUEVA RESPUESTA DEL REPORTANTE:
{new_message}

---
Actualiza el análisis con la nueva información. Determina si ahora tenemos toda la información necesaria.
"""

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
            ]
            
            # Add conversation history
            for msg in conversation_history:
                messages.append(msg)
            
            messages.append({"role": "user", "content": prompt})
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            result = json.loads(response.choices[0].message.content)
            
            return IncidentAnalysis(
                has_complete_info=result.get("has_complete_info", False),
                category=Category[result["category"]] if result.get("category") else original_analysis.category,
                priority=Priority[result["priority"]] if result.get("priority") else original_analysis.priority,
                missing_fields=result.get("missing_fields", []),
                extracted_info=result.get("extracted_info", original_analysis.extracted_info),
                follow_up_questions=result.get("follow_up_questions", []),
                summary=result.get("summary", original_analysis.summary),
            )
            
        except Exception as e:
            logger.error("Error processing follow-up: %s", str(e))
            return IncidentAnalysis(
                has_complete_info=True,
                category=original_analysis.category,
                priority=original_analysis.priority,
                missing_fields=[],
                extracted_info=original_analysis.extracted_info,
                follow_up_questions=[],
                summary=original_analysis.summary,
            )
