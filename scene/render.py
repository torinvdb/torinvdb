#!/usr/bin/env python3
"""
Hello there.

A 2D pixel-art scene for the profile README, drawn entirely in code: no image
files, no font files, no third-party packages. Every pixel comes from the
geometry below. Frames stream to ffmpeg, which builds one palette, upscales
with nearest neighbour and writes the GIF.

    python3 scene/render.py                       # writes assets/hello-there.gif
    python3 scene/render.py --out /tmp/test.gif   # somewhere else

Needs Python 3.9+ and ffmpeg on PATH.
"""

import argparse
import math
import os
import random
import shutil
import subprocess
import sys
import time

W, H = 288, 162          # native resolution
FPS = 12
PAN = 200                # how far the camera travels down the main plane
GROUND = 343             # main-plane row the fighters stand on
BEAM_Y = 61              # main-plane row Kenobi crouches on

# Parallax speeds relative to the main plane.
SPEED_FAR, SPEED_MID, SPEED_MAIN, SPEED_FG = 0.25, 0.55, 1.0, 1.4


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

SKY_TOP, SKY_BOT = (252, 234, 186), (220, 176, 116)
HAZE = (214, 170, 112)

FAR = dict(face=(206, 164, 114), face2=(198, 156, 108), lip=(228, 194, 146),
           shade=(184, 142, 98), win=(166, 124, 86), lit=(246, 216, 160),
           rim=(186, 140, 94))
MID = dict(face=(166, 114, 68), face2=(156, 106, 62), lip=(208, 158, 100),
           shade=(118, 78, 48), deep=(84, 52, 32), door=(52, 34, 24),
           lit=(255, 204, 116), rail=(100, 66, 42))
STEEL = dict(dark=(26, 22, 30), body=(46, 40, 50), mid=(62, 56, 66),
             hi=(98, 88, 94), rivet=(84, 76, 82))
FLOOR = dict(back=(178, 130, 82), front=(122, 82, 48), lip=(230, 188, 132),
             seam=(100, 68, 40), paint=(196, 150, 90))
FG = dict(sil=(14, 10, 18), sil2=(24, 18, 26), rim=(92, 58, 42))

RED_ON, RED_OFF, LAMP = (255, 64, 40), (86, 22, 22), (255, 222, 150)

# Character ramps: (shadow, base, light)
K_HAIR = ((112, 56, 26), (160, 88, 42), (204, 128, 66))
K_SKIN = ((178, 112, 84), (226, 162, 126), (246, 200, 164))
K_TUNIC = ((176, 156, 118), (216, 200, 160), (242, 232, 202))
K_TABARD = ((132, 104, 72), (164, 134, 96), (190, 162, 120))
K_ROBE = ((64, 40, 26), (100, 66, 40), (134, 92, 56))
K_BOOT = ((36, 26, 20), (60, 42, 32), (86, 62, 46))
K_LINE = (30, 18, 16)

G_BONE = ((150, 146, 132), (206, 202, 184), (236, 232, 216))
G_METAL = ((40, 42, 50), (64, 66, 76), (96, 98, 110))
G_CAPE = ((30, 30, 38), (50, 50, 60), (76, 76, 88))
G_LINE = (12, 12, 18)
G_EYE = (255, 222, 60)

D_TAN = ((132, 108, 72), (186, 160, 112), (224, 202, 152))
D_GUN = ((44, 44, 50), (66, 66, 72), (90, 90, 96))
D_LINE = (58, 42, 30)

HILT = ((70, 70, 78), (150, 150, 158), (210, 210, 220))
BLUE = ((70, 150, 255), (226, 242, 255))
GREEN = ((70, 236, 104), (230, 255, 232))

TEXT, TEXT_EDGE = (255, 230, 40), (10, 8, 8)
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

    def get(self, x, y):
        i = (int(y) * self.w + int(x)) * 3
        return self.px[i], self.px[i + 1], self.px[i + 2]

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

    def get(self, x, y):
        i = (y * self.w + x) * 3
        return self.px[i], self.px[i + 1], self.px[i + 2]

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


def fill_poly(target_plot, pts):
    """Even-odd scanline fill. target_plot(x, y) is called per pixel."""
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
                target_plot(x, y)


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
# Pixel font (5x7, hand-set bitmaps)
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


def draw_text(cv, s, cx, y, reveal=None):
    """Meme subtitle: yellow glyphs with a hard dark edge, centred on cx."""
    if reveal is not None:
        shown = s[:max(0, reveal)]
    else:
        shown = s
    x = int(cx - text_width(s) / 2)
    on = []
    for ch in shown:
        g = GLYPHS[ch]
        for gy, row in enumerate(g):
            for gx, bit in enumerate(row):
                if bit == '#':
                    on.append((x + gx, y + gy))
        x += len(g[0]) + 1
    lit = set(on)
    for px, py in on:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1, 2):
                if (px + dx, py + dy) not in lit:
                    cv.put(px + dx, py + dy, TEXT_EDGE)
    for px, py in on:
        cv.put(px, py, TEXT if py - y < 4 else mix(TEXT, (255, 168, 20), 0.35))


