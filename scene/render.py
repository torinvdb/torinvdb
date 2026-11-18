#!/usr/bin/env python3
"""
Hello there.

A 2D pixel-art scene for the profile README, drawn entirely in code: no image
files, no font files, no third-party packages. Every pixel comes from the
geometry below. Frames stream to ffmpeg, which builds one palette, upscales
with nearest neighbour and writes the GIF.

    python3 scene/render.py                       # writes assets/hello-there.gif
    python3 scene/render.py --out /tmp/test.gif   # somewhere else

Needs Python 3.9+ and ffmpeg on PATH. Output is deterministic.
"""

import argparse
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

W, H = 432, 243          # native resolution, shown at 2x
FPS = 12
PAN = 300                # how far the camera travels down the main plane
GROUND = 515             # main-plane row the fighters stand on
BEAM_Y = 95              # main-plane row Kenobi crouches on
FLOOR_TOP = GROUND - 70  # back edge of the landing platform

# Parallax speeds relative to the main plane.
SPEED_FAR, SPEED_MID, SPEED_FG = 0.25, 0.55, 1.4

# Characters are posed in rig units and drawn at these scales (pixels per unit).
KEN_K = 2.1              # Kenobi stands about 60 px
GRV_K = 1.85             # Grievous about 1.25x Kenobi
DROID_K = 2.0            # a B1 at scale 1.0 stands about 62 px


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

SKY_TOP, SKY_BOT = (252, 240, 206), (236, 206, 158)
FAR_HAZE = (240, 222, 186)
DEPTH_HAZE = (212, 178, 134)

FAR = dict(face=(220, 186, 142), face2=(210, 174, 130), lip=(238, 216, 178),
           shade=(196, 160, 118), win=(184, 146, 106), lit=(250, 228, 172),
           post=(228, 198, 156))
MID = dict(face=(184, 126, 70), face2=(170, 114, 62), lip=(228, 174, 108),
           shade=(126, 80, 44), deep=(86, 52, 28), door=(48, 30, 20),
           lit=(255, 202, 112), rim=(242, 194, 130), edge=(70, 42, 24),
           rail=(96, 62, 38))
STEEL = dict(dark=(24, 20, 28), body=(44, 38, 48), mid=(62, 56, 66),
             hi=(102, 92, 98), rivet=(86, 78, 84))
FLOOR = dict(back=(168, 116, 68), front=(104, 68, 38), lip=(226, 180, 120),
             seam=(88, 56, 32), paint=(188, 138, 78))
FG = dict(sil=(14, 10, 18), sil2=(26, 20, 28), rim=(96, 60, 42))

RED_ON, RED_OFF, LAMP = (255, 64, 40), (86, 22, 22), (255, 222, 150)

# Character ramps: (shadow, base, light)
K_HAIR = ((102, 50, 22), (152, 82, 38), (198, 120, 62))
K_BEARD = ((120, 62, 30), (170, 96, 50), (206, 134, 78))
K_SKIN = ((182, 116, 86), (228, 166, 130), (246, 204, 170))
K_TUNIC = ((172, 152, 114), (214, 198, 160), (240, 230, 202))
K_COLLAR = ((196, 182, 148), (232, 222, 194), (250, 244, 226))
K_UNDER = ((60, 34, 22), (84, 50, 32), (110, 70, 46))
K_TABARD = ((140, 112, 78), (172, 144, 104), (198, 172, 130))
K_ROBE = ((58, 34, 20), (92, 58, 34), (126, 86, 52))
K_BOOT = ((34, 24, 18), (58, 40, 30), (84, 60, 44))
K_BELT = ((52, 32, 20), (84, 54, 34), (116, 80, 52))
K_LINE = (28, 16, 12)
K_IRIS, K_WHITE = (92, 130, 158), (232, 226, 214)

G_MASK = ((168, 160, 138), (216, 210, 188), (242, 238, 222))
G_BONE = ((150, 146, 132), (204, 200, 184), (234, 230, 216))
G_LIMB = ((112, 112, 118), (166, 166, 172), (210, 210, 214))
G_METAL = ((38, 40, 48), (62, 64, 74), (94, 96, 108))
G_SAC = ((70, 50, 58), (100, 72, 80), (132, 100, 106))
G_CAPE = ((26, 26, 34), (46, 46, 56), (72, 72, 84))
G_LINE = (10, 10, 16)
G_EYE, G_EYE_HOT = (255, 206, 40), (255, 250, 176)

D_TAN = ((138, 112, 72), (194, 168, 118), (230, 208, 160))
D_TAN_BK = ((112, 90, 58), (156, 132, 92), (192, 168, 124))
D_JOINT = ((78, 62, 40), (108, 86, 58), (138, 114, 80))
D_GUN = ((34, 34, 40), (58, 58, 66), (92, 92, 102))
D_LINE = (54, 40, 26)

B2_BODY = ((62, 66, 76), (100, 104, 116), (146, 152, 164))
B2_BACK = ((48, 50, 58), (78, 82, 92), (112, 116, 128))
B2_GUN = ((28, 28, 34), (46, 46, 54), (70, 70, 80))
B2_LINE = (18, 18, 24)
B2_EYE = (255, 44, 30)

HILT_GRIP, HILT_RIDGE = (40, 40, 46), (24, 24, 28)
HILT_SILVER, HILT_SHINE = (176, 178, 188), (236, 238, 246)
BLUE = ((60, 132, 255), (150, 204, 255), (244, 250, 255))
GREEN = ((56, 230, 92), (168, 255, 176), (246, 255, 246))

TEXT, TEXT_LOW, TEXT_EDGE = (255, 230, 40), (255, 186, 26), (10, 8, 8)
DUST = (226, 194, 146)


def flat(c):
    return (c, c, c)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


