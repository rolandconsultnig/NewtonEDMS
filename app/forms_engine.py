"""HTML form generation from JSON schema and barcode rendering."""
from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path


def render_form(schema: dict, action: str, title: str = "Capture") -> str:
    fields = schema.get("fields") or schema.get("properties") or []
    if isinstance(fields, dict):
        fields = [{"name": k, **(v if isinstance(v, dict) else {"type": "text"})} for k, v in fields.items()]
    inputs = []
    for f in fields:
        name = escape(str(f.get("name") or f.get("id") or "field"))
        label = escape(str(f.get("label") or name))
        ftype = f.get("type") or "text"
        req = "required" if f.get("required") else ""
        if ftype == "textarea":
            inputs.append(f"<label>{label}<textarea name='{name}' {req}></textarea></label>")
        elif ftype == "select":
            opts = "".join(f"<option>{escape(str(o))}</option>" for o in (f.get("options") or []))
            inputs.append(f"<label>{label}<select name='{name}' {req}>{opts}</select></label>")
        elif ftype == "file":
            inputs.append(f"<label>{label}<input type='file' name='{name}' {req}/></label>")
        else:
            inputs.append(f"<label>{label}<input type='{escape(ftype)}' name='{name}' {req}/></label>")
    body = "".join(inputs)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width"/>
    <title>{escape(title)}</title>
    <style>body{{font-family:sans-serif;max-width:32rem;margin:2rem auto;padding:1rem}}
    label{{display:block;margin:.6rem 0}}input,select,textarea{{width:100%;padding:.4rem}}</style></head>
    <body><h1>{escape(title)}</h1>
    <form method="post" action="{escape(action)}" enctype="multipart/form-data">{body}
    <button type="submit">Submit</button></form></body></html>"""


# Code128B encoding table (start B = 104, stop = 106). Values are bar/space widths.
_CODE128_B = [
    "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
    "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
    "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
    "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
    "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
    "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
    "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
    "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
    "114131","311141","411131","211412","211214","211232","2331112",
]


def code128_png(data: str, dest: Path | None = None) -> bytes:
    from PIL import Image, ImageDraw

    chars = []
    checksum = 104
    for i, ch in enumerate(data):
        val = ord(ch) - 32
        if val < 0 or val > 94:
            val = 0
        chars.append(val)
        checksum += val * (i + 1)
    checksum %= 103
    pattern = _CODE128_B[104] + "".join(_CODE128_B[v] for v in chars) + _CODE128_B[checksum] + _CODE128_B[106]
    modules = []
    bar = True
    for w in pattern:
        modules.extend([1 if bar else 0] * int(w))
        bar = not bar
    scale, height = 2, 60
    img = Image.new("RGB", (len(modules) * scale + 20, height + 10), "white")
    draw = ImageDraw.Draw(img)
    x = 10
    for m in modules:
        if m:
            draw.rectangle([x, 5, x + scale - 1, height], fill="black")
        x += scale
    buf = BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    if dest:
        dest.write_bytes(raw)
    return raw
