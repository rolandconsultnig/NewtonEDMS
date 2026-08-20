"""SAML 2.0 SP-initiated SSO with optional XML signature and certificate checks."""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import now
from app.models import OidcState, SystemSetting, User
from app.security import get_password_hash

NS = {
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


def _saml_cfg(db: Session | None = None) -> dict:
    cfg = {
        "idp_sso_url": getattr(settings, "saml_idp_sso_url", "") or "",
        "entity_id": getattr(settings, "saml_entity_id", "") or "",
        "acs_url": getattr(settings, "saml_acs_url", "") or getattr(settings, "oidc_redirect_uri", "") or "",
        "idp_cert": getattr(settings, "saml_idp_cert", "") or "",
        "require_signature": bool(getattr(settings, "saml_require_signature", False)),
    }
    if db is not None:
        row = db.get(SystemSetting, "saml")
        if row and row.value:
            try:
                import json

                extra = json.loads(row.value) if isinstance(row.value, str) else (row.value or {})
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        if v not in (None, ""):
                            cfg[k] = v
            except Exception:
                pass
    return cfg


def enabled(db: Session | None = None) -> bool:
    cfg = _saml_cfg(db)
    return bool(cfg.get("idp_sso_url") and cfg.get("entity_id"))


def authn_request_redirect(db: Session) -> str:
    cfg = _saml_cfg(db)
    if not (cfg.get("idp_sso_url") and cfg.get("entity_id")):
        raise HTTPException(status_code=400, detail="SAML is not configured")
    request_id = "_" + secrets.token_hex(16)
    db.add(OidcState(state=request_id, nonce="saml", expires_at=now() + timedelta(minutes=10)))
    db.commit()
    issue = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    entity = cfg["entity_id"]
    acs = cfg.get("acs_url") or ""
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="{request_id}" Version="2.0" '
        f'IssueInstant="{issue}" AssertionConsumerServiceURL="{acs}" ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{entity}</saml:Issuer></samlp:AuthnRequest>"
    )
    deflated = zlib.compress(xml.encode("utf-8"))[2:-4]
    b64 = base64.b64encode(deflated).decode("ascii")
    return cfg["idp_sso_url"] + "?" + urlencode({"SAMLRequest": b64, "RelayState": request_id})


def _load_cert_der(pem_or_der: str | bytes) -> bytes:
    raw = pem_or_der.encode() if isinstance(pem_or_der, str) else pem_or_der
    text = raw.decode("utf-8", errors="ignore").strip()
    if "BEGIN CERTIFICATE" in text:
        body = "".join(text.split("-----")[2].split())
        return base64.b64decode(body)
    compact = re.sub(r"\s+", "", text)
    try:
        return base64.b64decode(compact)
    except Exception:
        return raw


def _cert_fingerprint(pem_or_der: str | bytes) -> str:
    der = _load_cert_der(pem_or_der)
    return hashlib.sha256(der).hexdigest()


def _extract_response_cert(root: ET.Element) -> str | None:
    for el in root.iter():
        if el.tag.endswith("X509Certificate") and (el.text or "").strip():
            return (el.text or "").strip()
    return None


def _verify_xml_signature(xml_bytes: bytes, idp_cert: str) -> bool:
    """Verify the enveloped XML signature with the configured IdP certificate.

    Uses cryptography RSA-SHA256 over a C14N-lite of SignedInfo when present.
    Returns False if verification cannot be completed.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from cryptography.x509 import load_der_x509_certificate
    except Exception:
        return False
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return False
    sig_value = None
    signed_info = None
    for el in root.iter():
        if el.tag.endswith("SignatureValue"):
            sig_value = re.sub(r"\s+", "", el.text or "")
        if el.tag.endswith("SignedInfo"):
            signed_info = el
    if not sig_value or signed_info is None:
        return False
    try:
        cert = load_der_x509_certificate(_load_cert_der(idp_cert))
        public = cert.public_key()
        signed_xml = ET.tostring(signed_info, encoding="utf-8")
        signature = base64.b64decode(sig_value)
        if isinstance(public, rsa.RSAPublicKey):
            public.verify(signature, signed_xml, padding.PKCS1v15(), hashes.SHA256())
            return True
    except Exception:
        # Many IdPs use exclusive C14N; fingerprint match is still required by caller.
        return False
    return False


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        try:
            return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def consume(db: Session, saml_response: str, relay_state: str | None) -> User:
    cfg = _saml_cfg(db)
    try:
        xml = base64.b64decode(saml_response)
        root = ET.fromstring(xml)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid SAMLResponse: {exc}") from exc

    if relay_state:
        st = db.query(OidcState).filter(OidcState.state == relay_state).first()
        if not st or (st.expires_at and st.expires_at < now()):
            raise HTTPException(status_code=400, detail="Unknown or expired RelayState")
        db.delete(st)
        db.commit()

    not_on_or_after = None
    for el in root.iter():
        if el.tag.endswith("Conditions"):
            not_on_or_after = el.attrib.get("NotOnOrAfter")
            break
    expiry = _parse_time(not_on_or_after)
    if expiry and expiry < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="SAML assertion has expired")

    idp_cert = cfg.get("idp_cert") or ""
    resp_cert = _extract_response_cert(root)
    if idp_cert:
        expected = _cert_fingerprint(idp_cert)
        if resp_cert:
            got = _cert_fingerprint(resp_cert)
            if got != expected:
                raise HTTPException(status_code=400, detail="IdP certificate mismatch")
        elif cfg.get("require_signature"):
            raise HTTPException(status_code=400, detail="SAML response is missing an IdP certificate")
        if cfg.get("require_signature") and not _verify_xml_signature(xml, idp_cert):
            raise HTTPException(status_code=400, detail="SAML signature validation failed")
    elif cfg.get("require_signature"):
        raise HTTPException(status_code=400, detail="SAML IdP certificate is not configured")

    nameid = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    email_el = root.find(
        ".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute[@Name='email']/{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue"
    )
    name = (nameid.text if nameid is not None else "") or ""
    email = (email_el.text if email_el is not None else "") or ""
    if not name and not email:
        av = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue")
        name = (av.text if av is not None else "") or f"saml_{secrets.token_hex(4)}"
    username = (email.split("@")[0] if email else name)[:80]
    user = (
        db.query(User).filter((User.username == username) | (User.email == email)).first()
        if email
        else db.query(User).filter(User.username == username).first()
    )
    if not user:
        user = User(
            username=username,
            email=email or None,
            hashed_password=get_password_hash(secrets.token_urlsafe(24)),
            role="user",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
