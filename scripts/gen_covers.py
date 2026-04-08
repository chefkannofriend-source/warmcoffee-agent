#!/usr/bin/env python3
"""
Coffee Agent XHS cover — 1080×1440
Style: white solid blocks + black hand-drawn lines on #D97757
Elements: deconstructed EK43 (dial, hopper, body) + coffee beans. No text.
"""

import math
import random
from PIL import Image, ImageDraw

random.seed(42)

BG    = (217, 119, 87)
WHITE = (255, 255, 255)
BLACK = (18,  10,  3)

W, H = 1080, 1440


# ── Helpers ───────────────────────────────────────────────────────────────────

def wobbly(draw, pts, fill, width, jit=3):
    """Draw a line through pts with slight random wobble on interior points."""
    result = [pts[0]]
    for p in pts[1:-1]:
        result.append((p[0] + random.randint(-jit, jit),
                       p[1] + random.randint(-jit, jit)))
    result.append(pts[-1])
    draw.line(result, fill=fill, width=width, joint="curve")


def rotated_ellipse_pts(cx, cy, rx, ry, angle_deg, n=80):
    a = math.radians(angle_deg)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        ex = rx * math.cos(t)
        ey = ry * math.sin(t)
        pts.append((
            cx + ex * math.cos(a) - ey * math.sin(a),
            cy + ex * math.sin(a) + ey * math.cos(a),
        ))
    return pts


# ── Elements ──────────────────────────────────────────────────────────────────

def draw_dial(draw, cx, cy, r):
    """EK43 adjustment dial — large circle, fills with white."""
    # Main circle
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=WHITE, outline=BLACK, width=6)

    # Tick marks (12 positions, major every 3)
    for i in range(12):
        ang = math.radians(i * 30 - 90)
        major = (i % 3 == 0)
        inner_t = 0.70 if major else 0.76
        outer_t = 0.90
        lw = 6 if major else 4
        x0 = int(cx + r * inner_t * math.cos(ang))
        y0 = int(cy + r * inner_t * math.sin(ang))
        x1 = int(cx + r * outer_t * math.cos(ang))
        y1 = int(cy + r * outer_t * math.sin(ang))
        draw.line([(x0, y0), (x1, y1)], fill=BLACK, width=lw)

    # Inner ring (drawn as circle outline)
    ir = int(r * 0.60)
    draw.ellipse([cx-ir, cy-ir, cx+ir, cy+ir], fill=WHITE, outline=BLACK, width=5)

    # Center dot
    draw.ellipse([cx-15, cy-15, cx+15, cy+15], fill=BLACK)

    # Needle — pointing roughly to 10-11 o'clock (≈ setting 10.75)
    needle_ang = math.radians(315 - 90)   # 315° from top
    nx = int(cx + (ir - 12) * math.cos(needle_ang))
    ny = int(cy + (ir - 12) * math.sin(needle_ang))
    draw.line([(cx, cy), (nx, ny)], fill=BLACK, width=7)


