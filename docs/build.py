#!/usr/bin/env python3
"""
Builds the README's view of the nav computer from docs/nav.json:

  assets/nav-computer.svg   a still of the galaxy chart, linked to the live page
  README.md                 the sector list between the nav:start / nav:end markers

    python3 docs/build.py

Standard library only. The live chart is docs/index.html, which reads the same file.
"""

import html
import json
import math
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "nav.json")
SVG_OUT = os.path.join(ROOT, "assets", "nav-computer.svg")
README = os.path.join(ROOT, "README.md")

# chart geometry, matching docs/index.html
CX, CY, R_CORE, R_IN, R_MID, R_OUT = 500, 500, 92, 170, 320, 470
FONT = "'Chakra Petch', 'Segoe UI', Verdana, sans-serif"
LINE, DIM, HOT, GLASS = "#7fe8e0", "#1e5d5a", "#e2fffb", "#031417"


def polar(r, deg):
    a = math.radians(deg - 90)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def P(r, deg):
    x, y = polar(r, deg)
    return f"{x:.1f} {y:.1f}"


def text_box(x, y, label, right, size=25):
    w = len(label) * size * 0.64
    x0 = x + 14 if right else x - 14 - w
    return [min(x0, x - 8), y - size * 0.8, max(x0 + w, x + 8), y + size * 0.35]


def layout(sectors):
    span = 360 / len(sectors)
    items = []
    for si, sec in enumerate(sectors):
        a0 = si * span
        n = len(sec["systems"])
        for k, sys in enumerate(sec["systems"]):
            t = 0.5 if n == 1 else k / (n - 1)
            ang = a0 + span * (0.2 + 0.6 * t)
            band = [1, 0, 2][k % 3] if n <= 3 else k % 3
            items.append({"sys": sys, "ang": ang, "r": R_IN + 45 + band * 95})

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


def glyphs(x, y, count, size, gap, rng):
    pts = [(0, 0), (1, 0), (0, .5), (1, .5), (0, 1), (1, 1), (.5, 0), (.5, 1)]
    d = []
    for i in range(count):
        if rng.random() < 0.14:
            continue
        ox = x + i * (size * 0.62 + gap)
        for _ in range(2 + int(rng.random() * 2)):
            a, b = rng.choice(pts), rng.choice(pts)
            if a != b:
                d.append(f"M{ox + a[0] * size * .62:.1f} {y + a[1] * size:.1f}"
                         f"L{ox + b[0] * size * .62:.1f} {y + b[1] * size:.1f}")
    return (f'<path d="{"".join(d)}" fill="none" stroke="{LINE}" stroke-opacity=".7" '
            f'stroke-width="{size / 7:.1f}" stroke-linecap="square"/>')


def build_svg(data):
    sectors = data["sectors"]
    span = 360 / len(sectors)
    rng = random.Random(1977)
    chart = []
    chart.append(glyphs(-225, -10, 9, 26, 7, rng))
    chart.append(glyphs(-225, 28, 6, 18, 6, rng))
    for r, cls in ((R_IN, "ring"), (R_MID, "ring"), (R_OUT, "main")):
        chart.append(f'<circle class="{cls}" cx="{CX}" cy="{CY}" r="{r}"/>')
    for si, sec in enumerate(sectors):
        a0 = si * span
        jog = 5 if si % 2 else -5
        chart.append(f'<path class="main" d="M{P(R_IN, a0)} L{P(R_MID, a0)} '
                     f'A{R_MID} {R_MID} 0 0 {1 if jog > 0 else 0} {P(R_MID, a0 + jog)} '
                     f'L{P(R_OUT, a0 + jog)}"/>')
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
    chart.append(f'<circle cx="{CX}" cy="{CY}" r="{R_CORE}" fill="{GLASS}" stroke="{LINE}" stroke-width="2.5"/>')
    chart.append(f'<text class="core" x="{CX}" y="{CY + 4}">{html.escape(data["core"]["name"])}</text>')
    chart.append(f'<text class="core sub" x="{CX}" y="{CY + 30}">you are here</text>')
    chart.append(f'<g class="sweep"><path d="M{CX} {CY} L{CX} {CY - R_OUT}" stroke="{HOT}" '
                 f'stroke-opacity=".5" stroke-width="2"/></g>')

    n_sys = sum(len(s["systems"]) for s in sectors)
    role, _, org = data["core"]["role"].partition(" at ")
    readout = [
        '<text class="r-small" x="0" y="0">Core</text>',
        f'<text class="r-big" x="0" y="48">{html.escape(data["core"]["name"])}</text>',
        f'<text class="r-mid" x="0" y="88">{html.escape(role)}</text>',
        f'<text class="r-mid" x="0" y="122">{html.escape(org)}</text>',
        f'<text class="r-small" x="0" y="200">{len(sectors)} sectors, {n_sys} systems</text>',
    ]
    for i, sec in enumerate(sectors):
        y = 252 + i * 44
        readout.append(f'<text class="r-row hot" x="14" y="{y}" text-anchor="middle">{len(sec["systems"])}</text>')
        readout.append(f'<text class="r-row" x="42" y="{y}">{html.escape(sec["name"])}</text>')
    y = 252 + len(sectors) * 44 + 54
    readout += [
        f'<text class="r-small" x="0" y="{y}">Click the chart to open the</text>',
        f'<text class="r-small" x="0" y="{y + 32}">interactive nav computer</text>',
        f'<rect class="caret" x="0" y="{y + 54}" width="16" height="26"/>',
    ]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900" role="img" aria-label="Galaxy chart of Torin's work: {len(sectors)} sectors, {n_sys} systems">
