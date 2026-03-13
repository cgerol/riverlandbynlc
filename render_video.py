#!/usr/bin/env python3
"""
RIVERLAND — Animated Video Presentation Generator
Line-motion + isometric 3D animation technique.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, AudioFileClip
import math, os, glob

# ================================================================
# CONSTANTS
# ================================================================
W, H = 1920, 1080
FPS = 30

BG = (14, 26, 14)
BG2 = (27, 46, 27)
GOLD = (196, 168, 107)
GOLD_DIM = (140, 120, 76)
GOLD_BRIGHT = (220, 195, 130)
CREAM = (232, 223, 196)
TSEC = (160, 152, 120)
MUTED = (107, 107, 90)
BLUE = (74, 141, 183)
BLUE_LIGHT = (100, 180, 220)
GREEN_A = (60, 106, 60)
GREEN_B = (80, 130, 80)
DARK_LINE = (40, 65, 40)
SIDE_COLOR = (110, 94, 60)  # darker gold for 3D sides
TOP_COLOR = (170, 150, 100)  # lighter gold for 3D tops

FONT_DIR = "C:/Windows/Fonts"
ASSET_DIR = "video_assets"
MAP_DIR = "video_assets/map_frames"

# ================================================================
# FONT LOADING
# ================================================================
_font_cache = {}

def font(name, size):
    key = (name, size)
    if key not in _font_cache:
        paths = {
            'serif': ['georgia.ttf', 'times.ttf'],
            'serifb': ['georgiab.ttf', 'timesbd.ttf'],
            'sans': ['segoeui.ttf', 'calibri.ttf', 'arial.ttf'],
            'sansb': ['segoeuib.ttf', 'calibrib.ttf', 'arialbd.ttf'],
            'sansl': ['segoeuil.ttf', 'calibril.ttf', 'arial.ttf'],
        }
        for p in paths.get(name, [name + '.ttf']):
            try:
                _font_cache[key] = ImageFont.truetype(os.path.join(FONT_DIR, p), size)
                break
            except Exception:
                continue
        if key not in _font_cache:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]

# ================================================================
# EASING
# ================================================================
def clamp01(t): return max(0.0, min(1.0, t))
def ease_out(t): t = clamp01(t); return 1 - (1 - t) ** 3
def ease_in_out(t): t = clamp01(t); return t * t * (3 - 2 * t)
def ease_out_quad(t): t = clamp01(t); return 1 - (1 - t) ** 2
def lerp(a, b, t): return a + (b - a) * clamp01(t)

def ease_in(t): t = clamp01(t); return t * t * t
def ease_out_back(t): t = clamp01(t); c = 1.70158; return 1 + (c + 1) * ((t - 1) ** 3) + c * ((t - 1) ** 2)

def color_alpha(color, alpha):
    a = clamp01(alpha)
    return tuple(int(lerp(BG[i], color[i], a)) for i in range(3))

# ================================================================
# DRAWING HELPERS
# ================================================================
def draw_line_anim(draw, pts, progress, color=GOLD, width=2):
    if progress <= 0 or len(pts) < 2: return
    segs, total = [], 0
    for i in range(len(pts)-1):
        l = math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
        segs.append(l); total += l
    if total == 0: return
    target = total * clamp01(progress); drawn = 0
    for i in range(len(pts)-1):
        if drawn >= target: break
        rem = target - drawn; sl = segs[i]
        if rem >= sl:
            draw.line([pts[i], pts[i+1]], fill=color, width=width); drawn += sl
        else:
            t = rem / sl if sl > 0 else 0
            draw.line([pts[i], (lerp(pts[i][0], pts[i+1][0], t), lerp(pts[i][1], pts[i+1][1], t))], fill=color, width=width)
            drawn += rem

def draw_text_fade(draw, text, pos, fnt, color, alpha, anchor='lt'):
    if alpha <= 0 or not text: return
    draw.text(pos, text, fill=color_alpha(color, alpha), font=fnt, anchor=anchor)

def draw_number_anim(draw, target_str, pos, fnt, color, progress, anchor='lt'):
    if progress <= 0: return
    num_str, suffix = '', ''
    for i, ch in enumerate(target_str):
        if ch.isdigit() or ch == '.': num_str += ch
        else: suffix = target_str[i:]; break
    if not num_str:
        draw_text_fade(draw, target_str, pos, fnt, color, progress, anchor); return
    val = float(num_str) * ease_out(clamp01(progress))
    text = f"{val:.1f}{suffix}" if '.' in num_str else f"{int(val)}{suffix}"
    draw.text(pos, text, fill=color, font=fnt, anchor=anchor)

def text_width(text, fnt):
    bbox = fnt.getbbox(text); return bbox[2] - bbox[0] if bbox else 0

_particle_cache = {}
def draw_ambient_particles(draw, t, count=40, speed=0.3, color=GOLD_DIM, opacity=0.25):
    """Floating gold dust particles for visual richness."""
    key = count
    if key not in _particle_cache:
        import random
        rng = random.Random(42)
        _particle_cache[key] = [(rng.random()*W, rng.random()*H, rng.uniform(1,3), rng.random()*20+10) for _ in range(count)]
    c = color_alpha(color, opacity * 0.7)
    for i, (px, py, sz, spd) in enumerate(_particle_cache[key]):
        fx = (px + math.sin(t * speed + i * 0.7) * 30) % W
        fy = (py - t * spd + i * 40) % H
        draw.rectangle([(fx-sz, fy-sz), (fx+sz, fy+sz)], fill=c)

def draw_grid_bg(draw, t, spacing=80, color=DARK_LINE, alpha=0.15):
    """Subtle animated architectural grid background."""
    offset = t * 3
    c = color_alpha(color, alpha)
    for x in range(0, W + spacing, spacing):
        xo = x + int(offset) % spacing
        if 0 <= xo <= W:
            draw.line([(xo, 0), (xo, H)], fill=c, width=1)
    for y in range(0, H + spacing, spacing):
        draw.line([(0, y), (W, y)], fill=c, width=1)

def draw_scan_line(draw, t, y_pos, width=W, color=GOLD, alpha=0.3):
    """Horizontal scanning line effect for tech feel."""
    c = color_alpha(color, alpha)
    draw.line([(0, y_pos), (width, y_pos)], fill=c, width=1)
    # Glow above/below
    for d in range(1, 4):
        gc = color_alpha(color, alpha * (1 - d/4))
        draw.line([(0, y_pos-d), (width, y_pos-d)], fill=gc, width=1)
        draw.line([(0, y_pos+d), (width, y_pos+d)], fill=gc, width=1)

def multiline_text(draw, text, pos, fnt, color, max_w, line_spacing=1.4):
    words = text.split(); lines = []; cur = ''
    for w in words:
        test = (cur + ' ' + w).strip()
        if text_width(test, fnt) > max_w and cur: lines.append(cur); cur = w
        else: cur = test
    if cur: lines.append(cur)
    x, y = pos; lh = fnt.getbbox('Αy')[3] * line_spacing
    for line in lines: draw.text((x, y), line, fill=color, font=fnt); y += lh
    return y - pos[1]

# ================================================================
# 3D ISOMETRIC BUILDING SYSTEM
# ================================================================
def draw_3d_building(draw, x, y, w, h, d, progress,
                     style='modern', floors=2, has_roof=True,
                     front_c=GOLD, side_c=SIDE_COLOR, top_c=TOP_COLOR, lw=2):
    """Draw isometric 3D building with construction animation.
    (x,y) = bottom-left of front face. w=width, h=height, d=depth offset."""
    if progress <= 0: return
    ah = h * ease_out(min(1.0, progress * 1.2))  # animated height
    dx = d * 0.6   # depth x-offset
    dy = -d * 0.35  # depth y-offset

    # Front face corners
    fl = (x, y); fr = (x+w, y); ftl = (x, y-ah); ftr = (x+w, y-ah)
    # Back face corners
    bl = (x+dx, y+dy); br = (x+w+dx, y+dy); btl = (x+dx, y-ah+dy); btr = (x+w+dx, y-ah+dy)

    # Construction scaffolding (early phase)
    if progress < 0.3:
        sp = progress / 0.3
        draw_line_anim(draw, [fl, fr], sp, DARK_LINE, 1)
        draw_line_anim(draw, [(x, y), (x, y - ah * 0.3)], sp, DARK_LINE, 1)
        draw_line_anim(draw, [(x+w, y), (x+w, y - ah * 0.3)], sp, DARK_LINE, 1)
        return

    # Right side face
    draw.line([fr, br], fill=side_c, width=lw)
    draw.line([br, btr], fill=side_c, width=lw)
    draw.line([btr, ftr], fill=side_c, width=lw)
    # Top face
    draw.line([ftl, btl], fill=top_c, width=lw)
    draw.line([btl, btr], fill=top_c, width=lw)
    draw.line([btr, ftr], fill=top_c, width=lw)
    draw.line([ftl, ftr], fill=top_c, width=lw)
    # Front face
    draw.line([fl, fr], fill=front_c, width=lw)
    draw.line([fr, ftr], fill=front_c, width=lw)
    draw.line([ftr, ftl], fill=front_c, width=lw)
    draw.line([ftl, fl], fill=front_c, width=lw)

    # Floor lines on front
    floor_h = ah / max(1, floors)
    for f in range(1, floors):
        fy = y - f * floor_h
        detail_p = ease_out(max(0, progress - 0.4) / 0.6)
        if detail_p > 0:
            draw.line([(x, fy), (x+w, fy)], fill=color_alpha(front_c, detail_p * 0.5), width=1)
            # Side floor line
            draw.line([(x+w, fy), (x+w+dx, fy+dy)], fill=color_alpha(side_c, detail_p * 0.3), width=1)

    # Windows on front face
    win_p = ease_out(max(0, progress - 0.5) / 0.5)
    if win_p > 0:
        ww = w * 0.12; wh = floor_h * 0.4; wgap = w * 0.06
        cols = max(1, int(w / (ww + wgap * 2)))
        for f in range(floors):
            wy = y - (f + 0.5) * floor_h - wh / 2
            for c in range(cols):
                wx = x + wgap + c * (ww + wgap * 1.5)
                if wx + ww > x + w - wgap: break
                wc = color_alpha(GOLD_BRIGHT, win_p * 0.7)
                draw.rectangle([(wx, wy), (wx+ww, wy+wh)], outline=wc, width=1)

    # Windows on right side
    if win_p > 0 and d > 20:
        side_cols = max(1, int(d / 30))
        for f in range(floors):
            for c in range(side_cols):
                t = (c + 0.5) / side_cols
                swx = lerp(x+w, x+w+dx, t)
                swy_base = lerp(y, y+dy, t) - (f + 0.5) * floor_h
                sww = ww * 0.7; swh = wh * 0.8
                wc = color_alpha(GOLD_BRIGHT, win_p * 0.4)
                draw.rectangle([(swx, swy_base - swh/2), (swx+sww, swy_base + swh/2)], outline=wc, width=1)

    # Pitched roof for villas
    if has_roof and style == 'villa' and progress > 0.6:
        rp = ease_out((progress - 0.6) / 0.4)
        ridge_y = y - ah - h * 0.25 * rp
        mid_x = x + w / 2
        mid_bx = x + w / 2 + dx
        # Front gable
        draw_line_anim(draw, [ftl, (mid_x, ridge_y), ftr], rp, front_c, lw)
        # Back gable
        draw_line_anim(draw, [btl, (mid_bx, ridge_y + dy), btr], rp, side_c, lw)
        # Ridge line
        draw_line_anim(draw, [(mid_x, ridge_y), (mid_bx, ridge_y + dy)], rp, top_c, lw)

    # Door on front
    if progress > 0.7:
        dp = ease_out((progress - 0.7) / 0.3)
        dw = w * 0.12; dh = floor_h * 0.55
        ddx = x + w * 0.45
        ddy = y - dh
        draw.rectangle([(ddx, ddy), (ddx+dw, y)], outline=color_alpha(front_c, dp), width=1)


def draw_3d_tree(draw, x, y, h, progress, color=GREEN_A):
    """3D-looking tree with trunk and layered canopy."""
    if progress <= 0: return
    # Trunk
    tw = h * 0.06
    draw.line([(x, y), (x, y - h * 0.4)], fill=color_alpha(SIDE_COLOR, progress), width=max(1, int(tw)))
    # Canopy layers (3D oval shapes)
    cp = ease_out(max(0, progress - 0.3) / 0.7)
    if cp > 0:
        for i in range(3):
            cy = y - h * (0.45 + i * 0.18)
            rw = h * (0.3 - i * 0.06) * cp
            rh = h * (0.18 - i * 0.03) * cp
            c = color_alpha(color if i < 2 else GREEN_B, cp * (0.8 - i * 0.15))
            draw.ellipse([(x-rw, cy-rh), (x+rw, cy+rh)], outline=c, width=2)


def draw_3d_neighborhood(draw, base_x, base_y, width, height, progress, num_buildings=5):
    """Draw a cluster of 3D buildings with progressive construction."""
    configs = [
        {'w': 90, 'h': 110, 'd': 40, 'style': 'villa', 'floors': 2},
        {'w': 80, 'h': 90, 'd': 35, 'style': 'modern', 'floors': 2},
        {'w': 100, 'h': 120, 'd': 45, 'style': 'villa', 'floors': 2},
        {'w': 75, 'h': 85, 'd': 32, 'style': 'modern', 'floors': 2},
        {'w': 95, 'h': 100, 'd': 42, 'style': 'villa', 'floors': 2},
    ]
    n = min(num_buildings, len(configs))
    spacing = width / n
    for i in range(n):
        bp = ease_out(max(0, progress - i * 0.15) / 0.6)
        if bp <= 0: continue
        cfg = configs[i]
        draw_3d_building(draw, base_x + i * spacing, base_y, cfg['w'], cfg['h'], cfg['d'], bp,
                        style=cfg['style'], floors=cfg['floors'],
                        has_roof=(cfg['style'] == 'villa'))
    # Road
    rp = ease_out(max(0, progress - 0.3) / 0.4)
    draw_line_anim(draw, [(base_x - 20, base_y + 8), (base_x + width + 20, base_y + 8)], rp, TSEC, 1)


# ================================================================
# ASSETS
# ================================================================
_assets = {}

def load_assets():
    global _assets
    for f in ['slide1_Picture_6.png', 'slide2_Picture_6.png',
              'slide10_Picture_9.png', 'slide10_Picture_15.png']:
        path = os.path.join(ASSET_DIR, f)
        if os.path.exists(path): _assets[f] = Image.open(path)
    if os.path.exists(MAP_DIR):
        frames = sorted(glob.glob(os.path.join(MAP_DIR, 'frame_*.png')))
        if frames: _assets['map_frames'] = frames; print(f"Loaded {len(frames)} map frames")
    for name in ['masterplan.jpg', 'location-map.jpg', 'hero-bg.jpg']:
        path = os.path.join('assets', name)
        if os.path.exists(path): _assets[name] = Image.open(path)
    for name in ['grid1.jpg', 'grid2.jpg', 'grid3.jpg', 'grid4.jpg', 'grid5.jpg', 'grid6.jpg']:
        path = os.path.join('assets', name)
        if os.path.exists(path): _assets[name] = Image.open(path)
    print(f"Loaded {len(_assets)} assets")

_bg_cache = {}
def get_bg(key='default'):
    if key not in _bg_cache:
        img = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)
        for y in range(H):
            t = y / H
            c = tuple(int(BG[i] + (BG2[i] - BG[i]) * t * 0.3) for i in range(3))
            draw.line([(0, y), (W, y)], fill=c)
        _bg_cache[key] = img
    return _bg_cache[key].copy()

# ================================================================
# SCENE 1: LOGO REVEAL (0-5s)
# ================================================================
def scene_logo(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    cx = W // 2

    # Ambient particles
    draw_ambient_particles(draw, t, count=25, speed=0.2, color=GOLD_DIM, opacity=0.15)

    # Expanding gold lines from center
    line_p = ease_out(t / 3.0)
    draw_line_anim(draw, [(cx-300*line_p, 350), (cx+300*line_p, 350)], line_p, GOLD_DIM, 1)
    draw_line_anim(draw, [(cx-300*line_p, 720), (cx+300*line_p, 720)], line_p, GOLD_DIM, 1)
    # Corner accents
    corner_p = ease_out(max(0, t-1)/2.0)
    if corner_p > 0:
        cl = 60
        for ox, oy, dx, dy in [(cx-310, 345, 1, -1), (cx+310, 345, -1, -1),
                                (cx-310, 725, 1, 1), (cx+310, 725, -1, 1)]:
            draw_line_anim(draw, [(ox, oy), (ox + cl*dx*corner_p, oy)], corner_p, GOLD_DIM, 1)
            draw_line_anim(draw, [(ox, oy), (ox, oy + cl*dy*corner_p)], corner_p, GOLD_DIM, 1)

    logo_key = 'slide1_Picture_6.png'
    if logo_key in _assets:
        fade = ease_out(t / 2.0)
        logo = _assets[logo_key].convert('RGBA')
        sz = 280
        logo_r = logo.resize((sz, sz), Image.LANCZOS)
        if fade < 1:
            alpha = logo_r.split()[3]; alpha = alpha.point(lambda p: int(p * fade)); logo_r.putalpha(alpha)
        img.paste(logo_r, ((W-sz)//2, 360), logo_r)
        draw = ImageDraw.Draw(img)

    tp = ease_out(max(0, t-1.5)/2.0)
    title = "R I V E R L A N D  3 0 0"
    f_title = font('serifb', 44); tw = text_width(title, f_title)
    n = int(len(title) * tp)
    if n > 0: draw.text(((W-tw)//2, 670), title[:n], fill=GOLD, font=f_title)
    sp = ease_out(max(0, t-3.0)/1.5)
    sub = "by Next Level Consulting"; f_sub = font('sans', 20); sw = text_width(sub, f_sub)
    sn = int(len(sub) * sp)
    if sn > 0: draw.text(((W-sw)//2, 730), sub[:sn], fill=TSEC, font=f_sub)
    return np.array(img)

# ================================================================
# SCENE 2: MASTERPLAN (5-10s) - Blurred bg + line animation + photos
# ================================================================
def scene_masterplan(t):
    mp_key = 'slide2_Picture_6.png'
    if mp_key in _assets:
        # Pre-cache blurred dark version and full version
        if '_mp_blurred' not in _assets:
            full = _assets[mp_key].convert('RGB').resize((W, H), Image.LANCZOS)
            _assets['_mp_full'] = np.array(full).astype(np.float32)
            # Create darkened + blurred version
            dark = Image.fromarray((np.array(full).astype(np.float32) * 0.25).astype(np.uint8))
            blurred = dark.filter(ImageFilter.GaussianBlur(radius=12))
            _assets['_mp_blurred'] = np.array(blurred).astype(np.float32)

        # Phase 1 (0-2s): Start with blurred dark background, draw development outline
        # Phase 2 (2-3.5s): Draw river + house footprints, reveal center
        # Phase 3 (3.5-5s): Reveal photos on left and right

        # Background: transition from blurred to clearer as animation progresses
        reveal = ease_in_out(min(1, t / 4.0))
        # Center region reveals faster, edges stay darker longer
        blurred = _assets['_mp_blurred']
        full = _assets['_mp_full']
        # Mix from blurred to partially revealed
        center_reveal = ease_in_out(min(1, t / 3.0)) * 0.55
        arr = blurred * (1 - center_reveal) + full * center_reveal
        img = Image.fromarray(arr.astype(np.uint8))
    else:
        img = get_bg()

    draw = ImageDraw.Draw(img)

    # Gold line animation: development boundary (elongated shape matching aerial view)
    # The development is roughly centered, wider at bottom, tapering at top
    outline_prog = ease_out(min(1, t / 2.5))
    boundary = [
        (700, 120), (760, 100), (830, 95), (880, 110), (920, 150),
        (950, 210), (970, 290), (990, 380), (1020, 470), (1050, 540),
        (1080, 600), (1120, 660), (1150, 720), (1170, 780), (1160, 840),
        (1120, 870), (1060, 880), (980, 870), (900, 850), (830, 820),
        (770, 780), (720, 720), (680, 640), (660, 560), (650, 480),
        (650, 400), (660, 320), (670, 240), (680, 180), (700, 120)
    ]
    draw_line_anim(draw, boundary, outline_prog, GOLD, 3)

    # River (blue) through the development - sinuous path top to bottom
    river_prog = ease_out(max(0, t - 0.8) / 2.0)
    river = []
    for i in range(40):
        tt = i / 39
        rx = lerp(870, 1000, tt) + 30 * math.sin(tt * 8)
        ry = lerp(100, 880, tt)
        river.append((rx, ry))
    draw_line_anim(draw, river, river_prog, BLUE_LIGHT, 3)

    # House footprints as small gold rectangles along the left side of the development
    house_prog = ease_out(max(0, t - 1.5) / 2.0)
    if house_prog > 0:
        import random
        rng = random.Random(99)
        # Rows of houses matching the masterplan layout
        house_rows = [
            (700, 350, 8), (690, 450, 9), (680, 550, 8),
            (700, 650, 7), (730, 740, 6), (780, 810, 5),
        ]
        for ri, (rx, ry, count) in enumerate(house_rows):
            rp = ease_out(max(0, house_prog - ri * 0.08) / 0.5)
            if rp <= 0: continue
            for j in range(count):
                hx = rx + j * 28 + rng.randint(-3, 3)
                hy = ry + rng.randint(-5, 5)
                c = color_alpha(GOLD_BRIGHT, rp * 0.6)
                draw.rectangle([(hx, hy), (hx+12, hy+8)], outline=c, width=1)

    # Road lines through the development
    road_prog = ease_out(max(0, t - 1.8) / 1.5)
    if road_prog > 0:
        for ry in [380, 480, 580, 680, 770]:
            rp = ease_out(max(0, road_prog - (ry-380)/800) / 0.5)
            if rp > 0:
                draw_line_anim(draw, [(670, ry), (850, ry)], rp, color_alpha(CREAM, 0.3), 1)

    # Photos on left and right fade in last
    photo_prog = ease_out(max(0, t - 3.0) / 1.5)
    if photo_prog > 0 and mp_key in _assets:
        # Increase photo visibility by brightening left (0-380px) and right (1540-1920px) regions
        arr = np.array(img).astype(np.float32)
        full = _assets['_mp_full']
        # Left photos region
        left_alpha = np.zeros(W)
        left_alpha[:380] = photo_prog * 0.7
        # Smooth transition edge
        for x in range(380, 430):
            left_alpha[x] = photo_prog * 0.7 * (1 - (x - 380) / 50)
        # Right photos region
        right_alpha = np.zeros(W)
        right_alpha[1540:] = photo_prog * 0.7
        for x in range(1490, 1540):
            right_alpha[x] = photo_prog * 0.7 * (1 - (1540 - x) / 50)
        combined = left_alpha + right_alpha
        alpha_mask = np.broadcast_to(combined[np.newaxis, :, np.newaxis], arr.shape)
        arr = arr * (1 - alpha_mask) + full * alpha_mask
        img = Image.fromarray(arr.astype(np.uint8))

    return np.array(img)

# ================================================================
# SCENE 3: THREE PILLARS (10-60s) - Real 3D construction animations
# ================================================================
def scene_pillars(t):
    """Three pillars shown sequentially: each pillar gets ~17s of focus.
    Total duration: 53s (10-63s). Voiceover timing:
    - 10-20s: Intro + residential (3 pillars intro, 'combines residential...')
    - 21-38s: Strategic / value ecosystem / creates from nothing
    - 39-63s: Green spaces (40k+30k, cycling, amphitheaters, 'upgrades the area')
    """
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    # Ambient particles throughout
    draw_ambient_particles(draw, t, count=20, speed=0.15, color=GOLD_DIM, opacity=0.1)

    # Phase 1 (0-18s): Residential Development - full screen
    # Phase 2 (18-35s): Strategic Developments - full screen
    # Phase 3 (35-53s): Green Spaces - full screen (extra 3s for voiceover)

    if t < 18:
        # === PHASE 1: RESIDENTIAL ===
        local_t = t
        # Title with scan line
        title_p = ease_out(local_t / 2.0)
        draw_text_fade(draw, 'Οικιστική Ανάπτυξη', (margin, 50), font('serifb', 48), CREAM, title_p)
        draw_line_anim(draw, [(margin, 115), (W-margin, 115)], ease_out(max(0, local_t-0.5)/1.5), GOLD_DIM, 1)

        sub_p = ease_out(max(0, local_t-2)/2.0)
        draw_text_fade(draw, 'Οικοσύστημα με θεσμική δομή', (margin, 130), font('sans', 22), GOLD, sub_p)

        # Scan line sweeping down
        if local_t < 4:
            scan_y = int(120 + local_t / 4.0 * (H - 200))
            draw_scan_line(draw, local_t, scan_y, W, GOLD, 0.15)

        # 3D neighborhood - builds across full width, takes longer
        art_prog = ease_in_out(max(0, min(1, (local_t - 1.5) / 12.0)))
        if art_prog > 0:
            # Two rows of buildings for density
            draw_3d_neighborhood(draw, margin + 40, 520, W - 2*margin - 100, 300, art_prog, 7)
            # Second row behind (fewer for performance)
            row2_p = ease_out(max(0, art_prog - 0.3) / 0.7)
            if row2_p > 0:
                for i in range(3):
                    bp = ease_out(max(0, row2_p - i*0.15)/0.5)
                    if bp > 0:
                        bx = margin + 120 + i * 450
                        draw_3d_building(draw, bx, 380, 85, 90, 38, bp, style='villa',
                                        floors=2, has_roof=True, lw=1,
                                        front_c=GOLD_DIM, side_c=color_alpha(SIDE_COLOR, 0.6))
                tp = ease_out(max(0, row2_p - 0.4)/0.6)
                if tp > 0:
                    for i in range(4):
                        tx = margin + 200 + i * 380
                        draw_3d_tree(draw, tx, 390, 35 + (i%3)*8, tp)

        # Key number reveal
        num_p = ease_out(max(0, local_t - 10) / 3.0)
        if num_p > 0:
            draw_number_anim(draw, '100κ+', (W - margin - 350, 180), font('serifb', 72), GOLD, num_p)
            draw_text_fade(draw, 'τ.μ. οικιστικός σχεδιασμός', (W - margin - 350, 265),
                          font('sans', 20), TSEC, ease_out(max(0, num_p-0.3)/0.7))

    elif t < 35:
        # === PHASE 2: STRATEGIC DEVELOPMENTS ===
        local_t = t - 18
        title_p = ease_out(local_t / 2.0)
        draw_text_fade(draw, 'Στρατηγικές Αναπτύξεις', (margin, 50), font('serifb', 48), CREAM, title_p)
        draw_line_anim(draw, [(margin, 115), (W-margin, 115)], ease_out(max(0, local_t-0.5)/1.5), GOLD_DIM, 1)

        sub_p = ease_out(max(0, local_t-2)/2.0)
        draw_text_fade(draw, 'Αναπτύξεις υψηλής εσωτερικής αξίας', (margin, 130), font('sans', 22), GOLD, sub_p)

        # Large commercial buildings rising
        build_prog = ease_in_out(max(0, min(1, (local_t - 1.5) / 10.0)))
        if build_prog > 0:
            commercials = [
                (margin+80, 580, 170, 210, 75, 'modern', 4),
                (margin+400, 580, 190, 250, 85, 'modern', 5),
                (margin+750, 580, 160, 200, 70, 'modern', 4),
                (margin+1100, 580, 180, 220, 80, 'modern', 4),
            ]
            for i, (bx, by, bw, bh, bd, bs, fl) in enumerate(commercials):
                bp = ease_out(max(0, build_prog - i * 0.1) / 0.5)
                if bp > 0:
                    draw_3d_building(draw, bx, by, bw, bh, bd, bp, style=bs, floors=fl, has_roof=False, lw=2)

            # Connecting paths
            wp = ease_out(max(0, build_prog - 0.5) / 0.5)
            if wp > 0:
                draw_line_anim(draw, [(margin+40, 588), (W-margin-40, 588)], wp, TSEC, 1)
                draw_line_anim(draw, [(margin+40, 592), (W-margin-40, 592)], wp, DARK_LINE, 1)

            # Trees between buildings
            tp = ease_out(max(0, build_prog - 0.6) / 0.4)
            if tp > 0:
                for tx in [margin+330, margin+650, margin+1000]:
                    draw_3d_tree(draw, tx, 578, 40, tp)

        # Key number
        num_p = ease_out(max(0, local_t - 8) / 3.0)
        if num_p > 0:
            draw_number_anim(draw, '25%', (W - margin - 250, 180), font('serifb', 72), GOLD, num_p)
            draw_text_fade(draw, 'στρατηγικές αναπτύξεις', (W - margin - 250, 265),
                          font('sans', 20), TSEC, ease_out(max(0, num_p-0.3)/0.7))

    else:
        # === PHASE 3: GREEN SPACES ===
        local_t = t - 35
        title_p = ease_out(local_t / 2.0)
        draw_text_fade(draw, 'Περιβάλλοντες Χώροι', (margin, 50), font('serifb', 48), CREAM, title_p)
        draw_line_anim(draw, [(margin, 115), (W-margin, 115)], ease_out(max(0, local_t-0.5)/1.5), GOLD_DIM, 1)

        sub_p = ease_out(max(0, local_t-2)/2.0)
        draw_text_fade(draw, 'Αποτύπωμα στον χώρο που ξεχωρίζει', (margin, 130), font('sans', 22), GOLD, sub_p)

        # Numbers "40κ + 30κ"
        num_t = max(0, local_t - 1.5) / 3.0
        if num_t > 0:
            f_num = font('serifb', 56)
            draw_number_anim(draw, '40κ', (margin, 180), f_num, GOLD, num_t)
            if num_t > 0.3:
                draw_text_fade(draw, '+', (margin+140, 190), f_num, CREAM, ease_out((num_t-0.3)/0.3))
            if num_t > 0.5:
                draw_number_anim(draw, '30κ', (margin+180, 180), f_num, GOLD, (num_t-0.5)/0.5)
            if num_t > 0.8:
                draw_text_fade(draw, 'τ.μ. που σας κάνουν μοναδικούς',
                              (margin+330, 200), font('sans', 22), TSEC, ease_out((num_t-0.8)/0.5))

        # Forest of 3D trees across bottom
        tree_prog = ease_in_out(max(0, min(1, (local_t - 2) / 8.0)))
        if tree_prog > 0:
            for i in range(8):
                tx = margin + 50 + i * 210
                th = 55 + (i % 3) * 15
                tp2 = ease_out(max(0, tree_prog - i * 0.06) / 0.3)
                col = GREEN_A if i % 2 == 0 else GREEN_B
                draw_3d_tree(draw, tx, 750, th, tp2, col)
            for i in range(5):
                tx = margin + 150 + i * 320
                tp2 = ease_out(max(0, tree_prog - 0.2 - i * 0.05) / 0.3)
                draw_3d_tree(draw, tx, 650, 40, tp2, color_alpha(GREEN_A, 0.6))

        # Cycling path (winding)
        cycle_p = ease_out(max(0, local_t - 5) / 5.0)
        if cycle_p > 0:
            pts = []
            for i in range(80):
                tt = i / 79
                px = lerp(margin + 50, W - margin - 50, tt)
                py = 620 + 30 * math.sin(tt * 6 * math.pi)
                pts.append((px, py))
            draw_line_anim(draw, pts, cycle_p, GOLD, 2)
            # Second path (jogging)
            pts2 = [(px, py + 35) for px, py in pts]
            draw_line_anim(draw, pts2, ease_out(max(0, cycle_p - 0.2) / 0.8), TSEC, 1)

        # Amphitheater
        amp_p = ease_out(max(0, local_t - 7) / 4.0)
        if amp_p > 0:
            acx, acy = W - margin - 250, 500
            for row in range(5):
                ri = 80 - row * 14
                pts = []
                for a in range(0, 181, 4):
                    rad = math.radians(a)
                    pts.append((acx + ri * math.cos(rad), acy - ri * math.sin(rad) * 0.4 - row * 8))
                draw_line_anim(draw, pts, amp_p, color_alpha(GOLD, amp_p * (0.9 - row * 0.12)), 2)

        # Sports field (3D perspective)
        fp = ease_out(max(0, local_t - 9) / 4.0)
        if fp > 0:
            fx, fy, fw, fh = margin + 100, 430, 180, 90
            draw_line_anim(draw, [(fx, fy), (fx+fw, fy), (fx+fw, fy+fh), (fx, fy+fh), (fx, fy)], fp, GOLD_DIM, 2)
            draw_line_anim(draw, [(fx+fw//2, fy), (fx+fw//2, fy+fh)], fp, GOLD_DIM, 1)
            # Center circle
            cc_pts = []
            for a in range(0, 361, 10):
                rad = math.radians(a)
                cc_pts.append((fx + fw//2 + 20*math.cos(rad), fy + fh//2 + 12*math.sin(rad)))
            draw_line_anim(draw, cc_pts, fp, GOLD_DIM, 1)

    return np.array(img)

# ================================================================
# SCENE 4: MAP (63-78s) - SLOWED DOWN further
# ================================================================
_map_frame_cache = {}

def scene_map(t):
    frames = _assets.get('map_frames', [])
    if frames:
        total = len(frames)
        # Match website speed: 360 frames captured at 30fps = 12s real-time
        # Play at 1:1 rate (one captured frame per video frame), hold last 3s
        anim_duration = total / FPS  # 12s at 30fps
        if t < anim_duration:
            frame_idx = int(t * FPS)
        else:
            frame_idx = total - 1
        frame_idx = max(0, min(frame_idx, total - 1))
        if frame_idx not in _map_frame_cache:
            _map_frame_cache[frame_idx] = np.array(
                Image.open(frames[frame_idx]).convert('RGB').resize((W, H), Image.LANCZOS))
            if len(_map_frame_cache) > 60:
                oldest = min(_map_frame_cache.keys()); del _map_frame_cache[oldest]
        return _map_frame_cache[frame_idx]
    # Fallback
    img = get_bg()
    draw = ImageDraw.Draw(img)
    draw_text_fade(draw, 'Τοποθεσία', (80, 40), font('serif', 48), CREAM, ease_out(t/2.0))
    return np.array(img)

# ================================================================
# SCENE 5: KEY NUMBERS (78-100s)
# ================================================================
def scene_numbers(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    draw_ambient_particles(draw, t, count=15, speed=0.15, color=GOLD_DIM, opacity=0.08)

    # Top section: paragraph text
    para = ("Η παρούσα πρόταση αξιοποιεί ένα ειδικό κυβερνητικό "
            "πολεοδομικό πρόγραμμα που επιτρέπει τη μετατροπή "
            "γεωργικής και δασικής γης σε περιοχές οικιστικής "
            "και εμπορικής ανάπτυξης, υπό συγκεκριμένες "
            "προϋποθέσεις και περιλαμβάνει:")
    para_prog = ease_out(min(1, t / 5.0))
    if para_prog > 0:
        n = int(len(para) * para_prog)
        multiline_text(draw, para[:n], (margin, 60), font('sans', 24), CREAM, W - 2*margin)

    # Three large columns filling most of the screen
    cols = [
        {'num': '40κ', 'label': 'τ.μ. ελάχιστη έκταση πρασίνου',
         'desc': '+30κ τμ πρασίνου δημιουργούν τον μεγαλύτερο οργανωμένο χώρο πρασίνου στην πόλη.',
         'icon_type': 'tree'},
        {'num': '25%', 'label': 'στρατηγικές αναπτύξεις',
         'desc': 'αναπτύξεις πραγματικά καινοτόμες χωρίς χωραταξικούς περιορισμούς.',
         'icon_type': 'building'},
        {'num': '100κ', 'label': 'τ.μ. οικιστικός σχεδιασμός',
         'desc': 'μια πρωτοποριακή κοινότητα που δένει και συμπληρώνει το έργο.',
         'icon_type': 'villa'},
    ]
    col_w = (W - 2*margin) // 3
    num_y = 250

    # Horizontal separator
    sep_p = ease_out(max(0, t-4)/2.0)
    draw_line_anim(draw, [(margin, num_y-20), (W-margin, num_y-20)], sep_p, GOLD_DIM, 1)

    for i, col in enumerate(cols):
        cx = margin + i * col_w + 20

        # Vertical separators between columns
        if i > 0:
            vx = margin + i * col_w
            draw_line_anim(draw, [(vx, num_y), (vx, H-80)], ease_out(max(0, t-6)/2.0), DARK_LINE, 1)

        # Large number
        np2 = ease_out(max(0, t-5-i*0.5)/3.0)
        if np2 > 0:
            draw_number_anim(draw, col['num'], (cx, num_y), font('serifb', 80), GOLD, np2)

        # Label
        lp = ease_out(max(0, t-8-i*0.5)/2.0)
        if lp > 0:
            draw_text_fade(draw, col['label'], (cx, num_y+100), font('sansb', 22), CREAM, lp)

        # Description
        dp = ease_out(max(0, t-11-i*0.5)/3.0)
        if dp > 0:
            multiline_text(draw, col['desc'], (cx, num_y+140), font('sans', 18),
                          color_alpha(TSEC, dp), col_w - 50)

        # 3D icon at bottom of each column - fills vertical space
        icon_p = ease_out(max(0, t-13-i*1.0)/4.0)
        if icon_p > 0:
            icon_cx = cx + col_w // 2 - 40
            if col['icon_type'] == 'tree':
                for j in range(4):
                    draw_3d_tree(draw, icon_cx - 60 + j*50, 830, 80 - j*10, icon_p, GREEN_A if j%2 else GREEN_B)
            elif col['icon_type'] == 'building':
                draw_3d_building(draw, icon_cx - 30, 830, 120, 160, 55, icon_p,
                               style='modern', floors=4, has_roof=False, lw=2)
            elif col['icon_type'] == 'villa':
                draw_3d_building(draw, icon_cx - 40, 830, 100, 120, 45, icon_p,
                               style='villa', floors=2, has_roof=True, lw=2)
                draw_3d_tree(draw, icon_cx + 80, 830, 50, icon_p * 0.8)

    # Bottom accent line
    bot_p = ease_out(max(0, t-16)/2.0)
    draw_line_anim(draw, [(margin, H-50), (W-margin, H-50)], bot_p, GOLD_DIM, 1)

    return np.array(img)

# ================================================================
# SCENE 6: STRATEGIC DEVELOPMENTS (100-122s) - Complex 3D
# ================================================================
def scene_strategic(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    draw_ambient_particles(draw, t, count=15, speed=0.15, color=GOLD_DIM, opacity=0.08)

    title_p = ease_out(t / 2.0)
    draw_text_fade(draw, 'Στρατηγικές Αναπτύξεις', (margin, 40), font('serif', 52), CREAM, title_p)
    draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, t-1)/1.5), GOLD_DIM, 1)

    # Left half: info text columns stacked vertically
    info_cols = [
        ('Σχέδιο χωρίς περιορισμούς', '50.000 τμ για την κάθε ανάπτυξη σε τοποθεσία μακριά από θόρυβο, κοντά στην πόλη.'),
        ('Καλυμμένοι χώροι', '15.000 τμ για βασικές και συμπληρωματικές χρήσεις, που κάνουν ικανό το σχέδιο.'),
        ('Το περιβάλλον', '70.000+ τμ πρασίνου, τα οποία δένουν με την ανάπτυξη, πολλαπλασιάζοντας την αξία.'),
    ]
    text_w = W // 2 - margin - 40
    for i, (title, text) in enumerate(info_cols):
        iy = 150 + i * 200
        cp = ease_out(max(0, t-2-i*1.5)/3.0)
        if cp > 0:
            # Gold accent bar on left
            draw_line_anim(draw, [(margin, iy), (margin, iy+150)], cp, GOLD, 3)
            draw_text_fade(draw, title, (margin+20, iy+5), font('sansb', 24), GOLD, cp)
            draw_line_anim(draw, [(margin+20, iy+38), (margin+text_w, iy+38)], cp*0.7, DARK_LINE, 1)
            multiline_text(draw, text, (margin+20, iy+50), font('sans', 18), color_alpha(CREAM, cp), text_w-20)

    # Vertical divider
    div_x = W // 2
    draw_line_anim(draw, [(div_x, 130), (div_x, H-60)], ease_out(max(0, t-1.5)/2.0), DARK_LINE, 1)

    # Right half: 3D building complex - large, fills the space
    build_prog = ease_in_out(max(0, min(1, (t-2)/10.0)))
    if build_prog > 0:
        rx = div_x + 40
        buildings = [
            (rx+20, 700, 150, 220, 65, 'modern', 5),
            (rx+220, 700, 120, 180, 55, 'modern', 4),
            (rx+390, 700, 170, 250, 75, 'modern', 6),
            (rx+610, 700, 130, 190, 60, 'modern', 4),
        ]
        for i, (bx, by, bw, bh, bd, bs, fl) in enumerate(buildings):
            bp = ease_out(max(0, build_prog - i*0.12)/0.5)
            if bp > 0:
                draw_3d_building(draw, bx, by, bw, bh, bd, bp, style=bs, floors=fl, has_roof=False, lw=2)

        # Ground path
        gp = ease_out(max(0, build_prog-0.4)/0.5)
        if gp > 0:
            draw_line_anim(draw, [(rx, 708), (W-margin, 708)], gp, TSEC, 1)
            draw_line_anim(draw, [(rx, 712), (W-margin, 712)], gp, DARK_LINE, 1)

        # Trees
        tp = ease_out(max(0, build_prog-0.5)/0.5)
        if tp > 0:
            for tx in [rx+180, rx+360, rx+560]:
                draw_3d_tree(draw, tx, 698, 45, tp)

        # Background hint buildings (simple lines only for performance)
        bg_p = ease_out(max(0, build_prog-0.3)/0.7)
        if bg_p > 0:
            for i in range(2):
                bx = rx + 120 + i * 350
                draw_3d_building(draw, bx, 520, 70, 90, 30, bg_p*0.4,
                               style='modern', floors=2, has_roof=False, lw=1,
                               front_c=GOLD_DIM, side_c=color_alpha(SIDE_COLOR, 0.3))

    # Bottom accent
    bot_p = ease_out(max(0, t-15)/2.0)
    draw_line_anim(draw, [(margin, H-40), (W-margin, H-40)], bot_p, GOLD_DIM, 1)

    return np.array(img)

# ================================================================
# SCENE 7: RESIDENTIAL IDENTITY (122-142s) - 3D neighborhood
# ================================================================
def scene_residential(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    draw_ambient_particles(draw, t, count=15, speed=0.15, color=GOLD_DIM, opacity=0.08)

    title_p = ease_out(t / 1.5)
    draw_text_fade(draw, 'Οικιστική Ταυτότητα', (margin, 40), font('serif', 52), CREAM, title_p)
    draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, t-0.5)/1.5), GOLD_DIM, 1)

    num_p = ease_out(max(0, t-1.5)/2.0)
    if num_p > 0:
        draw_number_anim(draw, '100κ+', (margin+20, 130), font('serifb', 64), GOLD, num_p)
        draw_text_fade(draw, 'τ.μ. οικιστικός σχεδιασμός', (margin+250, 155), font('sans', 22), TSEC,
                      ease_out(max(0, num_p-0.3)/0.7))

    # Full width content area - text on right, buildings on left
    mid_x = W // 2 - 30
    draw_line_anim(draw, [(mid_x, 220), (mid_x, H-50)], ease_out(max(0, t-2)/1.5), DARK_LINE, 1)

    # Right side: text content - spread more vertically
    rx = mid_x + 60
    draw_text_fade(draw, 'οικιστικός σχεδιασμός που διασφαλίζει:', (rx, 240),
                  font('sansb', 22), CREAM, ease_out(max(0, t-3)/1.5))

    bullets = ['Ιδιωτικότητα', 'Ανοικτούς Χώρους', 'Υψηλό επίπεδο καθημερινότητας']
    for i, b in enumerate(bullets):
        bp = ease_out(max(0, t-4-i*0.5)/1.5)
        if bp > 0:
            by = 290 + i * 45
            # Gold bullet dot
            draw.ellipse([(rx, by+8), (rx+8, by+16)], fill=color_alpha(GOLD, bp))
            draw_text_fade(draw, b, (rx+20, by), font('sansb', 22), CREAM, bp)

    draw_text_fade(draw, 'ενώ ταυτόχρονα:', (rx, 440), font('sansb', 22), CREAM,
                  ease_out(max(0, t-6)/1.5))

    guarantees = [
        ('Ελεγχόμενο χαμηλό ρίσκο επένδυσης', 'Χωρίς προαγορά γης.'),
        ('Υψηλές εγγυήσεις στο έργο', 'Εξασφάλιση αδειών από εμάς.'),
        ('Μεγάλα ποσοστά ασφάλειας', 'Τμηματική ανάπτυξη με δυνατότητες εξόδου.'),
    ]
    for i, (gtitle, gdesc) in enumerate(guarantees):
        gy = 500 + i * 110
        gp = ease_out(max(0, t-7-i*1.5)/2.0)
        if gp > 0:
            # Gold accent bar
            draw_line_anim(draw, [(rx, gy), (rx, gy+80)], gp, GOLD, 3)
            draw_text_fade(draw, gtitle, (rx+15, gy+5), font('sansb', 20), CREAM, gp)
            draw_text_fade(draw, gdesc, (rx+15, gy+35), font('sans', 17), TSEC, gp*0.8)

    # Left side: 3D residential neighborhood - fills full left half
    left_prog = ease_in_out(max(0, min(1, (t-2)/12.0)))
    if left_prog > 0:
        lbase = margin + 10
        lw_avail = mid_x - margin - 30
        # Row 1: Large villas (top)
        row1_y = 420
        for i in range(3):
            bp = ease_out(max(0, left_prog - i*0.1)/0.4)
            if bp > 0:
                bx = lbase + i * (lw_avail//3) + 10
                draw_3d_building(draw, bx, row1_y, 110, 120, 50, bp, style='villa', floors=2, has_roof=True)
        # Row 2: Medium houses
        row2_y = 620
        for i in range(4):
            bp = ease_out(max(0, left_prog - 0.25 - i*0.08)/0.4)
            if bp > 0:
                bx = lbase + i * (lw_avail//4)
                draw_3d_building(draw, bx, row2_y, 85, 90, 40, bp, style='villa', floors=2, has_roof=True)
        # Row 3: Compact units
        row3_y = 820
        for i in range(5):
            bp = ease_out(max(0, left_prog - 0.45 - i*0.06)/0.35)
            if bp > 0:
                bx = lbase + i * (lw_avail//5)
                draw_3d_building(draw, bx, row3_y, 70, 75, 32, bp, style='modern', floors=2, has_roof=False)
        # Roads
        rp = ease_out(max(0, left_prog - 0.35)/0.3)
        for ry in [row1_y+12, row2_y+12, row3_y+12]:
            draw_line_anim(draw, [(lbase-10, ry), (lbase+lw_avail+10, ry)], rp, TSEC, 1)
            draw_line_anim(draw, [(lbase-10, ry+4), (lbase+lw_avail+10, ry+4)], rp, DARK_LINE, 1)
        # Trees scattered
        tp2 = ease_out(max(0, left_prog - 0.5)/0.5)
        if tp2 > 0:
            for tx, ty2, th in [(lbase-15, row1_y-40, 35), (lbase+lw_avail+15, row1_y, 38),
                                (lbase+lw_avail//3, 340, 40), (lbase+lw_avail*2//3, 340, 32),
                                (lbase-15, row2_y-30, 30), (lbase+lw_avail+15, row2_y, 30)]:
                draw_3d_tree(draw, tx, ty2, th, tp2)

    # Bottom accent
    draw_line_anim(draw, [(margin, H-35), (W-margin, H-35)], ease_out(max(0, t-14)/2.0), GOLD_DIM, 1)

    return np.array(img)

# ================================================================
# SCENE 8: ASSUMPTIONS & PHASES (142-220s) - Fixed text + 3D
# ================================================================
def scene_assumptions(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    draw_ambient_particles(draw, t, count=12, speed=0.1, color=GOLD_DIM, opacity=0.06)

    # Phase 1 (0-22s): Categories with 3D buildings
    # Phase 2 (22-45s): Phases text + timeline
    # Phase 3 (45-78s): Financial indicators + summary

    if t < 24:
        # === PHASE 1: Building Categories ===
        tp = ease_out(t / 1.5)
        draw_text_fade(draw, 'Παραδοχές και Υποθέσεις', (margin, 40), font('serifb', 48), CREAM, tp)
        draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, t-0.5)/1.5), GOLD_DIM, 1)

        categories = [
            ('Α', '18% του ΣΔ', '220τμ σε τεμάχιο 700τμ', '22 μονάδες', 'villa', 2),
            ('Β', '57% του ΣΔ', '135τμ σε τεμάχιο 400τμ', '118 μονάδες', 'villa', 2),
            ('Β+', '14% του ΣΔ', '135τμ σε τεμάχιο 400τμ', '30 μονάδες', 'modern', 2),
            ('Γ', '11% του ΣΔ', '90τμ ισόγεια', '37 μονάδες', 'modern', 3),
        ]
        cat_w = (W - 2*margin - 60) // 4
        for i, (cat, pct, desc, units, style, fl) in enumerate(categories):
            cx = margin + i * (cat_w + 20)
            cp = ease_out(max(0, t-2-i*0.8)/2.5)
            if cp > 0:
                # Category header with gold accent
                draw_line_anim(draw, [(cx, 140), (cx, 280)], cp, GOLD, 3)
                draw_text_fade(draw, f'Κατηγορία {cat}', (cx+15, 140), font('sansb', 24), GOLD, cp)
                draw_text_fade(draw, pct, (cx+15, 175), font('sans', 18), TSEC, cp)
                draw_text_fade(draw, desc, (cx+15, 205), font('sans', 16), CREAM, cp*0.8)
                draw_text_fade(draw, units, (cx+15, 235), font('sansb', 18), GOLD, cp*0.7)

            # 3D building for each category - fills bottom half
            bp = ease_out(max(0, t-5-i*1.5)/6.0)
            if bp > 0:
                bw = cat_w - 40
                bh = int(bw * 1.1)
                bd = int(bw * 0.4)
                bx = cx + 15
                by = 310 + bh + 50
                draw_3d_building(draw, bx, by, bw, bh, bd, bp, style=style, floors=fl,
                               has_roof=(style=='villa'), lw=2)
                # Tree next to each
                tp2 = ease_out(max(0, bp-0.5)/0.5)
                if tp2 > 0:
                    draw_3d_tree(draw, bx + bw + 15, by, 40, tp2)

            # Vertical separator
            if i > 0:
                vx = margin + i * (cat_w + 20) - 10
                draw_line_anim(draw, [(vx, 130), (vx, H-60)], ease_out(max(0, t-3)/2.0), DARK_LINE, 1)

        # Bottom accent
        draw_line_anim(draw, [(margin, H-45), (W-margin, H-45)], ease_out(max(0, t-8)/2.0), GOLD_DIM, 1)

    elif t < 48:
        # === PHASE 2: Development phases + text ===
        local_t = t - 24
        tp = ease_out(local_t / 1.5)
        draw_text_fade(draw, 'Φάσεις Υλοποίησης', (margin, 40), font('serifb', 48), CREAM, tp)
        draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, local_t-0.5)/1.5), GOLD_DIM, 1)

        # Text block - left side
        lines = [
            (True, 'Η ανάπτυξη θα υλοποιηθεί σε'),
            (True, '3 φάσεις των 18 μηνών,'),
            (False, ''),
            (False, 'ενώ η προαγορά προϋποθέτει'),
            (True, '3 ισόποσες πληρωμές,'),
            (False, ''),
            (False, 'μειώνοντας δραματικά το ρίσκο'),
            (False, 'και επιτρέποντας την'),
            (False, 'αυτοχρηματοδότηση του έργου'),
            (False, 'σε μεγάλο βαθμό.'),
        ]
        text_x = margin + 20
        ty = 140
        for i, (bold, line) in enumerate(lines):
            if not line: ty += 15; continue
            lp = ease_out(max(0, local_t - 1.5 - i * 0.3) / 2.0)
            if lp > 0:
                fn = 'sansb' if bold else 'sans'
                fc = CREAM if bold else TSEC
                draw_text_fade(draw, line, (text_x, ty), font(fn, 24), fc, lp)
            ty += 38

        # Phases timeline - right and lower half, filling the space
        tl_y = 540
        tl_x = margin
        tl_w = W - 2*margin
        phase_w = tl_w // 3
        phases = [
            ('Φάση 1', '18 μήνες', '50% ανάπτυξης', '60% κόστους'),
            ('Φάση 2', '18 μήνες', '25% ανάπτυξης', '20% κόστους'),
            ('Φάση 3', '18 μήνες', '25% ανάπτυξης', '20% κόστους'),
        ]
        # Timeline base line
        draw_line_anim(draw, [(tl_x, tl_y-10), (tl_x+tl_w, tl_y-10)], ease_out(max(0, local_t-8)/2.0), GOLD_DIM, 1)
        for i, (name, dur, dev, cost) in enumerate(phases):
            px = tl_x + i * phase_w
            pp = ease_out(max(0, local_t-9-i*2.0)/3.0)
            if pp > 0:
                # Phase box
                draw_line_anim(draw, [(px+10, tl_y), (px+phase_w-10, tl_y), (px+phase_w-10, tl_y+80),
                                      (px+10, tl_y+80), (px+10, tl_y)], pp, GOLD, 2)
                draw_text_fade(draw, name, (px+25, tl_y+10), font('sansb', 22), GOLD, pp)
                draw_text_fade(draw, dur, (px+25, tl_y+42), font('sans', 16), TSEC, pp)
                # Details below box
                dp2 = ease_out(max(0, pp-0.4)/0.6)
                draw_text_fade(draw, dev, (px+25, tl_y+95), font('sansb', 18), CREAM, dp2)
                draw_text_fade(draw, cost, (px+25, tl_y+125), font('sans', 16), TSEC, dp2)

        # Small 3D buildings on right side as decoration
        dec_p = ease_in_out(max(0, min(1, (local_t-4)/8.0)))
        if dec_p > 0:
            for i in range(4):
                bx = W//2 + 80 + i * 180
                draw_3d_building(draw, bx, 470, 80+i*10, 100+i*15, 35+i*5, dec_p*0.6,
                               style='modern' if i%2 else 'villa', floors=2+i%2,
                               has_roof=(i%2==0), lw=1, front_c=GOLD_DIM)

    else:
        # === PHASE 3: Financial indicators ===
        local_t = t - 48
        tp = ease_out(local_t / 1.5)
        draw_text_fade(draw, 'Οικονομικοί Δείκτες', (margin, 40), font('serifb', 48), CREAM, tp)
        draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, local_t-0.5)/1.5), GOLD_DIM, 1)

        # Phases summary at top (smaller)
        phases = [
            ('Φάση 1', '50% ανάπτυξης / 60% κόστους'),
            ('Φάση 2', '25% ανάπτυξης / 20% κόστους'),
            ('Φάση 3', '25% ανάπτυξης / 20% κόστους'),
        ]
        ph_w = (W - 2*margin) // 3
        for i, (name, detail) in enumerate(phases):
            px = margin + i * ph_w
            draw.text((px+15, 130), name, fill=GOLD, font=font('sansb', 18))
            draw.text((px+15, 155), detail, fill=TSEC, font=font('sans', 14))

        draw_line_anim(draw, [(margin, 190), (W-margin, 190)], 1.0, DARK_LINE, 1)

        # Large financial indicators - filling the middle
        indicators = [
            ('x1.76', 'ΕΜ', 'Υπολογίζοντας τα αρχικά κόστη και αντισταθμίσματα μαζί με το 50% της αντιπαροχής.'),
            ('33.3%', 'IRR', 'Η επένδυση αποπληρώνεται πριν την έναρξη της Β φάσης.'),
            ('38.3%', 'ROI', 'Αυξημένη κερδοφορία με ελάχιστο ρίσκο.'),
        ]
        ind_w = (W - 2*margin) // 3
        for i, (num, label, desc) in enumerate(indicators):
            ix = margin + i * ind_w
            ip = ease_out(max(0, local_t-2-i*2.5)/4.0)
            if ip > 0:
                # Gold accent bar
                draw_line_anim(draw, [(ix+10, 220), (ix+10, 520)], ip, GOLD, 3)
                # Large number
                draw_number_anim(draw, num, (ix+25, 230), font('serifb', 72), GOLD, ip)
                draw_text_fade(draw, label, (ix+25, 320), font('sansb', 30), CREAM, ip)
                draw_line_anim(draw, [(ix+25, 365), (ix+ind_w-20, 365)], ip, DARK_LINE, 1)
                multiline_text(draw, desc, (ix+25, 385), font('sans', 18),
                              color_alpha(TSEC, ip), ind_w-50)
            # Vertical separator
            if i > 0:
                vx = margin + i * ind_w - 5
                draw_line_anim(draw, [(vx, 210), (vx, 530)], ease_out(max(0, local_t-3)/2.0), DARK_LINE, 1)

        # 3D skyline at bottom
        sky_p = ease_in_out(max(0, min(1, (local_t-5)/8.0)))
        if sky_p > 0:
            base_y = H - 60
            configs = [
                (margin+50, 100, 140, 55, 'modern', 3),
                (margin+350, 120, 150, 60, 'villa', 2),
                (margin+680, 110, 130, 55, 'modern', 4),
                (margin+1000, 90, 140, 50, 'villa', 2),
                (margin+1300, 105, 130, 55, 'modern', 3),
            ]
            for i, (bx, bh, bw, bd, style, fl) in enumerate(configs):
                bp = ease_out(max(0, sky_p - i*0.08)/0.4)
                if bp > 0:
                    draw_3d_building(draw, bx, base_y, bw, bh, bd, bp, style=style, floors=fl,
                                   has_roof=(style=='villa'), lw=1)
            tp2 = ease_out(max(0, sky_p-0.5)/0.5)
            if tp2 > 0:
                for tx in [margin+250, margin+850]:
                    draw_3d_tree(draw, tx, base_y, 35, tp2)

        draw_line_anim(draw, [(margin, H-40), (W-margin, H-40)], ease_out(max(0, local_t-8)/2.0), GOLD_DIM, 1)

    return np.array(img)

# ================================================================
# SCENE 9: OUR PROPOSAL (220-237s) - Evenly filled
# ================================================================
def scene_proposal(t):
    img = get_bg()
    draw = ImageDraw.Draw(img)
    margin = 80

    draw_ambient_particles(draw, t, count=20, speed=0.2, color=GOLD_DIM, opacity=0.1)

    # Title centered at top
    tp = ease_out(t / 1.5)
    draw_text_fade(draw, 'Η Πρότασή Μας', (margin, 40), font('serif', 52), CREAM, tp)
    draw_line_anim(draw, [(margin, 108), (W-margin, 108)], ease_out(max(0, t-0.5)/1.5), GOLD_DIM, 1)

    # 4 proposal points in 2x2 grid - larger to fill screen
    points = [
        {'title': 'Έλεγχος Ρίσκου', 'text': 'Κεφαλαιακή πειθαρχία, χωρίς αγορά γης με παράλληλη δυνατότητα εξόδου ανά φάση, που μειώνουν σημαντικά την έκθεση κινδύνου.', 'delay': 1.0},
        {'title': 'Το Πλαίσιο', 'text': 'Ανήκει σε θεσμικά προστατευμένη δομή, σε θεσμοθετημένο πλαίσιο, καταφέρνοντας να συνδυάσει την ενσωματωμένη υπεραξία με υψηλή απόδοση κερδοφορίας.', 'delay': 4.0},
        {'title': 'Η Λογική', 'text': 'Ολιστική προσέγγιση στη λογική δημιουργίας οικοσυστήματος με τρεις πυλώνες ανάπτυξης: Οικιστικό σκέλος, Στρατηγικές χρήσεις, Εκτεταμένη υποδομή πρασίνου.', 'delay': 7.0},
        {'title': 'Ο Στόχος', 'text': 'Η υπεραξία δεν προέρχεται μόνο από την κατασκευή, αλλά από τον πολεοδομικό επαναπροσδιορισμό της περιοχής.', 'delay': 10.0},
    ]

    # 2x2 grid layout - fills from top 130 to bottom 60
    grid_y = 130
    grid_h = (H - grid_y - 60) // 2
    grid_w = (W - 2*margin - 60) // 2

    for idx, pt in enumerate(points):
        row = idx // 2
        col = idx % 2
        px = margin + col * (grid_w + 60)
        py = grid_y + row * grid_h

        pp = ease_out(max(0, t - pt['delay']) / 2.5)
        if pp > 0:
            # Gold accent border on left
            draw_line_anim(draw, [(px, py+10), (px, py+grid_h-30)], pp, GOLD, 3)
            # Title
            draw_text_fade(draw, pt['title'], (px+20, py+15), font('sansb', 28), CREAM, pp)
            # Separator
            draw_line_anim(draw, [(px+20, py+55), (px+grid_w-20, py+55)], pp*0.8, DARK_LINE, 1)
            # Description - larger font
            multiline_text(draw, pt['text'], (px+20, py+72), font('sans', 20),
                          color_alpha(TSEC, pp*0.9), grid_w-50)

            # Small decorative 3D element in bottom-right of each cell
            dec_p = ease_out(max(0, pp-0.5)/0.5)
            if dec_p > 0:
                dx = px + grid_w - 80
                dy = py + grid_h - 50
                if idx == 0:
                    draw_3d_tree(draw, dx, dy, 35, dec_p * 0.5, GREEN_A)
                elif idx == 1:
                    draw_3d_building(draw, dx-20, dy, 40, 40, 18, dec_p*0.5, style='modern', floors=2, has_roof=False, lw=1, front_c=GOLD_DIM)
                elif idx == 2:
                    draw_3d_tree(draw, dx-15, dy, 30, dec_p*0.5, GREEN_B)
                    draw_3d_tree(draw, dx+15, dy, 25, dec_p*0.5, GREEN_A)
                else:
                    draw_3d_building(draw, dx-25, dy, 50, 45, 20, dec_p*0.5, style='villa', floors=2, has_roof=True, lw=1, front_c=GOLD_DIM)

    # Center cross-lines between quadrants
    cx_line = W // 2
    cy_line = grid_y + grid_h
    draw_line_anim(draw, [(cx_line, grid_y+10), (cx_line, H-70)], ease_out(max(0, t-2)/2.0), DARK_LINE, 1)
    draw_line_anim(draw, [(margin+20, cy_line), (W-margin-20, cy_line)], ease_out(max(0, t-2)/2.0), DARK_LINE, 1)

    # Logo in center intersection
    logo_key = 'slide1_Picture_6.png'
    if logo_key in _assets:
        lp2 = ease_out(max(0, t-3)/4.0)
        if lp2 > 0:
            logo = _assets[logo_key].convert('RGBA')
            sz = 100
            logo_r = logo.resize((sz, sz), Image.LANCZOS)
            if lp2 < 1:
                alpha = logo_r.split()[3]; alpha = alpha.point(lambda p: int(p * lp2)); logo_r.putalpha(alpha)
            img.paste(logo_r, ((W-sz)//2, cy_line - sz//2), logo_r)

    return np.array(img)

# ================================================================
# SCENE 10: CLOSING (237-247s) - FULL SCREEN
# ================================================================
def scene_closing(t):
    # Full screen background with project images
    img = Image.new('RGB', (W, H), BG)

    # Full-screen background image
    bg_key = 'slide10_Picture_9.png'
    if bg_key in _assets:
        fade = ease_out(t / 2.0) * 0.5
        bg_img = _assets[bg_key].convert('RGB').resize((W, H), Image.LANCZOS)
        arr = np.array(img).astype(float)
        bg_arr = np.array(bg_img).astype(float)
        img = Image.fromarray((arr * (1-fade) + bg_arr * fade).astype(np.uint8))

    # Dark overlay on right 60% for readability (vectorized)
    overlay_x = W * 2 // 5
    arr = np.array(img).astype(np.float32)
    # Create gradient alpha mask
    xs = np.arange(W)
    alpha_row = np.clip((xs - overlay_x) / 200.0 * 0.85, 0, 0.85)
    alpha_row[:overlay_x] = 0
    alpha_mask = np.broadcast_to(alpha_row[np.newaxis, :, np.newaxis], arr.shape)
    bg_arr = np.array(BG2, dtype=np.float32)
    arr = arr * (1 - alpha_mask) + bg_arr * alpha_mask
    img = Image.fromarray(arr.astype(np.uint8))
    draw = ImageDraw.Draw(img)

    # Logo - large, right-center
    logo_key = 'slide10_Picture_15.png'
    if logo_key in _assets:
        lp = ease_out(max(0, t-0.3)/2.0)
        logo = _assets[logo_key].convert('RGBA')
        lw = 500; lh = int(lw * logo.height / logo.width)
        logo_r = logo.resize((lw, lh), Image.LANCZOS)
        if lp < 1:
            alpha = logo_r.split()[3]; alpha = alpha.point(lambda p: int(p * lp)); logo_r.putalpha(alpha)
        lx = overlay_x + (W - overlay_x - lw) // 2
        ly = 50
        img.paste(logo_r, (lx, ly), logo_r)
        draw = ImageDraw.Draw(img)

    # RIVERLAND text
    text_x = overlay_x + 80
    tp2 = ease_out(max(0, t-1)/2.0)
    draw_text_fade(draw, 'R I V E R L A N D  3 0 0', (text_x, 380), font('serifb', 40), TSEC, tp2)
    draw_text_fade(draw, '2026', (text_x + 50, 430), font('sansb', 24), TSEC, tp2)

    # Contact info - full list with good spacing
    contacts = [
        ('by Next Level Consulting', 'sansb', 22, TSEC),
        ('', 'sans', 14, TSEC),
        ('Αγίου Ιωάννη 3, Λεμεσός', 'sans', 20, CREAM),
        ('70008017', 'sans', 20, CREAM),
        ('nlc@nlc-consulting.org', 'sans', 20, CREAM),
        ('', 'sans', 10, TSEC),
        ('www.riverlandbynlc.org', 'sans', 22, GOLD),
        ('www.nlc-consulting.org', 'sans', 20, TSEC),
    ]
    cy = 490
    for i, (txt, fn, fs, fc) in enumerate(contacts):
        if not txt: cy += 12; continue
        cp = ease_out(max(0, t-2-i*0.25)/2.0)
        draw_text_fade(draw, txt, (text_x, cy), font(fn, fs), fc, cp)
        cy += 36

    # Fade to black at end
    if t > 8:
        fade_out = (t - 8) / 2.0
        arr = np.array(img).astype(float) * max(0, 1 - fade_out)
        img = Image.fromarray(arr.astype(np.uint8))

    return np.array(img)

# ================================================================
# TRANSITIONS & MAIN
# ================================================================
def apply_transition(frame_arr, t_in_scene, scene_duration, fade_dur=0.8):
    arr = frame_arr.astype(np.float32)
    # Smooth fade in with ease curve
    if t_in_scene < fade_dur:
        f = ease_in_out(t_in_scene / fade_dur)
        arr *= f
    # Smooth fade out
    time_left = scene_duration - t_in_scene
    if time_left < fade_dur:
        f = ease_in_out(max(0, time_left / fade_dur))
        arr *= f
    return arr.astype(np.uint8)

scenes_config = [
    (0, 5, scene_logo, 0.3),
    (5, 10, scene_masterplan, 0.3),
    (10, 63, scene_pillars, 0.3),        # Extended to 63s (voiceover continues to ~62.6s)
    (63, 78, scene_map, 0.3),            # Shortened map: 15s (was 18s)
    (78, 100, scene_numbers, 0.3),
    (100, 122, scene_strategic, 0.3),
    (122, 142, scene_residential, 0.3),
    (142, 220, scene_assumptions, 0.3),
    (220, 237, scene_proposal, 0.3),
    (237, 247, scene_closing, 0.5),
]

_fc = [0]
def make_frame(t):
    for start, end, fn, fd in scenes_config:
        if start <= t < end:
            frame = fn(t - start)
            frame = apply_transition(frame, t - start, end - start, fd)
            _fc[0] += 1
            if _fc[0] % (FPS * 10) == 0: print(f"  Rendered {_fc[0]} frames ({t:.1f}s / 247s)")
            return frame
    return np.zeros((H, W, 3), dtype=np.uint8)

def main():
    print("=" * 60)
    print("RIVERLAND — Video Presentation Generator v2")
    print("=" * 60)
    print("\nLoading assets...")
    load_assets()
    print("Pre-loading fonts...")
    for n in ['serif', 'serifb', 'sans', 'sansb', 'sansl']:
        for s in [13, 14, 15, 16, 17, 18, 20, 22, 24, 26, 28, 30, 36, 40, 44, 48, 52, 64, 72]:
            font(n, s)
    get_bg()
    total = 247
    print(f"\nVideo: {W}x{H} @ {FPS}fps, {total}s = {total*FPS} frames")
    video = VideoClip(make_frame, duration=total)
    audio = AudioFileClip("riverland_presentation/audio voice over.mpeg")
    print(f"  Audio: {audio.duration:.1f}s")
    video = video.with_audio(audio)
    out = "RIVERLAND_300_Presentation.mp4"
    print(f"\nRendering {out}...")
    video.write_videofile(out, fps=FPS, codec='libx264', audio_codec='aac',
                         bitrate='5000k', preset='medium', threads=4, logger='bar')
    print(f"\nDone: {out}")
    video.close(); audio.close()

if __name__ == "__main__":
    main()
