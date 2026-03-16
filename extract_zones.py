"""
Extract zone polygons from zone drawings and map to masterplan coordinates.
Zone drawings (880x938) -> Masterplan (1024x1424)
Uses simple scale+offset transform visually calibrated in browser overlay.
"""
from PIL import Image, ImageDraw
import json, math

# ============================================================
# Step 1: Affine transform (visually calibrated)
# mp_x = zd_x * scX + offX
# mp_y = zd_y * scY + offY
# ============================================================
scX = 1.50
scY = 1.66
offX = -16
offY = -281

def apply_transform(x, y):
    return (x * scX + offX, y * scY + offY)

print(f"Transform: scX={scX}, scY={scY}, offX={offX}, offY={offY}")

# ============================================================
# Step 3: Load zone drawings and detect colored outlines
# ============================================================
img = Image.open('assets/masterpanPNG/zone drawings.png').convert('RGBA')
pixels = img.load()
zw, zh = img.size
print(f"\nZone drawings: {zw}x{zh}")

zone_colors = {
    'family':     {'r': (180, 255), 'g': (80, 180), 'b': (0, 60)},
    'premium':    {'r': (40, 160),  'g': (0, 80),   'b': (100, 255)},
    'green-area': {'r': (0, 60),    'g': (140, 255), 'b': (200, 255)},
    'luxury':     {'r': (200, 255), 'g': (200, 255), 'b': (0, 60)},
    'together':   {'r': (100, 180), 'g': (100, 180), 'b': (100, 180)},
    'wellness':   {'r': (180, 255), 'g': (0, 60),    'b': (0, 60)},
    'strategic':  {'r': (0, 40),    'g': (0, 40),     'b': (0, 40)},
}

def match_color(r, g, b, ranges):
    return (ranges['r'][0] <= r <= ranges['r'][1] and
            ranges['g'][0] <= g <= ranges['g'][1] and
            ranges['b'][0] <= b <= ranges['b'][1])

zone_px = {z: [] for z in zone_colors}
for y in range(zh):
    for x in range(zw):
        p = pixels[x, y]
        r, g, b, a = p[0], p[1], p[2], p[3] if len(p) > 3 else 255
        if a < 128 or (r > 240 and g > 240 and b > 240):
            continue
        for zone, ranges in zone_colors.items():
            if match_color(r, g, b, ranges):
                zone_px[zone].append((x, y))
                break

for z, pts in zone_px.items():
    print(f"  {z}: {len(pts)} pixels")

# ============================================================
# Step 4: Extract outlines using angle sweep
# ============================================================
def get_outline(pixel_list, n_angles=180):
    if len(pixel_list) < 10:
        return []
    cx = sum(p[0] for p in pixel_list) / len(pixel_list)
    cy = sum(p[1] for p in pixel_list) / len(pixel_list)

    angle_pts = {}
    for x, y in pixel_list:
        angle = math.atan2(y - cy, x - cx)
        step = math.pi / n_angles
        deg = round(angle / step) * step
        dist = math.sqrt((x-cx)**2 + (y-cy)**2)
        if deg not in angle_pts or dist > angle_pts[deg][1]:
            angle_pts[deg] = ((x, y), dist)

    sorted_angles = sorted(angle_pts.keys())
    return [angle_pts[a][0] for a in sorted_angles]

def simplify(points, epsilon=3):
    if len(points) <= 3:
        return points
    def perp_dist(pt, s, e):
        dx, dy = e[0]-s[0], e[1]-s[1]
        d = math.sqrt(dx*dx + dy*dy)
        if d == 0:
            return math.sqrt((pt[0]-s[0])**2 + (pt[1]-s[1])**2)
        return abs(dy*pt[0] - dx*pt[1] + e[0]*s[1] - e[1]*s[0]) / d
    def rdp(pts, eps):
        if len(pts) <= 2:
            return pts
        dmax, idx = 0, 0
        for i in range(1, len(pts)-1):
            d = perp_dist(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            return rdp(pts[:idx+1], eps)[:-1] + rdp(pts[idx:], eps)
        return [pts[0], pts[-1]]
    return rdp(points, epsilon)

# ============================================================
# Step 5: Transform and output SVG coordinates
# ============================================================
print("\n=== SVG Polygon Points (viewBox 0 0 1024 1424) ===\n")
results = {}
for zone in zone_colors:
    px_list = zone_px[zone]
    if len(px_list) < 10:
        print(f"  {zone}: too few pixels, skipping")
        continue
    outline = get_outline(px_list, n_angles=180)
    simplified = simplify(outline, epsilon=8)

    transformed = []
    for x, y in simplified:
        mx, my = apply_transform( x, y)
        mx = max(0, min(1024, mx))
        my = max(0, min(1424, my))
        transformed.append((round(mx), round(my)))

    results[zone] = transformed
    pts_str = " ".join(f"{p[0]},{p[1]}" for p in transformed)
    print(f"<!-- {zone.upper()} -->")
    print(f'points="{pts_str}"')
    print()

# ============================================================
# Step 6: Debug visualization on masterplan
# ============================================================
mp = Image.open('assets/masterplan-zones.jpg').convert('RGBA')
overlay = Image.new('RGBA', mp.size, (0,0,0,0))
draw = ImageDraw.Draw(overlay)

fills = {
    'family': (255,140,0,60), 'premium': (128,0,128,60),
    'green-area': (0,150,255,60), 'luxury': (255,215,0,60),
    'together': (160,160,160,60), 'wellness': (220,20,60,60),
    'strategic': (40,40,40,60)
}
strokes = {
    'family': (255,140,0,200), 'premium': (128,0,128,200),
    'green-area': (0,150,255,200), 'luxury': (255,215,0,200),
    'together': (160,160,160,200), 'wellness': (220,20,60,200),
    'strategic': (40,40,40,200)
}

for zone, pts in results.items():
    if len(pts) >= 3:
        draw.polygon(pts, fill=fills[zone], outline=strokes[zone])

composite = Image.alpha_composite(mp, overlay)
composite.convert('RGB').save('debug_zones.jpg', quality=90)
print("Saved debug_zones.jpg")

with open('zone_coordinates.json', 'w') as f:
    json.dump({z: [list(p) for p in pts] for z, pts in results.items()}, f, indent=2)
print("Saved zone_coordinates.json")
