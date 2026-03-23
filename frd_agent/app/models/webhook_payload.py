"""
Pydantic models for Azure DevOps Webhook Payload
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class AzureDevOpsWebhookPayload(BaseModel):
    subscriptionId: Optional[str] = None
    notificationId: Optional[int] = None
    id: Optional[str] = None
    eventType: str
    publisherId: Optional[str] = None
    message: Optional[Dict[str, Any]] = None
    detailedMessage: Optional[Dict[str, Any]] = None
    resource: Dict[str, Any] = Field(default_factory=dict)
    resourceVersion: Optional[str] = None
    resourceContainers: Optional[Dict[str, Any]] = None
    createdDate: Optional[str] = None


class WorkItemDocument(BaseModel):
    """Represents a document attachment from a Work Item"""
    filename: str
    content: str  # Extracted text content
    doc_type: str  # "sow", "mom", "transcript", "other"
    url: Optional[str] = None


class FRDSection(BaseModel):
    title: str
    content: str


class FRDDocument(BaseModel):
    work_item_id: int
    title: str
    sections: List[FRDSection]
    generated_at: str
