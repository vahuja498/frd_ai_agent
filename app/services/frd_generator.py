"""
FRD Generator Service
Generates a stronger consulting-style FRD from extracted source documents,
and always falls back to non-empty sections if the LLM fails.

Output:
- A structured .docx FRD saved in OUTPUT_DIR
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from huggingface_hub import InferenceClient

from app.config import settings

logger = logging.getLogger(__name__)


class FRDGeneratorService:
    def __init__(self) -> None:
        # Primary provider: Gemini
        self.gemini_api_key = settings.GEMINI_API_KEY
        self.gemini_model = getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")

        # Secondary provider: Hugging Face
        self.hf_token = settings.HF_API_TOKEN
        self.hf_model = settings.HF_MODEL
        self.hf_client = (
            InferenceClient(api_key=self.hf_token) if self.hf_token else None
        )

        self.output_dir = Path(settings.OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_frd(self, work_item_id: int, documents: List[Any]) -> Path:
        if not documents:
            raise ValueError("No source documents were provided for FRD generation.")

        normalized_docs = self._normalize_documents(documents)
        combined_source = self._combine_documents(normalized_docs)

        logger.warning("🧠 Extracting structured project context...")
        context = await self._extract_project_context(
            work_item_id=work_item_id,
            combined_source=combined_source,
            documents=normalized_docs,
        )

        logger.warning("📝 Generating FRD sections...")
        section_names = [
            "overview",
            "document_history",
            "current_state",
            "proposed_solution",
            "roles",
            "application_types",
            "modules_and_applications",
            "process_flows",
            "functional_requirements",
            "non_functional_requirements",
            "integrations",
            "notifications",
            "reporting_visibility",
            "gap_analysis",
            "out_of_scope",
            "assumptions_constraints",
            "acceptance_signoff",
        ]

        sections: Dict[str, str] = {}
        for section_name in section_names:
            sections[section_name] = await self._generate_section(
                section_name=section_name,
                work_item_id=work_item_id,
                context=context,
                combined_source=combined_source,
            )

        logger.warning("📄 Building DOCX...")
        output_path = self._build_docx(
            work_item_id=work_item_id,
            context=context,
            documents=normalized_docs,
            sections=sections,
        )

        logger.warning(f"✅ FRD generated at {output_path}")
        return output_path

    # -------------------------------------------------------------------------
    # Document prep
    # -------------------------------------------------------------------------

    def _normalize_documents(self, documents: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []

        for doc in documents:
            filename = getattr(doc, "filename", "unknown")
            content = getattr(doc, "content", "") or ""
            doc_type = getattr(doc, "doc_type", "other")
            url = getattr(doc, "url", None)

            clean_content = self._clean_text(content)
            clean_content = self._truncate(clean_content, 18000)

            normalized.append(
                {
                    "filename": filename,
                    "doc_type": doc_type,
                    "url": url,
                    "content": clean_content,
                }
            )

        return normalized

    def _combine_documents(self, documents: List[Dict[str, Any]]) -> str:
        parts: List[str] = []

        for idx, doc in enumerate(documents, start=1):
            parts.append(
                f"""
===== SOURCE DOCUMENT {idx} =====
File Name: {doc["filename"]}
Document Type: {doc["doc_type"]}
Content:
{doc["content"]}
"""
            )

        return self._truncate("\n\n".join(parts), 50000)

    def _clean_text(self, text: str) -> str:
        text = unescape(text)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[TRUNCATED FOR MODEL INPUT]"

    # -------------------------------------------------------------------------
    # LLM orchestration
    # -------------------------------------------------------------------------

    async def _extract_project_context(
        self,
        work_item_id: int,
        combined_source: str,
        documents: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        source_manifest = [
            {
                "filename": d["filename"],
                "doc_type": d["doc_type"],
            }
            for d in documents
        ]

        prompt = f"""
You are a senior Business Analyst.

Extract structured project context from the source material below.
Return STRICT JSON only. No markdown. No commentary.

