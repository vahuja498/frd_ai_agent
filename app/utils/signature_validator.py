"""
Webhook Signature Validator
Validates Azure DevOps webhook HMAC-SHA1 signatures (optional security layer).
"""

import hashlib
import hmac
import logging
from fastapi import HTTPException
from app.config import settings

logger = logging.getLogger(__name__)


def validate_webhook_signature(raw_body: bytes, signature_header: str | None) -> None:
    """
    Validates the X-Hub-Signature header from Azure DevOps.
    Only runs if WEBHOOK_SECRET is configured.
    """
    if not settings.WEBHOOK_SECRET:
        return  # Validation disabled

    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    expected = hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha1,
    ).hexdigest()

    provided = signature_header.replace("sha1=", "")

    if not hmac.compare_digest(expected, provided):
        logger.warning("Webhook signature mismatch!")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