<title>Torin's nav computer</title>
<style>
  text {{ font-family: {FONT}; }}
  .ring {{ fill: none; stroke: {DIM}; stroke-width: 2; }}
  .main {{ fill: none; stroke: {LINE}; stroke-width: 2.5; }}
  .sector {{ fill: {LINE}; font-size: 30px; font-weight: 500; }}
  .sys {{ fill: {LINE}; font-size: 25px; }}
  .dot {{ fill: {HOT}; animation: pulse 4s ease-in-out infinite; }}
  .core {{ fill: {HOT}; font-size: 32px; font-weight: 600; text-anchor: middle; }}
  .core.sub {{ fill: {LINE}; font-size: 18px; font-weight: 400; }}
  .sweep {{ transform-origin: {CX}px {CY}px; animation: sweep 8s linear infinite; }}
  .r-small {{ fill: {LINE}; font-size: 26px; opacity: .8; }}
  .r-big {{ fill: {HOT}; font-size: 46px; font-weight: 600; }}
  .r-mid {{ fill: {LINE}; font-size: 28px; }}
  .r-row {{ fill: {LINE}; font-size: 24px; }}
  .r-row.hot {{ fill: {HOT}; font-weight: 600; }}
  .caret {{ fill: {LINE}; animation: blink 1.1s steps(1) infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
  @keyframes sweep {{ to {{ transform: rotate(360deg); }} }}
  @keyframes blink {{ 50% {{ opacity: 0; }} }}
  @media (prefers-reduced-motion: reduce) {{ .dot, .sweep, .caret {{ animation: none; }} }}
</style>
<defs>
  <radialGradient id="glass" cx="50%" cy="45%" r="70%">
    <stop offset="0" stop-color="#06262a"/><stop offset="1" stop-color="{GLASS}"/>
  </radialGradient>
  <pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse">
    <rect y="2" width="4" height="1" fill="#000" fill-opacity=".22"/>
  </pattern>
</defs>
<rect width="1600" height="900" rx="28" fill="#4a1717"/>
<rect x="24" y="24" width="1064" height="852" rx="20" fill="#160707"/>
<rect x="40" y="40" width="1032" height="820" rx="12" fill="url(#glass)"/>
<svg x="40" y="40" width="1032" height="820" viewBox="-250 -40 1500 1080" preserveAspectRatio="xMidYMid meet">
{chr(10).join(chart)}
</svg>
<rect x="40" y="40" width="1032" height="820" rx="12" fill="url(#scan)"/>
<rect x="1108" y="24" width="468" height="852" rx="20" fill="#160707"/>
<rect x="1124" y="40" width="436" height="820" rx="12" fill="url(#glass)"/>
<g transform="translate(1160 110)">
{chr(10).join(readout)}
</g>
<rect x="1124" y="40" width="436" height="820" rx="12" fill="url(#scan)"/>
<circle cx="1520" cy="824" r="7" fill="#ff4433"/><circle cx="1496" cy="824" r="7" fill="#ffb340"/>
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
    os.makedirs(os.path.dirname(SVG_OUT), exist_ok=True)
    with open(SVG_OUT, "w", encoding="utf-8") as f:
        f.write(build_svg(data))
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
