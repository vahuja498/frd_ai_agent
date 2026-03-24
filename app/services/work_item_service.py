"""
Work Item Service
Interacts with Azure DevOps REST API to:
  - Detect 'presales' tag on Work Items
  - Fetch attached documents (SOW, MOM, Transcripts)
  - Upload the generated FRD back to the Work Item
"""

import logging
import base64
from pathlib import Path
from typing import List

import httpx

from app.models.webhook_payload import AzureDevOpsWebhookPayload, WorkItemDocument
from app.utils.document_extractor import DocumentExtractor
from app.config import settings

logger = logging.getLogger(__name__)


class WorkItemService:
    def __init__(self):
        self.org_url = settings.ADO_ORG_URL.rstrip("/")
        self.project = settings.ADO_PROJECT
        self.pat = settings.ADO_PAT
        self._auth_header = self._build_auth_header()
        self.extractor = DocumentExtractor()

    def _build_auth_header(self) -> dict:
        if not self.pat:
            raise ValueError("ADO_PAT is missing")

        token = base64.b64encode(f":{self.pat}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }

    async def has_generated_frd(self, work_item_id: int) -> bool:
        """
        Returns True if an auto-generated FRD is already attached to the work item.
        This prevents infinite webhook loops.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            wi_url = (
                f"{self.org_url}/{settings.ADO_PROJECT_ENCODED}/_apis/wit/workitems/{work_item_id}"
                f"?$expand=relations&api-version=7.1"
            )

            resp = await client.get(wi_url, headers=self._auth_header)
            resp.raise_for_status()

            work_item = resp.json()

            for rel in work_item.get("relations", []):
                if rel.get("rel") != "AttachedFile":
                    continue

                attrs = rel.get("attributes", {}) or {}
                name = (attrs.get("name") or "").lower()
                comment = (attrs.get("comment") or "").lower()

                if "frd" in name:
                    return True

                if "auto-generated frd" in comment:
                    return True

        return False

    def is_presales_tagged(self, payload: AzureDevOpsWebhookPayload) -> bool:
        """
        Checks whether the Work Item payload contains the 'presales' tag.
        Handles both workitem.created/updated events.
        """
        resource = payload.resource or {}

        fields = resource.get("fields", {}) or {}
        tags_str = (
            fields.get("System.Tags", "")
            or fields.get("System.Tags;", "")
            or resource.get("tags", "")
            or ""
        )

        if tags_str:
            tags = [t.strip().lower() for t in tags_str.split(";") if t.strip()]
            if "presales" in tags:
                return True

        revision = resource.get("revision", {}) or {}
        rev_fields = revision.get("fields", {}) or {}
        rev_tags = rev_fields.get("System.Tags", "") or ""
        if rev_tags:
            tags = [t.strip().lower() for t in rev_tags.split(";") if t.strip()]
            if "presales" in tags:
                return True

        return False

    async def fetch_work_item_documents(
        self, work_item_id: int
    ) -> List[WorkItemDocument]:
        """
        Fetches all attachments from the Work Item and extracts text content.
        Categorizes documents as sow, mom, transcript, or other.
        """
        documents: List[WorkItemDocument] = []

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            wi_url = (
                f"{self.org_url}/{settings.ADO_PROJECT_ENCODED}/_apis/wit/workitems/{work_item_id}"
                f"?$expand=relations&api-version=7.1"
            )

            resp = await client.get(wi_url, headers=self._auth_header)
            resp.raise_for_status()

            work_item = resp.json()
            relations = work_item.get("relations", []) or []
            logger.warning(
                f"Found {len(relations)} relations on Work Item #{work_item_id}"
            )

            for relation in relations:
                rel_type = relation.get("rel", "")
                if rel_type != "AttachedFile":
                    continue

                attachment_url = relation.get("url")
                if not attachment_url:
                    logger.warning("Skipping attachment relation with missing URL")
                    continue

                attrs = relation.get("attributes", {}) or {}
                filename = attrs.get("name", "unknown.bin")

                logger.warning(f"Downloading attachment: {filename}")

                try:
                    file_resp = await client.get(
                        attachment_url, headers=self._auth_header
                    )
                    file_resp.raise_for_status()
                    content_bytes = file_resp.content

                    text_content = self.extractor.extract_text(filename, content_bytes)
                    doc_type = self._classify_document(filename, text_content or "")

                    documents.append(
                        WorkItemDocument(
                            filename=filename,
                            content=text_content or "",
                            doc_type=doc_type,
                            url=attachment_url,
                        )
                    )

                    logger.warning(
                        f"Extracted document: {filename} → type={doc_type}, chars={len(text_content or '')}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to process attachment {filename}: {e}")

        return documents

    def _classify_document(self, filename: str, content: str) -> str:
        """Classify document type based on filename and content keywords."""
        name_lower = filename.lower()
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
            "payment terms",
            "statement of work",
        ]
        mom_keywords = [
            "minutes of meeting",
            "attendees",
            "action items",
            "meeting date",
        ]
        transcript_keywords = ["speaker", "00:", "transcript", "[00:", "host:"]

        sow_score = sum(1 for k in sow_keywords if k in content_lower)
        mom_score = sum(1 for k in mom_keywords if k in content_lower)
        transcript_score = sum(1 for k in transcript_keywords if k in content_lower)

        max_score = max(sow_score, mom_score, transcript_score)
        if max_score == 0:
            return "other"
        if sow_score == max_score:
            return "sow"
        if mom_score == max_score:
            return "mom"
        return "transcript"

    async def upload_frd_to_work_item(self, work_item_id: int, frd_path: Path) -> None:
        """Uploads the generated FRD .docx file as an attachment to the Work Item."""
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            upload_url = (
                f"{self.org_url}/{settings.ADO_PROJECT_ENCODED}/_apis/wit/attachments"
                f"?fileName={frd_path.name}&api-version=7.1"
            )

            with open(frd_path, "rb") as f:
                file_data = f.read()

            upload_headers = {
                **self._auth_header,
                "Content-Type": "application/octet-stream",
            }

            resp = await client.post(
                upload_url, headers=upload_headers, content=file_data
            )
            resp.raise_for_status()

            attachment = resp.json()
            attachment_url = attachment["url"]

            patch_url = (
                f"{self.org_url}/{settings.ADO_PROJECT_ENCODED}/_apis/wit/workitems/{work_item_id}"
                f"?api-version=7.1"
            )

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
                            "comment": "Auto-generated FRD by FRD AI Agent",
                            "name": frd_path.name,
                        },
                    },
                }
            ]

            resp2 = await client.patch(
                patch_url,
                headers=patch_headers,
                json=patch_body,
            )
            resp2.raise_for_status()

            logger.warning(f"✅ FRD uploaded and linked to Work Item #{work_item_id}")
