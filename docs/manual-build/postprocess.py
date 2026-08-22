"""Post-process the manual docx: footer PAGE format switches + pgNumType cleanup."""
import re
import shutil
import sys
import zipfile
from pathlib import Path

DOCX = Path(sys.argv[1])
TMP = DOCX.with_suffix(".tmp.docx")

with zipfile.ZipFile(DOCX) as zin:
    names = zin.namelist()
    data = {n: zin.read(n) for n in names}

doc_xml = data["word/document.xml"].decode("utf-8")

# 1. Remove empty pgNumType emitted for the cover section (confuses WPS).
doc_xml = doc_xml.replace("<w:pgNumType/>", "")

# 2. Map each section's footerReference to its footer part via rels.
rels_xml = data["word/_rels/document.xml.rels"].decode("utf-8")
rid_to_target = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="(footer\d+\.xml)"', rels_xml))

# Footer references appear in document order: section2 (TOC) then section3 (body).
footer_files = [rid_to_target[rid] for rid in re.findall(
    r'<w:footerReference[^>]*r:id="(rId\d+)"', doc_xml) if rid in rid_to_target]
print("footer order:", footer_files)

fmt_by_index = ["ROMAN", "arabic"]  # section 2 footer -> Roman, section 3 -> arabic
for i, fname in enumerate(footer_files):
    key = "word/" + fname
    fmt = fmt_by_index[min(i, 1)]
    xml = data[key].decode("utf-8")
    xml, n = re.subn(
        r"(<w:instrText[^>]*>)\s*PAGE\s*(</w:instrText>)",
        rf"\1 PAGE \\* {fmt} \\* MERGEFORMAT \2",
        xml,
    )
    print(f"{key}: patched {n} PAGE field(s) -> \\* {fmt}")
    data[key] = xml.encode("utf-8")

data["word/document.xml"] = doc_xml.encode("utf-8")

with zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED) as zout:
    for n in names:
        zout.writestr(n, data[n])
shutil.move(TMP, DOCX)
print("post-process done:", DOCX)
