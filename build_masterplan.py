"""Build a contour-rendered masterplan base from a KML polygon.

Default pipeline (simple, open-source):
  1. Parse KML  -> polygon (lon, lat) + bbox
  2. Fetch OpenTopoMap raster tiles covering the bbox (CC-BY-SA, no API key)
  3. Mosaic, crop to bbox, dim outside parcel, draw parcel outline
  4. Add scale bar + north arrow + attribution
  5. Write masterplan_base.png + masterplan_bounds.json (geo metadata)

OpenTopoMap is an open-source contour map built on OpenStreetMap data + SRTM
elevation, so we don't render terrain ourselves — we just composite their tiles.
Tile usage policy: <= a few thousand tiles/day, attribution required.
"""

import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).parent
KML_PATH = ROOT / "assets" / "rv1.kml"
OUT_DIR = ROOT / "assets" / "masterplan"
OUT_DIR.mkdir(exist_ok=True)

ZOOM = 17           # OpenTopoMap maxes at z=17; ESRI satellite goes to z=19
PAD_FRAC = 0.06     # bbox padding around the parcel
TARGET_WIDTH = 3000 # output width in px (height auto from terrain aspect)
USER_AGENT = "riverland-masterplan/1.0 (https://riverlandbynlc) python-requests"

# Hypsometric tint: gradient color between contour lines, derived from DEM
HYPSO_BLEND = 0.65          # 0..1 — strength of color tint over the OTM base
HYPSO_DEM_ZOOM = 14         # AWS Terrarium tile zoom for the elevation source
HYPSO_SMOOTH_SIGMA = 1.5    # Gaussian blur on elevation grid (in DEM pixels)
# After tint we multiply the OTM raster on top with this strength so brown
# contour lines / roads / labels remain crisp through the gradient.
HYPSO_OTM_MULT = 0.80       # 0..1 — strength of OTM-multiply pass on top
HYPSO_PALETTE = [           # (norm 0..1, R, G, B)
    (0.00,  90, 145,  85),  # deep green (lowest)
    (0.25, 175, 200, 110),  # meadow / wheat
    (0.50, 230, 210, 140),  # warm sand
    (0.75, 200, 155,  95),  # tan
    (1.00, 150,  95,  60),  # dark umber (highest)
]

# Layers to render.  Each writes its own PNG; same bounds metadata.
LAYERS = [
    {"key": "contour",    "provider": "opentopomap", "zoom": 17,
     "filename": "masterplan_contour.png",    "tint": (255, 247, 220), "tint_blend": 0.05,
     "outline_color": (190, 130, 30, 255), "hypsometric": True},
    {"key": "satellite",  "provider": "esri_world_imagery", "zoom": 18,
     "filename": "masterplan_satellite.png",  "tint": None,            "tint_blend": 0,
     "outline_color": (255, 220, 90, 255), "hypsometric": False},
]

PROVIDERS = {
    "opentopomap": {
        "url": "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
        "max_zoom": 17,
        "attribution": "© OpenTopoMap (CC-BY-SA) · OpenStreetMap contributors",
    },
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "max_zoom": 19,
        "attribution": "© OpenStreetMap contributors",
    },
    "esri_world_imagery": {
        # ESRI World Imagery — note y,x order in path
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "max_zoom": 19,
        "attribution": "Imagery © Esri, Maxar, Earthstar Geographics & the GIS Community",
    },
}

TS = 256


# ---------- KML ----------
def parse_kml(path: Path):
    txt = path.read_text(encoding="utf-8")
    m = re.search(r"<coordinates>([\s\S]*?)</coordinates>", txt)
    if not m:
        raise SystemExit("No <coordinates> found in KML")
    pts = []
    for tok in m.group(1).split():
        parts = tok.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))  # lon, lat
    return pts


# ---------- Web Mercator tile math ----------
def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


# ---------- Tile fetch ----------
def fetch_tile(prov_key, z, x, y, retries=3):
    p = PROVIDERS[prov_key]
    url = p["url"].format(z=z, x=x, y=y)
    headers = {"User-Agent": USER_AGENT, "Referer": "https://riverlandbynlc"}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
            last_err = f"HTTP {r.status_code}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.6 + attempt * 0.4)
    raise RuntimeError(f"tile {z}/{x}/{y} failed: {last_err}")


