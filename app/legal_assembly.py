"""Legal document assembly & automated template generation."""
from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException
from fpdf import FPDF
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.database import now
from app.legal_matter_engine import attach_document_to_matter
from app.models import Document, LegalTemplate, Matter, User

logger = logging.getLogger("newtonedms.legal.assembly")


DEFAULT_TEMPLATES = [
    {
        "name": "Standard Mutual Non-Disclosure Agreement",
        "category": "contract",
        "description": "Standard two-way confidential disclosure agreement.",
        "content_template": """# MUTUAL NON-DISCLOSURE AGREEMENT

This Mutual Non-Disclosure Agreement ("Agreement") is made and entered into as of {{effective_date}}, by and between **{{client_name}}** ("Disclosing Party"), and **{{counterparty_name}}** ("Receiving Party").

**Matter Reference:** {{matter_number}} — {{matter_title}}

### 1. Confidential Information
"Confidential Information" refers to any proprietary information, technical data, trade secrets, or know-how disclosed by either party to the other regarding {{purpose}}.

### 2. Obligations
The Receiving Party agrees to protect the Confidential Information of the Disclosing Party using the same degree of care it uses to protect its own confidential information, but in no event less than a reasonable degree of care.

### 3. Governing Law & Jurisdiction
This Agreement shall be governed by the laws of {{governing_jurisdiction}}, without regard to its conflict of laws principles.

**IN WITNESS WHEREOF**, the parties have executed this Agreement as of the date first written above.

**{{client_name}}**  
By: ___________________________  
Name: {{client_signatory_name}}  
Title: {{client_signatory_title}}  

**{{counterparty_name}}**  
By: ___________________________  
Name: {{counterparty_signatory_name}}  
Title: {{counterparty_signatory_title}}  
""",
        "fields_schema": [
            {"name": "effective_date", "label": "Effective Date", "type": "date", "required": True},
            {"name": "counterparty_name", "label": "Counterparty Name", "type": "text", "required": True},
            {"name": "purpose", "label": "Business Purpose", "type": "text", "required": True},
            {"name": "governing_jurisdiction", "label": "Governing Jurisdiction", "type": "text", "required": True},
            {"name": "client_signatory_name", "label": "Client Signatory Name", "type": "text", "required": True},
            {"name": "client_signatory_title", "label": "Client Signatory Title", "type": "text", "required": True},
            {"name": "counterparty_signatory_name", "label": "Counterparty Signatory Name", "type": "text", "required": False},
            {"name": "counterparty_signatory_title", "label": "Counterparty Signatory Title", "type": "text", "required": False},
        ],
    },
    {
        "name": "Court Pleading & Notice of Motion",
        "category": "pleading",
        "description": "Standard caption header and notice of motion for court filings.",
        "content_template": """{{court_name}}

{{case_caption}}
Case No.: {{case_number}}
Judge: {{judge_name}}

--------------------------------------------------------------------------------
### NOTICE OF MOTION FOR {{motion_title}}
--------------------------------------------------------------------------------

PLEASE TAKE NOTICE that upon the annexed Affirmation of {{attorney_name}}, Esq., dated {{affirmation_date}}, the exhibits attached thereto, and the accompanying Memorandum of Law, Plaintiff/Defendant will move this Court at {{court_address}} on {{motion_return_date}} at 9:30 AM, or as soon thereafter as counsel may be heard, for an Order pursuant to {{statutory_basis}}:

1. Granting {{motion_relief_requested}};
2. Awarding reasonable costs and attorneys' fees; and
3. Granting such other and further relief as this Court deems just and proper.

Dated: {{filing_date}}  
Respectfully submitted,  

___________________________________  
**{{attorney_name}}, Esq.**  
Attorney for {{client_name}}  
{{law_firm_name}}  
{{firm_address}}  
Tel: {{firm_phone}}  
Email: {{firm_email}}  
""",
        "fields_schema": [
            {"name": "motion_title", "label": "Motion Title", "type": "text", "required": True},
            {"name": "attorney_name", "label": "Lead Attorney Name", "type": "text", "required": True},
            {"name": "affirmation_date", "label": "Affirmation Date", "type": "date", "required": True},
            {"name": "motion_return_date", "label": "Return Date", "type": "date", "required": True},
            {"name": "statutory_basis", "label": "Statutory Basis (e.g. Fed. R. Civ. P. 12(b)(6))", "type": "text", "required": True},
            {"name": "motion_relief_requested", "label": "Relief Requested", "type": "text", "required": True},
        ],
    },
]


