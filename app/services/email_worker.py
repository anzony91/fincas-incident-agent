"""
Email Worker - Background task for polling emails
"""
import asyncio
import logging

from app.config import get_settings
from app.services.email_service import process_emails

logger = logging.getLogger(__name__)
settings = get_settings()

_worker_task: asyncio.Task | None = None
_shutdown_event: asyncio.Event | None = None


async def email_worker_loop():
    """Main loop for the email worker"""
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    logger.info("Email worker started - polling every %d seconds", settings.poll_interval_seconds)
    
    while not _shutdown_event.is_set():
        try:
            await process_emails()
        except Exception as e:
            logger.error("Error in email worker: %s", str(e))
        
        # Wait for next poll or shutdown
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=settings.poll_interval_seconds
            )
        except asyncio.TimeoutError:
            # Normal timeout, continue polling
            pass
    
    logger.info("Email worker stopped")


async def start_email_worker():
    """Start the email worker background task"""
    global _worker_task
    
    if _worker_task is not None and not _worker_task.done():
        logger.warning("Email worker already running")
        return
    
    _worker_task = asyncio.create_task(email_worker_loop())
    logger.info("Email worker task created")


async def stop_email_worker():
    """Stop the email worker gracefully"""
    global _worker_task, _shutdown_event
    
    if _shutdown_event is not None:
        _shutdown_event.set()
    
    if _worker_task is not None and not _worker_task.done():
        try:
            await asyncio.wait_for(_worker_task, timeout=5.0)
        except asyncio.TimeoutError:
            _worker_task.cancel()
            try:
                await _worker_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Email worker stopped")
    
    _worker_task = None
    _shutdown_event = None