# --------------------------------------------------------------------------
# Background layers
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
    h = H + int(PAN * SPEED_FAR)
    L = Layer(h)
    # Strata of uneven height so the wall reads as rock, not stairs.
    bands, y = [], 24
    rr = random.Random(7)
    while y < h:
        bh = rr.choice((14, 19, 23, 27))
        bands.append((y, bh))
        y += bh
    def band_at(y):
        for i, (b0, bh) in enumerate(bands):
            if b0 <= y < b0 + bh:
                return i, y - b0, bh
        return -1, y, 1
    for x in range(W):
        rim = int(22 + 5 * math.sin(x * 0.045) + 3 * math.sin(x * 0.13 + 1.3) + 2 * hn(x, 1))
        for y in range(rim, h):
            lvl, r, bh = band_at(y)
            # wall bulges in and out between vertical buttresses
            bulge = math.sin((x + lvl * 23) * 0.09)
            c = FAR['face'] if bulge > -0.2 else FAR['face2']
            if (x + lvl * 23) % 70 in (0, 1):
                c = FAR['shade']
            if y == rim or r == 0:
                c = FAR['lip']
            elif r == 1:
                c = FAR['shade']
            else:
                cell = (x + lvl * 7) // 16
                wx = (x + lvl * 7) % 16
                if hn(cell, lvl, 3) < 0.38 and 6 <= wx <= 8 and bh - 9 <= r <= bh - 3:
                    if not (r == bh - 9 and wx != 7):
                        c = FAR['lit'] if hn(cell, lvl, 4) < 0.2 else FAR['win']
            depth = y / h
            c = mix(c, (150, 102, 64), 0.42 * depth * depth)
            L.put(x, y, mix(c, SKY_TOP, 0.40 - 0.25 * depth))
    L.finish()
    return L


def build_mid():
    h = H + int(PAN * SPEED_MID)
    L = Layer(h)
    level_h = 30

    def edge(side, y):
        # the curve of the sinkhole wall, smooth with a little wobble
        return 42 + 7 * math.sin(y * 0.011 + side * 1.7) + 2 * math.sin(y * 0.05 + side * 3.1)

    for side in (0, 1):
        for y in range(h):
            e = edge(side, y)
            r = (y + 12) % level_h
            lvl = (y + 12) // level_h
            lip = r <= 1
            reach = int(e + (3 if lip else 0))
            for i in range(reach):
                x = i if side == 0 else W - 1 - i
                depth = i / max(1.0, e)        # 0 at the screen edge, 1 at the rim
                if lip:
                    c = MID['lip'] if r == 0 else MID['shade']
                elif r <= 4:
                    c = MID['deep'] if r <= 2 else MID['shade']
                else:
                    c = MID['face'] if depth < 0.55 else MID['face2']
                    if i >= e - 2:
                        c = mix(MID['face'], MID['lip'], 0.5)
                    elif i >= e - 5:
                        c = MID['face2']
                    slot = (i + lvl * 5) // 12
                    sx = (i + lvl * 5) % 12
                    if i < e - 6 and hn(slot, lvl, 9 + side) < 0.55:
                        if 4 <= sx <= 7 and 12 <= r <= 23:
                            if not (r == 12 and sx in (4, 7)):
                                lit = hn(slot, lvl, 11) < 0.3 and r > 16
                                c = MID['lit'] if lit else MID['door']
                                if sx == 4 and not lit:
                                    c = MID['deep']
                    if i < e - 6 and hn(slot, lvl, 13 + side) > 0.8 and 2 <= sx <= 3 and 8 <= r <= 9:
                        c = MID['deep']
                c = mix(c, (60, 36, 22), 0.28 * (1 - depth))
                L.put(x, y, mix(c, HAZE, 0.06))
    # A walkway across the pit, visible early in the pan.
    by = 98
    for x in range(W):
        if not L.has(x, by):
            for yy in range(by, by + 3):
                L.put(x, yy, MID['rail'] if yy > by else MID['lip'])
            if x % 7 == 0:
                for yy in range(by - 5, by):
                    L.put(x, yy, MID['rail'])
            L.put(x, by - 5, MID['rail'])
    L.finish()
    return L


