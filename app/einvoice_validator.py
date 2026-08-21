"""Tax Compliance and E-Invoicing Validator (PEPPOL BIS Billing 3.0, UBL 2.1, Factur-X)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def validate_peppol_ubl_xml(xml_content: str | bytes) -> dict[str, Any]:
    """Validate PEPPOL BIS Billing 3.0 / UBL XML e-Invoice against statutory schema rules."""
    if isinstance(xml_content, str):
        raw_bytes = xml_content.encode("utf-8")
    else:
        raw_bytes = xml_content

    result: dict[str, Any] = {
        "valid": False,
        "standard": "Unknown",
        "customization_id": "",
        "invoice_number": "",
        "issue_date": "",
        "due_date": "",
        "currency": "",
        "supplier_name": "",
        "supplier_tax_id": "",
        "customer_name": "",
        "subtotal": 0.0,
        "tax_amount": 0.0,
        "payable_amount": 0.0,
        "line_items_count": 0,
        "errors": [],
        "warnings": [],
    }

    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as e:
        result["errors"].append(f"Invalid XML syntax: {e}")
        return result

    # Strip XML namespaces for simplified querying
    tag_clean = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_clean not in ("Invoice", "CreditNote", "CrossIndustryInvoice"):
        result["errors"].append(f"Unsupported root element '{tag_clean}'. Expected 'Invoice' or 'CreditNote'.")
        return result

    # Find element helper ignoring namespaces
    def find_val(elem: ET.Element | None, target_tag: str) -> str:
        if elem is None:
            return ""
        for child in elem.iter():
            local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local_tag == target_tag:
                return (child.text or "").strip()
        return ""

    # 1. Standard & Customization ID
    customization_id = find_val(root, "CustomizationID")
    profile_id = find_val(root, "ProfileID")
    result["customization_id"] = customization_id

    if "peppol" in customization_id.lower() or "en16931" in customization_id.lower():
        result["standard"] = "PEPPOL BIS Billing 3.0"
    elif "ubl" in root.tag.lower():
        result["standard"] = "UBL 2.1"
    elif "crossindustryinvoice" in root.tag.lower():
        result["standard"] = "Factur-X / ZUGFeRD"
    else:
        result["standard"] = "Structured XML E-Invoice"

    # 2. Header data
    result["invoice_number"] = find_val(root, "ID")
    result["issue_date"] = find_val(root, "IssueDate")
    result["due_date"] = find_val(root, "DueDate")
    result["currency"] = find_val(root, "DocumentCurrencyCode") or "EUR"

    if not result["invoice_number"]:
        result["errors"].append("Mandatory element 'cbc:ID' (Invoice Number) missing.")
    if not result["issue_date"]:
        result["errors"].append("Mandatory element 'cbc:IssueDate' missing.")

    # 3. Parties
    supplier_party = None
    customer_party = None
    for child in root.iter():
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "AccountingSupplierParty":
            supplier_party = child
        elif local == "AccountingCustomerParty":
            customer_party = child

    if supplier_party is not None:
        result["supplier_name"] = find_val(supplier_party, "RegistrationName") or find_val(supplier_party, "Name")
        result["supplier_tax_id"] = find_val(supplier_party, "CompanyID")
    else:
        result["errors"].append("Mandatory 'AccountingSupplierParty' missing.")

    if customer_party is not None:
        result["customer_name"] = find_val(customer_party, "RegistrationName") or find_val(customer_party, "Name")
    else:
        result["warnings"].append("Customer party details missing.")

    # 4. Monetary Totals
    try:
        subtotal_str = find_val(root, "TaxExclusiveAmount") or find_val(root, "LineExtensionAmount")
        if subtotal_str:
            result["subtotal"] = float(subtotal_str)

        tax_str = find_val(root, "TaxAmount")
        if tax_str:
            result["tax_amount"] = float(tax_str)

        payable_str = find_val(root, "PayableAmount") or find_val(root, "TaxInclusiveAmount")
        if payable_str:
            result["payable_amount"] = float(payable_str)
    except ValueError as e:
        result["errors"].append(f"Failed to parse monetary total amounts: {e}")

    # 5. Line items count
    lines = [c for c in root.iter() if (c.tag.split("}")[-1] if "}" in c.tag else c.tag) in ("InvoiceLine", "CreditNoteLine")]
    result["line_items_count"] = len(lines)
    if result["line_items_count"] == 0:
        result["warnings"].append("No invoice line items found.")

    result["valid"] = len(result["errors"]) == 0
    return result
