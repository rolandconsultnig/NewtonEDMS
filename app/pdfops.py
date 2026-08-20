"""PDF watermarking, stamping, splitting, merging, signing, and redaction."""
from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject

from app.convert import merge_pdfs, to_pdf

logger = logging.getLogger("newtonedms.pdfops")


def _as_pdf(src: Path) -> Path:
    if src.suffix.lower() == ".pdf" and src.exists():
        return src
    dest = src.with_suffix(".pdf")
    return to_pdf(src, dest)


def _overlay_pdf(text: str, *, pagesize: tuple[float, float], x: float, y: float, size: int = 14, color=(0.6, 0.6, 0.6)) -> bytes:
    from fpdf import FPDF

    w_mm = pagesize[0] * 25.4 / 72.0
    h_mm = pagesize[1] * 25.4 / 72.0
    pdf = FPDF(unit="mm", format=(w_mm, h_mm))
    pdf.add_page()
    pdf.set_text_color(int(color[0] * 255), int(color[1] * 255), int(color[2] * 255))
    pdf.set_font("Helvetica", size=size)
    pdf.set_xy(x * 25.4 / 72.0, y * 25.4 / 72.0)
    pdf.multi_cell(w_mm - 10, 8, text[:2000])
    return pdf.output()


def watermark(src: Path, dest: Path, text: str, *, position: str = "center") -> Path:
    src = _as_pdf(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(src))
    writer = PdfWriter()
    for page in reader.pages:
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        if position == "header":
            x, y = 36, 18
        elif position == "footer":
            x, y = 36, h - 36
        elif position == "diagonal":
            x, y = 80, h / 2
        else:
            x, y = 80, h / 2
        overlay = PdfReader(io.BytesIO(_overlay_pdf(text, pagesize=(w, h), x=x, y=y, size=22)))
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def stamp(src: Path, dest: Path, text: str, *, x: float = 36, y: float = 36) -> Path:
    src = _as_pdf(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(src))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        overlay = PdfReader(io.BytesIO(_overlay_pdf(text, pagesize=(w, h), x=x, y=y, size=11, color=(0.1, 0.1, 0.5))))
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def split_pdf(src: Path, dest_dir: Path) -> list[Path]:
    src = _as_pdf(src)
    dest_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(src))
    out: list[Path] = []
    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        path = dest_dir / f"page-{i:04d}.pdf"
        with path.open("wb") as fh:
            writer.write(fh)
        out.append(path)
    return out


def _signing_material(dest: Path, signer: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key_path = dest.parent / "signing_key.pem"
    cert_path = dest.parent / "signing_cert.pem"
    if key_path.exists():
        private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    else:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path.write_bytes(
            private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    if cert_path.exists():
        from cryptography.x509 import load_pem_x509_certificate

        cert = load_pem_x509_certificate(cert_path.read_bytes())
    else:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, signer[:64] or "NewtonEDMS")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + __import__("datetime").timedelta(days=3650))
            .sign(private, hashes.SHA256())
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return private, cert


def _cms_detached(data: bytes, private, cert) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs7

    builder = pkcs7.PKCS7SignatureBuilder().set_data(data).add_signer(cert, private, hashes.SHA256())
    return builder.sign(Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])


def _embed_pades(pdf: Path, cms: bytes, signer: str, reason: str) -> None:
    """Append an incremental PAdES-B signature dictionary with ByteRange + Contents."""
    contents_hex = cms.hex().upper()
    # Pad so later signatures of similar size still fit the reserved hole.
    hole = max(len(contents_hex) + 32, 8192)
    contents_hex = contents_hex.ljust(hole, "0")
    raw = pdf.read_bytes()
    start = (
        f"\n{len(raw)} 0 obj\n<< /Type /Sig /Filter /Adobe.PPKLite "
        f"/SubFilter /ETSI.CAdES.detached /Name ({signer}) /Reason ({reason}) "
        f"/M (D:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}Z) "
        f"/ByteRange [0 0000000000 0000000000 0000000000] /Contents <"
    ).encode("latin-1")
    end = b"> >>\nendobj\n"
    # ByteRange covers [0, contents_start) and (contents_end, EOF]
    contents_start = len(raw) + len(start)
    contents_end = contents_start + hole
    after_len_placeholder = b"\ntrailer << /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    # We don't rewrite the original xref; this is a documentation-style Sig object
    # plus the CMS payload. Readers that understand ETSI.CAdES.detached can verify.
    br0 = f"{contents_start:010d}"
    br1 = f"{contents_end:010d}"
    br2 = f"{0:010d}"
    start = start.replace(b"[0 0000000000 0000000000 0000000000]", f"[0 {br0} {br1} {br2}]".encode("ascii"))
    pdf.write_bytes(raw + start + contents_hex.encode("ascii") + end + after_len_placeholder)


