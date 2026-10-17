"""Tiny SVG drawing kit used by build_diagrams.py (standard library only).

Logos are read from docs/architecture/logos/*.svg and embedded as base64 data URIs, so the finished
diagrams are single self-contained files that render on GitHub with no external requests.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

HERE = Path(__file__).parent
LOGOS = HERE / "logos"

FONT = "Inter, 'Segoe UI', Helvetica, Arial, 'DejaVu Sans', sans-serif"
MONO = "'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"
INK = "#0F172A"
MUTED = "#475569"
FAINT = "#94A3B8"

# name -> (stroke / accent, light background)
PAL = {
    "blue": ("#229ED9", "#E6F4FC"),     # Telegram
    "indigo": ("#4F46E5", "#EEF2FF"),   # Cadence application code
    "teal": ("#0F766E", "#E6F7F4"),     # accounts service
    "sky": ("#0284C7", "#E8F5FD"),      # dashboard
    "purple": ("#7C3AED", "#F3EEFF"),   # LLM and agents
    "amber": ("#C2410C", "#FFF3E0"),    # deterministic rules / engines
    "slate": ("#475569", "#F1F5F9"),    # external services
    "red": ("#DC2626", "#FEECEC"),      # failure paths
    "green": ("#15803D", "#E9F8EE"),
    "data": ("#0369A1", "#E3F1FA"),     # databases
}

# Simple Icons are single-colour glyphs with no fill; give them their brand colour.
TINT = {
    "telegram": "#26A5E4",
    "gmail": "#EA4335",
    "pydantic": "#E92063",
    "jsonwebtokens": "#D63AFF",
    "ollama": "#111827",
}

_UNCOLOURED = {"github", "ollama"}  # fine as they are (dark glyphs)


def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


# ---- optional text measuring, used only to warn about overflowing text ----------------------
try:  # pragma: no cover - convenience only
    from PIL import ImageFont

    _fonts: dict = {}

    def measure(s: str, size: float, bold: bool = False, mono: bool = False) -> float:
        name = "DejaVuSansMono" if mono else ("DejaVuSans-Bold" if bold else "DejaVuSans")
        key = (name, round(size * 4))
        if key not in _fonts:
            _fonts[key] = ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}.ttf", int(round(size * 4)))
        return _fonts[key].getlength(s) / 4

except Exception:  # noqa: BLE001

    def measure(s: str, size: float, bold: bool = False, mono: bool = False) -> float:
        return len(s) * size * (0.62 if bold else 0.58)


class Doc:
    def __init__(self, w: int, h: int, title: str, subtitle: str = "", part: str = ""):
        self.w, self.h = w, h
        self.body: list[str] = []
        self.markers: dict[str, str] = {}
        self.warnings: list[str] = []
        self._logo_cache: dict[str, str] = {}
        self.rect(0, 0, w, h, "#FFFFFF", rx=0)
        self.text(34, 46, title, size=28, weight=800)
        if subtitle:
            self.text(34, 74, subtitle, size=15, fill=MUTED)
        if part:
            self.pill(w - 34, 36, part, "indigo", anchor="end", size=13)

    # ---- primitives --------------------------------------------------------------------
    def rect(self, x, y, w, h, fill="#FFF", stroke=None, sw=1.5, rx=10, dash=None, opacity=None):
        a = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        if dash:
            a += f' stroke-dasharray="{dash}"'
        if opacity is not None:
            a += f' opacity="{opacity}"'
        self.body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{a}/>')

    def text(self, x, y, s, size=13.5, weight=400, fill=INK, anchor="start", mono=False, maxw=None, italic=False):
        if maxw is not None:
            width = measure(s, size, bold=weight >= 600, mono=mono)
            if width > maxw:
                self.warnings.append(f"overflow {width:.0f}>{maxw:.0f}: {s!r}")
        fam = MONO if mono else FONT
        st = ' font-style="italic"' if italic else ""
        self.body.append(
            f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{st}>{esc(s)}</text>'
        )

    def logo(self, name, x, y, size=26):
        if name not in self._logo_cache:
            svg = (LOGOS / f"{name}.svg").read_text()
            if name in TINT:
                svg = svg.replace("<svg ", f'<svg fill="{TINT[name]}" ', 1)
            self._logo_cache[name] = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        self.body.append(
            f'<image x="{x}" y="{y}" width="{size}" height="{size}" href="{self._logo_cache[name]}" '
            f'preserveAspectRatio="xMidYMid meet"/>'
        )

    def marker(self, color: str, start: bool = False) -> str:
        key = f"{'s' if start else 'e'}{color[1:]}"
        if key not in self.markers:
            if start:
                path = f'<path d="M10,0 L0,5 L10,10 z" fill="{color}"/>'
                self.markers[key] = (
                    f'<marker id="m{key}" markerWidth="11" markerHeight="10" refX="1" refY="5" '
                    f'orient="auto" markerUnits="userSpaceOnUse">{path}</marker>'
                )
            else:
                path = f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/>'
                self.markers[key] = (
                    f'<marker id="m{key}" markerWidth="11" markerHeight="10" refX="9" refY="5" '
                    f'orient="auto" markerUnits="userSpaceOnUse">{path}</marker>'
                )
        return f"m{key}"

    def arrow(self, pts, color="#334155", both=False, dashed=False, width=2.2):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        extra = ' stroke-dasharray="7 5"' if dashed else ""
        start = f' marker-start="url(#{self.marker(color, True)})"' if both else ""
        self.body.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"'
            f'{extra} marker-end="url(#{self.marker(color)})"{start}/>'
        )

    def pill(self, x, y, s, color="slate", anchor="middle", size=12.5, solid=True):
        """Small rounded label. (x, y) is the vertical middle; anchor decides horizontal alignment."""
        stroke, bg = PAL[color]
        w = measure(s, size, bold=True) + 18
        left = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        self.rect(left, y - 11, w, 22, stroke if solid else bg, stroke, 1.2, rx=11)
        self.text(left + w / 2, y + 4.5, s, size=size, weight=700, fill="#FFF" if solid else stroke, anchor="middle")

    def label(self, x, y, s, color="#334155", size=12):
        """White-backed text centred on (x, y), for annotating arrows."""
        w = measure(s, size, bold=True) + 14
        self.rect(x - w / 2, y - 10, w, 20, "#FFFFFF", color, 1, rx=10)
        self.text(x, y + 4.2, s, size=size, weight=700, fill=color, anchor="middle")

    def badge(self, cx, cy, n, color="#1E293B", r=13):
        self.body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" stroke="#FFF" stroke-width="2"/>')
        self.text(cx, cy + 5, str(n), size=14 if r >= 12 else 11, weight=800, fill="#FFF", anchor="middle")

    # ---- composite shapes -----------------------------------------------------------------
    def card(self, x, y, w, h, title, lines=(), logos=(), color="indigo", num=None, tsize=16,
             size=13.5, dashed=False, header=44, shadow=True, example=None):
        stroke, bg = PAL[color]
        if shadow:
            self.rect(x + 3, y + 4, w, h, "#CBD5E1", rx=12, opacity=0.55)
        self.rect(x, y, w, h, "#FFFFFF", rx=12)
        r = 12
        self.body.append(
            f'<path d="M{x},{y + r} a{r},{r} 0 0 1 {r},-{r} h{w - 2 * r} a{r},{r} 0 0 1 {r},{r} v{header - r} h-{w} z" '
            f'fill="{bg}"/>'
        )
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self.body.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="none" stroke="{stroke}" '
            f'stroke-width="1.9"{dash}/>'
        )
        self.body.append(
            f'<line x1="{x}" y1="{y + header}" x2="{x + w}" y2="{y + header}" stroke="{stroke}" '
            f'stroke-opacity="0.35" stroke-width="1"/>'
        )
        left = x + 14
        if num is not None:
            self.badge(x + 26, y + header / 2, num, stroke, r=14)
            left = x + 50
        logos_w = len(logos) * 32
        for i, name in enumerate(logos):
            self.logo(name, x + w - 12 - logos_w + i * 32 + 3, y + (header - 26) / 2, 26)
        self.text(left, y + header / 2 + 5.5, title, size=tsize, weight=700, fill=stroke if color != "slate" else INK,
                  maxw=x + w - logos_w - 12 - left)
        ly = y + header + 23
        for line in lines:
            fill, weight = INK, 400
            if isinstance(line, tuple):
                parts = list(line)
                line = parts[0]
                fill = parts[1] if len(parts) > 1 else INK
                weight = parts[2] if len(parts) > 2 else 400
            self.text(x + 16, ly, line, size=size, fill=fill, weight=weight, maxw=w - 30)
            ly += size + 5.5
        body_end = ly - (size + 5.5)
        if example:
            eh = 14 + len(example) * 17
            ey = y + h - eh - 10
            self.rect(x + 10, ey, w - 20, eh, bg, stroke, 1.1, rx=8)
            self.text(x + 20, ey + 20, "e.g.", size=12.5, weight=800, fill=stroke)
            for i, line in enumerate(example):
                self.text(x + 54, ey + 20 + i * 17, line, size=12.5, fill=INK, maxw=w - 54 - 14)
            if body_end > ey - 4:
                self.warnings.append(f"example strip overlaps text: {title!r}")
        elif body_end > y + h - 6:
            self.warnings.append(f"card too short: {title!r} needs {ly - y:.0f} has {h}")

    def group(self, x, y, w, h, title, color="slate", logos=(), dashed=True):
        stroke, bg = PAL[color]
        self.rect(x, y, w, h, bg, stroke, 1.8, rx=16, dash="9 6" if dashed else None, opacity=None)
        lw = len(logos) * 30
        for i, name in enumerate(logos):
            self.logo(name, x + 12 + i * 30, y + 8, 24)
        self.text(x + 16 + lw, y + 26, title, size=15, weight=700, fill=stroke, maxw=w - 30 - lw)

    def chip(self, x, y, s, logo=None, color="slate", size=12.5, mono=False):
        """Rounded tag with an optional logo. (x, y) = top-left. Returns its width."""
        stroke, bg = PAL[color]
        pad = 10
        tw = measure(s, size, bold=False, mono=mono)
        w = tw + 2 * pad + (24 if logo else 0)
        self.rect(x, y, w, 28, bg, stroke, 1.2, rx=14)
        tx = x + pad
        if logo:
            self.logo(logo, x + 8, y + 4, 20)
            tx = x + 34
        self.text(tx, y + 18.5, s, size=size, fill=INK, mono=mono)
        return w

    def service(self, x, y, w, h, title, sub, logo=None, color="slate", monogram=None, sub2=None):
        """Compact external-service card: big logo on the left, name and one or two description lines."""
        stroke, bg = PAL[color]
        self.rect(x + 2, y + 3, w, h, "#CBD5E1", rx=11, opacity=0.55)
        self.rect(x, y, w, h, "#FFFFFF", stroke, 1.8, rx=11)
        size = min(40, h - 20)
        ly = y + (h - size) / 2
        if logo:
            self.logo(logo, x + 12, ly, size)
        elif monogram:
            self.rect(x + 12, ly, size, size, bg, stroke, 1.5, rx=9)
            self.text(x + 12 + size / 2, ly + size / 2 + 5, monogram, size=15, weight=800, fill=stroke, anchor="middle")
        tx = x + 24 + size
        mw = w - (tx - x) - 10
        top = y + h / 2 - (7 if not sub2 else 14)
        self.text(tx, top, title, size=14.5, weight=700, fill=INK, maxw=mw)
        self.text(tx, top + 19, sub, size=12, fill=MUTED, maxw=mw)
        if sub2:
            self.text(tx, top + 35, sub2, size=12, fill=MUTED, maxw=mw)

    def person(self, cx, cy, color="#334155", s=1.0):
        self.body.append(
            f'<g fill="{color}"><circle cx="{cx}" cy="{cy - 9 * s}" r="{8 * s}"/>'
            f'<path d="M{cx - 15 * s},{cy + 17 * s} a{15 * s},{14 * s} 0 0 1 {30 * s},0 z"/></g>'
        )

    def browser(self, x, y, w=44, h=32, color="#334155"):
        self.rect(x, y, w, h, "#FFFFFF", color, 2.2, rx=5)
        self.body.append(f'<rect x="{x}" y="{y}" width="{w}" height="9" rx="4" fill="{color}"/>')
        for i in range(3):
            self.body.append(f'<circle cx="{x + 7 + i * 8}" cy="{y + 4.5}" r="1.8" fill="#FFF"/>')

    def begin_shift(self, dy):
        self.body.append(f'<g transform="translate(0,{dy})">')

    def end_shift(self):
        self.body.append("</g>")

    # ---- output ------------------------------------------------------------------------------
    def svg(self) -> str:
        defs = "".join(self.markers.values())
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img">'
            f"<defs>{defs}</defs>" + "".join(self.body) + "</svg>\n"
        )

    def save(self, path: Path):
        path.write_text(self.svg())
        for w in self.warnings:
            print(f"  WARN {path.name}: {w}")
        print(f"wrote {path} ({len(self.svg()) // 1024} KB)")
