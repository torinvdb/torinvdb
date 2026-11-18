#!/usr/bin/env python3
"""
Builds the README's view of the nav computer from docs/nav.json:

  assets/nav-computer.svg   a still of the galaxy chart, linked to the live page
  README.md                 the sector list between the nav:start / nav:end markers

    python3 docs/build.py

Standard library only. The live chart is docs/index.html, which reads the same file.
The Aurebesh font (docs/fonts, SIL OFL-1.1) is embedded in the SVG because GitHub
serves README images without letting them fetch anything.
"""

import base64
import html
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "nav.json")
FONT_FILE = os.path.join(HERE, "fonts", "Aurebesh.ttf")
SVG_OUT = os.path.join(ROOT, "assets", "nav-computer.svg")
README = os.path.join(ROOT, "README.md")

# chart geometry, matching docs/index.html
CX, CY, R_CORE, R_IN, R_MID, R_OUT = 500, 500, 92, 170, 320, 470
SANS = "'Chakra Petch', 'Segoe UI', Verdana, sans-serif"
GREEN, MID, DIM, FAINT, HOT, GLASS = "#6dff9e", "#3fbf6c", "#1c6a3c", "#0e3420", "#e2ffe9", "#020b06"


def polar(r, deg):
    a = math.radians(deg - 90)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def P(r, deg):
    x, y = polar(r, deg)
    return f"{x:.1f} {y:.1f}"


def A(r, a, b):
    return f"A{r} {r} 0 0 {1 if b > a else 0} {P(r, b)}"


def jog(si):
    return 5 if si % 2 else -5


def text_box(x, y, label, right, size=25):
    w = len(label) * size * 0.64
    x0 = x + 14 if right else x - 14 - w
    return [min(x0, x - 8), y - size * 0.8, max(x0 + w, x + 8), y + size * 0.35]


def layout(sectors):
    """Same placement as the live page: three radial bands, then nudge apart."""
    span = 360 / len(sectors)
    items = []
    for si, sec in enumerate(sectors):
        a0 = si * span
        n = len(sec["systems"])
        for k, sys in enumerate(sec["systems"]):
            t = 0.5 if n == 1 else k / (n - 1)
            band = [1, 0, 2][k % 3] if n <= 3 else k % 3
            items.append({"sys": sys, "ang": a0 + span * (0.2 + 0.6 * t), "r": R_IN + 45 + band * 95})

    def geom(it):
        x, y = polar(it["r"], it["ang"])
        right = x >= CX - 10
        return x, y, right, text_box(x, y, it["sys"]["name"], right)

    for _ in range(60):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = geom(items[i])[3], geom(items[j])[3]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    lo, hi = sorted((items[i], items[j]), key=lambda it: it["r"])
                    lo["r"] = max(R_IN + 34, lo["r"] - 9)
                    hi["r"] = min(R_OUT - 30, hi["r"] + 9)
                    moved = True
        if not moved:
            break
    return [(it, *geom(it)[:3]) for it in items]


def chamfer(x, y, w, h, c):
    return (f"M{x + c} {y}H{x + w - c}L{x + w} {y + c}V{y + h - c}L{x + w - c} {y + h}"
            f"H{x + c}L{x} {y + h - c}V{y + c}Z")


def brackets(x, y, w, h, b=18):
    return (f"M{x} {y + b}V{y}H{x + b}M{x + w - b} {y}H{x + w}V{y + b}"
            f"M{x + w} {y + h - b}V{y + h}H{x + w - b}M{x + b} {y + h}H{x}V{y + h - b}")


def screen(x, y, w, h):
    """Bezel edge, dark inner frame, then the glass with grid, brackets and scanlines."""
    return f"""
<path d="{chamfer(x, y, w, h, 22)}" fill="#4a5652"/>
<path d="{chamfer(x + 2, y + 2, w - 4, h - 4, 21)}" fill="#0b0e0e"/>
<path d="{chamfer(x + 14, y + 14, w - 28, h - 28, 14)}" fill="url(#glass)"/>
<path d="{chamfer(x + 14, y + 14, w - 28, h - 28, 14)}" fill="url(#grid)"/>
<path d="{chamfer(x + 14, y + 14, w - 28, h - 28, 14)}" fill="none" stroke="{FAINT}" stroke-width="1.5"/>
<path d="{brackets(x + 24, y + 24, w - 48, h - 48)}" fill="none" stroke="{DIM}" stroke-width="2.5"/>"""


