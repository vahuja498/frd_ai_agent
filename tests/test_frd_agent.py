"""
Unit Tests for FRD AI Agent
Run: pytest tests/ -v
"""

import pytest
from app.models.webhook_payload import AzureDevOpsWebhookPayload
from app.services.work_item_service import WorkItemService
from app.utils.document_extractor import DocumentExtractor


class TestPresalesTagDetection:
    def setup_method(self):
        import os

        os.environ.setdefault("ADO_ORG_URL", "https://dev.azure.com/test")
        os.environ.setdefault("ADO_PROJECT", "test")
        os.environ.setdefault("ADO_PAT", "test")
        os.environ.setdefault("HF_API_TOKEN", "test")
        self.service = WorkItemService()

    def _make_payload(self, tags: str, event: str = "workitem.updated"):
        return AzureDevOpsWebhookPayload(
            eventType=event,
            resource={
                "id": 42,
                "fields": {"System.Tags": tags},
            },
        )

    def test_detects_presales_tag(self):
        payload = self._make_payload("presales; client-review")
        assert self.service.is_presales_tagged(payload) is True

    def test_case_insensitive(self):
        payload = self._make_payload("PreSales; other")
        assert self.service.is_presales_tagged(payload) is True

    def test_no_presales_tag(self):
        payload = self._make_payload("in-progress; review")
        assert self.service.is_presales_tagged(payload) is False

    def test_empty_tags(self):
        payload = self._make_payload("")
        assert self.service.is_presales_tagged(payload) is False


class TestDocumentExtractor:
    def setup_method(self):
        self.extractor = DocumentExtractor()

    def test_extract_txt(self):
        content = b"Hello, this is a test document."
        result = self.extractor.extract_text("test.txt", content)
        assert "Hello" in result

    def test_extract_unsupported_falls_back(self):
        content = b"some bytes"
        result = self.extractor.extract_text("file.xyz", content)
        assert isinstance(result, str)

    def test_document_classification(self):
        from app.services.work_item_service import WorkItemService
        import os

        os.environ.setdefault("ADO_ORG_URL", "https://dev.azure.com/test")
        os.environ.setdefault("ADO_PROJECT", "test")
        os.environ.setdefault("ADO_PAT", "test")
        os.environ.setdefault("HF_API_TOKEN", "test")
        svc = WorkItemService()

        assert svc._classify_document("SOW_v2.docx", "") == "sow"
        assert svc._classify_document("MOM_kickoff.docx", "") == "mom"
        assert svc._classify_document("call_transcript.txt", "") == "transcript"
        assert svc._classify_document("presentation.pptx", "") == "other"
