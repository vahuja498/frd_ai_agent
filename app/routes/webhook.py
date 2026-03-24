"""
Azure DevOps Webhook Handler
Triggers FRD generation when a Work Item is tagged as 'presales'
"""

import logging
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException

from app.services.work_item_service import WorkItemService
from app.services.frd_generator import FRDGeneratorService

logger = logging.getLogger(__name__)
router = APIRouter()


# -------------------------------
# 🔍 Helper: Extract Tags Safely
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
    logger.warning("🚨 WEBHOOK HIT 🚨")

    try:
        payload = await request.json()
    except Exception as e:
        logger.error("❌ Invalid JSON", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("eventType", "")
    work_item_id = payload.get("resource", {}).get("id") or payload.get(
        "resource", {}
    ).get("workItemId")

    logger.warning(f"📩 EVENT TYPE: {event_type}")
    logger.warning(f"🔢 WORK ITEM ID: {work_item_id}")

    # ✅ Only process relevant events
    if event_type not in ["workitem.created", "workitem.updated"]:
        return {"status": "ignored", "reason": "Event not relevant"}

    if not work_item_id:
        raise HTTPException(status_code=400, detail="Missing Work Item ID")

    # -------------------------------
    # 🏷️ Tag Detection (Robust)
    # -------------------------------
    tags = extract_tags(payload)
    logger.warning(f"🏷️ TAGS: {tags}")

    is_presales = "presales" in tags.lower()

    if not is_presales:
        logger.warning("⛔ Not a presales item. Ignoring.")
        return {"status": "ignored", "reason": "No presales tag"}

    logger.warning(f"✅ PRESALES DETECTED → Work Item #{work_item_id}")

    # -------------------------------
    # 🚀 Background Task
    # -------------------------------
    background_tasks.add_task(process_frd, work_item_id)

    return {
        "status": "accepted",
        "message": f"FRD generation started for Work Item {work_item_id}",
    }


# -------------------------------
# 🤖 Background Processor
# -------------------------------
async def process_frd(work_item_id: int):
    work_item_service = WorkItemService()
    frd_generator = FRDGeneratorService()

    try:
        logger.warning(f"📄 Fetching work item #{work_item_id}")

        documents = await work_item_service.fetch_work_item_documents(work_item_id)
        logger.warning(f"📎 DOCUMENTS: {documents}")

        if not documents:
            logger.warning("⚠️ No documents found. Skipping FRD.")
            return

        logger.warning("🤖 Generating FRD...")

        frd_path = await frd_generator.generate_frd(
            work_item_id=work_item_id, documents=documents
        )

        logger.warning(f"📄 Generated file: {frd_path}")

        logger.warning("📤 Uploading FRD to Azure DevOps...")

        await work_item_service.upload_frd_to_work_item(work_item_id, frd_path)

        logger.warning(f"✅ FRD SUCCESS for Work Item #{work_item_id}")

    except Exception as e:
        logger.error(f"🔥 FRD FAILED for Work Item #{work_item_id}", exc_info=True)