def build_svg(data, font_b64):
    sectors = data["sectors"]
    span = 360 / len(sectors)
    n_sys = sum(len(s["systems"]) for s in sectors)

    chart = [
        '<text class="ab" x="-225" y="30" font-size="30">torin</text>',
        '<text class="ab" x="-225" y="64" font-size="20">sector map</text>',
    ]
    for r, cls in ((R_IN, "ring"), (R_MID, "ring"), (R_OUT, "main")):
        chart.append(f'<circle class="{cls}" cx="{CX}" cy="{CY}" r="{r}"/>')
    for si, sec in enumerate(sectors):
        a0 = si * span
        j0 = a0 + jog(si)
        chart.append(f'<path class="main" d="M{P(R_IN, a0)} L{P(R_MID, a0)} {A(R_MID, a0, j0)} L{P(R_OUT, j0)}"/>')
        nx, ny = polar(R_OUT + 40, a0 + span / 2)
        anchor = "middle" if abs(nx - CX) < 40 else ("start" if nx > CX else "end")
        chart.append(f'<text class="sector" x="{nx:.1f}" y="{ny + 7:.1f}" '
                     f'text-anchor="{anchor}">{html.escape(sec["name"])}</text>')
    for i, (it, x, y, right) in enumerate(layout(sectors)):
        tx = x + 14 if right else x - 14
        chart.append(f'<circle class="dot" style="animation-delay:{(i * 0.37) % 4:.2f}s" '
                     f'cx="{x:.1f}" cy="{y:.1f}" r="7"/>')
        chart.append(f'<text class="sys" x="{tx:.1f}" y="{y + 6:.1f}" '
                     f'text-anchor="{"start" if right else "end"}">{html.escape(it["sys"]["name"])}</text>')
    chart.append(f'<circle cx="{CX}" cy="{CY}" r="{R_CORE}" fill="{GLASS}" stroke="{GREEN}" stroke-width="2.5"/>')
    chart.append(f'<text class="core" x="{CX}" y="{CY + 4}">{html.escape(data["core"]["name"])}</text>')
    chart.append(f'<text class="core sub" x="{CX}" y="{CY + 30}">you are here</text>')
    chart.append(f'<g class="sweep"><path d="M{CX} {CY} L{CX} {CY - R_OUT}" stroke="{HOT}" '
                 f'stroke-opacity=".55" stroke-width="2.5"/></g>')

    role, _, org = data["core"]["role"].partition(" at ")
    readout = [
        f'<text class="r-small" x="0" y="0">Core</text>',
        f'<text class="r-big" x="0" y="48">{html.escape(data["core"]["name"])}</text>',
        f'<text class="r-mid" x="0" y="88">{html.escape(role)}</text>',
        f'<text class="r-mid" x="0" y="122">{html.escape(org)}</text>',
        f'<text class="r-small" x="0" y="196">{len(sectors)} sectors, {n_sys} systems</text>',
    ]
    for i, sec in enumerate(sectors):
        y = 246 + i * 42
        readout.append(f'<text class="r-row hot" x="14" y="{y}" text-anchor="middle">{len(sec["systems"])}</text>')
        readout.append(f'<text class="r-row" x="42" y="{y}">{html.escape(sec["name"])}</text>')
    y = 246 + len(sectors) * 42 + 40
    readout += [
        f'<text class="r-small" x="0" y="{y}">Click the chart to open the</text>',
        f'<text class="r-small" x="0" y="{y + 32}">interactive nav computer</text>',
        f'<rect class="caret" x="0" y="{y + 52}" width="16" height="26"/>',
    ]

    # control deck: one key per sector, plus the return key
    keys, kx = [], 132
    for sec in sectors:
        w = 46 + len(sec["name"]) * 12
        keys.append(f'<path d="{chamfer(kx, 0, w, 48, 8)}" fill="url(#key)"/>'
                    f'<circle cx="{kx + 20}" cy="24" r="4.5" fill="#2a1110"/>'
                    f'<text class="key" x="{kx + 34}" y="32">{html.escape(sec["name"])}</text>')
        kx += w + 12

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" width="1600" height="1000" role="img" aria-label="Galaxy chart of Torin's work: {len(sectors)} sectors, {n_sys} systems">
<title>Torin's nav computer</title>
<style>
  @font-face {{ font-family: "Aurebesh"; src: url(data:font/ttf;base64,{font_b64}) format("truetype"); }}
  text {{ font-family: {SANS}; }}
  .ab {{ font-family: "Aurebesh", sans-serif; fill: {MID}; }}
  .ring {{ fill: none; stroke: {DIM}; stroke-width: 2; }}
  .main {{ fill: none; stroke: {GREEN}; stroke-width: 2.5; }}
  .sector {{ fill: {MID}; font-size: 30px; font-weight: 500; }}
  .sys {{ fill: {GREEN}; font-size: 25px; }}
  .dot {{ fill: {HOT}; animation: pulse 4s ease-in-out infinite; }}
  .core {{ fill: {HOT}; font-size: 32px; font-weight: 600; text-anchor: middle; }}
  .core.sub {{ fill: {MID}; font-size: 18px; font-weight: 400; }}
  .sweep {{ transform-origin: {CX}px {CY}px; animation: sweep 8s linear infinite; }}
  .r-small {{ fill: {MID}; font-size: 26px; }}
  .r-big {{ fill: {HOT}; font-size: 46px; font-weight: 600; }}
  .r-mid {{ fill: {GREEN}; font-size: 28px; }}
  .r-row {{ fill: {GREEN}; font-size: 24px; }}
  .r-row.hot {{ fill: {HOT}; font-weight: 600; }}
  .bar {{ fill: {DIM}; font-size: 20px; }}
  .title {{ fill: #dfe9e5; font-size: 30px; font-weight: 600; }}
  .label {{ fill: #a7b6b1; font-size: 22px; }}
  .key {{ fill: #d6e3df; font-size: 21px; font-weight: 500; }}
  .caret {{ fill: {GREEN}; animation: blink 1.1s steps(1) infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
  @keyframes sweep {{ to {{ transform: rotate(360deg); }} }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  @media (prefers-reduced-motion: reduce) {{ .dot, .sweep, .caret {{ animation: none; }} }}
</style>
<defs>
  <radialGradient id="glass" cx="50%" cy="45%" r="72%">
    <stop offset="0" stop-color="#052012"/><stop offset="1" stop-color="{GLASS}"/>
  </radialGradient>
  <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
    <path d="M32 0H0V32" fill="none" stroke="{GREEN}" stroke-opacity=".05"/>
  </pattern>
  <pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse">
    <rect y="2" width="4" height="1" fill="#000" fill-opacity=".25"/>
  </pattern>
  <linearGradient id="hull" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#262c2e"/><stop offset=".3" stop-color="#171b1c"/>
  </linearGradient>
  <linearGradient id="key" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#323a3b"/><stop offset="1" stop-color="#222829"/>
  </linearGradient>
  <radialGradient id="screw" cx="35%" cy="35%" r="65%">
    <stop offset="0" stop-color="#5a6461"/><stop offset="1" stop-color="#1b2020"/>
  </radialGradient>
</defs>

<path d="{chamfer(0, 0, 1600, 1000, 30)}" fill="#39423f"/>
<path d="{chamfer(2, 2, 1596, 996, 29)}" fill="url(#hull)"/>

<circle cx="44" cy="44" r="7" fill="url(#screw)"/>
<text class="title" x="66" y="55">Torin's nav computer</text>
<text class="ab" x="470" y="54" font-size="24">nav computer</text>
<text class="label" x="1352" y="52">Uplink</text><circle cx="1436" cy="45" r="6.5" fill="{GREEN}"/>
<text class="label" x="1458" y="52">Power</text><circle cx="1532" cy="45" r="6.5" fill="#ff4a3a"/>
<circle cx="1562" cy="44" r="7" fill="url(#screw)"/>

{screen(24, 84, 1036, 760)}
<text class="ab" x="76" y="134" font-size="20">galaxy chart</text>
<text class="bar" x="1008" y="134" text-anchor="end">{len(sectors)} sectors, {n_sys} systems</text>
<svg x="50" y="146" width="984" height="680" viewBox="-250 -20 1500 1060" preserveAspectRatio="xMidYMid meet">
{chr(10).join(chart)}
</svg>
<path d="{chamfer(38, 98, 1008, 732, 14)}" fill="url(#scan)"/>

{screen(1076, 84, 500, 760)}
<text class="ab" x="1128" y="134" font-size="20">readout</text>
<text class="bar" x="1524" y="134" text-anchor="end">Standing by</text>
<g transform="translate(1130 196)">
{chr(10).join(readout)}
</g>
<path d="{chamfer(1090, 98, 472, 732, 14)}" fill="url(#scan)"/>

<path d="{chamfer(24, 862, 1552, 112, 14)}" fill="#0a0d0d"/>
<path d="{chamfer(26, 864, 1548, 108, 13)}" fill="#151a1b"/>
<text class="label" x="48" y="926">Sectors</text>
<g transform="translate(0 894)">
{"".join(keys)}
</g>
</svg>
"""


def build_list(data):
    out = []
    for sec in data["sectors"]:
        out.append(f"### {sec['name']}\n")
        for sys in sec["systems"]:
            meta = ", ".join(x for x in (sys.get("kind"), sys.get("year")) if x)
            links = ", ".join(f"[{l['label']}]({l['url']})" for l in sys["links"])
            # entries with links stay to one line; the full readouts live in the nav computer
            detail = links if links else sys["text"]
            out.append(f"- **{sys['name']}** ({meta}): {detail}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main():
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    with open(FONT_FILE, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode("ascii")
    os.makedirs(os.path.dirname(SVG_OUT), exist_ok=True)
    with open(SVG_OUT, "w", encoding="utf-8") as f:
        f.write(build_svg(data, font_b64))
    with open(README, encoding="utf-8") as f:
        readme = f.read()
    block = "<!-- nav:start -->\n" + build_list(data) + "<!-- nav:end -->"
    new, n = re.subn(r"<!-- nav:start -->.*?<!-- nav:end -->", lambda _: block, readme, flags=re.S)
    if n != 1:
        raise SystemExit("README.md needs exactly one <!-- nav:start --> ... <!-- nav:end --> block")
    with open(README, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"wrote {os.path.relpath(SVG_OUT, ROOT)} and the README list")


if __name__ == "__main__":
    main()
