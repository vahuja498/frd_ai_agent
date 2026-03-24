"""
Azure DevOps Webhook Handler
Triggers FRD generation when a Work Item is tagged as 'presales'
"""

import os

print("🔥 FILE LOADED:", __file__)
import logging
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException

from app.services.work_item_service import WorkItemService
from app.services.frd_generator import FRDGeneratorService

logger = logging.getLogger(__name__)
router = APIRouter()


# -------------------------------
# 🔍 Extract Tags (handles ADO variations)
# -------------------------------
def extract_tags(payload: dict) -> str:
    try:
        return payload["resource"]["fields"].get("System.Tags", "")
    except Exception:
        return (
            payload.get("resource", {})
            .get("revision", {})
            .get("fields", {})
            .get("System.Tags", "")
            or ""
        )


# -------------------------------
# 🚀 Webhook Endpoint
# -------------------------------
@router.post("/webhook/azure-devops")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.error("🔥 WEBHOOK EXECUTED (NEW CODE) 🔥")

    try:
        logger.error("🚨 NEW WEBHOOK HIT 🚨")
        payload = await request.json()
    except Exception:
        logger.error("❌ Invalid JSON received", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("eventType", "")
    resource = payload.get("resource", {})

    work_item_id = resource.get("id") or resource.get("workItemId")

    logger.info(f"📩 Event: {event_type}")
    logger.info(f"🔢 Work Item ID: {work_item_id}")

    # -------------------------------
    # ✅ Validate Event
    # -------------------------------
    if event_type not in ["workitem.created", "workitem.updated"]:
        logger.warning("⛔ Ignored event type")
        return {"status": "ignored", "reason": "event not supported"}

    if not work_item_id:
        logger.error("❌ Work Item ID missing")
        raise HTTPException(status_code=400, detail="Missing Work Item ID")

    # -------------------------------
    # 🏷️ Tag Detection
    # -------------------------------
    tags = extract_tags(payload)
    logger.info(f"🏷️ Tags: {tags}")

    is_presales = "presales" in tags.lower()

    if not is_presales:
        logger.warning("⛔ Not a presales item")
        return {"status": "ignored", "reason": "no presales tag"}

    logger.info(f"✅ Presales detected for Work Item #{work_item_id}")

    # -------------------------------
    # 🚀 Trigger Background Task
    # -------------------------------
    background_tasks.add_task(process_frd_pipeline, work_item_id)

    return {
        "status": "accepted",
        "message": f"FRD generation started for Work Item {work_item_id}",
    }


# -------------------------------
# 🤖 Background FRD Pipeline
# -------------------------------
async def process_frd_pipeline(work_item_id: int):
    work_item_service = WorkItemService()
    frd_generator = FRDGeneratorService()

    try:
        logger.info(f"📄 Fetching documents for WI #{work_item_id}")

        documents = await work_item_service.fetch_work_item_documents(work_item_id)
        logger.info(f"📎 Documents fetched: {len(documents)}")

        if not documents:
            logger.warning("⚠️ No attachments found. Skipping FRD generation.")
            return

        logger.info("🤖 Generating FRD...")

        frd_path = await frd_generator.generate_frd(
            work_item_id=work_item_id, documents=documents
        )

        logger.info(f"📄 FRD generated at: {frd_path}")

        logger.info("📤 Uploading FRD to Azure DevOps...")

        await work_item_service.upload_frd_to_work_item(work_item_id, frd_path)

        logger.info(f"✅ FRD successfully uploaded for WI #{work_item_id}")

    except Exception:
        logger.error(f"🔥 FRD PIPELINE FAILED for WI #{work_item_id}", exc_info=True)