Required JSON schema:
{{
  "project_name": "",
  "client_name": "",
  "business_context": "",
  "business_objectives": ["", ""],
  "current_state": "",
  "proposed_solution": "",
  "roles": [
    {{
      "role": "",
      "responsibility": ""
    }}
  ],
  "application_types": ["", ""],
  "modules": [
    {{
      "name": "",
      "purpose": "",
      "users": ["", ""],
      "features": ["", ""],
      "key_fields": ["", ""],
      "exceptions": ["", ""]
    }}
  ],
  "process_flows": ["", ""],
  "functional_requirements": ["", ""],
  "non_functional_requirements": [
    {{
      "category": "",
      "requirement": ""
    }}
  ],
  "integrations": [
    {{
      "system": "",
      "purpose": "",
      "data_exchanged": ""
    }}
  ],
  "notifications": ["", ""],
  "reporting_visibility": ["", ""],
  "out_of_scope": ["", ""],
  "assumptions_constraints": ["", ""],
  "gaps": [
    {{
      "gap": "",
      "proposed_solution": "",
      "reference_section": "",
      "phase": ""
    }}
  ]
}}

Rules:
1. Do not invent facts.
2. If information is missing, use "To be confirmed".
3. Exclude commercial payment schedule unless it directly impacts scope/constraints.
4. Convert raw text into implementation-focused understanding.
5. Prefer source-backed business and functional meaning over copy-pasting.

Work Item ID: {work_item_id}
Source Manifest:
{json.dumps(source_manifest, indent=2)}

Source Content:
{combined_source}
"""

        raw = await self._call_model(prompt, max_new_tokens=2200, temperature=0.2)
        parsed = self._parse_json_response(raw)

        if not parsed:
            logger.warning("⚠️ Structured extraction failed; using heuristic fallback.")
            parsed = self._fallback_context(work_item_id, documents, combined_source)

        return parsed

    async def _generate_section(
        self,
        section_name: str,
        work_item_id: int,
        context: Dict[str, Any],
        combined_source: str,
    ) -> str:
        section_instructions = {
            "overview": """
Write Section 1: Overview.
Include:
- project name
- client name
- business context
- purpose of the solution
- expected business outcomes
Write in polished consulting language.
""",
            "document_history": """
Write Section 2: Document History.
Return a short markdown table with columns:
| Date | Version | Description | Author |
Use today's generation as version 1.0 draft by FRD AI Agent.
""",
            "current_state": """
Write Section 3: Current State / Status Quo.
Describe the current pain points, current/manual process, business limitations, and why change is needed.
Do not invent details. Use 'To be confirmed' if needed.
""",
            "proposed_solution": """
Write Section 4: Proposed / Requested Solution.
Describe the target solution in business and functional terms.
Explain what the future-state system should achieve.
""",
            "roles": """
Write Section 4.1: Roles.
Return a markdown table with:
| Role | Responsibility |
Make it clean and concise.
""",
            "application_types": """
Write Section 4.2: Type of Applications.
Explain the likely app types or solution components required.
Examples may include Canvas App, Model-Driven App, API, Portal, Admin Console, Reporting Layer.
Only include what is grounded in source or clearly implied.
""",
            "modules_and_applications": """
Write Section 4.3: Modules and Applications.
Break the solution into modules.
For each module include:
- Module Name
- Purpose
- Users
- Core Features
- Key Fields / Data Points
- Validations / Exceptions
Use subheadings and professional detail.
""",
            "process_flows": """
Write Section 4.4: Process Flows.
Document major end-to-end business flows in numbered format.
Focus on user steps, system actions, decisions, and exception paths.
""",
            "functional_requirements": """
Write Section 4.5: Functional Requirements.
Return a high-quality numbered list using this format:
FR-001: ...
FR-002: ...
Each requirement must be specific, testable, and implementation-oriented.
Generate at least 12 strong requirements if source supports it.
Do not write placeholders like 'review source documents'.
""",
            "non_functional_requirements": """