# ---------- DEM (terrarium) for hypsometric tint ----------
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

def _terrarium_to_elev(img: Image.Image) -> np.ndarray:
    a = np.asarray(img, dtype=np.float32)
    return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0


def fetch_dem_grid(minlon, minlat, maxlon, maxlat, z=HYPSO_DEM_ZOOM):
    """Return (elev_grid, geo_bounds) where geo_bounds is (mlon0, mlat1, mlon1, mlat0)."""
    x0f, y1f = lonlat_to_tile(minlon, minlat, z)
    x1f, y0f = lonlat_to_tile(maxlon, maxlat, z)
    tx0, tx1 = int(math.floor(x0f)), int(math.ceil(x1f))
    ty0, ty1 = int(math.floor(y0f)), int(math.ceil(y1f))
    nx, ny = tx1 - tx0, ty1 - ty0
    print(f"  DEM tiles z={z}: {nx}x{ny}={nx*ny}")
    mosaic = np.empty((ny * TS, nx * TS), dtype=np.float32)
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            url = TERRARIUM_URL.format(z=z, x=tx, y=ty)
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            mosaic[j*TS:(j+1)*TS, i*TS:(i+1)*TS] = _terrarium_to_elev(img)
    mlon0, mlat1 = tile_to_lonlat(tx0, ty0, z)
    mlon1, mlat0 = tile_to_lonlat(tx1, ty1, z)
    return mosaic, (mlon0, mlat1, mlon1, mlat0)


def hypsometric_rgb(elev: np.ndarray) -> np.ndarray:
    """Map elevation -> per-pixel RGB using HYPSO_PALETTE."""
    e_min, e_max = float(elev.min()), float(elev.max())
    e = (elev - e_min) / max(1e-6, e_max - e_min)
    h, w = elev.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    pal = HYPSO_PALETTE
    for i in range(len(pal) - 1):
        s0, r0, g0, b0 = pal[i]
        s1, r1, g1, b1 = pal[i + 1]
        m = (e >= s0) & (e <= s1 + 1e-9)
        t = (e[m] - s0) / max(1e-9, s1 - s0)
        rgb[..., 0][m] = r0 + (r1 - r0) * t
        rgb[..., 1][m] = g0 + (g1 - g0) * t
        rgb[..., 2][m] = b0 + (b1 - b0) * t
    return rgb, (e_min, e_max)


# ---------- Polygon mask ----------
def polygon_mask(poly_px, w, h):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon(poly_px, fill=255)
    return np.asarray(m) > 0


