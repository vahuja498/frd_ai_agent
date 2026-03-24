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

    try:
        payload_data = await request.json()
        logger.info(f"🔥 FULL PAYLOAD: {payload_data}")

        payload = AzureDevOpsWebhookPayload(**payload_data)

    except Exception as e:
        logger.error(f"❌ Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    logger.info(
        f"📩 Event: {payload.eventType} | Work Item ID: {payload.resource.get('id')}"
    )

    # ✅ Only process relevant events
    if payload.eventType not in ["workitem.created", "workitem.updated"]:
        return {"status": "ignored", "reason": "Event type not relevant"}

    work_item_service = WorkItemService()

    # ✅ Extract tags safely
    tags = payload.resource.get("fields", {}).get("System.Tags", "")
    logger.info(f"🏷️ TAGS: {tags}")

    is_presales = "presales" in tags.lower()

    if not is_presales:
        logger.info("⛔ Work item is NOT tagged as 'presales'")
        return {"status": "ignored", "reason": "No presales tag"}

    work_item_id = payload.resource.get("id") or payload.resource.get("workItemId")

    if not work_item_id:
        raise HTTPException(status_code=400, detail="Work item ID not found")

    logger.info(f"✅ Presales detected → Triggering FRD for #{work_item_id}")

    # ✅ Run async background job
    background_tasks.add_task(
        process_frd_generation,
        work_item_id=work_item_id,
    )

    return {
        "status": "accepted",
        "message": f"FRD generation triggered for Work Item #{work_item_id}",
        "work_item_id": work_item_id,
    }


# =========================
# BACKGROUND TASK
# =========================


async def process_frd_generation(work_item_id: int):
    """Background task: fetch docs → generate FRD → upload"""

    work_item_service = WorkItemService()
    frd_generator = FRDGeneratorService()

    try:
        logger.info(f"📄 Fetching attachments for Work Item #{work_item_id}...")

        documents = await work_item_service.fetch_work_item_documents(work_item_id)

        if not documents:
            logger.warning(f"⚠️ No documents found for Work Item #{work_item_id}")
            return

        logger.info(f"🤖 Generating FRD for Work Item #{work_item_id}...")

        frd_docx_path = await frd_generator.generate_frd(
            work_item_id=work_item_id,
            documents=documents,
        )

        logger.info(f"📤 Uploading FRD to Work Item #{work_item_id}...")

        await work_item_service.upload_frd_to_work_item(work_item_id, frd_docx_path)

        logger.info(f"✅ FRD generation COMPLETE for Work Item #{work_item_id}")

    except Exception as e:
        logger.error(
            f"❌ FRD generation failed for Work Item #{work_item_id}: {e}",
            exc_info=True,
        )
