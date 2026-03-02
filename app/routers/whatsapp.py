"""
WhatsApp API Router - Webhook for Twilio
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.whatsapp_service import WhatsAppService

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(...),
    ProfileName: Optional[str] = Form(None),
    NumMedia: Optional[str] = Form("0"),
):
    """
    Webhook endpoint for incoming WhatsApp messages from Twilio.
    
    Twilio sends form-encoded data with:
    - From: The sender's phone number (whatsapp:+1234567890)
    - Body: The message text
    - MessageSid: Unique message identifier
    - ProfileName: The sender's WhatsApp profile name (if available)
    - NumMedia: Number of media attachments
    """
    logger.info("Received WhatsApp webhook: From=%s, Body=%s", From, Body[:50] if Body else "")
    
    # Validate the request signature (optional but recommended for production)
    # signature = request.headers.get("X-Twilio-Signature", "")
    # url = str(request.url)
    # params = dict(await request.form())
    # 
    # whatsapp_service = WhatsAppService(db)
    # if not whatsapp_service.validate_request(url, params, signature):
    #     logger.warning("Invalid Twilio signature")
    #     raise HTTPException(status_code=403, detail="Invalid signature")
    
    # Check for media (we don't support it yet)
    if int(NumMedia or 0) > 0:
        logger.info("Message contains %s media files - not supported yet", NumMedia)
    
    # Process the message
    whatsapp_service = WhatsAppService(db)
    
    try:
        response_message = await whatsapp_service.process_incoming_message(
            from_number=From,
            body=Body,
            message_sid=MessageSid,
            profile_name=ProfileName,
        )
        
        # Return TwiML response
        if response_message:
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{response_message}</Message>
</Response>"""
            return Response(content=twiml, media_type="application/xml")
        else:
            # Empty response - no reply needed
            return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>", 
                          media_type="application/xml")
            
    except Exception as e:
        logger.error("Error processing WhatsApp message: %s", str(e), exc_info=True)
        # Return user-friendly error
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>Lo sentimos, ha ocurrido un error procesando su mensaje. Por favor, inténtelo de nuevo más tarde o contacte con incidencias@adminsavia.com</Message>
</Response>"""
        return Response(content=error_twiml, media_type="application/xml")


@router.get("/webhook")
async def whatsapp_webhook_verify():
    """
    GET endpoint for webhook verification (some providers require this).
    """
    return {"status": "ok", "service": "whatsapp"}


@router.post("/send")
async def send_whatsapp_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    to: str = Form(...),
    message: str = Form(...),
):
    """
    Send a WhatsApp message (for testing or manual sending).
    """
    whatsapp_service = WhatsAppService(db)
    success = await whatsapp_service.send_message(to, message)
    
    if success:
        return {"status": "sent", "to": to}
    else:
        raise HTTPException(status_code=500, detail="Failed to send message")