# ---------- Map furniture ----------
def _font(size):
    for name in ("seguibold.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _nice_round(meters):
    exp = math.floor(math.log10(max(1, meters)))
    base = 10 ** exp
    for m in (5, 2, 1):
        v = m * base
        if v <= meters:
            return v
    return base


def draw_scale_bar(img: Image.Image, W: int, H: int, span_x_m: float):
    m_per_px = span_x_m / W
    target_m = _nice_round(span_x_m * 0.18)
    bar_px = int(round(target_m / m_per_px))
    segments = 4
    seg_px = bar_px // segments
    bar_h = max(12, H // 220)
    pad = max(24, H // 70)
    label_h = max(14, H // 130)
    fnt = _font(label_h)

    plate_pad_x = 16
    plate_pad_top = 14
    plate_pad_bottom = label_h + 10
    x0, y0 = pad, H - pad - bar_h - plate_pad_bottom

    d = ImageDraw.Draw(img)
    plate = (
        x0 - plate_pad_x, y0 - plate_pad_top,
        x0 + bar_px + plate_pad_x, y0 + bar_h + plate_pad_bottom,
    )
    d.rectangle(plate, fill=(255, 255, 255, 235), outline=(40, 30, 20), width=1)

    for i in range(segments):
        col = (30, 25, 20) if i % 2 == 0 else (255, 255, 255)
        d.rectangle((x0 + i * seg_px, y0, x0 + (i + 1) * seg_px, y0 + bar_h),
                    fill=col, outline=(30, 25, 20))

    for k in range(segments + 1):
        v = int(round(target_m * k / segments))
        label = f"{v} m" if k == segments else str(v)
        x = x0 + k * seg_px
        tw = d.textlength(label, font=fnt)
        d.text((x - tw / 2, y0 + bar_h + 4), label, font=fnt, fill=(30, 25, 20))


def draw_north_arrow(img: Image.Image, W: int, H: int):
    pad = max(24, H // 50)
    R = max(40, H // 50)
    cx, cy = W - pad - R, pad + R + 10
    d = ImageDraw.Draw(img)
    d.ellipse((cx - R - 6, cy - R - 6, cx + R + 6, cy + R + 6),
              fill=(255, 255, 255, 235), outline=(40, 30, 20), width=2)
    tip = (cx, cy - R + 8)
    left = (cx - R * 0.5, cy + R - 10)
    right = (cx + R * 0.5, cy + R - 10)
    base = (cx, cy + 4)
    d.polygon([tip, right, base], fill=(180, 30, 30))
    d.polygon([tip, left, base], fill=(60, 50, 40))
    fnt = _font(max(16, R // 2))
    tw = d.textlength("N", font=fnt)
    d.text((cx - tw / 2, cy - R - fnt.size - 4), "N", font=fnt, fill=(30, 25, 20))


def draw_attribution(img: Image.Image, W: int, H: int, text: str):
    d = ImageDraw.Draw(img)
    fnt = _font(max(11, H // 200))
    tw = d.textlength(text, font=fnt)
    pad = 6
    x = W - tw - pad - 6
    y = H - fnt.size - pad - 4
    d.rectangle((x - 4, y - 2, x + tw + 4, y + fnt.size + 2),
                fill=(255, 255, 255, 200))
    d.text((x, y), text, font=fnt, fill=(40, 30, 20))


def render_layer(layer, poly_lonlat, padded_bbox, dem_cache=None):
    """Render one layer (provider+zoom) and write it to disk.
    Returns (target_w, target_h, span_x_m, span_y_m, c_bounds_lonlat, meta).
    dem_cache: optional dict to memoize the DEM grid across layers.
    """
    minlon, minlat, maxlon, maxlat = padded_bbox
    prov_key = layer["provider"]
    p = PROVIDERS[prov_key]
    z = min(layer["zoom"], p["max_zoom"])

    x0f, y1f = lonlat_to_tile(minlon, minlat, z)  # SW
    x1f, y0f = lonlat_to_tile(maxlon, maxlat, z)  # NE (y inverted)
    tx0, tx1 = int(math.floor(x0f)), int(math.ceil(x1f))
    ty0, ty1 = int(math.floor(y0f)), int(math.ceil(y1f))
    nx, ny = tx1 - tx0, ty1 - ty0
    total = nx * ny
    print(f"\n[{layer['key']}] provider={prov_key}  z={z}  tiles "
          f"x[{tx0}..{tx1}) y[{ty0}..{ty1})  ({nx}x{ny}={total})")

    mosaic = Image.new("RGBA", (nx * TS, ny * TS), (240, 240, 235, 255))
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            sys.stdout.write(f"\r  fetching {j*nx+i+1}/{total}  z/{tx}/{ty}    ")
            sys.stdout.flush()
            try:
                tile = fetch_tile(prov_key, z, tx, ty)
            except Exception as exc:
                print(f"\n  WARN: {exc}; using blank")
                tile = Image.new("RGBA", (TS, TS), (240, 240, 235, 255))
            mosaic.paste(tile, (i * TS, j * TS))
            time.sleep(0.05)
    print()

    mlon0, mlat1 = tile_to_lonlat(tx0, ty0, z)
    mlon1, mlat0 = tile_to_lonlat(tx1, ty1, z)

    W, H = mosaic.size
    cx0 = max(0, int(math.floor((minlon - mlon0) / (mlon1 - mlon0) * W)))
    cx1 = min(W, int(math.ceil((maxlon - mlon0) / (mlon1 - mlon0) * W)))
    cy0 = max(0, int(math.floor((mlat1 - maxlat) / (mlat1 - mlat0) * H)))
    cy1 = min(H, int(math.ceil((mlat1 - minlat) / (mlat1 - mlat0) * H)))
    cropped = mosaic.crop((cx0, cy0, cx1, cy1))
    c_minlon = mlon0 + cx0 / W * (mlon1 - mlon0)
    c_maxlon = mlon0 + cx1 / W * (mlon1 - mlon0)
    c_maxlat = mlat1 - cy0 / H * (mlat1 - mlat0)
    c_minlat = mlat1 - cy1 / H * (mlat1 - mlat0)

    lat_mid = (c_minlat + c_maxlat) / 2
    span_x_m = (c_maxlon - c_minlon) * 111320 * math.cos(math.radians(lat_mid))
    span_y_m = (c_maxlat - c_minlat) * 110540
    target_w = TARGET_WIDTH
    target_h = int(round(target_w * span_y_m / span_x_m))
    print(f"  render {target_w}x{target_h}  ({span_x_m:.0f}m x {span_y_m:.0f}m)")
    base = cropped.resize((target_w, target_h), Image.LANCZOS).convert("RGBA")

    def lonlat_to_render_px(lon, lat):
        x = (lon - c_minlon) / (c_maxlon - c_minlon) * target_w
        y = (c_maxlat - lat) / (c_maxlat - c_minlat) * target_h
        return (x, y)

    poly_px = [lonlat_to_render_px(lon, lat) for lon, lat in poly_lonlat]
    inside = polygon_mask(poly_px, target_w, target_h)

    arr = np.asarray(base).astype(np.float32)
    out_mask = ~inside
    gray = arr[..., :3].mean(axis=-1, keepdims=True)
    arr[..., :3] = np.where(
        out_mask[..., None],
        (arr[..., :3] * 0.55 + gray * 0.20),
        arr[..., :3],
    )
    arr[..., :3] = np.clip(arr[..., :3], 0, 255)

    if layer.get("tint"):
        inside_arr = arr[..., :3].copy()
        tint = np.array(layer["tint"], dtype=np.float32)
        blend = layer["tint_blend"]
        inside_arr = inside_arr * (1 - blend) + tint * blend
        arr[..., :3] = np.where(inside[..., None], inside_arr, arr[..., :3])

    # ---- Hypsometric tint (gradient between contour lines) ----
    elev_min = elev_max = None
    if layer.get("hypsometric"):
        if dem_cache is None or "elev" not in dem_cache:
            print("  fetching DEM for hypsometric tint")
            dem, dem_geo = fetch_dem_grid(minlon, minlat, maxlon, maxlat)
            if dem_cache is not None:
                dem_cache["elev"] = dem
                dem_cache["geo"] = dem_geo
        else:
            dem, dem_geo = dem_cache["elev"], dem_cache["geo"]

        # Crop the DEM to the OUR rendered crop's geo bounds
        dmlon0, dmlat1, dmlon1, dmlat0 = dem_geo
        dh, dw = dem.shape
        def _xpx(lon): return (lon - dmlon0) / (dmlon1 - dmlon0) * dw
        def _ypy(lat): return (dmlat1 - lat) / (dmlat1 - dmlat0) * dh
        dx0 = max(0, int(math.floor(_xpx(c_minlon))))
        dx1 = min(dw, int(math.ceil(_xpx(c_maxlon))))
        dy0 = max(0, int(math.floor(_ypy(c_maxlat))))
        dy1 = min(dh, int(math.ceil(_ypy(c_minlat))))
        elev_crop = dem[dy0:dy1, dx0:dx1]
        # Resize DEM crop to match the rendered base
        elev_img = Image.fromarray(elev_crop)
        elev_r = np.asarray(
            elev_img.resize((target_w, target_h), Image.BICUBIC),
            dtype=np.float32,
        )
        elev_r = gaussian_filter(elev_r, sigma=HYPSO_SMOOTH_SIGMA)

        rgb_hyp, (elev_min, elev_max) = hypsometric_rgb(elev_r)
        # Step 1: blend hypsometric color over the OTM base
        b = HYPSO_BLEND
        otm_inside = arr[..., :3].copy()  # snapshot before tint
        blended = otm_inside * (1 - b) + rgb_hyp * b
        # Step 2: multiply the original OTM raster on top so contour lines /
        # roads / labels remain visible through the tint.
        # multiply: result = blended * (otm/255).  Lerp by HYPSO_OTM_MULT so
        # we keep some saturation in light areas.
        otm_norm = otm_inside / 255.0
        mult = blended * otm_norm
        m = HYPSO_OTM_MULT
        composited = blended * (1 - m) + mult * m
        arr[..., :3] = np.where(inside[..., None], composited, arr[..., :3])
        arr[..., :3] = np.clip(arr[..., :3], 0, 255)
        print(f"  hypsometric + OTM-multiply applied  (elev {elev_min:.0f}–{elev_max:.0f} m)")

    composed = Image.fromarray(arr.astype(np.uint8))

    odraw = ImageDraw.Draw(composed)
    odraw.line(poly_px + [poly_px[0]], fill=layer["outline_color"], width=5)

    draw_north_arrow(composed, target_w, target_h)
    draw_scale_bar(composed, target_w, target_h, span_x_m)
    draw_attribution(composed, target_w, target_h, p["attribution"])

    out_png = OUT_DIR / layer["filename"]
    composed.convert("RGB").save(out_png, "PNG", optimize=True)
    print(f"  wrote {out_png}")

    meta = {"zoom": z, "provider": prov_key, "attribution": p["attribution"]}
    if elev_min is not None:
        meta["elevMin"] = float(elev_min)
        meta["elevMax"] = float(elev_max)
    return (target_w, target_h, span_x_m, span_y_m,
            (c_minlon, c_minlat, c_maxlon, c_maxlat),
            meta)


def main():
    poly_lonlat = parse_kml(KML_PATH)
    lons = [p[0] for p in poly_lonlat]
    lats = [p[1] for p in poly_lonlat]
    minlon, maxlon = min(lons), max(lons)
    minlat, maxlat = min(lats), max(lats)
    dlon = maxlon - minlon
    dlat = maxlat - minlat
    minlon -= dlon * PAD_FRAC
    maxlon += dlon * PAD_FRAC
    minlat -= dlat * PAD_FRAC
    maxlat += dlat * PAD_FRAC
    print(f"Polygon: {len(poly_lonlat)} pts, bbox padded: "
          f"lon[{minlon:.5f},{maxlon:.5f}] lat[{minlat:.5f},{maxlat:.5f}]")

    dem_cache = {}
    layer_results = []
    for layer in LAYERS:
        layer_results.append((layer, render_layer(layer, poly_lonlat,
                                                  (minlon, minlat, maxlon, maxlat),
                                                  dem_cache=dem_cache)))

    # All layers share the SAME crop logic (driven by padded bbox), so their
    # geo bounds are identical to within sub-pixel rounding. Use the first.
    _, (tw, th, sxm, sym, cb, meta) = layer_results[0]
    c_minlon, c_minlat, c_maxlon, c_maxlat = cb

    bounds = {
        "minLon": c_minlon, "maxLon": c_maxlon,
        "minLat": c_minlat, "maxLat": c_maxlat,
        "width": tw, "height": th,
        "polygon": [{"lon": lon, "lat": lat} for lon, lat in poly_lonlat],
        "spanXMeters": sxm, "spanYMeters": sym,
        "layers": [
            {"key": l[0]["key"], "filename": l[0]["filename"], **l[1][5]}
            for l in layer_results
        ],
    }
    (OUT_DIR / "masterplan_bounds.json").write_text(json.dumps(bounds, indent=2))
    # Mirror as a JS file so the editor works opened directly via file:// (no fetch needed)
    js_path = OUT_DIR / "masterplan_bounds.js"
    js_path.write_text("window.MASTERPLAN_BOUNDS = " + json.dumps(bounds) + ";\n")
    print(f"\nWrote {OUT_DIR / 'masterplan_bounds.json'}")
    print(f"Wrote {js_path}")


if __name__ == "__main__":
    main()