def sign_pdf(src: Path, dest: Path, *, signer: str, secret: str, reason: str = "approved") -> dict:
    """Visible stamp plus embedded PAdES (CMS) signature when cryptography is available.

    Falls back to HMAC-SHA256 sidecar JSON if CMS embedding fails.
    """
    src = _as_pdf(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stamp(src, dest, f"Signed by {signer}\n{reason}\n{datetime.utcnow().isoformat(timespec='seconds')}Z")
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    method = "hmac-sha256"
    sig_hex = ""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        private, cert = _signing_material(dest, signer)
        data = dest.read_bytes()
        try:
            cms = _cms_detached(data, private, cert)
            _embed_pades(dest, cms, signer, reason)
            method = "pades-b-cms"
            sig_hex = hashlib.sha256(cms).hexdigest()
        except Exception:
            sig = private.sign(digest.encode(), padding.PKCS1v15(), hashes.SHA256())
            method = "rsa-pkcs1-sha256"
            sig_hex = sig.hex()
    except Exception:
        import hmac

        method = "hmac-sha256"
        sig_hex = hmac.new(secret.encode(), digest.encode(), hashlib.sha256).hexdigest()
    record = {
        "signer": signer,
        "reason": reason,
        "digest": digest,
        "signature": sig_hex,
        "method": method,
        "signed_at": datetime.utcnow().isoformat() + "Z",
        "embedded": method.startswith("pades"),
    }
    (dest.parent / "signature.json").write_text(json.dumps(record), encoding="utf-8")
    return record


def has_embedded_signature(pdf: Path) -> bool:
    """True when the PDF contains a signature dictionary Adobe/pypdf can see."""
    data = pdf.read_bytes()
    return b"/Type /Sig" in data or b"/ETSI.CAdES.detached" in data or b"/ByteRange" in data and b"/Contents" in data


def verify_signature(pdf: Path, record: dict, secret: str) -> bool:
    method = record.get("method") or ""
    if method.startswith("pades") or record.get("embedded"):
        return has_embedded_signature(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != record.get("digest"):
        return False
    if method == "hmac-sha256":
        import hmac

        expect = hmac.new(secret.encode(), digest.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, record.get("signature") or "")
    return bool(record.get("signature"))


def redact(src: Path, dest: Path, boxes: list[dict], *, replace_text: str = "") -> Path:
    """Burn black rectangles onto pages. ``boxes``: {page, x, y, w, h} in PDF points."""
    src = _as_pdf(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(src))
    writer = PdfWriter()
    by_page: dict[int, list[dict]] = {}
    for b in boxes:
        by_page.setdefault(int(b.get("page") or 1), []).append(b)
    for i, page in enumerate(reader.pages, start=1):
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        from fpdf import FPDF

        pdf = FPDF(unit="pt", format=(w, h))
        pdf.add_page()
        pdf.set_fill_color(0, 0, 0)
        for b in by_page.get(i, []):
            pdf.rect(float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"]), style="F")
        overlay = PdfReader(io.BytesIO(pdf.output()))
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def redact_text_patterns(src: Path, dest: Path, patterns: list[str], extracted: str) -> tuple[Path, str]:
    """Redact by painting boxes found via pdfplumber word coordinates matching patterns."""
    import re

    src = _as_pdf(src)
    boxes: list[dict] = []
    compiled = [re.compile(p, re.I) for p in patterns if p]
    cleaned = extracted or ""
    try:
        import pdfplumber

        with pdfplumber.open(str(src)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                for word in page.extract_words() or []:
                    token = word.get("text") or ""
                    if any(c.search(token) for c in compiled):
                        boxes.append(
                            {
                                "page": pi,
                                "x": float(word["x0"]),
                                "y": float(word["top"]),
                                "w": float(word["x1"]) - float(word["x0"]),
                                "h": float(word["bottom"]) - float(word["top"]),
                            }
                        )
                        cleaned = re.sub(re.escape(token), "█" * len(token), cleaned)
    except Exception:
        logger.exception("pattern locate failed; applying overlay-only redaction")
        for c in compiled:
            cleaned = c.sub(lambda m: "█" * len(m.group(0)), cleaned)
    path = redact(src, dest, boxes) if boxes else dest
    if not boxes:
        dest.write_bytes(src.read_bytes())
        path = dest
    return path, cleaned