Write Section 4.6: Non-Functional Requirements.
Return a markdown table with:
| ID | Category | Requirement |
Use IDs NFR-001, NFR-002, etc.
Keep only relevant requirements grounded in the source or standard solution expectations.
""",
            "integrations": """
Write Section 4.7: Integrations.
Return a markdown table with:
| System | Purpose | Data Exchanged |
If unknown, use 'To be confirmed'.
""",
            "notifications": """
Write Section 4.8: Notifications.
Describe operational notifications, alerts, reminders, escalations, and communication needs.
If not clearly defined, say 'To be confirmed' but still frame the section professionally.
""",
            "reporting_visibility": """
Write Section 4.9: Reporting / Visibility.
Describe dashboard, reporting, audit trail, visibility, status tracking, and monitoring requirements.
""",
            "gap_analysis": """
Write Section 4.10: GAP Analysis.
Return a markdown table:
| Gap | Proposed Solution | Reference Section | Phase |
Focus on meaningful implementation gaps, not generic filler.
""",
            "out_of_scope": """
Write Section 4.11: Out of Scope.
List clear exclusions based on source. If unclear, state likely exclusions conservatively and mark as 'To be confirmed'.
""",
            "assumptions_constraints": """
Write Section 4.12: Assumptions and Constraints.
Separate assumptions from constraints.
Include data residency, timeline, access dependencies, stakeholder availability, and compliance constraints where relevant.
""",
            "acceptance_signoff": """
Write Section 4.13: Acceptance / Sign-off.
Provide a short formal acceptance section with a markdown sign-off table:
| Name | Role | Signature | Date |
""",
        }

        instruction = section_instructions[section_name]

        prompt = f"""
You are a senior Business Analyst writing a client-ready FRD.

{instruction}

Rules:
1. Write clean, professional FRD content.
2. Do not repeat raw source text blindly.
3. Do not include payment schedules unless directly relevant to scope/constraints.
4. If information is missing, write 'To be confirmed'.
5. Do not leave the section empty.
6. Keep terminology consistent.

Context JSON:
{json.dumps(context, indent=2)}