def hn(x, y, s=0):
    """Cheap deterministic hash noise in [0, 1)."""
    n = (x * 374761393 + y * 668265263 + s * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65536.0


BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def bayer(x, y):
    return (BAYER[y & 3][x & 3] + 0.5) / 16.0


# --------------------------------------------------------------------------
# Raster targets
# --------------------------------------------------------------------------

class Canvas:
    """RGB frame buffer."""

    def __init__(self, w, h, color=(0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(color) * (w * h))

    def copy(self):
        c = Canvas.__new__(Canvas)
        c.w, c.h, c.px = self.w, self.h, bytearray(self.px)
        return c

    def put(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            p = self.px
            p[i], p[i + 1], p[i + 2] = c

    def blend(self, x, y, c, a):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h and a > 0:
            i = (y * self.w + x) * 3
            p = self.px
            p[i] = int(p[i] + (c[0] - p[i]) * a)
            p[i + 1] = int(p[i + 1] + (c[1] - p[i + 1]) * a)
            p[i + 2] = int(p[i + 2] + (c[2] - p[i + 2]) * a)

    def add(self, x, y, c, k):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            p = self.px
            p[i] = min(255, p[i] + int(c[0] * k))
            p[i + 1] = min(255, p[i + 1] + int(c[1] * k))
            p[i + 2] = min(255, p[i + 2] + int(c[2] * k))


class Recorder:
    """Collects put() calls so a sprite can be drawn once and stamped many times."""

    def __init__(self):
        self.items = []

    def put(self, x, y, c):
        self.items.append((int(x), int(y), c))

    def stamp(self, cv, ox, oy):
        for x, y, c in self.items:
            cv.put(x + ox, y + oy, c)


class Layer:
    """A parallax plane: RGB plus a mask, blitted by opaque row spans."""

    def __init__(self, h):
        self.w, self.h = W, h
        self.px = bytearray(W * h * 3)
        self.mask = bytearray(W * h)
        self.spans = None

    def put(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            j = y * self.w + x
            self.mask[j] = 1
            i = j * 3
            self.px[i], self.px[i + 1], self.px[i + 2] = c

    def has(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h and self.mask[y * self.w + x]

    def finish(self):
        self.spans = []
        for y in range(self.h):
            row, x, base = [], 0, y * self.w
            while x < self.w:
                if self.mask[base + x]:
                    x0 = x
                    while x < self.w and self.mask[base + x]:
                        x += 1
                    row.append((x0, x))
                else:
                    x += 1
            self.spans.append(row)

    def blit(self, dst, oy):
        for y in range(H):
            ly = y + oy
            if 0 <= ly < self.h:
                for x0, x1 in self.spans[ly]:
                    s, e = (ly * self.w + x0) * 3, (ly * self.w + x1) * 3
                    d = (y * W + x0) * 3
                    dst.px[d:d + (e - s)] = self.px[s:e]


def fill_poly(plot, pts):
    """Even-odd scanline fill. plot(x, y) is called per pixel."""
    ys = [p[1] for p in pts]
    y0, y1 = int(math.floor(min(ys))), int(math.ceil(max(ys)))
    n = len(pts)
    for y in range(y0, y1 + 1):
        sy = y + 0.5
        xs = []
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            if (ay <= sy < by) or (by <= sy < ay):
                xs.append(ax + (sy - ay) * (bx - ax) / (by - ay))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            for x in range(int(math.ceil(xs[i] - 0.5)), int(math.floor(xs[i + 1] - 0.5)) + 1):
                plot(x, y)


def thick_line(plot, x0, y0, x1, y1, r):
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    R = int(math.ceil(r))
    rr = r * r + 0.25
    seen = set()
    for i in range(n + 1):
        t = i / n
        cx = math.floor(x0 + (x1 - x0) * t + 0.5)
        cy = math.floor(y0 + (y1 - y0) * t + 0.5)
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                if dx * dx + dy * dy <= rr and (cx + dx, cy + dy) not in seen:
                    seen.add((cx + dx, cy + dy))
                    plot(cx + dx, cy + dy)


# --------------------------------------------------------------------------
# Pixel font (5x7, hand-set bitmaps, drawn at 2x)
# --------------------------------------------------------------------------

GLYPHS = {
    'H': ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    'G': [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."],
    'K': ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    'a': [".....", ".....", ".###.", "....#", ".####", "#...#", ".####"],
    'b': ["#....", "#....", "####.", "#...#", "#...#", "#...#", "####."],
    'e': [".....", ".....", ".###.", "#...#", "#####", "#....", ".###."],
    'h': ["#....", "#....", "####.", "#...#", "#...#", "#...#", "#...#"],
    'i': ["#", ".", "#", "#", "#", "#", "#"],
    'l': ["##.", ".#.", ".#.", ".#.", ".#.", ".#.", "###"],
    'n': [".....", ".....", "####.", "#...#", "#...#", "#...#", "#...#"],
    'o': [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."],
    'r': [".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."],
    't': [".#..", ".#..", "####", ".#..", ".#..", ".#..", "..##"],
    '!': ["#", "#", "#", "#", "#", ".", "#"],
    ' ': ["...", "...", "...", "...", "...", "...", "..."],
}


def text_width(s):
    return sum(len(GLYPHS[ch][0]) + 1 for ch in s) - 1


def draw_text(cv, s, cx, y, reveal=None, sc=2):
    """Meme subtitle: yellow glyphs with a hard dark edge, centred on cx."""
    shown = s if reveal is None else s[:max(0, reveal)]
    width = text_width(s) * sc
    x = int(min(W - 4 - width, max(4, cx - width / 2)))
    on = []
    for ch in shown:
        g = GLYPHS[ch]
        for gy, row in enumerate(g):
            for gx, bit in enumerate(row):
                if bit == '#':
                    for sy in range(sc):
                        for sx in range(sc):
                            on.append((x + gx * sc + sx, y + gy * sc + sy, gy))
        x += (len(g[0]) + 1) * sc
    lit = {(a, b) for a, b, _ in on}
    for px, py, _ in on:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1, 2):
                if (px + dx, py + dy) not in lit:
                    cv.put(px + dx, py + dy, TEXT_EDGE)
    for px, py, gy in on:
        cv.put(px, py, TEXT if gy < 4 else TEXT_LOW)


# --------------------------------------------------------------------------
# Background layers (far to near: lighter, hazier, lower contrast to darker,
# warmer, sharper)
# --------------------------------------------------------------------------

def build_sky():
    L = Layer(H)
    for y in range(H):
        for x in range(W):
            t = y / (H - 1) * 9 + bayer(x, y) - 0.5
            L.put(x, y, mix(SKY_TOP, SKY_BOT, max(0, min(9, round(t))) / 9))
    L.finish()
    return L


def build_far():
    """The far side of the sinkhole: tiered rock with even bands of windows."""
    h = H + int(PAN * SPEED_FAR)
    L = Layer(h)
    rr = random.Random(7)
    tiers, y = [], 36
    while y < h:
        th = rr.choice((24, 28, 32))
        tiers.append((y, th, rr.randint(0, 13)))
        y += th
    row_tier = {}
    for t in tiers:
        for yy in range(t[0], min(h, t[0] + t[1])):
            row_tier[yy] = t
    for x in range(W):
        rim = int(30 + 7 * math.sin(x * 0.03) + 4 * math.sin(x * 0.09 + 1.3))
        for y in range(rim, h):
            t0, th, off = row_tier.get(y, (36, 24, 0))
            r = y - t0
            col = (x + off) % 72
            c = FAR['face'] if col < 60 else FAR['face2']
            if col == 60:
                c = FAR['post']
            if y <= rim + 1:
                c = FAR['lip']
            elif r == 0:
                c = FAR['lip']
            elif r <= 3:
                c = mix(FAR['shade'], FAR['face'], (r - 1) / 3)
            else:
                wx = (x + off) % 14
                wr = r - (th - 12)
                if 0 <= wr <= 6 and 5 <= wx <= 8 and col < 58:
                    if not (wr == 0 and wx in (5, 8)):
                        lit = hn((x + off) // 14, t0, 4) < 0.16
                        c = FAR['lit'] if lit else FAR['win']
            depth = y / h
            c = mix(c, (176, 136, 96), 0.30 * depth * depth)
            L.put(x, y, mix(c, FAR_HAZE, 0.42 - 0.16 * depth))
    L.finish()
    return L


def build_mid():
    """Near walls of the sinkhole on both sides: tiers with lips, arches, windows."""
    h = H + int(PAN * SPEED_MID)
    L = Layer(h)
    tier = 44

    def edge(side, y):
        return 66 + 9 * math.sin(y * 0.009 + side * 1.7) + 3 * math.sin(y * 0.037 + side * 3.1)

    for side in (0, 1):
        for y in range(h):
            e = edge(side, y)
            r = (y + 18) % tier
            lvl = (y + 18) // tier
            lip = r <= 2
            reach = int(e + (5 if lip else 0))
            for i in range(reach):
                x = i if side == 0 else W - 1 - i
                depth = i / max(1.0, e)
                if lip:
                    c = (MID['lip'], MID['face'], MID['shade'])[r]
                elif r <= 7:
                    c = mix(MID['deep'], MID['face2'], (r - 3) / 5)
                else:
                    c = MID['face'] if (i + lvl * 7) % 22 < 18 else MID['face2']
                    ai = (i + lvl * 7) % 22
                    slot = (i + lvl * 7) // 22
                    # arched doorways
                    if i < e - 8 and 18 <= r <= 37 and 6 <= ai <= 14:
                        w = 4 if r >= 22 else (2, 3, 4, 4)[r - 18]
                        if abs(ai - 10) <= w:
                            lit = hn(slot, lvl, 11) < 0.28
                            c = MID['lit'] if lit and r > 24 else MID['door']
                            if ai == 10 - w and not (lit and r > 24):
                                c = MID['deep']
                    if i < e - 8 and r == 38 and 5 <= ai <= 15:
                        c = MID['lip']
                    # small round windows above
                    wi = (i + lvl * 7 + 11) % 22
                    if i < e - 8 and 10 <= r <= 13 and 9 <= wi <= 12:
                        if not ((r in (10, 13)) and wi in (9, 12)):
                            c = MID['deep']
                    # pilaster between arches
                    if i < e - 8 and ai in (0, 1):
                        c = MID['lip'] if ai == 0 else MID['shade']
                    if i >= e - 3:
                        c = MID['rim']
                if i >= reach - 1:
                    c = MID['edge']
                c = mix(c, MID['deep'], 0.30 * (1 - depth) ** 2)
                L.put(x, y, mix(c, FAR_HAZE, 0.05))
    # a walkway across the pit, visible early in the drop
    by = 147
    for x in range(W):
        if not L.has(x, by):
            L.put(x, by, MID['lip'])
            L.put(x, by + 1, MID['rail'])
            L.put(x, by + 2, MID['rail'])
            L.put(x, by + 3, MID['edge'])
            L.put(x, by - 7, MID['rail'])
            if x % 9 == 0:
                for yy in range(by - 7, by):
                    L.put(x, yy, MID['rail'])
    L.finish()
    return L


def build_main():
    h = H + PAN
    L = Layer(h)
    # ceiling
    for y in range(0, 17):
        for x in range(W):
            c = STEEL['dark']
            if x % 27 == 0 or y == 16:
                c = (18, 14, 20)
            if y == 8 and x % 27 in (4, 22):
                c = STEEL['rivet']
            L.put(x, y, c)
    # truss chords
    for y0 in (18, 57):
        for x in range(W):
            for k, c in enumerate((STEEL['hi'], STEEL['mid'], STEEL['body'],
                                   STEEL['body'], STEEL['dark'])):
                L.put(x, y0 + k, c if not (k == 2 and x % 9 == 4) else STEEL['rivet'])
    plot = lambda x, y: L.put(x, y, STEEL['body']) if 0 <= x < W else None
    for x0 in range(-36, W + 36, 36):
        thick_line(plot, x0, 23, x0 + 18, 56, 1.1)
        thick_line(plot, x0 + 18, 56, x0 + 36, 23, 1.1)
        thick_line(lambda x, y: L.put(x, y, STEEL['mid']), x0, 23, x0, 56, 0.6)
    # beam Kenobi crouches on, with its hangers
    for x in (20, 250):
        for y in range(62, BEAM_Y + 1):
            L.put(x, y, STEEL['mid'])
            L.put(x + 1, y, STEEL['body'])
            L.put(x + 2, y, STEEL['dark'])
    for x in range(8, 264):
        for k, c in enumerate((STEEL['hi'], STEEL['mid'], STEEL['body'], STEEL['body'],
                               STEEL['body'], STEEL['dark'], STEEL['mid'], STEEL['dark'])):
            if k == 3 and x % 8 == 0:
                c = STEEL['rivet']
            L.put(x, BEAM_Y + 1 + k, c)
    # hanging cables and lamps
    for cx, bottom in ((184, 225), (306, 177), (357, 147), (60, 198)):
        for y in range(62, bottom):
            L.put(cx, y, (20, 16, 22))
        for dx in range(-3, 4):
            L.put(cx + dx, bottom, STEEL['mid'])
            L.put(cx + dx, bottom + 1, STEEL['dark'])
        for dx in (-1, 0, 1):
            L.put(cx + dx, bottom + 2, LAMP)
    # railing along the back edge of the platform
    for x in range(W):
        L.put(x, FLOOR_TOP - 9, STEEL['mid'])
        L.put(x, FLOOR_TOP - 8, STEEL['dark'])
        L.put(x, FLOOR_TOP - 4, STEEL['body'])
        if x % 14 == 0:
            for y in range(FLOOR_TOP - 9, FLOOR_TOP):
                L.put(x, y, STEEL['body'])
                L.put(x + 1, y, STEEL['dark'])
    # landing platform
    top = FLOOR_TOP
    vx, vy = W / 2, top - 110
    seams = [top + int((h - top) * (k / 8) ** 1.5) for k in range(1, 9)]
    for y in range(top, h):
        t = (y - top) / (h - top)
        for x in range(W):
            if y == top:
                c = FLOOR['lip']
            elif y == top + 1:
                c = mix(FLOOR['lip'], FLOOR['back'], 0.5)
            elif y == top + 2:
                c = mix(FLOOR['seam'], FLOOR['back'], 0.4)
            else:
                c = mix(FLOOR['back'], FLOOR['front'], t)
                if y in seams:
                    c = mix(c, FLOOR['seam'], 0.6)
                elif y - 1 in seams:
                    c = mix(c, FLOOR['lip'], 0.12)
                else:
                    x0 = vx + (x - vx) * (h - vy) / (y - vy)
                    if int(x0) % 60 == 0:
                        c = mix(c, FLOOR['seam'], 0.5)
                ring = ((x - 228) / 182) ** 2 + ((y - (GROUND - 6)) / 26) ** 2
                if 0.87 < ring < 1.0:
                    c = mix(c, FLOOR['paint'], 0.45)
            L.put(x, y, c)
    L.finish()
    return L


def build_fg():
    h = H + int(PAN * SPEED_FG)
    L = Layer(h)
    sil = lambda x, y: L.put(x, y, FG['sil'])

    def column(x0, x1, y1):
        for y in range(0, y1):
            for x in range(x0, x0 + 4):
                sil(x, y)
            for x in range(x1 - 4, x1):
                sil(x, y)
        for y0 in range(0, y1 - 20, 24):
            thick_line(sil, x0 + 3, y0, x1 - 4, y0 + 24, 0.9)
            thick_line(sil, x1 - 4, y0, x0 + 3, y0 + 24, 0.9)

    column(0, 18, 392)
    column(405, 432, 392)
    thick_line(sil, 252, -9, 450, 66, 5.4)
    for y in range(309, 321):
        for x in range(W):
            sil(x, y)
    for y in range(378, 386):
        for x in range(W):
            sil(x, y)
    thick_line(sil, 18, 321, 90, 378, 2.2)
    thick_line(sil, 414, 321, 342, 378, 2.2)
    rim = []
    for y in range(h):
        for x in range(W):
            if L.has(x, y):
                if y > 0 and not L.has(x, y - 1):
                    rim.append((x, y, FG['rim']))
                elif x > 0 and not L.has(x - 1, y):
                    rim.append((x, y, FG['sil2']))
                elif (x * 7 + y * 3) % 29 == 0:
                    rim.append((x, y, FG['sil2']))
    for x, y, c in rim:
        L.put(x, y, c)
    L.finish()
    return L


RED_LIGHTS = [(x, 62) for x in (45, 135, 225, 315, 387)] + [(x, 23) for x in (90, 270)]
LAMPS = [(184, 228), (306, 180), (357, 150), (60, 201)]


def light_shafts(cv, cam):
    """Warm light shafts slanting down through the haze, fixed to the mid plane."""
    off = cam * SPEED_MID
    for y in range(H):
        wy = y + off
        for x in range(W):
            v = (x * 0.62 + wy) % 225
            k = 0.0
            if v < 33:
                k = 0.11 * math.sin(v / 33 * math.pi)
            elif 96 < v < 111:
                k = 0.07 * math.sin((v - 96) / 15 * math.pi)
            if k > 0.01:
                cv.blend(x, y, (255, 240, 200), k)


_vig = None


def vignette(cv):
    """Darken the corners in a few hard steps, retro style."""
    global _vig
    if _vig is None:
        steps = []
        for y in range(H):
            for x in range(W):
                dx, dy = (x - W / 2) / (W / 2), (y - H * 0.45) / (H * 0.62)
                v = max(0.0, dx * dx + dy * dy - 0.45)
                steps.append(min(4, int(v * 5 + bayer(x, y) * 0.999)))
        _vig = bytes(steps)
    tables = [bytes(int(v * (1 - 0.07 * s)) for v in range(256)) for s in range(5)]
    p = cv.px
    for j, s in enumerate(_vig):
        if s:
            t = tables[s]
            i = j * 3
            p[i], p[i + 1], p[i + 2] = t[p[i]], t[p[i + 1]], t[p[i + 2]]


_bg_cache = {}
HOUSE_DIM = bytes(int(v * 0.78) for v in range(256))


def background(layers, cam):
    if cam not in _bg_cache:
        sky, far, mid, main, _fg = layers
        cv = Canvas(W, H)
        sky.blit(cv, 0)
        far.blit(cv, int(round(cam * SPEED_FAR)))
        mid.blit(cv, int(round(cam * SPEED_MID)))
        light_shafts(cv, cam)
        main.blit(cv, cam)
        vignette(cv)
        _bg_cache[cam] = cv
    return _bg_cache[cam].copy()


# --------------------------------------------------------------------------
# Character rigs
# --------------------------------------------------------------------------

class Sprite:
    """Collects part-tagged pixels, then shades, separates and outlines them.

    Pose points are in rig units (x forward, y up negative) and map to pixels
    through the origin, facing d and scale k. Details that must stay crisp at
    any scale (eyes, slats, seams) go through the pixel-offset helpers.
    """

    def __init__(self, ox, oy, d, k=1.0):
        self.ox, self.oy, self.d, self.k = ox, oy, d, k
        self.cells = {}
        self.over = {}
        self.sep = set()
        self.pid = 0
        self.ramp = None

    def P(self, p):
        return (self.ox + self.d * p[0] * self.k, self.oy + p[1] * self.k)

    def pix(self, p, dx=0, dy=0):
        x, y = self.P(p)
        return (math.floor(x + 0.5) + int(round(self.d * dx)), math.floor(y + 0.5) + dy)

    def part(self, ramp, sep=False):
        self.pid += 1
        self.ramp = ramp
        if sep:
            self.sep.add(self.pid)

    def plot(self, x, y):
        self.cells[(x, y)] = (self.pid, self.ramp)

    def line(self, a, b, r=0.5):
        (x0, y0), (x1, y1) = self.P(a), self.P(b)
        thick_line(self.plot, x0, y0, x1, y1, max(0.5, r * self.k))

    def disc(self, c, r):
        x, y = self.P(c)
        thick_line(self.plot, x, y, x, y, max(0.5, r * self.k))

    def tube(self, a, b, r0, r1):
        """Tapered limb from a (radius r0) to b (radius r1), in rig units."""
        (ax, ay), (bx, by) = self.P(a), self.P(b)
        dx, dy = bx - ax, by - ay
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n
        k = self.k
        fill_poly(self.plot, [(ax + nx * r0 * k, ay + ny * r0 * k), (bx + nx * r1 * k, by + ny * r1 * k),
                              (bx - nx * r1 * k, by - ny * r1 * k), (ax - nx * r0 * k, ay - ny * r0 * k)])
        thick_line(self.plot, ax, ay, ax, ay, max(0.5, r0 * k))
        thick_line(self.plot, bx, by, bx, by, max(0.5, r1 * k))

    def poly(self, pts):
        fill_poly(self.plot, [self.P(p) for p in pts])

    def poly_px(self, p, pts):
        """Polygon in pixel offsets from pose point p, mirrored by facing."""
        x, y = self.P(p)
        cx, cy = math.floor(x + 0.5), math.floor(y + 0.5)
        fill_poly(self.plot, [(cx + self.d * a, cy + b) for a, b in pts])

    def bitmap(self, p, rows, key, anchor, sep=False):
        """Hand-set pixel map placed at pose point p; anchor is the map cell on p."""
        x0, y0 = self.P(p)
        cx, cy = math.floor(x0 + 0.5), math.floor(y0 + 0.5)
        sd = 1 if self.d >= 0 else -1
        self.part(None, sep)
        for ry, row in enumerate(rows):
            for rx, ch in enumerate(row):
                if ch != '.':
                    self.cells[(cx + sd * (rx - anchor[0]), cy + ry - anchor[1])] = (self.pid, flat(key[ch]))

    def paint(self, x, y, c, inside=True, pid=None):
        """Detail pixel on top of shading. With pid, it survives only if that part
        is still the visible one there when the sprite is rendered."""
        if not inside or (x, y) in self.cells:
            self.over[(x, y)] = (c, pid)

    def paint_line(self, a, b, c, inside=True, pid=None):
        thick_line(lambda x, y: self.paint(x, y, c, inside, pid), a[0], a[1], b[0], b[1], 0.5)

    def render(self, cv, outline, dim=0.0, dim_to=DEPTH_HAZE):
        cells = self.cells
        shade = {}
        for (x, y), (pid, ramp) in cells.items():
            up, dn = cells.get((x, y - 1)), cells.get((x, y + 1))
            lf, rt = cells.get((x - 1, y)), cells.get((x + 1, y))
            top = up is None or up[0] != pid
            bot = dn is None or dn[0] != pid
            left = lf is None or lf[0] != pid
            right = rt is None or rt[0] != pid
            if top and not bot:
                tone = 2
            elif bot and not top:
                tone = 0
            elif right and not left:
                tone = 0
            elif left and not right:
                tone = 2
            else:
                tone = 1
            shade[(x, y)] = ramp[tone]
        # parts flagged sep get a soft dark seam where they overlap earlier parts
        for (x, y), (pid, ramp) in cells.items():
            if pid in self.sep:
                for n in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    o = cells.get(n)
                    if o is not None and o[0] < pid and o[0] not in self.sep:
                        shade[n] = mix(o[1][0], outline, 0.55)
        for xy, (c, pid) in self.over.items():
            if pid is None or (xy in cells and cells[xy][0] == pid):
                shade[xy] = c
        oc = mix(outline, dim_to, dim * 0.8) if dim else outline
        for (x, y) in cells:
            for n in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if n not in cells:
                    cv.put(n[0], n[1], oc)
        for (x, y), c in shade.items():
            cv.put(x, y, mix(c, dim_to, dim) if dim else c)


def lerp_pose(a, b, t):
    out = {}
    for k in a:
        va, vb = a[k], b[k]
        if isinstance(va, tuple):
            out[k] = (lerp(va[0], vb[0], t), lerp(va[1], vb[1], t))
        else:
            out[k] = lerp(va, vb, t)
    return out


def add(p, dx, dy):
    return (p[0] + dx, p[1] + dy)


# ---- Kenobi, facing +x, feet at (0, 0), y up is negative.
K_STAND = dict(ff=(2, 0), fb=(-2, 0), kf=(1.5, -7), kb=(-1.5, -7), hip=(0, -13),
               chest=(0.5, -21), sh=(0.5, -20), head=(1, -25),
               ef=(2, -15.5), hf=(2.5, -11), eb=(-1.5, -15.5), hb=(-2, -11),
               tail=(-5, -1))
K_GESTURE = dict(K_STAND, ef=(3.5, -15), hf=(6.5, -16))
K_CROUCH = dict(ff=(4, 0), fb=(-3, 0), kf=(6, -6), kb=(1, -4), hip=(-1, -8),
                chest=(2, -15), sh=(2, -14), head=(4, -19),
                ef=(5, -10), hf=(6, -6), eb=(0, -10), hb=(1, -2),
                tail=(-7, 0))
K_LEAP = dict(ff=(8, -5), fb=(-5, -1), kf=(7, -11), kb=(-1, -7), hip=(1, -14),
              chest=(4, -21), sh=(4, -20), head=(6, -25),
              ef=(1, -16), hf=(-3, -14), eb=(-1, -16), hb=(-5, -13),
              tail=(-10, -6))
K_FALL = dict(ff=(4, -2), fb=(-3, -3), kf=(4, -8), kb=(-2, -8), hip=(0, -14),
              chest=(0.5, -22), sh=(0.5, -21), head=(1, -26),
              ef=(5, -20), hf=(9, -23), eb=(-4, -20), hb=(-8, -23),
              tail=(-8, -31))
K_LAND = dict(ff=(6, 0), fb=(-5, 0), kf=(7, -5), kb=(-3, -2), hip=(-1, -7),
              chest=(2, -13), sh=(2, -12), head=(4, -17),
              ef=(6, -7), hf=(9, -1), eb=(-3, -11), hb=(-7, -9),
              tail=(-10, 0))
# Signature guard: saber hand high beside the head, blade up and over it,
# off arm straight at Grievous with two fingers pointing, wide stance.
K_GUARD = dict(ff=(7, 0), fb=(-6, 0), kf=(6.5, -6.5), kb=(-3.5, -6.5), hip=(0, -12),
               chest=(1.4, -20), sh=(1.2, -19.5), head=(2.4, -24.5),
               ef=(6, -19.6), hf=(10.5, -19.8), eb=(-3.6, -23.8), hb=(-1.2, -26.6),
               tail=(-7, -1))
K_SABER_DIR = (0.66, -0.75)


# Hand-set pixel maps. One character per pixel, '.' is empty. Faces right.
KEN_HEAD = [
    "..dhhHHh...",
    ".dhhHhhHhh.",
    "dhhkSSSSSs.",
    "dhhkswwSSs.",
    "dhhkseiSSSS",
    ".dhbssSskS.",
    ".dbbbBBBB..",
    "..dbbmmbb..",
    "...dbbbb...",
]
KEN_HEAD_KEY = dict(d=(100, 48, 20), h=(152, 82, 38), H=(206, 132, 70),
                    S=(246, 204, 170), s=(228, 166, 130), k=(182, 116, 86),
                    w=(104, 52, 24), e=(236, 232, 222), i=(84, 122, 152),
                    b=(166, 94, 48), B=(122, 62, 30), m=(102, 48, 38))
HAND_FIST = ["Ss", "ss"]
HAND_POINT = ["sSSS", "ss.."]
HAND_KEY = dict(S=(246, 204, 170), s=(222, 160, 124))


def draw_kenobi(cv, ox, oy, p, d, t, flutter=1.0, point=0.0):
    """Layered back to front: back arm in its sleeve, back leg, cloak back panel,
    front leg, under-tunic, tunic with crossed flaps and skirt, tabard, belt,
    the cloak's side drape, front arm in its bell sleeve, then neck and head."""
    s = Sprite(ox, oy, d, KEN_K)
    wave = math.sin(t * 0.9) * 1.2 * flutter
    sh, hip, tail, ch = p['sh'], p['hip'], p['tail'], p['chest']
    head = p['head']
    hd = (sh[0] + (head[0] - sh[0]) * 0.8, sh[1] + (head[1] - sh[1]) * 0.7)
    sh_f, sh_b = add(sh, 0.4, 0.3), add(sh, -0.9, 0.3)
    hanging = tail[1] > hip[1]
    hem_y = tail[1] if hanging else hip[1] + 1.5
    fold_dk = mix(K_ROBE[0], K_LINE, 0.35)

    def arm(shp, e, h, sep, hand):
        s.part(K_ROBE, sep)
        sid = s.pid
        s.disc(shp, 1.3)                                   # shoulder cap
        s.tube(shp, e, 1.2, 1.1)
        cuff = (lerp(e[0], h[0], 0.78), lerp(e[1], h[1], 0.78))
        s.tube(e, cuff, 1.1, 1.75)                         # bell sleeve
        ex, ey = s.pix(e)
        cx, cy = s.pix(cuff)
        s.paint_line((ex, ey + 1), (cx, cy + 1), fold_dk, pid=sid)
        s.part(K_UNDER)
        s.disc(cuff, 0.75)                                 # inside of the cuff
        if hand == 'point':
            s.bitmap(h, HAND_POINT, HAND_KEY, (0, 1))
        else:
            s.bitmap(h, HAND_FIST, HAND_KEY, (1, 1))

    def leg(hp, k, f):
        s.part(K_TUNIC)                                    # trousers
        s.tube(hp, k, 1.25, 1.0)
        s.part(K_BOOT)
        bid = s.pid
        s.tube(add(k, 0, 0.5), f, 1.08, 0.95)              # tall boot
        s.poly([add(f, -0.9, 0.3), add(f, 2.5, 0.3), add(f, 2.1, -0.8), add(f, -0.6, -1.1)])
        kx, ky = s.pix(add(k, 0, 0.7))
        for i in (-2, -1, 0, 1, 2):
            s.paint(kx + i, ky, K_BOOT[2], pid=bid)        # boot cuff

    # 1-2: back arm, back leg
    arm(sh_b, p['eb'], p['hb'], False, 'fist')
    leg(add(hip, -0.7, 0), p['kb'], p['fb'])

    # 3: cloak back panel, hanging from both shoulders and widening to the hem
    s.part(K_ROBE)
    cloak = s.pid
    hem_b = add(tail, -2.2 + wave, 0)
    hem_f = (lerp(tail[0], hip[0], 0.35) + 2.6 + wave * 0.4, tail[1] + 0.8)
    back_top = add(sh, -3.4, -0.2)
    billow = ((back_top[0] + hem_b[0]) / 2 - 1.2 - abs(wave) * 0.6,
              (back_top[1] + hem_b[1]) / 2)
    s.poly([add(sh, 0.6, -1.0), add(sh, -1.8, -1.1), back_top, billow,
            hem_b, add(hem_b, 1.6, 0.9 + wave * 0.3), hem_f, add(hip, -0.5, 1)])
    for f in (0.25, 0.6):
        a = s.pix(add(sh, -2.8 + f, 0))
        b = s.pix((lerp(hem_b[0], hem_f[0], f), lerp(hem_b[1], hem_f[1], f) - 0.3))
        s.paint_line(a, b, fold_dk, pid=cloak)
        s.paint_line((a[0] + d, a[1] + 2), (b[0] + d, b[1]), K_ROBE[2], pid=cloak)

    # 4: front leg
    leg(add(hip, 0.7, 0), p['kf'], p['ff'])

    # neck sits between the shoulders, under the collar
    s.part(K_SKIN)
    s.tube(add(ch, 0.6, -1.0), add(hd, 0, 3.2), 0.8, 0.75)

    # 5: dark under-tunic
    s.part(K_UNDER)
    s.poly([add(ch, -2.5, -1.4), add(ch, 2.6, -1.4), add(hip, 2.4, 0.5), add(hip, -2.4, 0.5)])

    # 6: cream tunic, open in a V at the chest, skirt over the thigh tops
    s.part(K_TUNIC)
    tun = s.pid
    s.poly([add(ch, -2.6, -1.2), add(ch, 0.9, -1.3), add(ch, 1.8, 2.6), add(ch, 2.8, -1.0),
            add(hip, 2.5, 0), add(hip, -2.5, 0)])
    kf, kb = p['kf'], p['kb']
    sk_f = (lerp(hip[0], kf[0], 0.5) + 1.3, lerp(hip[1], kf[1], 0.5) + 0.4)
    sk_b = (lerp(hip[0], kb[0], 0.5) - 1.3, lerp(hip[1], kb[1], 0.5) + 0.4)
    sk_m = ((sk_f[0] + sk_b[0]) / 2, max(sk_f[1], sk_b[1]) + 0.6)
    s.poly([add(hip, -2.7, -0.6), add(hip, 2.7, -0.6), sk_f, sk_m, sk_b])
    s.paint_line(s.pix(add(ch, 1.8, 2.6)), s.pix(add(hip, -0.6, 0)), K_TUNIC[0], pid=tun)
    s.part(K_COLLAR, True)                                  # crossed front flaps
    s.tube(add(sh, -1.2, -1.3), add(ch, 1.8, 2.6), 0.7, 0.5)
    s.tube(add(sh, 1.6, -1.2), add(ch, 1.9, 2.4), 0.55, 0.45)

    # 7-8: tabard strips, belt and pouch
    s.part(K_TABARD)
    s.tube(add(ch, 2.3, 1.6), add(hip, 1.9, 0), 0.5, 0.55)
    s.tube(add(hip, 1.9, 0), add(sk_f, -0.7, -0.3), 0.55, 0.6)
    s.part(K_BELT, True)
    s.tube(add(hip, -2.7, -0.2), add(hip, 2.8, -0.2), 0.65, 0.65)
    bx, by = s.pix(add(hip, 1.9, -0.2))
    s.paint(bx, by, (200, 176, 124))
    s.paint(bx, by + 1, (150, 126, 84))
    s.part(K_BELT, True)
    s.poly([add(hip, -1.9, 0.3), add(hip, -0.6, 0.3), add(hip, -0.6, 1.8), add(hip, -1.9, 1.8)])

    # 9: the cloak's side drape over the torso, open at the front
    s.part(K_ROBE, True)
    drape = s.pid
    hm_b = (lerp(tail[0], hip[0], 0.5) - 1 + wave * 0.5, hem_y + 0.2)
    hm_f = (hip[0] - 0.6, hem_y + 0.6)
    s.poly([add(sh, 0.9, -1.0), add(sh, -1.4, -1.2), add(ch, -3.0, 2.0), add(hip, -3.0, 1.0),
            hm_b, hm_f, add(hip, -0.6, 1.5), add(ch, -0.4, 1.0)])
    for f in (0.3, 0.65):
        a = s.pix(add(sh, -1.0 + f, -1.0))
        b = s.pix((lerp(hm_b[0], hm_f[0], f), hm_b[1] - 0.2))
        s.paint_line(a, b, fold_dk, pid=drape)
    a, b = s.pix(add(ch, -0.4, 1.0)), s.pix(hm_f)
    s.paint_line(a, b, K_ROBE[2], pid=drape)               # lit front edge

    # 10: front arm in its bell sleeve
    arm(sh_f, p['ef'], p['hf'], True, 'point' if point > 0.5 else 'fist')

    # 11: head and hair
    s.bitmap(hd, KEN_HEAD, KEN_HEAD_KEY, (5, 4))
    s.render(cv, K_LINE)


# ---- Grievous, facing +x. Digitigrade legs, hunched, cloak behind.
G_IDLE = dict(toe_f=(5, 0), heel_f=(2, -4), knee_f=(5, -12),
              toe_b=(-2, 0), heel_b=(-5, -4), knee_b=(-2, -12),
              hip=(0, -20), chest=(1, -31), head=(6, -34),
              e1=(4, -25), h1=(5, -18), e2=(-2, -25), h2=(-2, -18),
              e3=(4, -25), h3=(5, -18), e4=(-2, -25), h4=(-2, -18), spread=0.0)
G_FOUR = dict(toe_f=(10, 0), heel_f=(6, -4), knee_f=(9, -12),
              toe_b=(-5, 0), heel_b=(-9, -4), knee_b=(-4, -12),
              hip=(0, -19), chest=(1, -30), head=(6, -33),
              e1=(7, -36), h1=(11, -40), e2=(-4, -36), h2=(-8, -41),
              e3=(9, -23), h3=(12, -15), e4=(-6, -23), h4=(-10, -15), spread=1.0)


GRV_MASK = [
    "f.....F..",
    "f....FF..",
    "fLLLL.F..",
    "fLMMLLF..",
    "fMMMMLLF.",
    "fMMDMMMF.",
    "fMMDMMLL.",
    "fMxxxxxL.",
    "fMxxxyYx.",
    "fMMDxxMM.",
    ".DMzMzMM.",
    ".DMzMzMM.",
    ".DDzMzM..",
    "..DgDg...",
]
GRV_MASK_KEY = dict(M=(216, 210, 188), L=(242, 238, 222), D=(168, 160, 138),
                    f=(226, 220, 198), F=(150, 144, 126), x=(40, 34, 34),
                    y=(255, 206, 40), Y=(255, 250, 176), z=(60, 52, 50),
                    g=(240, 236, 220))


def draw_grievous(cv, ox, oy, p, d, t):
    """Cloak behind; back arms and legs; pelvis, organ sac, chest plate with two
    shoulder sockets; long neck and small mask; front arms from the front socket."""
    s = Sprite(ox, oy, d, GRV_K)
    sp = p['spread']
    ch, hip, hd = p['chest'], p['hip'], p['head']
    sway = math.sin(t * 0.5) * 0.6
    sock_f, sock_b = add(ch, 1.8, -1.0), add(ch, -1.6, -0.8)

    # cloak hanging from the shoulders, high collar behind the neck
    s.part(G_CAPE)
    cape = s.pid
    hem = [(-8 - 9 * sp + sway, -5 - 8 * sp), (-10 - 9 * sp + sway * 1.5, -3 - 7 * sp),
           (-5 - 6 * sp + sway, -4 - 4 * sp)]
    s.poly([add(sock_f, 0.5, -1.2), add(ch, 0.8, -5.5), add(ch, -1.8, -6.5), add(ch, -4.4, -2.5)]
           + hem + [(-1 - 3 * sp, -9 - 2 * sp), add(hip, -0.5, -2)])
    for f in (0.3, 0.65):
        a = s.pix(add(ch, -2 - f, -2))
        b = s.pix((lerp(hem[0][0], hem[1][0], f), lerp(hem[0][1], hem[1][1], f) - 1))
        s.paint_line(a, b, G_CAPE[0], pid=cape)
        s.paint_line((a[0] - d, a[1] + 3), (b[0] - d, b[1] - 1), G_CAPE[2], pid=cape)

    def arm(sock, e, h, front):
        s.part(G_LIMB, front)
        s.tube(sock, e, 0.6, 0.5)
        s.tube(e, h, 0.48, 0.4)
        s.part(G_METAL)
        s.disc(e, 0.55)
        hx, hy = s.pix(h)
        ex, ey = s.pix(e)
        ux, uy = hx - ex, hy - ey
        n = math.hypot(ux, uy) or 1.0
        ux, uy = ux / n, uy / n
        s.part(G_LIMB, front)
        for side in (-0.6, 0.0, 0.6):                      # three claws
            cx = ux * math.cos(side) - uy * math.sin(side)
            cy = ux * math.sin(side) + uy * math.cos(side)
            thick_line(s.plot, hx, hy, hx + cx * 3, hy + cy * 3, 0.5)

    def leg(sock, knee, heel, toe, front):
        s.part(G_LIMB, front)
        s.tube(sock, knee, 0.9, 0.7)
        s.tube(knee, heel, 0.6, 0.5)
        s.tube(heel, toe, 0.5, 0.42)
        s.part(G_METAL)
        s.disc(knee, 0.65)
        s.disc(heel, 0.45)
        tx, ty = s.pix(toe)
        hx, hy = s.pix(heel)
        s.part(G_LIMB, front)
        thick_line(s.plot, tx, ty, tx + d * 2, ty, 0.5)    # talon
        thick_line(s.plot, hx, hy + 2, hx - d * 2, hy + 4, 0.5)

    arm(sock_b, p['e4'], p['h4'], False)
    arm(sock_b, p['e2'], p['h2'], False)
    leg(add(hip, -0.8, 0.5), p['knee_b'], p['heel_b'], p['toe_b'], False)
    leg(add(hip, 0.8, 0.5), p['knee_f'], p['heel_f'], p['toe_f'], True)
    # spine, pelvis, organ sac
    s.part(G_METAL)
    s.tube(hip, add(ch, 0, 2), 1.3, 1.1)
    s.part(G_BONE, True)
    s.poly([add(hip, -2.4, -1.2), add(hip, 2.8, -1.2), add(hip, 2.0, 1.8), add(hip, -1.8, 1.8)])
    s.part(G_SAC, True)
    s.disc(add(hip, 1.2, -3.4), 1.5)
    # chest plate with its shoulder sockets
    s.part(G_BONE, True)
    plate = s.pid
    s.poly([add(ch, -3, -1.5), add(ch, 4, -0.5), add(ch, 3.2, 6), add(ch, -2.2, 5)])
    for a, b in ((add(ch, 1, -0.5), add(ch, 0.5, 4.5)), (add(ch, -2.2, 3), add(ch, 3.3, 3.4))):
        s.paint_line(s.pix(a), s.pix(b), G_BONE[0], pid=plate)
    s.part(G_METAL)
    s.disc(sock_b, 0.75)
    # long neck forward to the mask
    s.part(G_METAL, True)
    s.tube(add(ch, 2.2, -1.6), add(hd, -1.2, 2.5), 0.75, 0.6)
    s.bitmap(hd, GRV_MASK, GRV_MASK_KEY, (4, 8))
    arm(sock_f, p['e1'], p['h1'], True)
    arm(sock_f, p['e3'], p['h3'], True)
    s.part(G_BONE, True)
    s.disc(sock_f, 0.85)                                    # shoulder cap
    s.render(cv, G_LINE)


def mix_ramp(ramp, c, t):
    return tuple(mix(r, c, t) for r in ramp)


# ---- B1 battle droid, body facing +x; hh turns the head (+1 forward, -1 back).
def draw_b1(cv, ox, oy, d, sc, hh, raised, dim):
    s = Sprite(ox, oy, d, DROID_K * sc)

    def leg(hip, knee, ankle, ramp):
        s.part(ramp)
        s.tube(hip, knee, 0.55, 0.45)
        s.tube(knee, ankle, 0.45, 0.4)
        s.part(D_JOINT)
        s.disc(knee, 0.7)
        s.part(ramp)
        s.poly([add(ankle, -1.0, 1.0), add(ankle, 2.6, 1.0), add(ankle, 2.2, 0.0),
                add(ankle, 0.0, -0.5)])

    if raised:
        arms = (((1.0, -20.8), (3.4, -21.4)), ((2.6, -20.6), (5.0, -21.6)))
        gun = ((1.6, -21.6), (9.8, -21.9))
    else:
        arms = (((0.8, -19.0), (3.0, -19.4)), ((2.2, -18.6), (4.2, -18.2)))
        gun = ((0.8, -19.2), (8.4, -17.8))

    def arm(e, h, ramp):
        s.part(ramp)
        s.tube((0.3, -22.6), e, 0.45, 0.4)
        s.tube(e, h, 0.4, 0.4)
        s.part(D_JOINT)
        s.disc(e, 0.55)

    leg((-0.6, -15), (-1.4, -8.2), (-1.8, -1.0), D_TAN_BK)
    s.part(D_TAN_BK)
    s.poly([(-3.6, -18.5), (-1.2, -18.3), (-1.0, -24.2), (-3.2, -24.6)])   # backpack
    arm(*arms[0], D_TAN_BK)
    s.part(D_JOINT)
    s.tube((0, -15), (0.3, -18), 0.5, 0.5)                                  # spine rod
    leg((0.6, -15), (1.8, -8.2), (1.8, -1.0), D_TAN)
    s.part(D_TAN, True)
    s.poly([(-1.5, -14.0), (1.5, -14.0), (1.2, -16.4), (-1.2, -16.4)])     # pelvis block
    s.part(D_JOINT)
    s.disc((0.6, -15.0), 0.55)                                              # hip joint
    s.part(D_TAN, True)
    s.poly([(-1.3, -18), (1.6, -17.6), (2.6, -23.2), (1.2, -24.2), (-1.4, -23.8)])
    s.part(D_TAN)
    s.tube((1.0, -23.6), (1.8, -27.0), 0.4, 0.35)                           # neck
    # head: rounded back, long flat snout
    pv = (1.8, -27.0)
    pts = [(-1.1, -0.2), (-1.1, -1.6), (0.3, -2.3), (2.2, -1.8), (4.6, 0.3),
           (5.0, 1.1), (4.5, 1.5), (2.0, 0.5), (0.3, 0.5)]
    s.part(D_TAN, True)
    s.poly([(pv[0] + x * hh, pv[1] + y) for x, y in pts])
    ex, ey = s.pix((pv[0] + 0.2 * hh, pv[1] - 1.4))
    s.paint(ex, ey, D_JOINT[0])
    s.paint(ex + 1, ey, D_JOINT[0])
    s.part(D_TAN)
    s.line((pv[0] - 0.9 * hh, pv[1] - 2.2), (pv[0] - 1.3 * hh, pv[1] - 3.8), 0.3)  # antenna
    # blaster and front arm
    s.part(D_GUN, True)
    s.tube(gun[0], gun[1], 0.42, 0.36)
    gx, gy = s.pix(gun[0])
    hx, hy = s.pix(gun[1])
    s.paint_line((lerp(gx, hx, 0.35), gy - 1 + (hy - gy) * 0.35),
                 (lerp(gx, hx, 0.6), gy - 1 + (hy - gy) * 0.6), D_GUN[2], inside=False)
    s.part(D_JOINT)
    s.disc((0.3, -22.6), 0.6)                                               # shoulder joint
    arm(*arms[1], D_TAN)
    s.render(cv, D_LINE, dim=dim)


# ---- B2 super battle droid: bulky gunmetal, head sunk between the shoulders.
B2_EYE_AT = (1.9, -31.6)


def draw_b2(cv, ox, oy, d, sc, raised, dim):
    """Three-quarter view so the shoulders read as broad as in the films."""
    s = Sprite(ox, oy, d, DROID_K * sc)

    def leg(hip, knee, ankle, ramp, front):
        s.part(ramp, front)
        s.tube(hip, knee, 1.3, 1.1)
        s.tube(knee, ankle, 1.1, 0.95)
        s.part(B2_GUN)
        s.disc(knee, 1.0)
        s.part(ramp, front)
        s.disc(add(knee, 0.4, -0.3), 0.75)
        s.poly([add(ankle, -1.8, 1.6), add(ankle, 3.0, 1.6), add(ankle, 2.4, 0),
                add(ankle, -1.2, -0.4)])

    def arm(shoulder, elbow, wrist, ramp, front):
        s.part(ramp, front)
        sid = s.pid
        s.tube(shoulder, elbow, 0.9, 0.85)
        s.tube(elbow, wrist, 1.5, 1.35)
        ex, ey = s.pix(elbow)
        wx, wy = s.pix(wrist)
        s.paint_line((lerp(ex, wx, 0.2), lerp(ey, wy, 0.2)),
                     (lerp(ex, wx, 0.8), lerp(ey, wy, 0.8)), ramp[0], pid=sid)
        s.part(B2_GUN)
        s.disc(wrist, 0.9)

    leg((-1.6, -15.5), (-2.2, -8.5), (-2.4, -1.6), B2_BACK, False)
    arm((-5.4, -28.6), (-6.4, -22.6), (-6.4, -15.8), B2_BACK, False)
    # segmented waist
    s.part(B2_BODY)
    wid = s.pid
    s.tube((0, -15.5), (0, -21.6), 1.8, 2.0)
    for k in range(5):
        a, b = s.pix((-2.0, -16.4 - k * 1.1)), s.pix((2.0, -16.4 - k * 1.1))
        s.paint_line(a, b, B2_BODY[0], pid=wid)
    s.part(B2_BODY)
    s.poly([(-2.6, -14.2), (2.6, -14.2), (2.2, -16.6), (-2.2, -16.6)])   # hips
    leg((1.6, -15.5), (2.0, -8.5), (1.8, -1.6), B2_BODY, True)
    s.part(B2_GUN)
    s.disc((1.6, -15.2), 0.8)                                              # hip joint
    # chest shell, wide at the shoulders and tapering to the waist
    s.part(B2_BODY, True)
    cid = s.pid
    s.poly([(-3.4, -21.0), (3.6, -21.0), (6.2, -27.0), (4.6, -31.4), (-4.6, -31.4), (-6.2, -27.0)])
    for a, b in (((0.6, -31.0), (0.6, -22.0)), ((-4.6, -27.4), (5.0, -27.2))):
        s.paint_line(s.pix(a), s.pix(b), B2_BODY[0], pid=cid)
    # head sunk between the shoulders
    s.part(B2_BODY)
    s.disc((0.8, -31.6), 1.6)
    ex, ey = s.pix(B2_EYE_AT)
    s.paint(ex, ey, B2_EYE)
    s.paint(ex, ey + 1, mix(B2_EYE, B2_GUN[0], 0.5))
    # shoulder pads
    s.part(B2_BACK, True)
    s.disc((-5.0, -29.4), 2.2)
    s.part(B2_BODY, True)
    s.disc((5.2, -29.2), 2.4)
    if raised:
        arm((5.6, -28.6), (8.6, -25.2), (12.6, -24.6), B2_BODY, True)
    else:
        arm((5.6, -28.6), (6.8, -22.6), (6.8, -15.8), B2_BODY, True)
    s.render(cv, B2_LINE, dim=dim)


_droid_cache = {}


def stamp_droid(cv, kind, x, y, sc, state, dim):
    key = (kind, sc, state, dim)
    if key not in _droid_cache:
        rec = Recorder()
        if kind == 'b1':
            draw_b1(rec, 0, 0, -1, sc, state[0], state[1], dim)
        else:
            draw_b2(rec, 0, 0, -1, sc, state, dim)
        _droid_cache[key] = rec
    _droid_cache[key].stamp(cv, x, y)


# --------------------------------------------------------------------------
# VFX
# --------------------------------------------------------------------------

_kernels = {}


def glow(cv, x, y, col, r, k):
    """Additive halo with a smooth quadratic falloff."""
    key = round(r * 2) / 2
    if key not in _kernels:
        R = int(math.ceil(key))
        _kernels[key] = [(dx, dy, (1 - math.sqrt(dx * dx + dy * dy) / key) ** 2)
                         for dy in range(-R, R + 1) for dx in range(-R, R + 1)
                         if dx * dx + dy * dy < key * key]
    xi, yi = int(round(x)), int(round(y))
    for dx, dy, w in _kernels[key]:
        cv.add(xi + dx, yi + dy, col, w * k)


def floor_spill(cv, x, y, col, rx, ry, k):
    """Coloured light pooling on the deck under a blade."""
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            w = 1 - (dx / rx) ** 2 - (dy / ry) ** 2
            if w > 0:
                cv.add(x + dx, y + dy, col, k * w * w)


def flare(cv, x, y, col, k):
    """Ignition lens flare: a short cross, a smaller diagonal star, a radial glow."""
    glow(cv, x, y, col, 13, 0.55 * k)
    glow(cv, x, y, (255, 255, 255), 6, 0.9 * k)
    arm = int(10 * k) + 3
    for i in range(1, arm):
        a = (1 - i / arm) ** 1.5 * k
        for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cv.add(x + sx * i, y + sy * i, (255, 255, 255), a)
        if i < arm // 2:
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                cv.add(x + sx * i, y + sy * i, col, a * 0.8)


def draw_saber(cv, hx, hy, dx, dy, length, colors, hum=1.0, trail=(), flash=0.0,
               floor_y=None, amp=1.0):
    """Hilt, smears, bloom, colour band, hot core, tip, flare and light spill.
    amp scales the whole blade so it can fade out after the rest of the scene."""
    col, inner, core = (mix((0, 0, 0), c, amp) for c in colors)
    hum *= amp
    # hilt: silver pommel, dark ridged grip, silver emitter
    for i in range(-4, 5):
        x, y = round(hx + dx * i), round(hy + dy * i)
        if i <= -3:
            c = HILT_SILVER
        elif i <= 2:
            c = HILT_RIDGE if i % 2 == 0 else HILT_GRIP
        else:
            c = HILT_SHINE if i == 4 else HILT_SILVER
        cv.put(x, y, c)
        cv.put(x + round(-dy), y + round(dx), mix(c, (0, 0, 0), 0.35))
    ex, ey = hx + dx * 5, hy + dy * 5
    # motion smears for spinning blades
    for tdx, tdy, a in trail:
        for i in range(0, int(length * 2)):
            t = 5 + i * 0.5
            cv.add(round(hx + tdx * t), round(hy + tdy * t), col, a)
            cv.add(round(hx + tdx * t + 1), round(hy + tdy * t), col, a * 0.5)
    if length > 0:
        x1, y1 = ex + dx * length, ey + dy * length
        # light spill on whatever is near: face, robe, droids, deck
        mx, my = lerp(ex, x1, 0.3), lerp(ey, y1, 0.3)
        glow(cv, mx, my, col, 24 + 3 * hum, 0.17 * hum)
        if floor_y is not None:
            floor_spill(cv, int(lerp(ex, x1, 0.5)), floor_y, col, 28, 5, 0.4 * hum)
        # bloom along the blade
        R = 6.5 + 2 * hum
        steps = max(1, int(length / 3))
        for j in range(steps + 1):
            t = j / steps
            glow(cv, lerp(ex, x1, t), lerp(ey, y1, t), col, R, 0.21 * hum)
        glow(cv, x1, y1, col, R + 1, 0.26 * hum)
        thick_line(lambda x, y: cv.put(x, y, col), ex, ey, x1, y1, 1.6)
        thick_line(lambda x, y: cv.put(x, y, inner), ex, ey, x1, y1, 1.0)
        thick_line(lambda x, y: cv.put(x, y, core), ex, ey, x1, y1, 0.5)
        glow(cv, x1, y1, (255, 255, 255), 2.5, 0.5 * hum)
    if flash > 0:
        flare(cv, round(ex), round(ey), col, flash * amp)


class Particles:
    def __init__(self):
        self.items = []

    def burst(self, x, y, n, rng, speed, up, life, color, grav=0.35, kind='dust'):
        for _ in range(n):
            a = rng.uniform(-math.pi, 0)
            v = rng.uniform(0.4, 1.0) * speed
            self.items.append(dict(x=x, y=y, vx=math.cos(a) * v * 1.6,
                                   vy=math.sin(a) * v * up, life=rng.randint(*life),
                                   age=0, color=color, grav=grav, kind=kind))

    def step(self, cv, cam):
        alive = []
        for p in self.items:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += p['grav']
            p['vx'] *= 0.9
            p['age'] += 1
            if p['y'] > GROUND + 1 and p['kind'] != 'spark':
                p['y'] = GROUND + 1
                p['vy'] *= -0.2
            if p['age'] >= p['life']:
                continue
            alive.append(p)
            fade = 1 - p['age'] / p['life']
            sx, sy = p['x'], p['y'] - cam
            if p['kind'] == 'puff':
                r = 2 + 5 * (1 - fade)
                R = int(r) + 1
                for dy in range(-R, R + 1):
                    for dx in range(-R, R + 1):
                        if dx * dx + dy * dy <= r * r:
                            cv.blend(sx + dx, sy + dy, p['color'], 0.5 * fade)
            elif p['kind'] == 'dust':
                cv.blend(sx, sy, p['color'], 0.95 * fade)
                if fade > 0.4:
                    cv.blend(sx + 1, sy, p['color'], 0.7 * fade)
                    cv.blend(sx, sy + 1, p['color'], 0.5 * fade)
            else:
                cv.put(sx, sy, mix((255, 160, 40), (255, 250, 210), fade))
                cv.blend(sx - p['vx'] * 0.6, sy - p['vy'] * 0.6, (255, 190, 80), 0.6 * fade)
                cv.add(sx, sy, (255, 170, 60), 0.3 * fade)
        self.items = alive


def shadow(cv, x, y, rx, a):
    for dx in range(-rx, rx + 1):
        for dy in (-2, -1, 0, 1, 2):
            if (dx / rx) ** 2 + (dy / 2.2) ** 2 <= 1:
                cv.blend(x + dx, y + dy, (60, 36, 20), a)


def shake_frame(cv, sx, sy):
    if not sx and not sy:
        return cv
    out = Canvas(W, H)
    for y in range(H):
        yy = min(H - 1, max(0, y - sy))
        src = cv.px[yy * W * 3:(yy + 1) * W * 3]
        if sx > 0:
            src = src[:3] * sx + src[:-3 * sx]
        elif sx < 0:
            src = src[-3 * sx:] + src[-3:] * (-sx)
        out.px[y * W * 3:(y + 1) * W * 3] = src
    return out


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def kenobi_track():
    """Physics for the drop. Returns per-frame (x, y, pose), the landing frame and x."""
    track = []
    x, y = 118.0, float(BEAM_Y)
    for _ in range(17):
        track.append((x, y, K_CROUCH))
    track.append((x + 1.5, y, lerp_pose(K_CROUCH, K_LEAP, 0.5)))
    track.append((x + 3, y - 3, K_LEAP))
    x, y, vy = x + 4.5, y - 4.5, -3.5
    f = 0
    while True:
        x += 0.5
        y += vy
        vy = min(32.0, vy + 3.0)
        if y >= GROUND:
            break
        track.append((x, y, lerp_pose(K_LEAP, K_FALL, ease(f / 3))))
        f += 1
    return track, len(track), x


def breathe(pose, f, amt):
    b = math.sin(f * 0.45) * amt
    out = dict(pose)
    for k in ('chest', 'sh', 'head', 'eb', 'hb', 'ef', 'hf'):
        out[k] = (pose[k][0], pose[k][1] + b)
    return out


def render(out_path, scale):
    t0 = time.time()
    rng = random.Random(1138)
    layers = (build_sky(), build_far(), build_mid(), build_main(), build_fg())
    fg = layers[4]

    track, L, land_x = kenobi_track()
    KX = land_x
    GX = 318
    S = L + 30            # Grievous turns
    A = S + 27            # arms split
    K = A + 9             # Kenobi takes his guard and ignites
    END = K + 26          # fade begins
    TOTAL = END + 9

    # The army, back to front: two thinning B1 ranks, a rank of B2s, a front B1 rank.
    ranks = (('b1', 0.6, GROUND - 56, 15, 196, 0.46),
             ('b1', 0.8, GROUND - 40, 20, 204, 0.28),
             ('b2', 1.05, GROUND - 25, 46, 214, 0.10),
             ('b1', 1.0, GROUND - 12, 34, 226, 0.02))
    droids = []
    for row, (kind, sc, fy, step, x0, dim) in enumerate(ranks):
        x = x0
        while x < W + 8:
            near = abs(x - GX) < (40 if kind == 'b1' else 46)
            if not (row >= 1 and near):
                droids.append(dict(kind=kind, x=x + int(hn(x, row, 5) * 5), y=fy, sc=sc, dim=dim,
                                   snap=L + 2 + int((x - 180) / 40) + row,
                                   bob=kind == 'b1' and hn(x, row, 6) < 0.3,
                                   phase=int(hn(x, row, 8) * 18)))
            x += step

    motes = [dict(x=rng.uniform(0, W), y=rng.uniform(0, GROUND - 60),
                  ph=rng.uniform(0, 6.28)) for _ in range(50)]

    parts = Particles()
    cam = 0.0
    shake = {L: (0, 4), L + 1: (1, -3), L + 2: (-1, 3), L + 3: (0, -2), L + 4: (0, 1)}
    fade_tables = {}

    frames = []

    for f in range(TOTAL):
        # ---- camera and Kenobi state
        point = 0.0
        if f < L:
            kx, ky, kpose = track[f]
        else:
            kx, ky = KX, float(GROUND)
            if f < L + 4:
                kpose = K_LAND
            elif f < L + 9:
                kpose = lerp_pose(K_LAND, K_STAND, ease((f - L - 4) / 5))
            elif f < K:
                g = ease((f - (L + 10)) / 3) - ease((f - (L + 26)) / 3)
                kpose = lerp_pose(K_STAND, K_GESTURE, g)
            else:
                u = ease((f - K) / 4)
                kpose = breathe(lerp_pose(K_STAND, K_GUARD, u), f, 0.3 * u)
                point = u
        target = max(0.0, min(PAN, ky - 110))
        cam += (target - cam) * 0.55
        if f >= L:
            cam = cam + (PAN - cam) * 0.6
        ci = int(round(cam))
        floor_y = GROUND - ci

        cv = background(layers, ci)
        lit_scene = f > A + 3
        if lit_scene:
            # house lights drop once the blades are out, so they read as light sources
            cv.px = bytearray(cv.px.translate(HOUSE_DIM))

        # ---- lights on the main plane
        for i, (lx, ly) in enumerate(RED_LIGHTS):
            sy = ly - ci
            if -6 <= sy < H + 6:
                on = ((f + i * 5) // 7) % 2 == 0
                for dx in (0, 1, 2):
                    cv.put(lx + dx, sy, RED_ON if on else RED_OFF)
                if on:
                    glow(cv, lx + 1, sy, (255, 60, 30), 6, 0.45)
        for lx, ly in LAMPS:
            sy = ly - ci
            if -9 <= sy < H + 9:
                glow(cv, lx, sy, (255, 200, 120), 9, 0.35)

        # ---- dust motes drifting in the shafts
        for m in motes:
            mx = (m['x'] + math.sin(f * 0.08 + m['ph']) * 4) % W
            my = (m['y'] + f * 0.35) % (GROUND - 60)
            sy = my - ci
            if 0 <= sy < H:
                cv.blend(int(mx), int(sy), (255, 244, 214), 0.55)

        # ---- shadows on the platform
        if f < L:
            a = max(0.0, 0.38 - (GROUND - ky) / 420)
            if a > 0.02:
                shadow(cv, int(kx), floor_y + 1, 8, a)
        else:
            shadow(cv, int(KX), floor_y + 1, 10, 0.42)
        shadow(cv, GX, floor_y + 1, 14, 0.42)

        # ---- droid army
        for dr in droids:
            sy = dr['y'] - ci
            if sy - 80 > H:
                continue
            bob = 1 if dr['bob'] and ((f + dr['phase']) // 9) % 2 == 0 else 0
            reacted = f > dr['snap']
            if dr['kind'] == 'b1':
                hh = -0.6 if f < dr['snap'] else (0.2 if f == dr['snap'] else 1.0)
                stamp_droid(cv, 'b1', dr['x'], sy + bob, dr['sc'], (hh, reacted), dr['dim'])
            else:
                stamp_droid(cv, 'b2', dr['x'], sy, dr['sc'], reacted, dr['dim'])
                k = DROID_K * dr['sc']
                ex, ey = dr['x'] - B2_EYE_AT[0] * k, sy + B2_EYE_AT[1] * k
                glow(cv, ex, ey, (255, 40, 20), 3.5, 0.5 if reacted else 0.25)

        # ---- Grievous
        if f < S:
            gpose, gd = G_IDLE, 1.0
        elif f < S + 6:
            u = (f - S) / 5
            gpose = dict(G_IDLE, spread=0.8 * math.sin(math.pi * u))
            gd = lerp(1.0, -1.0, ease(u))
            if abs(gd) < 0.25:
                gd = 0.25 if u < 0.5 else -0.25
        elif f < A:
            gpose, gd = G_IDLE, -1.0
        else:
            gpose, gd = lerp_pose(G_IDLE, G_FOUR, ease((f - A) / 4)), -1.0
        draw_grievous(cv, GX, floor_y, gpose, gd, f)

        # Blades are light sources: they are queued and drawn after the scene
        # fade, so they fade out last.
        blades = []

        # Grievous blades: upper front, upper back, lower front, lower back
        if f >= A + 3:
            spin = f - (A + 8)
            for i, (hk, base_ang, colors) in enumerate((('h1', -62, BLUE), ('h2', -112, GREEN),
                                                         ('h3', -20, GREEN), ('h4', 200, BLUE))):
                lit = A + 3 + i
                if f < lit:
                    continue
                age = f - lit
                grow = (0.4, 0.8, 1.0)[min(2, age)]
                ang = math.radians(base_ang)
                trail = ()
                if i >= 2 and spin >= 0:
                    step = math.radians(56 if i == 2 else -56)
                    ang += step * spin
                    trail = tuple((math.cos(ang - step * j / 3) * gd, math.sin(ang - step * j / 3),
                                   (0.34, 0.22, 0.12)[j - 1]) for j in (1, 2, 3))
                dx, dy = math.cos(ang) * gd, math.sin(ang)
                hx, hy = gpose[hk]
                sx, sy = GX + gd * hx * GRV_K, floor_y + hy * GRV_K
                hum = 0.8 + 0.4 * hn(f, i, 31)
                blades.append(((sx, sy, dx, dy, 28 * grow, colors, hum, trail),
                               dict(flash=(1.0, 0.5)[age] if age < 2 else 0.0, floor_y=floor_y)))
                # spinning blades scrape the platform
                if i >= 2 and spin >= 0:
                    tx, ty = sx + dx * 33, sy + dy * 33
                    if ty >= floor_y - 1:
                        px = sx + dx * (floor_y - 1 - sy) / dy if dy > 0.05 else tx
                        parts.burst(px, GROUND - 1, 6, rng, 3.4, 1.4, (3, 7), None,
                                    grav=0.45, kind='spark')

        # ---- Kenobi
        draw_kenobi(cv, kx, ky - ci, kpose, 1, f,
                    flutter=2.5 if L - 20 < f < L else 1.0, point=point)
        if f >= K + 2:
            age = f - (K + 2)
            grow = (0.4, 0.8, 1.0)[min(2, age)]
            hx, hy = kpose['hb']
            sx, sy = kx + hx * KEN_K, ky - ci + hy * KEN_K
            hum = 0.8 + 0.4 * hn(f, 9, 33)
            blades.append(((sx, sy, K_SABER_DIR[0], K_SABER_DIR[1], 32 * grow, BLUE, hum),
                           dict(flash=(1.2, 0.6)[age] if age < 2 else 0.0, floor_y=floor_y)))

        # ---- landing
        if f == L:
            parts.burst(KX, GROUND - 2, 24, rng, 6.0, 0.35, (9, 15), DUST, grav=0.0, kind='puff')
            parts.burst(KX, GROUND - 1, 34, rng, 7.0, 1.8, (6, 12), mix(DUST, (255, 255, 255), 0.35),
                        grav=0.5)
        if L <= f < L + 4:
            r = 15 + (f - L) * 16
            for dx in range(-r, r + 1):
                if abs(dx) > r - 4:
                    for yy in (0, 1):
                        cv.blend(KX + dx, floor_y + yy, (255, 236, 196), 0.75 - (f - L) * 0.17)
        parts.step(cv, ci)

        # ---- motion streaks during the drop
        if 20 <= f < L:
            for j in range(12):
                lx = int(hn(f, j, 41) * W)
                ln = 15 + int(hn(f, j, 42) * 33)
                ly = int(hn(f, j, 43) * H)
                for k in range(ln):
                    cv.blend(lx, ly + k, (255, 246, 226), 0.16 * (1 - k / ln))
            for j, off in enumerate((-8, -2, 4, 10)):
                ln = 15 + j * 6
                for k in range(ln):
                    cv.blend(kx + off, ky - ci - 66 - k, (255, 250, 236), 0.4 * (1 - k / ln))

        # ---- foreground girders
        fg.blit(cv, int(round(ci * SPEED_FG)))

        # ---- subtitles
        t1 = L + 8
        if t1 <= f < t1 + 20:
            draw_text(cv, "Hello there!", KX, 224, (f - t1) * 3 + 1)
        t2 = S + 6
        if t2 <= f < t2 + 20:
            draw_text(cv, "General Kenobi!", GX, 224, (f - t2) * 3 + 1)

        # ---- fades and shake
        if f < 5:
            level = f / 5
        elif f >= END:
            level = max(0.0, 1 - (f - END + 1) / 6)
        else:
            level = 1.0
        if level != 1.0:
            q = round(level * 8) / 8
            if q not in fade_tables:
                fade_tables[q] = bytes(min(255, int(v * q)) for v in range(256))
            cv.px = bytearray(cv.px.translate(fade_tables[q]))
        amp = 1.0 if level >= 1.0 else min(1.0, level * 2)
        for args, kw in blades:
            draw_saber(cv, *args, amp=amp, **kw)
        sx, sy = shake.get(f, (0, 0))
        cv = shake_frame(cv, sx, sy)

        frames.append(bytes(cv.px))

    # Start the file on the first fully lit frame and move the fade-in to the tail.
    # The loop plays in the same order, but anything that shows only frame 0
    # (autoplay off, link previews) gets the rafters shot instead of black.
    encode(frames[5:] + frames[:5], out_path, scale)
    return TOTAL, time.time() - t0


def reserved_colours():
    """Blade colours the palette must keep: each blade ramp, its bloom over the
    dark deck and dimmed walls, and its fade-out steps. Without these, one
    global palette spends its slots on the background and the blades go grey."""
    out = []
    grounds = ((30, 22, 16), (62, 42, 26), (104, 72, 44), (150, 116, 80))
    for ramp in (BLUE, GREEN):
        out += list(ramp)
        for g in grounds:
            for k in (0.12, 0.25, 0.45, 0.7):
                out.append(tuple(min(255, int(g[i] + ramp[0][i] * k)) for i in range(3)))
        for a in (0.3, 0.55, 0.8):
            out += [mix((0, 0, 0), c, a) for c in ramp[:2]]
    out += [(255, 160, 40), (255, 210, 120), (255, 250, 210), B2_EYE, (255, 255, 255)]
    return out


def encode(frames, out_path, scale):
    """Two passes: a global palette from the clip, topped up with the reserved
    blade colours, then the frames mapped onto it without dithering."""
    ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'
    with tempfile.TemporaryDirectory() as tmp:
        raw, pal = os.path.join(tmp, 'frames.rgb'), os.path.join(tmp, 'palette.rgba')
        with open(raw, 'wb') as fh:
            for px in frames:
                fh.write(px)
        src = ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', raw]
        reserved = []
        for c in reserved_colours():
            if c not in reserved:
                reserved.append(c)
        keep = 255 - len(reserved)
        subprocess.run([ffmpeg, '-v', 'error', '-y'] + src +
                       ['-vf', f'palettegen=max_colors={keep + 1}:stats_mode=full:reserve_transparent=1',
                        '-f', 'rawvideo', '-pix_fmt', 'rgba', pal], check=True)
        entries = open(pal, 'rb').read()
        base = []
        for i in range(0, 1024, 4):
            r, g, b, a = entries[i:i + 4]
            if a == 255 and (r, g, b) not in base:
                base.append((r, g, b))
        colours = (base[:keep] + [c for c in reserved if c not in base])[:255]
        colours += [colours[-1]] * (255 - len(colours))
        with open(pal, 'wb') as fh:
            for r, g, b in colours:
                fh.write(bytes((r, g, b, 255)))
            fh.write(bytes((0, 255, 0, 0)))
        subprocess.run([ffmpeg, '-v', 'error', '-y'] + src +
                       ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', '16x16', '-i', pal,
                        '-filter_complex',
                        f'[0:v]scale=iw*{scale}:ih*{scale}:flags=neighbor[v];'
                        '[v][1:v]paletteuse=dither=none:diff_mode=rectangle',
                        '-loop', '0', out_path], check=True)



def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--out', default=os.path.join(here, '..', 'assets', 'hello-there.gif'))
    ap.add_argument('--scale', type=int, default=2)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    frames, secs = render(args.out, args.scale)
    size = os.path.getsize(args.out)
    print(f"{args.out}: {frames} frames @ {FPS} fps, {W * args.scale}x{H * args.scale}, "
          f"{size / 1e6:.2f} MB, rendered in {secs:.1f}s")


if __name__ == '__main__':
    main()
