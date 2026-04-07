"""
FRD Manual Generation Route
Allows direct file upload via Swagger UI or API call to generate an FRD document.
"""

import logging
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from app.models.webhook_payload import WorkItemDocument
from app.services.frd_generator import FRDGeneratorService
from app.utils.document_extractor import DocumentExtractor

logger = logging.getLogger(__name__)
router = APIRouter()

frd_generator = FRDGeneratorService()
extractor = DocumentExtractor()

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


@router.post(
    "/frd/generate",
    summary="Generate FRD from uploaded documents",
    description="""
Upload one or more documents (SOW, MOM, Transcripts) and receive a professionally
generated **Functional Requirements Document (FRD)** as a `.docx` file.

### Instructions:
- Upload at least one document (SOW, MOM, or Transcript)
- Optionally provide a **Project Name** and **Work Item ID**
- The AI will analyze all documents and generate a complete FRD
- The response is a downloadable `.docx` file

### Tips:
- Upload multiple files together for best results
- Supported formats: `.docx`, `.pdf`, `.txt`, `.md`
- File names help auto-classify documents (e.g. `SOW_project.docx`, `MOM_kickoff.pdf`)
    """,
    response_class=FileResponse,
)
async def generate_frd(
    files: List[UploadFile] = File(
        ...,
        description="Upload SOW, MOM, Transcript documents (supports .docx, .pdf, .txt, .md)",
    ),
    project_name: Optional[str] = Form(
        default="Untitled Project",
        description="Name of the project (used in FRD title)",
    ),
    work_item_id: Optional[int] = Form(
        default=0,
        description="Azure DevOps Work Item ID (optional, used for file naming)",
    ),
    client_name: Optional[str] = Form(
        default="", description="Client / Customer name (optional)"
    ),
):
    if not files:
        raise HTTPException(
            status_code=400, detail="Please upload at least one document."
        )

    documents: List[WorkItemDocument] = []

    for upload in files:
        filename = upload.filename or "unknown.txt"
        content_bytes = await upload.read()

        if not content_bytes:
            logger.warning(f"Skipping empty file: {filename}")
            continue

        logger.info(
            f"Processing uploaded file: {filename} ({len(content_bytes)} bytes)"
        )

        text_content = extractor.extract_text(filename, content_bytes)
        doc_type = _classify_document(filename, text_content)

        documents.append(
            WorkItemDocument(
                filename=filename,
                content=text_content,
                doc_type=doc_type,
            )
        )
        logger.info(
            f"Extracted: {filename} → type={doc_type}, chars={len(text_content)}"
        )

    if not documents:
        raise HTTPException(
            status_code=400, detail="No readable content found in uploaded files."
        )

    # Inject project name / client into generator context
    wi_id = work_item_id or 0
    meta_doc = WorkItemDocument(
        filename="__metadata__.txt",
        content=f"Project Name: {project_name}\nClient: {client_name or 'Not specified'}",
        doc_type="other",
    )
    documents.insert(0, meta_doc)

    logger.info(
        f"Generating FRD for project='{project_name}', {len(documents)} documents..."
    )

    try:
        frd_path = await frd_generator.generate_frd(
            work_item_id=wi_id,
            documents=documents,
        )
    except Exception as e:
        logger.error(f"FRD generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"FRD generation failed: {str(e)}")

    return FileResponse(
        path=str(frd_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=frd_path.name,
        headers={"Content-Disposition": f'attachment; filename="{frd_path.name}"'},
    )


@router.get(
    "/frd/list",
    summary="List previously generated FRDs",
    description="Returns a list of all FRD documents previously generated and stored on the server.",
)
async def list_generated_frds():
    files = sorted(OUTPUT_DIR.glob("FRD_*.docx"), key=os.path.getmtime, reverse=True)
    return {
        "count": len(files),
        "files": [
            {
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "download_url": f"/api/v1/frd/download/{f.name}",
            }
            for f in files
        ],
    }


@router.get(
    "/frd/download/{filename}",
    summary="Download a previously generated FRD",
    response_class=FileResponse,
)
async def download_frd(filename: str):
    # Sanitize filename
    safe_name = Path(filename).name
    frd_path = OUTPUT_DIR / safe_name

    if not frd_path.exists() or not safe_name.startswith("FRD_"):
        raise HTTPException(status_code=404, detail="FRD file not found.")

    return FileResponse(
        path=str(frd_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_name,
    )


def _classify_document(filename: str, content: str) -> str:
    name_lower = filename.lower()
    content_lower = content.lower()

    if any(k in name_lower for k in ["sow", "statement_of_work", "statement-of-work"]):
        return "sow"
    if any(k in name_lower for k in ["mom", "minutes", "meeting"]):
        return "mom"
    if any(k in name_lower for k in ["transcript", "recording", "call"]):
        return "transcript"

    sow_score = sum(
        1
        for k in ["scope of work", "deliverables", "payment terms", "statement of work"]
        if k in content_lower
    )
    mom_score = sum(
        1
        for k in ["minutes of meeting", "attendees", "action items", "meeting date"]
        if k in content_lower
    )
    transcript_score = sum(
        1 for k in ["speaker", "00:", "transcript", "host:"] if k in content_lower
    )

    max_score = max(sow_score, mom_score, transcript_score)
    if max_score == 0:
        return "other"
    if sow_score == max_score:
        return "sow"
    if mom_score == max_score:
        return "mom"
    return "transcript"