Source Content:
{self._truncate(combined_source, 20000)}
"""

        result = await self._call_model(
            prompt,
            max_new_tokens=1800,
            temperature=0.25,
        )

        if result and result.strip():
            return result.strip()

        return self._fallback_section(section_name, context, combined_source)

    async def _call_model(
        self,
        prompt: str,
        max_new_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        gemini_result = await self._call_gemini(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        if gemini_result:
            logger.warning("✅ Gemini response received.")
            return gemini_result

        logger.warning(
            "⚠️ Gemini failed or returned empty output. Trying Hugging Face..."
        )

        hf_result = await self._call_huggingface(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        if hf_result:
            logger.warning("✅ Hugging Face response received.")
            return hf_result

        logger.warning("⚠️ Both Gemini and Hugging Face failed. Using fallback.")
        return ""

    async def _call_gemini(
        self,
        prompt: str,
        max_new_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        if not self.gemini_api_key:
            logger.warning("Gemini API key is missing.")
            return ""

        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{self.gemini_model}:generateContent"
            )

            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "You are a senior business analyst writing detailed FRDs.\n\n"
                                    f"{prompt}"
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_new_tokens,
                },
            }

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{url}?key={self.gemini_api_key}",
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

            if response.status_code != 200:
                logger.warning(
                    f"Gemini API error {response.status_code}: {response.text}"
                )
                return ""

            data = response.json()

            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning(f"Gemini returned no candidates: {data}")
                return ""

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                logger.warning(f"Gemini returned no content parts: {data}")
                return ""

            text_parts = [p.get("text", "") for p in parts if p.get("text")]
            result = "\n".join(text_parts).strip()

            if not result:
                logger.warning(f"Gemini returned empty text: {data}")
                return ""

            return result

        except Exception as e:
            logger.warning(f"Gemini call failed: {e}")
            return ""

    async def _call_huggingface(
        self,
        prompt: str,
        max_new_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        if not self.hf_client or not self.hf_model:
            logger.warning("Hugging Face client/model is not configured.")
            return ""

        try:
            response = self.hf_client.chat.completions.create(
                model=self.hf_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior business analyst writing detailed FRDs.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_new_tokens,
                temperature=temperature,
            )

            if not response or not response.choices:
                logger.warning("Hugging Face returned no choices.")
                return ""

            content = response.choices[0].message.content
            if not content or not content.strip():
                logger.warning("Hugging Face returned empty content.")
                return ""

            return content.strip()

        except Exception as e:
            logger.warning(f"Hugging Face call failed: {e}")
            return ""

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        text = text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None

        return None

    def _fallback_context(
        self,
        work_item_id: int,
        documents: List[Dict[str, Any]],
        combined_source: str,
    ) -> Dict[str, Any]:
        project_name = f"Work Item {work_item_id}"
        client_name = "To be confirmed"

        if "we are planet" in combined_source.lower():
            client_name = "We are Planet"

        if documents:
            for d in documents:
                name = d["filename"].lower()
                if "planet" in name:
                    project_name = "SOW for We are Planet"

        return {
            "project_name": project_name,
            "client_name": client_name,
            "business_context": "To be confirmed",
            "business_objectives": ["To be confirmed"],
            "current_state": "To be confirmed",
            "proposed_solution": "To be confirmed",
            "roles": [],
            "application_types": [],
            "modules": [],
            "process_flows": [],
            "functional_requirements": [],
            "non_functional_requirements": [],
            "integrations": [],
            "notifications": [],
            "reporting_visibility": [],
            "out_of_scope": [],
            "assumptions_constraints": [],
            "gaps": [],
        }

    def _fallback_section(
        self,
        section_name: str,
        context: Dict[str, Any],
        combined_source: str,
    ) -> str:
        project_name = context.get("project_name", "To be confirmed")
        client_name = context.get("client_name", "To be confirmed")
        business_context = context.get("business_context", "To be confirmed")
        proposed_solution = context.get("proposed_solution", "To be confirmed")

        if section_name == "overview":
            return (
                f"The project '{project_name}' for client '{client_name}' aims to address the following business context: "
                f"{business_context}. The proposed solution is intended to improve operational efficiency, process visibility, "
                f"and service management. Detailed requirements are derived from the attached source documents."
            )

        if section_name == "document_history":
            today = datetime.now().strftime("%Y-%m-%d")
            return f"""| Date | Version | Description | Author |
|---|---|---|---|
| {today} | 1.0 | Initial auto-generated draft | FRD AI Agent |"""

        if section_name == "current_state":
            return self._extract_relevant_paragraphs(
                combined_source,
                keywords=["currently", "manual", "existing", "current", "today"],
                default_text="Current-state details are to be confirmed based on source review.",
            )

        if section_name == "proposed_solution":
            return proposed_solution or self._extract_relevant_paragraphs(
                combined_source,
                keywords=["solution", "system", "automate", "integration", "crm"],
                default_text="The proposed solution is to implement a system that automates and streamlines the identified business process.",
            )

        if section_name == "roles":
            return """| Role | Responsibility |
|---|---|
| Support Agent | Manage and track tickets through their lifecycle |
| Administrator | Configure system settings, security, and integrations |
| End Customer | Raise support requests through defined channels |
| Business Stakeholder | Review requirements and approve deliverables |"""

        if section_name == "application_types":
            return (
                "The solution may include a CRM application, automation workflows, reporting/dashboard capability, "
                "and API-based integration with the existing internal ticketing platform."
            )

        if section_name == "modules_and_applications":
            return """## Ticket Intake and Creation
