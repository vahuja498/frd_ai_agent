"""
Webhook Route - Receives Azure DevOps Work Item events
Triggers FRD generation when a Work Item is tagged as 'presales'
"""

import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Header
from typing import Optional

from app.models.webhook_payload import AzureDevOpsWebhookPayload
from app.services.work_item_service import WorkItemService
from app.services.frd_generator import FRDGeneratorService
from app.utils.signature_validator import validate_webhook_signature

logger = logging.getLogger(__name__)
router = APIRouter()





@router.post("/webhook/azure-devops")
async def handle_azure_devops_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(None),
):
    """
    Receives Azure DevOps webhook events.
    Triggers FRD generation when a Work Item is tagged with 'presales'.
    """
    raw_body = await request.body()

    # Optional: Validate webhook signature for security
    # validate_webhook_signature(raw_body, x_hub_signature)

    try:
        payload_data = await request.json()
        payload = AzureDevOpsWebhookPayload(**payload_data)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    logger.info(
        f"Received webhook event: {payload.eventType} | "
        f"Resource: {payload.resource.get('id', 'unknown')}"
    )

    # Only process work item created or updated events
    if payload.eventType not in [
        "workitem.created",
        "workitem.updated",
        "workitem.tagged",
    ]:
        return {"status": "ignored", "reason": "Event type not relevant"}

    # Check if the work item is tagged as 'presales'
    work_item_service = WorkItemService()
    is_presales = work_item_service.is_presales_tagged(payload)

    if not is_presales:
        return {"status": "ignored", "reason": "Work item not tagged as presales"}

    work_item_id = payload.resource.get("id") or payload.resource.get("workItemId")
    if not work_item_id:
        raise HTTPException(status_code=400, detail="Could not extract work item ID")

    logger.info(f"✅ Presales tag detected on Work Item #{work_item_id}. Triggering FRD generation...")

    # Process in background to avoid webhook timeout
    background_tasks.add_task(
        process_frd_generation,
        work_item_id=work_item_id,
        payload=payload,
    )

    return {
        "status": "accepted",
        "message": f"FRD generation triggered for Work Item #{work_item_id}",
        "work_item_id": work_item_id,
    }


async def process_frd_generation(work_item_id: int, payload: AzureDevOpsWebhookPayload):
    """Background task: fetch documents, generate FRD, upload back to ADO."""
    try:
        logger.info(f"📄 Fetching attachments for Work Item #{work_item_id}...")
        documents = await work_item_service.fetch_work_item_documents(work_item_id)

        if not documents:
            logger.warning(f"No documents found for Work Item #{work_item_id}")
            return

        logger.info(f"🤖 Generating FRD using LLM for Work Item #{work_item_id}...")
        frd_docx_path = await frd_generator.generate_frd(
            work_item_id=work_item_id,
            documents=documents,
        )

        logger.info(f"📤 Uploading FRD to Work Item #{work_item_id}...")
        await work_item_service.upload_frd_to_work_item(work_item_id, frd_docx_path)

        logger.info(f"✅ FRD generation complete for Work Item #{work_item_id}")

    except Exception as e:
        logger.error(f"❌ FRD generation failed for Work Item #{work_item_id}: {e}", exc_info=True)
