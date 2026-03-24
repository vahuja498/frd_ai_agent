"""
Azure DevOps Webhook Handler
Triggers FRD generation when a Work Item is tagged as 'presales'
Stops re-processing if an FRD is already attached
"""

import logging
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException

from app.services.work_item_service import WorkItemService
from app.services.frd_generator import FRDGeneratorService

logger = logging.getLogger(__name__)
router = APIRouter()


def extract_tags(payload: dict) -> str:
    resource = payload.get("resource", {})

    tags = resource.get("fields", {}).get("System.Tags")
    if tags:
        return tags

    tags = resource.get("revision", {}).get("fields", {}).get("System.Tags")
    if tags:
        return tags

    return ""


@router.post("/webhook/azure-devops")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.info("🔥 WEBHOOK EXECUTED")

    try:
        payload = await request.json()
    except Exception:
        logger.error("❌ Invalid JSON received", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("eventType", "")
    resource = payload.get("resource", {})

    work_item_id = (
        resource.get("workItemId")
        or resource.get("revision", {}).get("id")
        or resource.get("id")
    )

    logger.info(f"📩 Event: {event_type}")
    logger.info(f"🔢 Work Item ID: {work_item_id}")

    if event_type not in ["workitem.created", "workitem.updated"]:
        logger.warning("⛔ Ignored event type")
        return {"status": "ignored", "reason": "event not supported"}

    if not work_item_id:
        logger.error("❌ Work Item ID missing")
        raise HTTPException(status_code=400, detail="Missing Work Item ID")

    tags = extract_tags(payload)
    logger.info(f"🏷️ Tags: {tags}")

    is_presales = "presales" in tags.lower()
    if not is_presales:
        logger.warning("⛔ Not a presales item")
        return {"status": "ignored", "reason": "no presales tag"}

    logger.info(f"✅ Presales detected for Work Item #{work_item_id}")

    background_tasks.add_task(process_frd_pipeline, int(work_item_id))

    return {
        "status": "accepted",
        "message": f"FRD generation started for Work Item {work_item_id}",
    }


async def process_frd_pipeline(work_item_id: int):
    logger.error(f"🚀 PIPELINE STARTED for WI {work_item_id}")

    try:
        work_item_service = WorkItemService()
        frd_generator = FRDGeneratorService()

        # STOP LOOP: if FRD already exists, do nothing
        already_exists = await work_item_service.has_generated_frd(work_item_id)
        if already_exists:
            logger.warning(
                f"⏭️ FRD already exists for WI {work_item_id}. Skipping regeneration."
            )
            return

        logger.error("📄 Fetching documents...")
        documents = await work_item_service.fetch_work_item_documents(work_item_id)

        logger.error(f"📎 Documents fetched: {len(documents)}")

        if not documents:
            logger.error("❌ NO DOCUMENTS FOUND - STOPPING")
            return

        logger.error("🤖 Generating FRD...")
        frd_path = await frd_generator.generate_frd(
            work_item_id=work_item_id, documents=documents
        )

        logger.error(f"📄 FRD GENERATED: {frd_path}")

        logger.error("📤 Uploading to Azure DevOps...")
        await work_item_service.upload_frd_to_work_item(work_item_id, frd_path)

        logger.error("✅ PIPELINE COMPLETED SUCCESSFULLY")

    except Exception:
        logger.error("🔥🔥🔥 PIPELINE CRASHED 🔥🔥🔥", exc_info=True)
