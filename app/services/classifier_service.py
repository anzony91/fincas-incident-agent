"""
Classifier Service - Email classification and categorization
"""
import re
from typing import Tuple

from app.models.ticket import Category, Priority


class ClassifierService:
    """Service for classifying emails into categories and priorities"""
    
    # Keyword patterns for each category (Spanish)
    CATEGORY_PATTERNS = {
        Category.WATER: [
            r'\bagua\b', r'\bfuga\b', r'\btubería\b', r'\btuberias\b',
            r'\binundaci[oó]n\b', r'\bhumedad\b', r'\bgoteras?\b',
            r'\bcañería\b', r'\bcanerias\b', r'\batasco\b',
            r'\bfontaner[oí]a\b', r'\bdesagüe\b', r'\bdesague\b',
            r'\bcisterna\b', r'\bgrifo\b', r'\blavabo\b',
        ],
        Category.ELEVATOR: [
            r'\bascensor\b', r'\bascensores\b', r'\belevador\b',
            r'\bquedarse encerrado\b', r'\batrapado\b', r'\bparado\b',
            r'\bno funciona.*ascensor\b', r'\bascensor.*no funciona\b',
            r'\bbot[oó]n.*ascensor\b', r'\bpuerta.*ascensor\b',
        ],
        Category.ELECTRICITY: [
            r'\belectricidad\b', r'\bcorriente\b', r'\bluz\b',
            r'\bapag[oó]n\b', r'\bcorte de luz\b', r'\bcorte.*el[eé]ctrico\b',
            r'\benchufe\b', r'\binterruptor\b', r'\bcuadro el[eé]ctrico\b',
            r'\bcable\b', r'\bcables\b', r'\bcortocircuito\b',
            r'\bfusible\b', r'\bdiferencial\b', r'\bmagnet[oó]t[eé]rmico\b',
        ],
        Category.GARAGE_DOOR: [
            r'\bgaraje\b', r'\bpuerta.*garaje\b', r'\bgaraje.*puerta\b',
            r'\bcancela\b', r'\bport[oó]n\b', r'\bbarrera\b',
            r'\bmando\b', r'\bmotor.*puerta\b', r'\bpuerta.*motor\b',
            r'\bpuerta.*autom[aá]tica\b',
        ],
        Category.CLEANING: [
            r'\blimpieza\b', r'\blimpiar\b', r'\bsuciedad\b', r'\bbasura\b',
            r'\bportal\b', r'\bescalera\b', r'\bzaguán\b',
            r'\bpintada\b', r'\bgrafiti\b', r'\bgraffiti\b',
            r'\bolores?\b', r'\bmal olor\b',
        ],
        Category.SECURITY: [
            r'\bseguridad\b', r'\brobo\b', r'\bvandalismo\b',
            r'\bintrusi[oó]n\b', r'\balarma\b', r'\bc[aá]mara\b',
            r'\bvideoportero\b', r'\bporter[oi]\b', r'\bllave\b',
            r'\bcerradura\b', r'\bpuerta.*entrada\b', r'\bentrada.*puerta\b',
        ],
    }
    
    # Priority keywords (Spanish)
    URGENT_PATTERNS = [
        r'\burgente\b', r'\bemergencia\b', r'\binmediato\b',
        r'\bya\b', r'\bahora mismo\b', r'\bcrític[oa]\b',
        r'\bgrave\b', r'\bpeligro\b', r'\binundando\b',
        r'\bsin luz\b', r'\batrapado\b', r'\bencerrado\b',
        r'\bfuego\b', r'\bincendio\b', r'\bhumo\b',
    ]
    
    HIGH_PATTERNS = [
        r'\bimportante\b', r'\bpronto\b', r'\br[aá]pido\b',
        r'\bcuanto antes\b', r'\bno puede esperar\b',
        r'\bmuy necesario\b', r'\bpor favor.*pronto\b',
    ]
    
    LOW_PATTERNS = [
        r'\bcuando pued[ae]s?\b', r'\bsin prisa\b', r'\bcuando sea\b',
        r'\bno urgente\b', r'\bno es urgente\b', r'\bpequeñ[oa]\b',
        r'\bmenor\b', r'\bleve\b',
    ]
    
    def classify_email(self, subject: str, body: str) -> Tuple[Category, Priority]:
        """
        Classify an email based on subject and body content.
        Returns tuple of (Category, Priority)
        """
        text = f"{subject} {body}".lower()
        
        category = self._detect_category(text)
        priority = self._detect_priority(text, category)
        
        return category, priority
    
    def _detect_category(self, text: str) -> Category:
        """Detect the category based on keyword patterns"""
        category_scores = {}
        
        for category, patterns in self.CATEGORY_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                score += len(matches)
            category_scores[category] = score
        
        # Find category with highest score
        if category_scores:
            best_category = max(category_scores.items(), key=lambda x: x[1])
            if best_category[1] > 0:
                return best_category[0]
        
        return Category.OTHER
    
    def _detect_priority(self, text: str, category: Category) -> Priority:
        """Detect the priority based on keywords and category"""
        # Check for urgent keywords
        for pattern in self.URGENT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return Priority.URGENT
        
        # Check for high priority keywords
        for pattern in self.HIGH_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return Priority.HIGH
        
        # Check for low priority keywords
        for pattern in self.LOW_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return Priority.LOW
        
        # Default priorities based on category
        category_default_priority = {
            Category.ELEVATOR: Priority.HIGH,  # Ascensores suelen ser urgentes
            Category.WATER: Priority.HIGH,     # Agua puede causar daños rápidos
            Category.ELECTRICITY: Priority.HIGH,
            Category.SECURITY: Priority.HIGH,
            Category.GARAGE_DOOR: Priority.MEDIUM,
            Category.CLEANING: Priority.LOW,
            Category.OTHER: Priority.MEDIUM,
        }
        
        return category_default_priority.get(category, Priority.MEDIUM)
    
    def extract_community_name(self, email_address: str, body: str) -> str | None:
        """Try to extract the community name from email or body"""
        # Try common patterns for community emails
        # e.g., comunidad.lasfuentes@gmail.com or presidencialomar@outlook.com
        
        patterns = [
            r'comunidad[.\s]*([\w\s]+)@',
            r'presidente[.\s]*([\w\s]+)@', 
            r'administ[.\s]*([\w\s]+)@',
            r'comunidad de (propietarios )?(?:de )?([\w\s]+)',
            r'urbanizaci[oó]n ([\w\s]+)',
            r'residencial ([\w\s]+)',
            r'edificio ([\w\s]+)',
        ]
        
        full_text = f"{email_address} {body}"
        
        for pattern in patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                # Get the last captured group (the name)
                name = match.group(match.lastindex or 1)
                return name.strip().title()
        
        return None