def build_main():
    h = H + PAN
    L = Layer(h)
    # ceiling
    for y in range(0, 11):
        for x in range(W):
            c = STEEL['dark']
            if x % 18 == 0 or y == 10:
                c = (20, 16, 22)
            if y == 5 and x % 18 in (3, 15):
                c = STEEL['rivet']
            L.put(x, y, c)
    # truss chords
    for y0 in (12, 38):
        for x in range(W):
            L.put(x, y0, STEEL['hi'])
            L.put(x, y0 + 1, STEEL['mid'])
            L.put(x, y0 + 2, STEEL['body'])
            L.put(x, y0 + 3, STEEL['dark'])
    # zig-zag bracing between chords
    plot = lambda x, y: L.put(x, y, STEEL['body']) if 0 <= x < W else None
    for x0 in range(-24, W + 24, 24):
        thick_line(plot, x0, 15, x0 + 12, 37, 0.8)
        thick_line(plot, x0 + 12, 37, x0 + 24, 15, 0.8)
        thick_line(lambda x, y: L.put(x, y, STEEL['mid']), x0, 16, x0, 37, 0.5)
    # beam Kenobi crouches on, with its hangers
    for x in (14, 166):
        for y in range(42, BEAM_Y + 1):
            L.put(x, y, STEEL['mid'])
            L.put(x + 1, y, STEEL['dark'])
    for x in range(6, 176):
        L.put(x, BEAM_Y + 1, STEEL['hi'])
        L.put(x, BEAM_Y + 2, STEEL['mid'])
        L.put(x, BEAM_Y + 3, STEEL['body'] if x % 6 else STEEL['rivet'])
        L.put(x, BEAM_Y + 4, STEEL['body'])
        L.put(x, BEAM_Y + 5, STEEL['dark'])
    # hanging cables and lamps
    for cx, bottom in ((122, 150), (204, 118), (238, 96), (40, 132)):
        for y in range(42, bottom):
            L.put(cx, y, (20, 16, 22))
        for dx in range(-2, 3):
            L.put(cx + dx, bottom, STEEL['mid'])
            L.put(cx + dx, bottom + 1, STEEL['dark'])
        L.put(cx, bottom + 2, LAMP)
    # landing platform
    top = GROUND - 37
    vx, vy = W / 2, top - 70
    seams = [top + int(56 * (k / 7) ** 1.5) for k in range(1, 8)]
    for y in range(top, h):
        t = (y - top) / (h - top)
        for x in range(W):
            if y == top:
                c = FLOOR['lip']
            elif y == top + 1:
                c = mix(FLOOR['lip'], FLOOR['back'], 0.6)
            else:
                c = mix(FLOOR['back'], FLOOR['front'], t)
                if y in seams:
                    c = mix(c, FLOOR['seam'], 0.55)
                else:
                    x0 = vx + (x - vx) * (h - vy) / (y - vy)
                    if int(x0) % 40 in (0,):
                        c = mix(c, FLOOR['seam'], 0.45)
                ring = ((x - 156) / 118) ** 2 + ((y - (GROUND - 6)) / 17) ** 2
                if 0.84 < ring < 1.0:
                    c = mix(c, FLOOR['paint'], 0.45)
                n = hn(x // 2, y, 21)
                if n < 0.05:
                    c = mix(c, FLOOR['seam'], 0.3)
                elif n > 0.97:
                    c = mix(c, FLOOR['lip'], 0.4)
            L.put(x, y, c)
    L.finish()
    return L


def build_fg():
    h = H + int(PAN * SPEED_FG)
    L = Layer(h)
    sil = lambda x, y: L.put(x, y, FG['sil'])

    def column(x0, x1, y1):
        for y in range(0, y1):
            for x in range(x0, x0 + 3):
                sil(x, y)
            for x in range(x1 - 3, x1):
                sil(x, y)
        for y0 in range(0, y1 - 14, 16):
            thick_line(sil, x0 + 2, y0, x1 - 3, y0 + 16, 0.6)
            thick_line(sil, x1 - 3, y0, x0 + 2, y0 + 16, 0.6)

    column(0, 12, 262)
    column(270, 288, 262)
    thick_line(sil, 168, -6, 300, 44, 3.6)
    for y in range(206, 214):
        for x in range(W):
            sil(x, y)
    for y in range(252, 257):
        for x in range(W):
            sil(x, y)
    thick_line(sil, 12, 214, 60, 252, 1.5)
    thick_line(sil, 276, 214, 228, 252, 1.5)
    # rim light from the sinkhole opening above
    rim = []
    for y in range(h):
        for x in range(W):
            if L.has(x, y):
                if not L.has(x, y - 1) and y > 0:
                    rim.append((x, y, FG['rim']))
                elif not L.has(x - 1, y) and x > 0:
                    rim.append((x, y, FG['sil2']))
                elif (x * 7 + y * 3) % 23 == 0:
                    rim.append((x, y, FG['sil2']))
    for x, y, c in rim:
        L.put(x, y, c)
    L.finish()
    return L


RED_LIGHTS = [(x, 41) for x in (30, 90, 150, 210, 258)] + [(x, 15) for x in (60, 180)]
LAMPS = [(122, 152), (204, 120), (238, 98), (40, 134)]


def light_shafts(cv, cam):
    """Warm light shafts slanting down through the haze, fixed to the mid plane."""
    off = cam * SPEED_MID
    for y in range(H):
        wy = y + off
        for x in range(W):
            v = (x * 0.62 + wy * 1.0) % 150
            k = 0.0
            if v < 22:
                k = 0.11 * math.sin(v / 22 * math.pi)
            elif 64 < v < 74:
                k = 0.07 * math.sin((v - 64) / 10 * math.pi)
            if k > 0.01:
                cv.blend(x, y, (255, 240, 200), k)


_vig = None


def vignette(cv):
    """Darken the corners in a few hard steps, retro style."""
    global _vig
    if _vig is None:
        _vig = []
        for y in range(H):
            for x in range(W):
                dx, dy = (x - W / 2) / (W / 2), (y - H * 0.45) / (H * 0.62)
                v = max(0.0, dx * dx + dy * dy - 0.45)
                step = min(4, int(v * 5 + bayer(x, y) * 0.999))
                _vig.append(step)
        _vig = bytes(_vig)
    tables = [bytes(int(v * (1 - 0.07 * s)) for v in range(256)) for s in range(5)]
    p = cv.px
    for j, s in enumerate(_vig):
        if s:
            t = tables[s]
            i = j * 3
            p[i], p[i + 1], p[i + 2] = t[p[i]], t[p[i + 1]], t[p[i + 2]]


_bg_cache = {}
HOUSE_DIM = bytes(int(v * 0.74) for v in range(256))


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
    """Collects part-tagged pixels, then shades and outlines them."""

    def __init__(self, ox, oy, d, k=1.0):
        self.ox, self.oy, self.d, self.k = ox, oy, d, k
        self.cells = {}
        self.pid = 0
        self.ramp = None

    def P(self, p):
        return (self.ox + self.d * p[0] * self.k, self.oy + p[1] * self.k)

    def part(self, ramp, new=True):
        if new:
            self.pid += 1
        self.ramp = ramp

    def plot(self, x, y):
        self.cells[(x, y)] = (self.pid, self.ramp)

    def at(self, p):
        x, y = self.P(p)
        self.plot(math.floor(x + 0.5), math.floor(y + 0.5))

    def line(self, a, b, r=0.5):
        (x0, y0), (x1, y1) = self.P(a), self.P(b)
        thick_line(self.plot, x0, y0, x1, y1, max(0.5, r * self.k))

    def poly(self, pts):
        fill_poly(self.plot, [self.P(p) for p in pts])

    def render(self, cv, outline, dim=0.0, dim_to=HAZE):
        cells = self.cells
        out = []
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
            out.append((x, y, ramp[tone]))
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (nx, ny) not in cells:
                    out.append((nx, ny, None))
        oc = mix(outline, dim_to, dim) if dim else outline
        for x, y, c in out:
            if c is None:
                cv.put(x, y, oc)
        for x, y, c in out:
            if c is not None:
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


# Kenobi, facing +x, feet at (0, 0), y up is negative.
K_STAND = dict(ff=(2, 0), fb=(-2, 0), kf=(1.5, -7), kb=(-1.5, -7), hip=(0, -13),
               chest=(0.5, -21), sh=(0.5, -20), head=(1, -25),
               ef=(2, -15.5), hf=(2.5, -11), eb=(-1.5, -15.5), hb=(-2, -11),
               tail=(-4, -1))
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
K_GUARD = dict(ff=(5, 0), fb=(-4, 0), kf=(4.5, -7), kb=(-2.5, -6), hip=(0, -12.5),
               chest=(1, -20.5), sh=(1, -19.5), head=(2, -24.5),
               ef=(4, -15), hf=(6, -16), eb=(2.5, -15), hb=(5.5, -16.5),
               tail=(-6, -1))
K_SABER_DIR = (0.42, -0.91)


RIG_K = 1.3      # characters are posed in rig units and drawn at this scale


def draw_kenobi(cv, ox, oy, pose, d, t, flutter=1.0):
    s = Sprite(ox, oy, d, RIG_K)
    p = pose
    wave = math.sin(t * 0.9) * 1.2 * flutter
    sh, hip, tail, ch = p['sh'], p['hip'], p['tail'], p['chest']
    # cloak: over the shoulders, down the back, hem flicking behind
    s.part(K_ROBE)
    s.poly([add(sh, 1.8, -1.6), add(sh, -0.5, -2.8), add(sh, -3.4, -1.2),
            add(tail, -1 + wave, 0), add(tail, 4 + wave * 0.5, 1),
            add(hip, 0.5, 2), add(ch, 0, 3)])
    # back arm, in the cloak's sleeve
    s.part(K_ROBE)
    s.line(sh, p['eb'], 1.1)
    s.line(p['eb'], p['hb'], 0.9)
    s.part(K_SKIN)
    s.line(p['hb'], p['hb'], 0.6)
    # back leg
    s.part(K_TUNIC)
    s.line(hip, p['kb'], 1.1)
    s.part(K_BOOT)
    s.line(p['kb'], p['fb'], 1.0)
    s.line(p['fb'], add(p['fb'], 2, 0), 0.6)
    # torso: tunic, crossed tabard, belt
    s.part(K_TUNIC)
    s.poly([add(ch, -2.6, -1), add(ch, 2.8, -1), add(hip, 3.2, 3), add(hip, -3.2, 3)])
    s.part(K_TABARD)
    s.line(add(ch, 2.2, -0.5), add(hip, 0.8, 0), 0.6)
    s.line(add(ch, -1.0, -0.5), add(ch, 1.6, 2.5), 0.5)
    s.part(K_BOOT)
    s.line(add(hip, -2.8, 0), add(hip, 3.0, 0), 0.6)
    # front leg
    s.part(K_TUNIC)
    s.line(hip, p['kf'], 1.1)
    s.part(K_BOOT)
    s.line(p['kf'], p['ff'], 1.0)
    s.line(p['ff'], add(p['ff'], 2, 0), 0.6)
    # hood bunched behind the neck
    s.part(K_ROBE)
    s.line(add(sh, -2.2, -2), add(sh, -0.6, -2.6), 1.2)
    # head: neck, then face, swept hair and beard classified per pixel
    hd = p['head']
    s.part(K_SKIN)
    s.line(add(ch, 0.5, -1), hd, 0.8)
    s.part(K_SKIN)
    pid = s.pid
    hx, hy = s.P(hd)
    hx, hy = math.floor(hx + 0.5), math.floor(hy + 0.5)
    R = int(math.ceil(3.4 * RIG_K))
    for py in range(-R, R + 1):
        for px in range(-R, R + 1):
            rx, ry = px / RIG_K, py / RIG_K
            if rx * rx + ry * ry > 3.3 * 3.3 or (ry > 2.6 and rx < -0.5):
                continue
            if ry <= -1.9 or rx <= -1.6 or (ry <= -1.0 and rx <= 0.0):
                ramp = K_HAIR                      # hair, parted and swept back
            elif ry >= 1.25 and rx >= -1.0:
                ramp = K_HAIR                      # beard
            else:
                ramp = K_SKIN
            s.pid, s.ramp = pid, ramp
            s.plot(hx + d * px, hy + py)
    s.part(K_SKIN)
    s.at(add(hd, 3.3, -0.2))                       # nose
    s.part(flat(K_LINE))
    s.at(add(hd, 1.4, -0.6))                       # eye
    s.part(flat(mix(K_HAIR[0], K_SKIN[0], 0.4)))
    s.at(add(hd, 1.6, 1.3))                        # mouth
    # front arm, in the sleeve
    s.part(K_ROBE)
    s.line(sh, p['ef'], 1.1)
    s.line(p['ef'], p['hf'], 0.9)
    s.part(K_SKIN)
    s.line(p['hf'], p['hf'], 0.6)
    s.render(cv, K_LINE)


# Grievous, facing +x. Digitigrade legs, hunched, cape behind.
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


def draw_grievous(cv, ox, oy, pose, d, t):
    s = Sprite(ox, oy, d, RIG_K)
    p = pose
    sp = p['spread']
    ch, hip = p['chest'], p['hip']
    sway = math.sin(t * 0.5) * 0.6
    # cape
    s.part(G_CAPE)
    s.poly([add(ch, 2.5, -3.5), add(ch, -1, -4.5), add(ch, -4.5, -2),
            (-8 - 9 * sp + sway, -5 - 8 * sp), (-10 - 9 * sp + sway * 1.5, -3 - 7 * sp),
            (-5 - 6 * sp + sway, -4 - 4 * sp), (-1 - 3 * sp, -9 - 2 * sp),
            add(hip, 1, -1)])

    def arm(e, h):
        s.part(G_BONE)
        s.line(add(ch, 0, 1), e, 0.6)
        s.line(e, h, 0.6)
        s.part(flat(G_METAL[1]))
        s.at(e)
        s.part(G_BONE)
        s.at(add(h, 1, 0))
        s.at(add(h, 0, 1))

    def leg(knee, heel, toe):
        s.part(G_BONE)
        s.line(hip, knee, 1.0)
        s.line(knee, heel, 0.7)
        s.line(heel, toe, 0.6)
        s.part(flat(G_METAL[0]))
        s.at(knee)
        s.part(G_BONE)
        s.at(add(toe, 1, 0))

    arm(p['e4'], p['h4'])
    arm(p['e2'], p['h2'])
    leg(p['knee_b'], p['heel_b'], p['toe_b'])
    # exposed spine and gut sac
    s.part(G_METAL)
    s.line(hip, add(ch, 0, 2), 1.3)
    s.part(flat(G_METAL[0]))
    for k in range(3):
        s.at(add(hip, 1, -2 - k * 2))
    # chest plate and pelvis
    s.part(G_BONE)
    s.poly([add(ch, -3, -1.5), add(ch, 4, -0.5), add(ch, 3, 6), add(ch, -2, 5)])
    s.part(flat(G_BONE[0]))
    s.line(add(ch, 1, 0), add(ch, 0.5, 4), 0.5)
    s.part(G_BONE)
    s.poly([add(hip, -2.5, -1.5), add(hip, 3, -1.5), add(hip, 2, 2), add(hip, -2, 2)])
    leg(p['knee_f'], p['heel_f'], p['toe_f'])
    # neck and mask
    hd = p['head']
    s.part(G_METAL)
    s.line(add(ch, 1, -1), hd, 0.9)
    s.part(G_BONE)
    s.poly([add(hd, -2.5, -6), add(hd, 1, -6.5), add(hd, 3, -4.5), add(hd, 4, -1.5),
            add(hd, 3, 1), add(hd, 2.2, 6), add(hd, 0, 6.5), add(hd, -1.5, 3),
            add(hd, -2.5, -1)])
    s.part(flat(G_LINE))
    for dx in (0.5, 1.5, 2.6, 3.3):
        s.at(add(hd, dx, -1.2))                    # shadowed eye band under the brow
    s.at(add(hd, -0.5, -4.5))
    s.at(add(hd, 0.2, -3.5))
    s.part(flat(G_BONE[0]))
    for dy in (1.5, 2.5, 3.5, 4.5):
        s.at(add(hd, 1.2, dy))                     # faceplate grille
    s.part(flat(G_EYE))
    s.at(add(hd, 2.4, -1.2))
    s.part(flat((255, 250, 190)))
    s.at(add(hd, 2.4, -1.2 + 0.8))
    arm(p['e1'], p['h1'])
    arm(p['e3'], p['h3'])
    s.render(cv, G_LINE)


# B1 battle droid, body facing +x; hh turns the head (+1 forward, -1 back).
def draw_droid(cv, ox, oy, d, sc, hh, raised, dim):
    s = Sprite(ox, oy, d)
    J = lambda x, y: (x * sc, y * sc)
    s.part(D_TAN)
    s.line(J(0, -7), J(1.5, 0), 0.5)
    s.line(J(0, -7), J(-1.5, 0), 0.5)
    s.part(D_TAN)
    s.line(J(0, -7), J(0, -12), 0.5)
    s.line(J(-1, -12), J(1, -12), 0.5)
    s.part(flat(D_TAN[0]))
    s.line(J(-2, -12), J(-2, -10), 0.5)
    s.part(D_TAN)
    s.line(J(0, -12), J(0.4, -14), 0.5)
    s.line(J(0.4 - 1.3 * hh, -15.4), J(0.4 + 2.6 * hh, -14.8), 0.6)
    s.part(D_TAN)
    if raised:
        s.line(J(0, -11.5), J(2, -10), 0.5)
        s.part(D_GUN)
        s.line(J(1, -10), J(4.5, -10.5), 0.5)
    else:
        s.line(J(0, -11.5), J(1.5, -8.5), 0.5)
        s.part(D_GUN)
        s.line(J(0.5, -8.5), J(3, -6), 0.5)
    s.render(cv, D_LINE, dim=dim)


# --------------------------------------------------------------------------
# VFX
# --------------------------------------------------------------------------

_kernels = {}


def glow(cv, x, y, col, r, k):
    key = r
    if key not in _kernels:
        R = int(math.ceil(r))
        _kernels[key] = [(dx, dy, (1 - math.sqrt(dx * dx + dy * dy) / r) ** 2)
                         for dy in range(-R, R + 1) for dx in range(-R, R + 1)
                         if dx * dx + dy * dy < r * r]
    xi, yi = int(round(x)), int(round(y))
    for dx, dy, w in _kernels[key]:
        cv.add(xi + dx, yi + dy, col, w * k)


def draw_saber(cv, hx, hy, dx, dy, length, colors, hum=1.0, trail=()):
    col, core = colors
    for (tdx, tdy, a) in trail:
        for i in range(4, int(length * 2)):
            t = i * 0.5
            cv.blend(round(hx + tdx * t), round(hy + tdy * t), col, a)
    for i in range(-1, 3):
        c = HILT[2] if i == 0 else HILT[1] if i > 0 else HILT[0]
        cv.put(round(hx + dx * i), round(hy + dy * i), c)
    if length <= 0:
        return
    pts = []
    for i in range(6, int((3 + length) * 2)):
        t = i * 0.5
        pts.append((round(hx + dx * t), round(hy + dy * t)))
    for j, (x, y) in enumerate(pts):
        if j % 3 == 0:
            glow(cv, x, y, col, 5, 0.22 * hum)
    for x, y in pts:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            cv.put(nx, ny, col)
    for x, y in pts:
        cv.put(x, y, core)


class Particles:
    def __init__(self):
        self.items = []

    def burst(self, x, y, n, rng, speed, up, life, color, grav=0.25, kind='dust'):
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
                r = 1.5 + 3.5 * (1 - fade)
                R = int(r) + 1
                for dy in range(-R, R + 1):
                    for dx in range(-R, R + 1):
                        if dx * dx + dy * dy <= r * r:
                            cv.blend(sx + dx, sy + dy, p['color'], 0.55 * fade)
            elif p['kind'] == 'dust':
                cv.blend(sx, sy, p['color'], 0.95 * fade)
                if fade > 0.4:
                    cv.blend(sx + 1, sy, p['color'], 0.7 * fade)
                    cv.blend(sx, sy + 1, p['color'], 0.5 * fade)
            else:
                cv.put(sx, sy, mix((255, 160, 40), (255, 250, 210), fade))
                cv.blend(sx - p['vx'] * 0.6, sy - p['vy'] * 0.6, (255, 190, 80), 0.6 * fade)
        self.items = alive


def shadow(cv, x, y, rx, a):
    for dx in range(-rx, rx + 1):
        for dy in (-1, 0, 1):
            if (dx / rx) ** 2 + (dy / 1.5) ** 2 <= 1:
                cv.blend(x + dx, y + dy, (70, 42, 24), a)


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
    """Physics for the drop. Returns per-frame (x, y, pose) and the landing frame."""
    track = []
    x, y = 78.0, float(BEAM_Y)
    for f in range(17):
        track.append((x, y, K_CROUCH))
    track.append((x + 1, y, lerp_pose(K_CROUCH, K_LEAP, 0.5)))
    track.append((x + 2, y - 2, K_LEAP))
    x, y, vy = x + 3, y - 3, -2.5
    f = 0
    while True:
        x += 0.35
        y += vy
        vy = min(22.0, vy + 2.0)
        if y >= GROUND:
            break
        pose = lerp_pose(K_LEAP, K_FALL, ease(f / 3))
        track.append((x, y, pose))
        f += 1
    return track, len(track), x


def subtitle_reveal(f, start):
    return (f - start) * 3 + 1


def render(out_path, scale):
    t0 = time.time()
    rng = random.Random(1138)
    layers = (build_sky(), build_far(), build_mid(), build_main(), build_fg())
    fg = layers[4]

    track, L, land_x = kenobi_track()
    KX = land_x
    GX = 206
    S = L + 30            # Grievous turns
    A = S + 27            # arms split
    K = A + 9             # Kenobi ignites
    END = K + 24          # fade begins
    TOTAL = END + 9

    # droid army
    droids = []
    for row, (sc, fy, step, x0, dim) in enumerate(((0.85, GROUND - 27, 13, 128, 0.42),
                                                  (1.05, GROUND - 17, 16, 134, 0.22),
                                                  (1.25, GROUND - 7, 20, 142, 0.05))):
        x = x0 + row * 3
        while x < W + 4:
            if not (row >= 1 and 186 <= x <= 228):
                droids.append(dict(x=x + int(hn(x, row, 5) * 4), y=fy, sc=sc, dim=dim,
                                   snap=L + 2 + int((x - 120) / 28) + row,
                                   bob=hn(x, row, 6) < 0.3, phase=int(hn(x, row, 8) * 18)))
            x += step

    motes = [dict(x=rng.uniform(0, W), y=rng.uniform(0, GROUND - 40),
                  ph=rng.uniform(0, 6.28)) for _ in range(34)]

    parts = Particles()
    cam = 0.0
    shake = {L: (0, 3), L + 1: (1, -2), L + 2: (-1, 2), L + 3: (0, -1), L + 4: (0, 1)}
    fade_tables = {}

    ff = [shutil.which('ffmpeg') or 'ffmpeg', '-v', 'error', '-y',
          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
          '-filter_complex',
          f'[0:v]scale=iw*{scale}:ih*{scale}:flags=neighbor,split[a][b];'
          '[a]palettegen=max_colors=255:stats_mode=full:reserve_transparent=1[p];'
          '[b][p]paletteuse=dither=none:diff_mode=rectangle',
          '-loop', '0', out_path]
    proc = subprocess.Popen(ff, stdin=subprocess.PIPE)
    frames = []

    for f in range(TOTAL):
        # ---- camera and Kenobi state
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
                kpose = lerp_pose(K_STAND, K_GUARD, ease((f - K) / 3))
        target = max(0.0, min(PAN, ky - 74))
        cam += (target - cam) * 0.55
        if f >= L:
            cam = cam + (PAN - cam) * 0.6
        ci = int(round(cam))

        cv = background(layers, ci)
        if f > A + 3:
            # house lights drop once the blades are out, so they read as light sources
            cv.px = bytearray(cv.px.translate(HOUSE_DIM))

        # ---- lights on the main plane
        for i, (lx, ly) in enumerate(RED_LIGHTS):
            sy = ly - ci
            if -4 <= sy < H + 4:
                on = ((f + i * 5) // 7) % 2 == 0
                cv.put(lx, sy, RED_ON if on else RED_OFF)
                cv.put(lx + 1, sy, RED_ON if on else RED_OFF)
                if on:
                    glow(cv, lx, sy, (255, 60, 30), 4, 0.45)
        for lx, ly in LAMPS:
            sy = ly - ci
            if -6 <= sy < H + 6:
                glow(cv, lx, sy, (255, 200, 120), 6, 0.35)

        # ---- dust motes drifting in the shafts
        for m in motes:
            mx = (m['x'] + math.sin(f * 0.08 + m['ph']) * 3) % W
            my = (m['y'] + f * 0.25) % (GROUND - 40)
            sy = my - ci
            if 0 <= sy < H:
                cv.blend(int(mx), int(sy), (255, 244, 214), 0.55)

        # ---- shadows on the platform
        if f < L:
            height = GROUND - ky
            a = max(0.0, 0.35 - height / 300)
            if a > 0.02:
                shadow(cv, int(kx), GROUND + 1 - ci, 5, a)
        else:
            shadow(cv, int(KX), GROUND + 1 - ci, 6, 0.4)
        shadow(cv, GX, GROUND + 1 - ci, 9, 0.4)

        # ---- droid army
        for dr in droids:
            sy = dr['y'] - ci
            if sy - 20 > H:
                continue
            bob = 1 if dr['bob'] and ((f + dr['phase']) // 9) % 2 == 0 else 0
            if f < dr['snap']:
                hh, raised = -0.6, False
            elif f == dr['snap']:
                hh, raised = 0.3, False
            else:
                hh, raised = 1.0, True
            draw_droid(cv, dr['x'], sy + bob, -1, dr['sc'], hh, raised, dr['dim'])

        # ---- Grievous
        if f < S:
            gpose, gd, gx = G_IDLE, 1.0, 0.0
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
        draw_grievous(cv, GX, GROUND - ci, gpose, gd, f)

        # Grievous blades: upper front, upper back, lower front, lower back
        if f >= A + 3:
            spin = f - (A + 8)
            for i, (hk, base_ang, colors) in enumerate((('h1', -62, BLUE), ('h2', -112, GREEN),
                                                         ('h3', -20, GREEN), ('h4', 200, BLUE))):
                lit = A + 3 + i
                if f < lit:
                    continue
                grow = min(1.0, (f - lit + 1) / 2)
                ang = math.radians(base_ang)
                trail = ()
                if i >= 2 and spin >= 0:
                    step = math.radians(56 if i == 2 else -56)
                    ang += step * spin
                    trail = tuple((math.cos(ang - step * k * 0.5),
                                   math.sin(ang - step * k * 0.5), 0.3 / k) for k in (1, 2))
                dx, dy = math.cos(ang), math.sin(ang)
                hx, hy = gpose[hk]
                sx, sy = GX + gd * hx * RIG_K, GROUND - ci + hy * RIG_K
                trail = tuple((tx * gd, ty, a) for tx, ty, a in trail)
                hum = 0.85 + 0.3 * hn(f, i, 31)
                draw_saber(cv, sx, sy, dx * gd, dy, 18 * grow, colors, hum, trail)
                if f == lit:
                    glow(cv, sx, sy, (255, 255, 255), 7, 0.9)
                # spinning blades scrape the platform
                if i >= 2 and spin >= 0:
                    tipy = sy + dy * 21
                    if tipy >= GROUND - ci - 1:
                        parts.burst(sx + dx * gd * 21, GROUND - 1, 4, rng, 2.4, 1.2,
                                    (3, 6), None, grav=0.35, kind='spark')

        # ---- Kenobi
        draw_kenobi(cv, kx, ky - ci, kpose, 1, f, flutter=2.5 if L - 20 < f < L else 1.0)
        if f >= K:
            grow = min(1.0, max(0.0, (f - K - 1) / 2))
            hx, hy = kpose['hf']
            sx, sy = kx + hx * RIG_K, ky - ci + hy * RIG_K
            hum = 0.85 + 0.3 * hn(f, 9, 33)
            draw_saber(cv, sx, sy, K_SABER_DIR[0], K_SABER_DIR[1], 19 * grow, BLUE, hum)
            if f == K + 1:
                glow(cv, sx, sy, (210, 235, 255), 8, 0.9)

        # ---- landing
        if f == L:
            parts.burst(KX, GROUND - 2, 22, rng, 4.2, 0.35, (9, 15), DUST, grav=0.0, kind='puff')
            parts.burst(KX, GROUND - 1, 30, rng, 5.0, 1.8, (6, 12), mix(DUST, (255, 255, 255), 0.35))
        if L <= f < L + 4:
            r = 10 + (f - L) * 11
            for dx in range(-r, r + 1):
                if abs(dx) > r - 3:
                    for yy in (0, 1):
                        cv.blend(KX + dx, GROUND - ci + yy, (255, 236, 196), 0.75 - (f - L) * 0.17)
        parts.step(cv, ci)

        # ---- motion streaks during the drop
        if 20 <= f < L:
            for j in range(9):
                lx = int(hn(f, j, 41) * W)
                ln = 10 + int(hn(f, j, 42) * 22)
                ly = int(hn(f, j, 43) * H)
                for k in range(ln):
                    cv.blend(lx, ly + k, (255, 246, 226), 0.16 * (1 - k / ln))
            for j, off in enumerate((-5, -1, 3, 7)):
                ln = 10 + j * 4
                for k in range(ln):
                    cv.blend(kx + off, ky - ci - 30 - k, (255, 250, 236), 0.4 * (1 - k / ln))

        # ---- foreground girders
        fg.blit(cv, int(round(ci * SPEED_FG)))

        # ---- subtitles
        t1 = L + 8
        if t1 <= f < t1 + 20:
            draw_text(cv, "Hello there!", KX, 150, subtitle_reveal(f, t1))
        t2 = S + 6
        if t2 <= f < t2 + 20:
            draw_text(cv, "General Kenobi!", GX, 150, subtitle_reveal(f, t2))

        # ---- fades and shake
        if f < 5:
            level = f / 5
        elif f >= END:
            level = max(0.0, 1 - (f - END + 1) / 6)
        else:
            level = 1.0
        if f == A + 3:
            level = 1.08                          # ignition flash
        if level != 1.0:
            q = round(level * 8) / 8 if level < 1 else level
            if q not in fade_tables:
                fade_tables[q] = bytes(min(255, int(v * q)) for v in range(256))
            cv.px = bytearray(cv.px.translate(fade_tables[q]))
        sx, sy = shake.get(f, (0, 0))
        cv = shake_frame(cv, sx, sy)

        frames.append(bytes(cv.px))

    # Start the file on the first fully lit frame and move the fade-in to the tail.
    # The loop plays in the same order, but anything that shows only frame 0
    # (autoplay off, link previews) gets the rafters shot instead of black.
    for px in frames[5:] + frames[:5]:
        proc.stdin.write(px)
    proc.stdin.close()
    proc.wait()
    if proc.returncode:
        sys.exit(f"ffmpeg failed with exit code {proc.returncode}")
    return TOTAL, time.time() - t0


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--out', default=os.path.join(here, '..', 'assets', 'hello-there.gif'))
    ap.add_argument('--scale', type=int, default=3)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    frames, secs = render(args.out, args.scale)
    size = os.path.getsize(args.out)
    print(f"{args.out}: {frames} frames @ {FPS} fps, {W * args.scale}x{H * args.scale}, "
          f"{size / 1e6:.2f} MB, rendered in {secs:.1f}s")


if __name__ == '__main__':
    main()
