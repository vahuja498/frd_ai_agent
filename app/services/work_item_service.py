"""
Work Item Service
Interacts with Azure DevOps REST API to:
- detect whether an FRD already exists
- fetch and classify source attachments
- upload the generated FRD back to the Work Item
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List

import httpx

from app.config import settings
from app.models.webhook_payload import WorkItemDocument
from app.utils.document_extractor import DocumentExtractor

logger = logging.getLogger(__name__)


class WorkItemService:
    SUPPORTED_EXTENSIONS = {
        ".docx",
        ".doc",
        ".pdf",
        ".txt",
        ".md",
        ".rtf",
    }

    GENERATED_FRD_COMMENT = "Auto-generated FRD by FRD AI Agent"

    def __init__(self) -> None:
        self.org_url = (getattr(settings, "ADO_ORG_URL", "") or "").rstrip("/")
        self.project = (getattr(settings, "ADO_PROJECT", "") or "").strip()
        self.project_encoded = (
            getattr(settings, "ADO_PROJECT_ENCODED", "") or self.project
        )
        self.pat = (getattr(settings, "ADO_PAT", "") or "").strip()

        self._validate_config()
        self._auth_header = self._build_auth_header()
        self.extractor = DocumentExtractor()

    def _validate_config(self) -> None:
        missing = []

        if not self.org_url:
            missing.append("ADO_ORG_URL")
        if not self.project:
            missing.append("ADO_PROJECT")
        if not self.pat:
            missing.append("ADO_PAT")

        if missing:
            raise ValueError(
                f"Missing Azure DevOps configuration: {', '.join(missing)}"
            )

    def _build_auth_header(self) -> Dict[str, str]:
        token = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }

    def _work_item_url(self, work_item_id: int, expand_relations: bool = False) -> str:
        suffix = "?api-version=7.1"
        if expand_relations:
            suffix = "?$expand=relations&api-version=7.1"

        return (
            f"{self.org_url}/{self.project_encoded}/_apis/wit/workitems/{work_item_id}"
            f"{suffix}"
        )

    def _attachment_upload_url(self, filename: str) -> str:
        return (
            f"{self.org_url}/{self.project_encoded}/_apis/wit/attachments"
            f"?fileName={filename}&api-version=7.1"
        )

    def _is_generated_frd_attachment(self, name: str, comment: str) -> bool:
        low_name = (name or "").lower()
        low_comment = (comment or "").lower()

        if low_name.startswith("frd_wi") and low_name.endswith(".docx"):
            return True
        if self.GENERATED_FRD_COMMENT.lower() in low_comment:
            return True
        return False

    async def has_generated_frd(self, work_item_id: int) -> bool:
        """
        Returns True if an auto-generated FRD is already attached to the work item.
        Prevents infinite loops and duplicate uploads.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                self._work_item_url(work_item_id, expand_relations=True),
                headers=self._auth_header,
            )
            resp.raise_for_status()
            work_item = resp.json()

        for rel in work_item.get("relations", []) or []:
            if rel.get("rel") != "AttachedFile":
                continue

            attrs = rel.get("attributes", {}) or {}
            name = attrs.get("name", "")
            comment = attrs.get("comment", "")

            if self._is_generated_frd_attachment(name=name, comment=comment):
                return True

        return False

    async def fetch_work_item_documents(
        self, work_item_id: int
    ) -> List[WorkItemDocument]:
        """
        Fetches supported attachments from the work item and extracts text content.
        Unsupported files are skipped.
        """
        documents: List[WorkItemDocument] = []

        async with httpx.AsyncClient(timeout=90) as client:
            work_item_resp = await client.get(
                self._work_item_url(work_item_id, expand_relations=True),
                headers=self._auth_header,
            )
            work_item_resp.raise_for_status()
            work_item = work_item_resp.json()

            relations = work_item.get("relations", []) or []
            logger.info(
                "Fetched work item relations | work_item_id=%s | relation_count=%s",
                work_item_id,
                len(relations),
            )

            for relation in relations:
                if relation.get("rel") != "AttachedFile":
                    continue

                attrs = relation.get("attributes", {}) or {}
                filename = attrs.get("name", "unknown.bin")
                comment = attrs.get("comment", "")
                attachment_url = relation.get("url")

                if self._is_generated_frd_attachment(filename, comment):
                    logger.info(
                        "Skipping generated FRD attachment | work_item_id=%s | filename=%s",
                        work_item_id,
                        filename,
                    )
                    continue

                if not attachment_url:
                    logger.warning(
                        "Skipping attachment with missing url | work_item_id=%s | filename=%s",
                        work_item_id,
                        filename,
                    )
                    continue

                ext = Path(filename).suffix.lower()
                if ext not in self.SUPPORTED_EXTENSIONS:
                    logger.info(
                        "Skipping unsupported attachment | work_item_id=%s | filename=%s | extension=%s",
                        work_item_id,
                        filename,
                        ext,
                    )
                    continue

                try:
                    file_resp = await client.get(
                        attachment_url, headers=self._auth_header
                    )
                    file_resp.raise_for_status()
                    content_bytes = file_resp.content

                    text_content = self.extractor.extract_text(filename, content_bytes)
                    text_content = (text_content or "").strip()

                    if not text_content:
                        logger.warning(
                            "Skipping empty extracted document | work_item_id=%s | filename=%s",
                            work_item_id,
                            filename,
                        )
                        continue

                    doc_type = self._classify_document(filename, text_content)

                    documents.append(
                        WorkItemDocument(
                            filename=filename,
                            content=text_content,
                            doc_type=doc_type,
                            url=attachment_url,
                        )
                    )

                    logger.info(
                        "Attachment processed | work_item_id=%s | filename=%s | doc_type=%s | chars=%s",
                        work_item_id,
                        filename,
                        doc_type,
                        len(text_content),
                    )

                except Exception as exc:
                    logger.warning(
                        "Failed to process attachment | work_item_id=%s | filename=%s | error=%s",
                        work_item_id,
                        filename,
                        exc,
                    )

        documents.sort(
            key=lambda d: self._doc_type_rank(getattr(d, "doc_type", "other"))
        )
        return documents

    def _doc_type_rank(self, doc_type: str) -> int:
        order = {
            "sow": 0,
            "mom": 1,
            "transcript": 2,
            "other": 3,
        }
        return order.get((doc_type or "other").lower(), 9)

    def _classify_document(self, filename: str, content: str) -> str:
        name_lower = (filename or "").lower()
        content_lower = (content or "").lower()

        if any(
            k in name_lower for k in ["sow", "statement_of_work", "statement-of-work"]
        ):
            return "sow"
        if any(k in name_lower for k in ["mom", "minutes", "meeting"]):
            return "mom"
        if any(k in name_lower for k in ["transcript", "recording", "call"]):
            return "transcript"

        sow_keywords = [
            "scope of work",
            "deliverables",
            "statement of work",
            "project scope",
            "solution scope",
        ]
        mom_keywords = [
            "minutes of meeting",
            "action items",
            "attendees",
            "discussion points",
            "next steps",
        ]
        transcript_keywords = [
            "transcript",
            "[00:",
            "speaker",
            "host:",
            "participant",
        ]

        sow_score = sum(1 for k in sow_keywords if k in content_lower)
        mom_score = sum(1 for k in mom_keywords if k in content_lower)
        transcript_score = sum(1 for k in transcript_keywords if k in content_lower)

        max_score = max(sow_score, mom_score, transcript_score)
        if max_score <= 0:
            return "other"
        if sow_score == max_score:
            return "sow"
        if mom_score == max_score:
            return "mom"
        return "transcript"

    async def upload_frd_to_work_item(self, work_item_id: int, frd_path: Path) -> None:
        """
        Uploads the generated FRD .docx as an Azure DevOps attachment
        and links it to the Work Item.
        """
        if not frd_path.exists():
            raise FileNotFoundError(f"FRD file not found: {frd_path}")

        file_name = frd_path.name

        async with httpx.AsyncClient(timeout=90) as client:
            with open(frd_path, "rb") as file_obj:
                file_data = file_obj.read()

            upload_headers = {
                **self._auth_header,
                "Content-Type": "application/octet-stream",
            }

            upload_resp = await client.post(
                self._attachment_upload_url(file_name),
                headers=upload_headers,
                content=file_data,
            )
            upload_resp.raise_for_status()

            attachment = upload_resp.json()
            attachment_url = attachment["url"]

            patch_headers = {
                **self._auth_header,
                "Content-Type": "application/json-patch+json",
            }

            patch_body = [
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {
                        "rel": "AttachedFile",
                        "url": attachment_url,
                        "attributes": {
                            "comment": self.GENERATED_FRD_COMMENT,
                            "name": file_name,
                        },
                    },
                }
            ]

            patch_resp = await client.patch(
                self._work_item_url(work_item_id, expand_relations=False),
                headers=patch_headers,
                json=patch_body,
            )
            patch_resp.raise_for_status()

        logger.info(
            "FRD uploaded and linked | work_item_id=%s | file_name=%s",
            work_item_id,
            file_name,
        )