def ensure_default_templates(db: Session, user: User) -> None:
    """Seed standard legal templates if not existing."""
    for tpl in DEFAULT_TEMPLATES:
        existing = db.query(LegalTemplate).filter(LegalTemplate.name == tpl["name"]).first()
        if not existing:
            db.add(
                LegalTemplate(
                    name=tpl["name"],
                    category=tpl["category"],
                    description=tpl["description"],
                    content_template=tpl["content_template"],
                    fields_schema=tpl["fields_schema"],
                    created_by=user.id,
                    created_at=now(),
                )
            )
    db.commit()


def assemble_document(
    db: Session,
    user: User,
    template_id: int,
    matter_id: int,
    variables: dict[str, Any],
    document_title: str | None = None,
    output_format: str = "pdf",
    folder_id: int = 1,
) -> dict[str, Any]:
    """Merge template variables with Matter metadata and generate a new legal instrument."""
    template = db.get(LegalTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Legal template not found.")

    matter = db.get(Matter, matter_id)
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found.")

    # Context merges matter fields with user variables
    context = {
        "matter_number": matter.matter_number,
        "matter_title": matter.title,
        "client_name": matter.client_name,
        "client_id": matter.client_id or "",
        "court_name": matter.court_name or "IN THE UNITED STATES DISTRICT COURT",
        "case_caption": matter.case_caption or f"{matter.client_name} v. Adverse Party",
        "case_number": matter.metadata_json.get("case_number", matter.matter_number),
        "judge_name": matter.judge_name or "Honorable Judge",
        "opposing_counsel": matter.opposing_counsel or "",
        "filing_date": now().strftime("%B %d, %Y"),
        "effective_date": now().strftime("%B %d, %Y"),
        "attorney_name": user.username.title(),
        "law_firm_name": "Newton & Associates LLP",
        "firm_address": "100 Legal Avenue, Suite 500",
        "firm_phone": "(555) 019-2831",
        "firm_email": user.email or "legal@newtonedms.local",
    }
    context.update(matter.metadata_json or {})
    context.update(variables or {})

    # Replace {{variable}} tags
    rendered_text = template.content_template
    for k, v in context.items():
        pattern = re.compile(r"\{\{\s*" + re.escape(k) + r"\s*\}\}", re.IGNORECASE)
        rendered_text = pattern.sub(str(v), rendered_text)

    # Clean unreplaced variables
    rendered_text = re.sub(r"\{\{\s*[\w_]+\s*\}\}", "[_____]", rendered_text)

    storage_root = BASE_DIR / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    title = document_title or f"{template.name} - {matter.matter_number}"
    safe_slug = re.sub(r"[^\w\-]", "_", title.lower())

    if output_format.lower() == "pdf":
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for line in rendered_text.splitlines():
            clean_line = line.replace("#", "").replace("*", "").replace("—", "-").replace("–", "-").replace('“', '"').replace('”', '"').replace("’", "'").strip()
            clean_line = clean_line.encode("latin-1", "replace").decode("latin-1")
            if line.startswith("#"):
                pdf.set_font("Helvetica", "B", size=14)
                pdf.cell(0, 8, clean_line, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=10)
            elif line.startswith("###"):
                pdf.set_font("Helvetica", "B", size=11)
                pdf.cell(0, 6, clean_line, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=10)
            else:
                pdf.multi_cell(pdf.epw, 5, clean_line if clean_line else " ")
        raw_data = bytes(pdf.output())
        ext = "pdf"
        mime = "application/pdf"
    else:
        raw_data = rendered_text.encode("utf-8")
        ext = "md"
        mime = "text/markdown"

    rel_path = f"legal_assembly/{now().strftime('%Y%m%d_%H%M%S')}_{safe_slug}.{ext}"
    target_file = storage_root / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(raw_data)

    doc = Document(
        name=f"{title}.{ext}",
        title=title,
        file_path=str(rel_path).replace("\\", "/"),
        mime=mime,
        size=len(raw_data),
        folder_id=folder_id,
        created_by=user.id,
        created_at=now(),
        extracted_text=rendered_text,
        metadata_json={"template_id": template.id, "template_name": template.name, "matter_id": matter.id},
        tags=f"legal,assembled,{template.category},matter-{matter.matter_number}",
        status="draft",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Link to Matter under template's category
    category_map = {"pleading": "pleading", "contract": "contract", "nda": "contract", "discovery": "discovery"}
    attach_document_to_matter(
        db, user, matter.id, doc.id,
        category=category_map.get(template.category, "pleading"),
        confidentiality="confidential",
        notes=f"Assembled from template '{template.name}'",
    )

    return {
        "status": "success",
        "document_id": doc.id,
        "title": doc.title,
        "size": doc.size,
        "matter_id": matter.id,
        "template_id": template.id,
        "rendered_preview": rendered_text[:500],
    }