def draw_hopper(draw, cx, top_y, tw, bw, h):
    """EK43 hopper — wide trapezoid."""
    pts = [
        (cx - tw // 2, top_y),
        (cx + tw // 2, top_y),
        (cx + bw // 2, top_y + h),
        (cx - bw // 2, top_y + h),
    ]
    draw.polygon(pts, fill=WHITE, outline=BLACK, width=6)

    # Thick top lip
    draw.line([pts[0], pts[1]], fill=BLACK, width=10)

    # Internal divider line (wobbly)
    mid_y = top_y + h // 2
    wobbly(draw,
           [(cx - bw // 3, mid_y), (cx, mid_y), (cx + bw // 3, mid_y)],
           fill=BLACK, width=4, jit=5)

    # Bean inlet circle at top center
    hole_r = 22
    hole_cy = top_y + h // 4
    draw.ellipse([cx - hole_r, hole_cy - hole_r,
                  cx + hole_r, hole_cy + hole_r],
                 fill=BG, outline=BLACK, width=4)


def draw_body(draw, x0, y0, x1, y1):
    """Main grinder body rectangle."""
    draw.rectangle([x0, y0, x1, y1], fill=WHITE, outline=BLACK, width=6)

    # Front panel (inner rect, upper ~30%)
    pi = 22
    ph = int((y1 - y0) * 0.30)
    px0, py0 = x0 + pi, y0 + pi
    px1, py1 = x1 - pi, y0 + pi + ph
    if px0 < 0:
        px0 = 4   # clip to canvas edge nicely
    draw.rectangle([px0, py0, px1, py1], fill=WHITE, outline=BLACK, width=4)

    # Label bars inside panel
    bm = (py0 + py1) // 2
    draw.rectangle([px0 + 20, bm - 18, px1 - 20, bm - 8], fill=BLACK)
    draw.rectangle([px0 + 36, bm + 6,  px1 - 36, bm + 14], fill=BLACK)

    # Horizontal seam below panel
    seam_y = py1 + 28
    wobbly(draw,
           [(max(x0 + pi, 0), seam_y), (x1 - pi, seam_y)],
           fill=BLACK, width=4, jit=4)

    # Chute at bottom center of body
    body_mid_x = (max(x0, 0) + x1) // 2
    chute_w = 95
    chute_h = 55
    cx0 = body_mid_x - chute_w // 2
    cx1 = body_mid_x + chute_w // 2
    draw.rectangle([cx0, y1 - 2, cx1, y1 + chute_h],
                   fill=WHITE, outline=BLACK, width=5)

    # Coffee dots falling from chute
    dot_y = y1 + chute_h + 10
    for i, dx in enumerate([-22, 0, 22]):
        dy = i * 14
        draw.ellipse([body_mid_x + dx - 5, dot_y + dy,
                      body_mid_x + dx + 5, dot_y + dy + 9],
                     fill=BLACK)


def draw_bean(draw, cx, cy, rx, ry, angle_deg, lw=5):
    """Coffee bean — rotated ellipse with S-curve crease."""
    pts = rotated_ellipse_pts(cx, cy, rx, ry, angle_deg)
    draw.polygon(pts, fill=WHITE, outline=BLACK, width=lw)

    # S-curve crease along major axis
    a = math.radians(angle_deg)
    crease = []
    for i in range(17):
        t = (i / 16 - 0.5) * 2      # -1 → 1
        ex = rx * 0.80 * t
        ey = ry * 0.25 * math.sin(t * math.pi)
        ex += random.uniform(-2, 2)
        ey += random.uniform(-1.5, 1.5)
        crease.append((
            cx + ex * math.cos(a) - ey * math.sin(a),
            cy + ex * math.sin(a) + ey * math.cos(a),
        ))
    draw.line(crease, fill=BLACK, width=max(2, lw - 2), joint="curve")


# ── Compose ───────────────────────────────────────────────────────────────────

def make_xhs():
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 1. DIAL — top-right, cropped by top + right canvas edges
    draw_dial(draw, cx=980, cy=210, r=310)

    # 2. HOPPER — center, slightly left of middle
    draw_hopper(draw, cx=420, top_y=530, tw=315, bw=215, h=220)

    # 3. BODY — lower-left, cropped by left + bottom edges
    draw_body(draw, x0=-35, y0=820, x1=555, y1=1280)

    # 4. COFFEE BEANS — scattered
    draw_bean(draw, cx=200, cy=360, rx=72, ry=48, angle_deg=28)   # top-left
    draw_bean(draw, cx=875, cy=660, rx=58, ry=39, angle_deg=-25)  # mid-right
    draw_bean(draw, cx=830, cy=1090, rx=50, ry=33, angle_deg=42)  # lower-right
    draw_bean(draw, cx=660, cy=1370, rx=66, ry=44, angle_deg=-8)  # bottom

    out = "/Users/wenliang/coffee-agent/outputs/cover-xhs.png"
    img.save(out, quality=95)
    print(f"→ {out}")


def make_16x9():
    CW, CH = 1920, 1080
    img  = Image.new("RGB", (CW, CH), BG)
    draw = ImageDraw.Draw(img)

    # Right-side composition — left ~40% is breathing room

    # 1. DIAL — top-right, cropped right + top
    draw_dial(draw, cx=1820, cy=170, r=270)

    # 2. HOPPER — center-right
    draw_hopper(draw, cx=1340, top_y=230, tw=290, bw=200, h=200)

    # 3. BODY — lower-right, cropped right + bottom
    draw_body(draw, x0=870, y0=540, x1=1960, y1=1160)

    # 4. BEANS
    # One lone bean on left (anchors the breathing room)
    draw_bean(draw, cx=280, cy=480, rx=68, ry=45, angle_deg=20)
    # Two beans in transition zone
    draw_bean(draw, cx=760, cy=350, rx=52, ry=35, angle_deg=38)
    draw_bean(draw, cx=1680, cy=730, rx=50, ry=33, angle_deg=-20)

    out = "/Users/wenliang/restaurant-brain/outputs/content/mise/2026-04-05-coffee-agent-16x9.jpg"
    img.save(out, quality=95)
    print(f"→ {out}")


make_xhs()
make_16x9()