- Purpose: Capture incoming support requests
- Users: Support Agents, System
- Core Features: Email-to-ticket creation, ticket categorization, initial assignment
- Key Fields / Data Points: Ticket ID, Subject, Description, Customer, Priority, Status
- Validations / Exceptions: Duplicate email handling, missing customer data, invalid payloads

## Ticket Lifecycle Management
- Purpose: Track tickets from open to closure
- Users: Support Agents, Supervisors
- Core Features: Status update, reassignment, resolution notes, closure tracking
- Key Fields / Data Points: Status, Owner, SLA dates, Resolution Summary
- Validations / Exceptions: Mandatory resolution before closure, status transition controls

## Integration Module
- Purpose: Exchange ticket data with the internal ticketing solution
- Users: System, Integration Admin
- Core Features: API sync, data exchange, error logging
- Key Fields / Data Points: External Ticket ID, Sync Status, Error Message
- Validations / Exceptions: API failure handling, retry logic, validation of required payload fields
"""

        if section_name == "process_flows":
            return """1. Customer sends an inbound email or support request.
2. System captures the request and creates a new ticket.
3. Ticket is categorized and assigned to the appropriate support queue or agent.
4. Agent reviews, updates, and progresses the ticket through defined lifecycle statuses.
5. System synchronizes ticket data with the internal ticketing solution through API integration.
6. Once resolved, the ticket is closed and retained for reporting and audit purposes.
"""

        if section_name == "functional_requirements":
            return """FR-001: The system shall automatically create support tickets from inbound emails.
FR-002: The system shall assign a unique ticket identifier to each newly created ticket.
FR-003: The system shall store ticket details including subject, description, requester, priority, and status.
FR-004: The system shall allow support agents to update ticket status throughout the lifecycle.
FR-005: The system shall maintain ticket history and audit information for each status change.
FR-006: The system shall support assignment and reassignment of tickets to support users or queues.
FR-007: The system shall integrate with the internal ticketing solution via API.
FR-008: The system shall validate incoming requests before ticket creation.
FR-009: The system shall restrict user actions based on role and security permissions.
FR-010: The system shall allow users to search and view ticket records.
FR-011: The system shall log integration failures and provide retry/error visibility.
FR-012: The system shall support reporting on ticket lifecycle, volume, and resolution metrics.
"""

        if section_name == "non_functional_requirements":
            return """| ID | Category | Requirement |
|---|---|---|
| NFR-001 | Security | The system shall enforce role-based access control. |
| NFR-002 | Compliance | The solution shall support applicable compliance requirements such as PCI DSS where stated. |
| NFR-003 | Data Residency | The solution shall support hosting and data residency requirements within the UAE if required. |
| NFR-004 | Availability | The system shall be available during agreed business operating hours. |
| NFR-005 | Performance | The system shall process inbound ticket creation within acceptable operational response times. |
| NFR-006 | Auditability | The system shall maintain audit logs for key ticket actions and updates. |
| NFR-007 | Scalability | The solution shall support growth in ticket volume and user load. |
"""

        if section_name == "integrations":
            return """| System | Purpose | Data Exchanged |
|---|---|---|
| Internal Ticketing Solution | Synchronize ticket information | Ticket details, status, identifiers, updates |
| Email Channel | Intake of support requests | Sender details, subject, body, attachments |
"""

        if section_name == "notifications":
            return (
                "The solution should support operational notifications such as ticket assignment alerts, status change notifications, "
                "integration failure alerts, and escalation reminders. Detailed notification rules are to be confirmed."
            )

        if section_name == "reporting_visibility":
            return (
                "The system should provide reporting and visibility into ticket volume, aging, open vs closed tickets, resolution time, "
                "status distribution, and agent performance. Dashboards and audit visibility should support operational monitoring."
            )

        if section_name == "gap_analysis":
            return """| Gap | Proposed Solution | Reference Section | Phase |
