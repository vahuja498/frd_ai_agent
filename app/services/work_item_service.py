from __future__ import annotations

import base64
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, List

import httpx

from app.config import settings
from app.models.webhook_payload import WorkItemDocument
from app.utils.document_extractor import DocumentExtractor

logger = logging.getLogger(__name__)


class WorkItemService:
    SUPPORTED_EXTENSIONS = {".docx", ".doc", ".pdf", ".txt", ".md", ".rtf"}
    GENERATED_FRD_COMMENT = "Auto-generated FRD by FRD AI Agent"

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self) -> None:
        self.org_url = settings.ADO_ORG_URL.rstrip("/")
        self.project = settings.ADO_PROJECT.strip()
        self.project_encoded = settings.ADO_PROJECT_ENCODED
        self.pat = settings.ADO_PAT.strip()

        self._validate_config()
        self._auth_header = self._build_auth_header()
        self.extractor = DocumentExtractor()

    # -------------------------------
    # Config
    # -------------------------------
    def _validate_config(self) -> None:
        missing = []
        if not self.org_url:
            missing.append("ADO_ORG_URL")
        if not self.project:
            missing.append("ADO_PROJECT")
        if not self.pat:
            missing.append("ADO_PAT")

        if missing:
            raise ValueError(f"Missing Azure DevOps config: {', '.join(missing)}")

    def _build_auth_header(self) -> Dict[str, str]:
        token = base64.b64encode(f":{self.pat}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }

    # -------------------------------
    # HTTP RETRY WRAPPER
    # -------------------------------
    async def _request_with_retry(self, method, url, client, **kwargs):
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.exception("HTTP request failed after retries | url=%s", url)
                    raise

                logger.warning(
                    "Retry %s/%s failed | url=%s | error=%s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                    str(e),
                )
                await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))

    # -------------------------------
    # URL BUILDERS
    # -------------------------------
    def _work_item_url(self, work_item_id: int, expand=False) -> str:
        suffix = "?api-version=7.1"
        if expand:
            suffix = "?$expand=relations&api-version=7.1"

        return f"{self.org_url}/{self.project_encoded}/_apis/wit/workitems/{work_item_id}{suffix}"

    def _attachment_upload_url(self, filename: str) -> str:
        return f"{self.org_url}/{self.project_encoded}/_apis/wit/attachments?fileName={filename}&api-version=7.1"

    # -------------------------------
    # FRD EXISTS CHECK
    # -------------------------------
    async def has_generated_frd(self, work_item_id: int) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._request_with_retry(
                "GET",
                self._work_item_url(work_item_id, expand=True),
                client,
                headers=self._auth_header,
            )

            work_item = resp.json()

        for rel in work_item.get("relations", []) or []:
            if rel.get("rel") != "AttachedFile":
                continue

            attrs = rel.get("attributes", {}) or {}
            name = attrs.get("name", "").lower()
            comment = attrs.get("comment", "").lower()

            if (
                name.startswith("frd_wi")
                or self.GENERATED_FRD_COMMENT.lower() in comment
            ):
                return True

        return False

    # -------------------------------
    # FETCH DOCUMENTS
    # -------------------------------
    async def fetch_work_item_documents(
        self, work_item_id: int
    ) -> List[WorkItemDocument]:
        documents: List[WorkItemDocument] = []

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await self._request_with_retry(
                "GET",
                self._work_item_url(work_item_id, expand=True),
                client,
                headers=self._auth_header,
            )

            work_item = resp.json()
            relations = work_item.get("relations", []) or []

            for relation in relations:
                if relation.get("rel") != "AttachedFile":
                    continue

                attrs = relation.get("attributes", {})
                filename = attrs.get("name", "unknown.bin")
                url = relation.get("url")

                ext = Path(filename).suffix.lower()
                if ext not in self.SUPPORTED_EXTENSIONS:
                    continue

                try:
                    file_resp = await self._request_with_retry(
                        "GET", url, client, headers=self._auth_header
                    )

                    content_bytes = file_resp.content
                    text = self.extractor.extract_text(filename, content_bytes).strip()

                    if not text:
                        continue

                    documents.append(
                        WorkItemDocument(
                            filename=filename,
                            content=text,
                            doc_type=self._classify_document(filename, text),
                            url=url,
                        )
                    )

                except Exception:
                    logger.exception(
                        "Failed to process attachment | work_item_id=%s | file=%s",
                        work_item_id,
                        filename,
                    )

        return sorted(documents, key=lambda d: self._doc_type_rank(d.doc_type))

    # -------------------------------
    # UPLOAD FRD
    # -------------------------------
    async def upload_frd_to_work_item(self, work_item_id: int, frd_path: Path) -> None:
        if not frd_path.exists():
            raise FileNotFoundError(f"FRD file not found: {frd_path}")

        async with httpx.AsyncClient(timeout=60) as client:
            with open(frd_path, "rb") as f:
                data = f.read()

            upload_resp = await self._request_with_retry(
                "POST",
                self._attachment_upload_url(frd_path.name),
                client,
                headers={
                    **self._auth_header,
                    "Content-Type": "application/octet-stream",
                },
                content=data,
            )

            attachment_url = upload_resp.json()["url"]

            patch_body = [
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {
                        "rel": "AttachedFile",
                        "url": attachment_url,
                        "attributes": {
                            "comment": self.GENERATED_FRD_COMMENT,
                            "name": frd_path.name,
                        },
                    },
                }
            ]

            await self._request_with_retry(
                "PATCH",
                self._work_item_url(work_item_id),
                client,
                headers={
                    **self._auth_header,
                    "Content-Type": "application/json-patch+json",
                },
                json=patch_body,
            )

        logger.info("FRD uploaded successfully | work_item_id=%s", work_item_id)

    # -------------------------------
    # HELPERS
    # -------------------------------
    def _doc_type_rank(self, doc_type: str) -> int:
        return {"sow": 0, "mom": 1, "transcript": 2}.get(doc_type, 9)

    def _classify_document(self, filename: str, content: str) -> str:
        name = filename.lower()
        content = content.lower()

        if "sow" in name:
            return "sow"
        if "mom" in name:
            return "mom"
        if "transcript" in name:
            return "transcript"

        return "other"
