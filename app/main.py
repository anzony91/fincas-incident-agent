"""
Fincas Incident Agent - Main FastAPI Application
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.database import close_db, init_db
from app.routers import emails, events, providers, tickets, dashboard, reporters, public, whatsapp

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting %s", settings.app_name)
    await init_db()
    
    # Start email polling worker if configured
    if settings.imap_user and settings.imap_password:
        from app.services.email_worker import start_email_worker
        await start_email_worker()
        logger.info("Email worker started")
    else:
        logger.warning("IMAP credentials not configured - email worker disabled")
    
    yield
    
    # Shutdown
    logger.info("Shutting down %s", settings.app_name)
    if settings.imap_user and settings.imap_password:
        from app.services.email_worker import stop_email_worker
        await stop_email_worker()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    description="Agente automatizado para gestión de incidencias en comunidades de vecinos",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(tickets.router, prefix="/api/tickets", tags=["Tickets"])
app.include_router(providers.router, prefix="/api/providers", tags=["Providers"])
app.include_router(reporters.router, prefix="/api/reporters", tags=["Reporters"])
app.include_router(emails.router, prefix="/api/emails", tags=["Emails"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(dashboard.router)
app.include_router(public.router)  # Public routes for incident form
app.include_router(whatsapp.router, prefix="/api/whatsapp", tags=["WhatsApp"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - redirects to dashboard"""
    return RedirectResponse(url="/dashboard")


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
