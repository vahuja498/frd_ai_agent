"""
FRD Generator Service - Reliable Document Intelligence
Generates a professional FRD using:
  1. Smart content extraction directly from source documents (always works)
  2. HuggingFace LLM enhancement (optional, used only if API responds within timeout)
"""

import logging
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.models.webhook_payload import WorkItemDocument
from app.config import settings

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

HF_API_URL = "https://api-inference.huggingface.co/models/{model}"
DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"


class FRDGeneratorService:
    def __init__(self):
        self.hf_token = getattr(settings, "HF_API_TOKEN", "")
        self.model = getattr(settings, "HF_MODEL", DEFAULT_MODEL)
        self._headers = {"Authorization": f"Bearer {self.hf_token}"}

    # ─────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────

    async def generate_frd(
        self,
        work_item_id: int,
        documents: List[WorkItemDocument],
        project_name: str = "Untitled Project",
        client_name: str = "",
    ) -> Path:
        real_docs = [d for d in documents if d.filename != "__metadata__.txt"]

        logger.info("Extracting content from source documents...")
        extracted = self._extract_all_sections(real_docs)

        logger.info("Attempting LLM enhancement (15s timeout)...")
        llm_enhancements = await self._try_llm_enhancement(
            extracted, real_docs, project_name, client_name
        )

        sections = self._merge_sections(extracted, llm_enhancements)

        logger.info("Rendering FRD document...")
        return self._render_docx(
            work_item_id, sections, real_docs, project_name, client_name
        )

    # ─────────────────────────────────────────────────────────
    # Content Extraction
    # ─────────────────────────────────────────────────────────

    def _extract_all_sections(self, documents: List[WorkItemDocument]) -> dict:
        combined = "\n\n".join(
            f"[{d.doc_type.upper()}: {d.filename}]\n{d.content}" for d in documents
        )
        return {
            "project_overview": self._extract_project_overview(combined, documents),
            "business_objectives": self._extract_business_objectives(combined),
            "scope_in": self._extract_scope_in(combined),
            "scope_out": self._extract_scope_out(combined),
            "stakeholders": self._extract_stakeholders(combined),
            "functional_requirements": self._extract_functional_requirements(
                combined, documents
            ),
            "non_functional_requirements": self._extract_nfr(combined),
            "assumptions": self._extract_assumptions(combined),
            "constraints": self._extract_constraints(combined),
            "risks": self._extract_risks(combined),
            "glossary": self._extract_glossary(combined),
        }

    def _extract_project_overview(
        self, text: str, documents: List[WorkItemDocument]
    ) -> str:
        lines = []
        patterns = [
            r"(?:scope of work|project overview|background|introduction)[^\n]*\n+([\s\S]{100,800}?)(?:\n\n|\n[A-Z*])",
            r"(?:solution|system|platform) is built[^\n]*\n*([\s\S]{50,600}?)(?:\n\n|\n[A-Z*\-])",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                lines.append(m.group(1).strip())
                break

        if not lines:
            paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 150]
            if paras:
                lines.append(paras[0][:800])

        doc_types = list({d.doc_type.upper() for d in documents})
        lines.append(
            f"This FRD was generated from the following source document types: {', '.join(doc_types)}."
        )
        return "\n\n".join(lines)

    def _extract_business_objectives(self, text: str) -> str:
        objectives = []
        kpi_patterns = [
            r"(?:reduction|increase|improve|decrease|achieve|target|goal)[^.\n]{10,150}(?:\d+%|percent)[^.\n]*",
            r"\d+%[^.\n]{5,100}",
            r"(?:measurable outcome|objective|goal)[^\n]*:[^\n]*",
        ]
        for p in kpi_patterns:
            for m in re.finditer(p, text, re.IGNORECASE):
                obj = m.group(0).strip().strip("-*").strip()
                if obj and obj not in objectives:
                    objectives.append(obj)

        bullet_section = re.search(
            r"(?:objective|goal|purpose|aim)[s]?\s*[:\-]\s*\n((?:[\s]*[-*]\s*.+\n?){1,15})",
            text,
            re.IGNORECASE,
        )
        if bullet_section:
            for line in bullet_section.group(1).splitlines():
                line = line.strip().strip("-* ").strip()
                if len(line) > 20 and line not in objectives:
                    objectives.append(line)

        if not objectives:
            for line in text.splitlines():
                if any(
                    k in line.lower()
                    for k in [
                        "to improve",
                        "to reduce",
                        "to automate",
                        "to provide",
                        "to enable",
                        "to ensure",
                    ]
                ):
                    clean = line.strip().strip("-* ")
                    if 20 < len(clean) < 200 and clean not in objectives:
                        objectives.append(clean)

        return (
            "\n".join(f"- {o}" for o in objectives[:10])
            if objectives
            else "- Refer to source documents for business objectives."
        )

    def _extract_scope_in(self, text: str) -> str:
        items = []
        m = re.search(
            r"(?:in[\s-]?scope|scope of work|inclusions?)[^\n]*\n((?:[\s]*[-*]\s*.+\n?){1,30})",
            text,
            re.IGNORECASE,
        )
        if m:
            for line in m.group(1).splitlines():
                clean = line.strip().strip("-* ").strip()
                if len(clean) > 15:
                    items.append(clean)

        section_headers = re.findall(
            r"\*\*([A-Z][A-Za-z\s&,/]+(?:Setup|Development|Configuration|Module|Integration|Reporting|Analytics|Automation|Design|Security|Data[^\n]{0,30}))\*\*",
            text,
        )
        for h in section_headers:
            h = h.strip()
            if h and h not in items and len(h) > 10:
                items.append(h)

        return (
            "\n".join(f"- {i}" for i in items[:20])
            if items
            else "- Refer to source documents."
        )

    def _extract_scope_out(self, text: str) -> str:
        m = re.search(
            r"(?:out[\s-]?of[\s-]?scope|exclusions?|not included)[^\n]*\n((?:[\s]*[-*]\s*.+\n?){1,20})",
            text,
            re.IGNORECASE,
        )
        items = []
        if m:
            for line in m.group(1).splitlines():
                clean = line.strip().strip("-* ").strip()
                if len(clean) > 10:
                    items.append(clean)
        return (
            "\n".join(f"- {i}" for i in items[:15])
            if items
            else "- Not explicitly defined in source documents."
        )

    def _extract_stakeholders(self, text: str) -> list:
        stakeholders = []
        seen = set()

        for label in ["Author", "Stakeholder", "End Customer", "submitted to"]:
            m = re.search(
                rf"\*?\*?{label}\*?\*?\s*[|:]?\s*([^\n|]+)", text, re.IGNORECASE
            )
            if m:
                val = m.group(1).strip().strip("*|").strip()
                if val and len(val) > 2 and val.lower() not in seen:
                    seen.add(val.lower())
                    stakeholders.append(f"{label}: {val}")

        role_patterns = [
            r"(?:Field User|Reviewer|Administrator|Executive|PM|Project Manager|Business Analyst|Developer|Client|Customer|Vendor|Sponsor)[^\n]{0,80}"
        ]
        for p in role_patterns:
            for m in re.finditer(p, text, re.IGNORECASE):
                role = m.group(0).strip().split("\n")[0][:100]
                key = role[:30].lower()
                if key not in seen and len(role) > 5:
                    seen.add(key)
                    stakeholders.append(role)

        return stakeholders[:15]

    def _extract_functional_requirements(
        self, text: str, documents: List[WorkItemDocument]
    ) -> list:
        requirements = []
        counter = 1
        seen = set()

        for doc in documents:
            if doc.doc_type in ["sow", "mom", "other"]:
                bullets = re.findall(r"(?:^|\n)\s*[-*]\s+(.{20,200})", doc.content)
                for b in bullets:
                    b = b.strip()
                    key = b[:40].lower()
                    if key in seen:
                        continue
                    if any(
                        k in b.lower()
                        for k in [
                            "setup",
                            "config",
                            "develop",
                            "creat",
                            "integrat",
                            "automat",
                            "generat",
                            "provid",
                            "support",
                            "enabl",
                            "allow",
                            "manag",
                            "track",
                            "monitor",
                            "report",
                            "upload",
                            "download",
                            "notif",
                            "assign",
                            "resolv",
                            "escalat",
                            "validat",
                            "encrypt",
                            "design",
                        ]
                    ):
                        seen.add(key)
                        requirements.append(
                            {
                                "id": f"FR-{counter:03d}",
                                "description": b,
                                "priority": self._infer_priority(b),
                                "source": doc.doc_type.upper(),
                            }
                        )
                        counter += 1
                        if counter > 50:
                            break
            if counter > 50:
                break

        return requirements

    def _infer_priority(self, text: str) -> str:
        t = text.lower()
        if any(
            k in t
            for k in [
                "must",
                "critical",
                "mandatory",
                "security",
                "compliance",
                "encrypt",
                "pci",
                "gdpr",
            ]
        ):
            return "High"
        if any(
            k in t for k in ["should", "recommend", "report", "dashboard", "analytic"]
        ):
            return "Medium"
        return "Low"

    def _extract_nfr(self, text: str) -> dict:
        nfr = {}
        perf = re.findall(
            r"(?:response time|performance|speed|latency|throughput|SLA)[^\n.]{0,150}",
            text,
            re.IGNORECASE,
        )
        nfr["Performance"] = (
            perf[:3]
            if perf
            else [
                "System shall respond within acceptable time limits for all operations."
            ]
        )

        sec = re.findall(
            r"(?:PCI DSS|encryption|security|compliance|GDPR|access control|role.based|authentication)[^\n.]{0,150}",
            text,
            re.IGNORECASE,
        )
        nfr["Security"] = (
            list(set(s.strip() for s in sec[:5]))
            if sec
            else [
                "System shall enforce role-based access control.",
                "Data shall be encrypted at rest and in transit.",
            ]
        )

        host = re.findall(
            r"(?:hosted|hosting|data residency|UAE|region|geographic)[^\n.]{0,150}",
            text,
            re.IGNORECASE,
        )
        nfr["Compliance & Data Residency"] = (
            host[:3]
            if host
            else ["Data hosting shall comply with applicable regional regulations."]
        )

        nfr["Availability"] = [
            "The system shall maintain 99.5% uptime during business hours.",
            "Scheduled maintenance windows shall be communicated 48 hours in advance.",
        ]
        nfr["Scalability"] = [
            "The system shall support the projected user base without performance degradation.",
            "The architecture shall allow scaling as user volume grows.",
        ]
        return nfr

    def _extract_assumptions(self, text: str) -> list:
        m = re.search(
            r"(?:assumption)[s]?\s*[:\-]?\s*\n((?:[\s]*[-*]\s*.+\n?){1,25})",
            text,
            re.IGNORECASE,
        )
        items = []
        if m:
            for line in m.group(1).splitlines():
                clean = line.strip().strip("-* ").strip()
                if len(clean) > 20:
                    items.append(clean)
        return items[:15]

    def _extract_constraints(self, text: str) -> list:
        constraints = []
        seen = set()
        tech = re.findall(
            r"(?:Microsoft|Dynamics|Power Platform|Dataverse|Power Automate|Azure|SharePoint)[^\n.]{0,100}",
            text,
            re.IGNORECASE,
        )
        for t in tech[:5]:
            c = f"Technology: {t.strip()}"
            if c[:40] not in seen:
                seen.add(c[:40])
                constraints.append(c)
        dates = re.findall(
            r"(?:\d{1,2}[\-/]\w+[\-/]\d{2,4}|Q[1-4]\s+\d{4}|deadline|timeline|go.live)[^\n.]{0,100}",
            text,
            re.IGNORECASE,
        )
        for d in dates[:3]:
            c = d.strip()
            if c and c[:30] not in seen:
                seen.add(c[:30])
                constraints.append(c)
        return constraints[:10]

    def _extract_risks(self, text: str) -> list:
        risks = []
        seen = set()
        for p in [
            r"(?:Failure to|If .{5,50} not)[^\n.]{10,200}",
            r"(?:failure|delay|risk|dependency|blocker)[^\n.]{20,200}",
        ]:
            for m in re.finditer(p, text, re.IGNORECASE):
                risk = m.group(0).strip()
                key = risk[:40].lower()
                if key not in seen and len(risk) > 30:
                    seen.add(key)
                    risks.append(risk[:250])
        return risks[:10]

    def _extract_glossary(self, text: str) -> list:
        terms = []
        seen = set()
        common = {
            "CRM": "Customer Relationship Management",
            "SOW": "Statement of Work",
            "FRD": "Functional Requirements Document",
            "MOM": "Minutes of Meeting",
            "API": "Application Programming Interface",
            "UAT": "User Acceptance Testing",
            "SLA": "Service Level Agreement",
            "PCI": "Payment Card Industry",
            "DSS": "Data Security Standard",
            "RBAC": "Role-Based Access Control",
            "UI": "User Interface",
            "UX": "User Experience",
            "PM": "Project Manager",
        }
        for acr in re.findall(r"\b([A-Z]{2,8})\b", text):
            if acr in common and acr not in seen:
                seen.add(acr)
                terms.append({"term": acr, "definition": common[acr]})

        for term, defn in re.findall(
            r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,4})\s*[--:]\s*([^.\n]{20,100})", text
        )[:10]:
            if term not in seen:
                seen.add(term)
                terms.append({"term": term, "definition": defn.strip()})

        return terms[:20]

    # ─────────────────────────────────────────────────────────
    # LLM Enhancement (optional)
    # ─────────────────────────────────────────────────────────

    async def _try_llm_enhancement(
        self, extracted, documents, project_name, client_name
    ) -> dict:
        if not self.hf_token or self.hf_token in ("hf_your_token_here", "test", ""):
            logger.info("No HF token — skipping LLM enhancement.")
            return {}

        combined = "\n\n".join(d.content[:2000] for d in documents)[:4000]
        prompt = (
            f"<s>[INST] You are a senior business analyst. Based on this project document, "
            f"write a professional 2-paragraph Project Overview for a Functional Requirements Document. "
            f"Project: {project_name}. Client: {client_name or 'Not specified'}.\n\n"
            f"DOCUMENT:\n{combined}\n\nPROJECT OVERVIEW:[/INST]"
        )
        try:
            result = await asyncio.wait_for(self._call_llm(prompt), timeout=20.0)
            if result and len(result) > 80:
                logger.info("LLM enhancement successful.")
                return {"project_overview_llm": result}
        except asyncio.TimeoutError:
            logger.warning("LLM timed out — using extracted content.")
        except Exception as e:
            logger.warning(f"LLM unavailable: {e}")
        return {}

    async def _call_llm(self, prompt: str) -> str:
        url = HF_API_URL.format(model=self.model)
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 400,
                "temperature": 0.3,
                "return_full_text": False,
            },
        }
        async with httpx.AsyncClient(timeout=18) as client:
            resp = await client.post(url, headers=self._headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, list) and data:
            return data[0].get("generated_text", "").strip()
        return ""

    def _merge_sections(self, extracted: dict, llm: dict) -> dict:
        sections = dict(extracted)
        if llm.get("project_overview_llm"):
            sections["project_overview"] = llm["project_overview_llm"]
        return sections

    # ─────────────────────────────────────────────────────────
    # DOCX Renderer
    # ─────────────────────────────────────────────────────────

    def _render_docx(
        self, work_item_id, sections, documents, project_name, client_name
    ) -> Path:
        doc = DocxDocument()
        self._configure_styles(doc)
        self._add_cover_page(doc, work_item_id, documents, project_name, client_name)
        self._add_toc(doc)
        self._add_overview(doc, sections)
        self._add_objectives(doc, sections)
        self._add_scope(doc, sections)
        self._add_stakeholders(doc, sections)
        self._add_functional_reqs(doc, sections)
        self._add_nfr(doc, sections)
        self._add_assumptions(doc, sections)
        self._add_risks(doc, sections)
        self._add_glossary(doc, sections)
        self._add_source_docs(doc, documents)
        self._add_footer(doc, work_item_id, project_name)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        wi_label = f"WI{work_item_id}" if work_item_id else "Manual"
        out_path = OUTPUT_DIR / f"FRD_{wi_label}_{ts}.docx"
        doc.save(out_path)
        logger.info(f"FRD saved: {out_path}")
        return out_path

    def _configure_styles(self, doc):
        s = doc.sections[0]
        s.top_margin = Cm(2.5)
        s.bottom_margin = Cm(2.5)
        s.left_margin = Cm(3.0)
        s.right_margin = Cm(2.5)
        doc.styles["Normal"].font.name = "Calibri"
        doc.styles["Normal"].font.size = Pt(11)

    def _h(self, doc, text, level=1):
        p = doc.add_heading(text, level=level)
        for run in p.runs:
            run.font.name = "Calibri"
            run.font.color.rgb = (
                RGBColor(0x1F, 0x49, 0x7D) if level == 1 else RGBColor(0x2E, 0x75, 0xB6)
            )
            run.font.size = Pt(14) if level == 1 else Pt(12)

    def _p(self, doc, text, bold=False, italic=False):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.font.name = "Calibri"
        r.font.size = Pt(11)
        r.bold = bold
        r.italic = italic

    def _b(self, doc, text):
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(text)
        r.font.name = "Calibri"
        r.font.size = Pt(11)

    def _table_header(self, table, headers):
        for i, h in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = h
            if cell.paragraphs[0].runs:
                cell.paragraphs[0].runs[0].bold = True
                cell.paragraphs[0].runs[0].font.name = "Calibri"
                cell.paragraphs[0].runs[0].font.size = Pt(11)

    def _add_cover_page(self, doc, work_item_id, documents, project_name, client_name):
        doc.add_paragraph()
        doc.add_paragraph()

        t = doc.add_paragraph()
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = t.add_run("FUNCTIONAL REQUIREMENTS DOCUMENT")
        r.font.size = Pt(26)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
        r.font.name = "Calibri"

        doc.add_paragraph()

        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(project_name)
        r2.font.size = Pt(18)
        r2.font.bold = True
        r2.font.color.rgb = RGBColor(0x2E, 0x75, 0xB6)
        r2.font.name = "Calibri"

        if client_name:
            p3 = doc.add_paragraph()
            p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r3 = p3.add_run(f"Client: {client_name}")
            r3.font.size = Pt(13)
            r3.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
            r3.font.name = "Calibri"

        doc.add_paragraph()

        real_docs = [d for d in documents if d.filename != "__metadata__.txt"]
        meta = [
            ("Document Type", "Functional Requirements Document (FRD)"),
            ("Project Name", project_name),
            ("Client", client_name or "Not specified"),
            ("Work Item ID", f"#{work_item_id}" if work_item_id else "N/A"),
            ("Version", "1.0 — DRAFT"),
            ("Status", "Auto-Generated — Pending Review"),
            ("Generated By", "FRD AI Agent"),
            ("Date", datetime.now().strftime("%B %d, %Y")),
            ("Source Documents", ", ".join(d.filename for d in real_docs) or "N/A"),
        ]
        table = doc.add_table(rows=len(meta), cols=2)
        table.style = "Table Grid"
        for i, (k, v) in enumerate(meta):
            table.rows[i].cells[0].text = k
            table.rows[i].cells[1].text = v
            if table.rows[i].cells[0].paragraphs[0].runs:
                table.rows[i].cells[0].paragraphs[0].runs[0].bold = True
                table.rows[i].cells[0].paragraphs[0].runs[0].font.name = "Calibri"

        doc.add_page_break()

    def _add_toc(self, doc):
        self._h(doc, "Table of Contents", 1)
        for item in [
            "1. Project Overview",
            "2. Business Objectives",
            "3. Scope",
            "4. Stakeholders",
            "5. Functional Requirements",
            "6. Non-Functional Requirements",
            "7. Assumptions & Constraints",
            "8. Risks & Dependencies",
            "9. Glossary",
            "10. Source Documents",
        ]:
            self._b(doc, item)
        self._p(
            doc,
            "In Microsoft Word, right-click → Update Field to generate a live TOC.",
            italic=True,
        )
        doc.add_page_break()

    def _add_overview(self, doc, sections):
        self._h(doc, "1. Project Overview", 1)
        text = sections.get("project_overview", "")
        if text:
            for para in text.split("\n\n"):
                if para.strip():
                    self._p(doc, para.strip())
        else:
            self._p(doc, "See source documents.", italic=True)
        doc.add_paragraph()

    def _add_objectives(self, doc, sections):
        self._h(doc, "2. Business Objectives", 1)
        text = sections.get("business_objectives", "")
        for line in text.splitlines():
            line = line.strip().lstrip("- ").strip()
            if line:
                self._b(doc, line)
        doc.add_paragraph()

    def _add_scope(self, doc, sections):
        self._h(doc, "3. Scope", 1)
        self._h(doc, "3.1 In Scope", 2)
        for line in sections.get("scope_in", "").splitlines():
            line = line.strip().lstrip("- ").strip()
            if line:
                self._b(doc, line)
        doc.add_paragraph()
        self._h(doc, "3.2 Out of Scope", 2)
        for line in sections.get("scope_out", "").splitlines():
            line = line.strip().lstrip("- ").strip()
            if line:
                self._b(doc, line)
        doc.add_paragraph()

    def _add_stakeholders(self, doc, sections):
        self._h(doc, "4. Stakeholders", 1)
        stakeholders = sections.get("stakeholders", [])
        if stakeholders:
            table = doc.add_table(rows=1 + len(stakeholders), cols=3)
            table.style = "Table Grid"
            self._table_header(table, ["#", "Stakeholder / Role", "Notes"])
            for idx, s in enumerate(stakeholders, 1):
                table.rows[idx].cells[0].text = str(idx)
                table.rows[idx].cells[1].text = s
                table.rows[idx].cells[2].text = ""
        else:
            self._p(doc, "Not explicitly defined in source documents.", italic=True)
        doc.add_paragraph()

    def _add_functional_reqs(self, doc, sections):
        self._h(doc, "5. Functional Requirements", 1)
        reqs = sections.get("functional_requirements", [])
        if reqs:
            table = doc.add_table(rows=1 + len(reqs), cols=4)
            table.style = "Table Grid"
            self._table_header(table, ["ID", "Description", "Priority", "Source"])
            for idx, req in enumerate(reqs, 1):
                table.rows[idx].cells[0].text = req["id"]
                table.rows[idx].cells[1].text = req["description"]
                table.rows[idx].cells[2].text = req["priority"]
                table.rows[idx].cells[3].text = req["source"]
        else:
            self._p(doc, "Please review source documents.", italic=True)
        doc.add_paragraph()

    def _add_nfr(self, doc, sections):
        self._h(doc, "6. Non-Functional Requirements", 1)
        nfr = sections.get("non_functional_requirements", {})
        counter = 1
        if nfr:
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            self._table_header(table, ["ID", "Category", "Requirement"])
            for category, items in nfr.items():
                for item in items:
                    row = table.add_row()
                    row.cells[0].text = f"NFR-{counter:03d}"
                    row.cells[1].text = category
                    row.cells[2].text = item.strip()
                    counter += 1
        doc.add_paragraph()

    def _add_assumptions(self, doc, sections):
        self._h(doc, "7. Assumptions & Constraints", 1)
        self._h(doc, "7.1 Assumptions", 2)
        assumptions = sections.get("assumptions", [])
        if assumptions:
            for a in assumptions:
                self._b(doc, a)
        else:
            self._p(doc, "No explicit assumptions documented.", italic=True)
        doc.add_paragraph()
        self._h(doc, "7.2 Constraints", 2)
        constraints = sections.get("constraints", [])
        if constraints:
            for c in constraints:
                self._b(doc, c)
        else:
            self._p(doc, "No explicit constraints documented.", italic=True)
        doc.add_paragraph()

    def _add_risks(self, doc, sections):
        self._h(doc, "8. Risks & Dependencies", 1)
        risks = sections.get("risks", [])
        if risks:
            table = doc.add_table(rows=1 + len(risks), cols=3)
            table.style = "Table Grid"
            self._table_header(table, ["#", "Risk / Dependency", "Mitigation"])
            for idx, risk in enumerate(risks, 1):
                table.rows[idx].cells[0].text = str(idx)
                table.rows[idx].cells[1].text = risk[:300]
                table.rows[idx].cells[2].text = "To be defined by project team."
        else:
            self._p(doc, "No explicit risks identified.", italic=True)
        doc.add_paragraph()

    def _add_glossary(self, doc, sections):
        self._h(doc, "9. Glossary", 1)
        terms = sections.get("glossary", [])
        if terms:
            table = doc.add_table(rows=1 + len(terms), cols=2)
            table.style = "Table Grid"
            self._table_header(table, ["Term / Acronym", "Definition"])
            for idx, entry in enumerate(terms, 1):
                table.rows[idx].cells[0].text = entry["term"]
                table.rows[idx].cells[1].text = entry["definition"]
        else:
            self._p(doc, "No glossary terms identified.", italic=True)
        doc.add_paragraph()

    def _add_source_docs(self, doc, documents):
        self._h(doc, "10. Source Documents", 1)
        real_docs = [d for d in documents if d.filename != "__metadata__.txt"]
        table = doc.add_table(rows=1 + len(real_docs), cols=3)
        table.style = "Table Grid"
        self._table_header(table, ["#", "File Name", "Type"])
        for idx, d in enumerate(real_docs, 1):
            table.rows[idx].cells[0].text = str(idx)
            table.rows[idx].cells[1].text = d.filename
            table.rows[idx].cells[2].text = d.doc_type.upper()

    def _add_footer(self, doc, work_item_id, project_name):
        footer = doc.sections[0].footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        label = f"WI#{work_item_id}" if work_item_id else "Manual"
        fp.text = (
            f"FRD | {project_name} | {label} | "
            f"Auto-Generated by FRD AI Agent | CONFIDENTIAL | "
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )
        for run in fp.runs:
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            run.font.name = "Calibri"
