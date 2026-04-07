"""
Azure DevOps Webhook Handler
Triggers FRD generation when a Work Item is tagged as 'presales'.
Prevents duplicate regeneration when an FRD is already attached.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.services.frd_generator import FRDGeneratorService
from app.services.work_item_service import WorkItemService

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_EVENT_TYPES = {"workitem.created", "workitem.updated"}


def _extract_tags(payload: dict) -> list[str]:
    resource = payload.get("resource", {}) or {}

    possible_sources = [
        resource.get("fields", {}).get("System.Tags"),
        resource.get("revision", {}).get("fields", {}).get("System.Tags"),
        resource.get("tags"),
    ]

    for tags in possible_sources:
        if not tags:
            continue

        if isinstance(tags, str):
            return [t.strip().lower() for t in tags.split(";") if t.strip()]

        if isinstance(tags, dict):
            new_val = tags.get("newValue") or tags.get("oldValue")
            if isinstance(new_val, str):
                return [t.strip().lower() for t in new_val.split(";") if t.strip()]

    return []


def _extract_work_item_id(payload: Dict[str, Any]) -> int:
    resource = payload.get("resource", {}) or {}

    raw_work_item_id = (
        resource.get("workItemId")
        or resource.get("revision", {}).get("id")
        or resource.get("id")
    )

    if raw_work_item_id is None:
        raise HTTPException(status_code=400, detail="Missing Work Item ID")

    try:
        return int(raw_work_item_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Work Item ID") from exc


def _is_supported_event(payload: Dict[str, Any]) -> bool:
    event_type = (payload.get("eventType") or "").strip().lower()
    return event_type in SUPPORTED_EVENT_TYPES


def _is_likely_self_update(payload: Dict[str, Any]) -> bool:
    resource = payload.get("resource", {}) or {}
    revision_fields = resource.get("revision", {}).get("fields", {}) or {}
    changed_fields = resource.get("fields", {}) or {}

    for field_map in (revision_fields, changed_fields):
        for value in field_map.values():
            if isinstance(value, str) and "auto-generated frd" in value.lower():
                return True

    return False


@router.post("/webhook/azure-devops")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    request_id = request.headers.get("x-request-id") or request.headers.get(
        "x-ms-request-id"
    )

    logger.info("Webhook received | request_id=%s", request_id)

    try:
        payload = await request.json()
    except Exception as exc:
        logger.exception(
            "Invalid webhook JSON | request_id=%s | error=%s",
            request_id,
            exc,
        )
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload format")

    event_type = (payload.get("eventType") or "").strip().lower()
    logger.info(
        "Webhook event | request_id=%s | event_type=%s",
        request_id,
        event_type,
    )

    if not _is_supported_event(payload):
        logger.info(
            "Ignoring unsupported event | request_id=%s | event_type=%s",
            request_id,
            event_type,
        )
        return {"status": "ignored", "reason": "unsupported_event"}

    if _is_likely_self_update(payload):
        logger.info("Ignoring likely self-update | request_id=%s", request_id)
        return {"status": "ignored", "reason": "self_update"}

    work_item_id = _extract_work_item_id(payload)
    tags = _extract_tags(payload)

    logger.info(
        "Webhook parsed | request_id=%s | work_item_id=%s | tags=%s",
        request_id,
        work_item_id,
        tags,
    )

    if "presales" not in tags:
        logger.info(
            "Ignoring non-presales work item | request_id=%s | work_item_id=%s",
            request_id,
            work_item_id,
        )
        return {"status": "ignored", "reason": "missing_presales_tag"}

    # BackgroundTasks supports async callables; keep the task small and fully self-contained.
    background_tasks.add_task(process_frd_pipeline, work_item_id, request_id)

    return {
        "status": "accepted",
        "message": f"FRD generation queued for Work Item {work_item_id}",
        "work_item_id": work_item_id,
    }


async def process_frd_pipeline(
    work_item_id: int, request_id: str | None = None
) -> None:
    logger.info(
        "FRD pipeline started | request_id=%s | work_item_id=%s",
        request_id,
        work_item_id,
    )

    try:
        logger.info(
            "STEP 0 START | init WorkItemService | work_item_id=%s", work_item_id
        )
        work_item_service = WorkItemService()
        logger.info("STEP 0 OK | init WorkItemService | work_item_id=%s", work_item_id)

        logger.info(
            "STEP 0 START | init FRDGeneratorService | work_item_id=%s", work_item_id
        )
        frd_generator = FRDGeneratorService()
        logger.info(
            "STEP 0 OK | init FRDGeneratorService | work_item_id=%s", work_item_id
        )

        logger.info("STEP 1 START | has_generated_frd | work_item_id=%s", work_item_id)
        already_exists = await work_item_service.has_generated_frd(work_item_id)
        logger.info(
            "STEP 1 OK | already_exists=%s | work_item_id=%s",
            already_exists,
            work_item_id,
        )

        if already_exists:
            logger.info(
                "STEP 1 EXIT | FRD already exists | work_item_id=%s", work_item_id
            )
            return

        logger.info(
            "STEP 2 START | fetch_work_item_documents | work_item_id=%s", work_item_id
        )
        documents = await work_item_service.fetch_work_item_documents(work_item_id)
        logger.info(
            "STEP 2 OK | document_count=%s | work_item_id=%s",
            len(documents),
            work_item_id,
        )

        if not documents:
            logger.warning("STEP 2 EXIT | no documents | work_item_id=%s", work_item_id)
            return

        logger.info("STEP 3 START | generate_frd | work_item_id=%s", work_item_id)
        frd_path = await frd_generator.generate_frd(
            work_item_id=work_item_id,
            documents=documents,
        )
        logger.info("STEP 3 OK | frd_path=%s | work_item_id=%s", frd_path, work_item_id)

        logger.info(
            "STEP 4 START | upload_frd_to_work_item | work_item_id=%s", work_item_id
        )
        await work_item_service.upload_frd_to_work_item(work_item_id, frd_path)
        logger.info("STEP 4 OK | work_item_id=%s", work_item_id)

        logger.info(
            "FRD pipeline completed successfully | request_id=%s | work_item_id=%s",
            request_id,
            work_item_id,
        )

    except Exception as exc:
        logger.exception(
            "FRD pipeline failed | request_id=%s | work_item_id=%s | error=%r",
            request_id,
            work_item_id,
            exc,
        )
        return