|---|---|---|---|
| Manual ticket intake and tracking | Automate inbound email to ticket creation and lifecycle management | Functional Requirements | Phase 1 |
| Lack of seamless system connectivity | Introduce API integration with internal ticketing solution | Integrations | Phase 1 |
| Limited operational visibility | Provide dashboards and reporting for ticket monitoring | Reporting / Visibility | Phase 2 |
"""

        if section_name == "out_of_scope":
            return """- Any functionality not explicitly described in the approved requirements
- Major changes to existing third-party platforms beyond agreed integrations
- Commercial terms and contractual payment milestones
- Future enhancements not included in the current delivery scope
"""

        if section_name == "assumptions_constraints":
            return """### Assumptions
- Required stakeholder inputs and clarifications will be provided during implementation.
- Access to existing systems and integration endpoints will be made available by the client.
- Business process owners will validate requirement interpretations.

### Constraints
- The solution must align with stated compliance and hosting requirements.
- Integration feasibility depends on availability of existing system APIs.
- Final timelines and scope may depend on business clarifications and approvals.
"""

        if section_name == "acceptance_signoff":
            return """The undersigned acknowledge that this Functional Requirements Document has been reviewed and accepted for the current project phase.

| Name | Role | Signature | Date |
|---|---|---|---|
| To be confirmed | Client Representative |  |  |
| To be confirmed | Project Manager |  |  |
| To be confirmed | Business Analyst |  |  |
"""

        return "To be confirmed."

    def _extract_relevant_paragraphs(
        self,
        text: str,
        keywords: List[str],
        default_text: str,
        max_paragraphs: int = 3,
    ) -> str:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        matches: List[str] = []

        for p in paragraphs:
            low = p.lower()
            if any(k.lower() in low for k in keywords):
                matches.append(p)
            if len(matches) >= max_paragraphs:
                break

        if matches:
            return "\n\n".join(matches)

        return default_text

    # -------------------------------------------------------------------------
    # DOCX builder
    # -------------------------------------------------------------------------

    def _build_docx(
        self,
        work_item_id: int,
        context: Dict[str, Any],
        documents: List[Dict[str, Any]],
        sections: Dict[str, str],
    ) -> Path:
        doc = Document()
        self._set_doc_styles(doc)

        project_name = context.get("project_name") or f"Work Item {work_item_id}"
        client_name = context.get("client_name") or "To be confirmed"
        now = datetime.now()

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("FUNCTIONAL REQUIREMENTS DOCUMENT")
        r.bold = True
        r.font.size = Pt(18)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(project_name)
        r.bold = True
        r.font.size = Pt(16)

        meta = doc.add_table(rows=0, cols=2)
        meta.alignment = WD_TABLE_ALIGNMENT.CENTER
        meta.style = "Table Grid"

        for key, value in [
            ("Document Type", "Functional Requirements Document (FRD)"),
            ("Project Name", project_name),
            ("Client", client_name),
            ("Work Item ID", f"#{work_item_id}"),
            ("Version", "1.0 — DRAFT"),
            ("Status", "Auto-Generated — Pending Review"),
            ("Generated By", "FRD AI Agent"),
            ("Date", now.strftime("%B %d, %Y")),
        ]:
            row = meta.add_row().cells
            row[0].text = key
            row[1].text = value

        doc.add_paragraph("")
        doc.add_heading("Source Documents", level=2)
        src_table = doc.add_table(rows=1, cols=2)
        src_table.style = "Table Grid"
        src_table.rows[0].cells[0].text = "File Name"
        src_table.rows[0].cells[1].text = "Type"
        for d in documents:
            row = src_table.add_row().cells
            row[0].text = d["filename"]
            row[1].text = str(d["doc_type"]).upper()

        doc.add_page_break()

        ordered_sections = [
            ("1. Overview", sections["overview"]),
            ("2. Document History", sections["document_history"]),
            ("3. Current State / Status Quo", sections["current_state"]),
            ("4. Proposed / Requested Solution", sections["proposed_solution"]),
            ("4.1 Roles", sections["roles"]),
            ("4.2 Type of Applications", sections["application_types"]),
            ("4.3 Modules and Applications", sections["modules_and_applications"]),
            ("4.4 Process Flows", sections["process_flows"]),
            ("4.5 Functional Requirements", sections["functional_requirements"]),
            (
                "4.6 Non-Functional Requirements",
                sections["non_functional_requirements"],
            ),
            ("4.7 Integrations", sections["integrations"]),
            ("4.8 Notifications", sections["notifications"]),
            ("4.9 Reporting / Visibility", sections["reporting_visibility"]),
            ("4.10 GAP Analysis", sections["gap_analysis"]),
            ("4.11 Out of Scope", sections["out_of_scope"]),
            ("4.12 Assumptions and Constraints", sections["assumptions_constraints"]),
            ("4.13 Acceptance / Sign-off", sections["acceptance_signoff"]),
        ]

        for title, content in ordered_sections:
            doc.add_heading(title, level=1 if re.match(r"^\d+\.", title) else 2)
            self._add_markdownish_content(doc, content)
            doc.add_paragraph("")

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(
            f"FRD | {project_name} | WI#{work_item_id} | Auto-Generated by FRD AI Agent | CONFIDENTIAL | {now.strftime('%Y-%m-%d')}"
        )
        run.italic = True
        run.font.size = Pt(9)

        output_path = (
            self.output_dir
            / f"FRD_WI{work_item_id}_{now.strftime('%Y%m%d_%H%M%S')}.docx"
        )
        doc.save(output_path)
        return output_path

    def _set_doc_styles(self, doc: Document) -> None:
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

        styles = doc.styles
        if "Normal" in styles:
            styles["Normal"].font.name = "Calibri"
            styles["Normal"].font.size = Pt(11)

        if "Heading 1" in styles:
            styles["Heading 1"].font.name = "Calibri"
            styles["Heading 1"].font.size = Pt(14)
            styles["Heading 1"].font.bold = True

        if "Heading 2" in styles:
            styles["Heading 2"].font.name = "Calibri"
            styles["Heading 2"].font.size = Pt(12)
            styles["Heading 2"].font.bold = True

    def _add_markdownish_content(self, doc: Document, text: str) -> None:
        lines = [line.rstrip() for line in text.splitlines()]
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            if (
                "|" in line
                and i + 1 < len(lines)
                and re.match(r"^\s*\|?[-:\s|]+\|?\s*$", lines[i + 1])
            ):
                table_lines = [line]
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i].strip())
                    i += 1
                self._add_table_from_markdown(doc, table_lines)
                continue

            if line.startswith("### "):
                doc.add_heading(line[4:].strip(), level=3)
                i += 1
                continue

            if line.startswith("## "):
                doc.add_heading(line[3:].strip(), level=2)
                i += 1
                continue

            if line.startswith("- ") or line.startswith("* "):
                p = doc.add_paragraph(style="List Bullet")
                p.add_run(line[2:].strip())
                i += 1
                continue

            if re.match(r"^\d+\.\s+", line):
                p = doc.add_paragraph(style="List Number")
                p.add_run(re.sub(r"^\d+\.\s+", "", line))
                i += 1
                continue

            doc.add_paragraph(line)
            i += 1

    def _add_table_from_markdown(self, doc: Document, table_lines: List[str]) -> None:
        rows = []
        for line in table_lines:
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cols)

        if not rows:
            return

        header = rows[0]
        body = rows[1:]

        table = doc.add_table(rows=1, cols=len(header))
        table.style = "Table Grid"

        hdr_cells = table.rows[0].cells
        for idx, col in enumerate(header):
            hdr_cells[idx].text = col

        for row_data in body:
            if all(
                re.match(r"^-+$", c.replace(":", "").replace(" ", "")) for c in row_data
            ):
                continue
            row_cells = table.add_row().cells
            for idx in range(min(len(header), len(row_data))):
                row_cells[idx].text = row_data[idx]
