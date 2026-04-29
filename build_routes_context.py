"""Render a wide-area painterly contour map covering the parcel + all
surrounding route KMLs. Used as the background for the Routes modal in
destination.html.

Output: assets/masterplan/routes_context.png
        assets/masterplan/routes_context.json (geo bounds for SVG overlay)
"""

import io
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

# Reuse our local helpers from build_masterplan.py by reimporting if useful;
# but keep this script self-contained for clarity.

ROOT = Path(__file__).parent
KML_DIR = ROOT / "assets" / "kml"
OUT_DIR = ROOT / "assets" / "masterplan"
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "riverland-routes-context/1.0"
ZOOM = 15        # broad coverage; OTM goes to z=17 but z=15 keeps tile count modest
TARGET_W = 2400
PAD_FRAC = 0.05
HYPSO_BLEND = 0.55
HYPSO_OTM_MULT = 0.78
HYPSO_DEM_ZOOM = 13   # wider DEM coverage

OTM_URL = "https://a.tile.opentopomap.org/{z}/{x}/{y}.png"
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

PALETTE = [
    (0.00,  90, 145,  85),
    (0.25, 175, 200, 110),
    (0.50, 230, 210, 140),
    (0.75, 200, 155,  95),
    (1.00, 150,  95,  60),
]


def parse_kml_coords(path: Path):
    txt = path.read_text(encoding="utf-8")
    pts = []
    for blk in re.findall(r"<coordinates>([\s\S]*?)</coordinates>", txt):
        for tok in blk.split():
            parts = tok.split(",")
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
    return pts


def collect_bbox():
    all_pts = []
    for p in KML_DIR.glob("*.kml"):
        all_pts.extend(parse_kml_coords(p))
    if not all_pts:
        raise SystemExit("No KMLs found in " + str(KML_DIR))
    lons = [p[0] for p in all_pts]
    lats = [p[1] for p in all_pts]
    return min(lons), min(lats), max(lons), max(lats)


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


def fetch_image_tile(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def fetch_otm_mosaic(minlon, minlat, maxlon, maxlat, z):
    x0f, y1f = lonlat_to_tile(minlon, minlat, z)
    x1f, y0f = lonlat_to_tile(maxlon, maxlat, z)
    tx0, tx1 = int(math.floor(x0f)), int(math.ceil(x1f))
    ty0, ty1 = int(math.floor(y0f)), int(math.ceil(y1f))
    nx, ny = tx1 - tx0, ty1 - ty0
    print(f"OTM tiles z={z}: {nx}x{ny}={nx*ny}")
    TS = 256
    mosaic = Image.new("RGBA", (nx * TS, ny * TS), (240, 240, 235, 255))
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            sys.stdout.write(f"\r  {j*nx+i+1}/{nx*ny}")
            sys.stdout.flush()
            try:
                tile = fetch_image_tile(OTM_URL.format(z=z, x=tx, y=ty))
                mosaic.paste(tile, (i * TS, j * TS))
            except Exception as exc:
                print(f"\n  WARN tile {z}/{tx}/{ty}: {exc}")
            time.sleep(0.05)
    print()
    mlon0, mlat1 = tile_to_lonlat(tx0, ty0, z)
    mlon1, mlat0 = tile_to_lonlat(tx1, ty1, z)
    return mosaic, (mlon0, mlat1, mlon1, mlat0)


def fetch_dem(minlon, minlat, maxlon, maxlat, z=HYPSO_DEM_ZOOM):
    x0f, y1f = lonlat_to_tile(minlon, minlat, z)
    x1f, y0f = lonlat_to_tile(maxlon, maxlat, z)
    tx0, tx1 = int(math.floor(x0f)), int(math.ceil(x1f))
    ty0, ty1 = int(math.floor(y0f)), int(math.ceil(y1f))
    nx, ny = tx1 - tx0, ty1 - ty0
    print(f"DEM tiles z={z}: {nx}x{ny}")
    TS = 256
    mosaic = np.empty((ny * TS, nx * TS), dtype=np.float32)
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            sys.stdout.write(f"\r  {j*nx+i+1}/{nx*ny}")
            sys.stdout.flush()
            r = requests.get(TERRARIUM_URL.format(z=z, x=tx, y=ty), timeout=30,
                             headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            a = np.asarray(img, dtype=np.float32)
            mosaic[j*TS:(j+1)*TS, i*TS:(i+1)*TS] = (
                a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0
            )
    print()
    mlon0, mlat1 = tile_to_lonlat(tx0, ty0, z)
    mlon1, mlat0 = tile_to_lonlat(tx1, ty1, z)
    return mosaic, (mlon0, mlat1, mlon1, mlat0)


def hypsometric(elev):
    e_min, e_max = float(elev.min()), float(elev.max())
    e = (elev - e_min) / max(1e-6, e_max - e_min)
    h, w = elev.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    for k in range(len(PALETTE) - 1):
        s0, r0, g0, b0 = PALETTE[k]
        s1, r1, g1, b1 = PALETTE[k + 1]
        m = (e >= s0) & (e <= s1 + 1e-9)
        t = (e[m] - s0) / max(1e-9, s1 - s0)
        rgb[..., 0][m] = r0 + (r1 - r0) * t
        rgb[..., 1][m] = g0 + (g1 - g0) * t
        rgb[..., 2][m] = b0 + (b1 - b0) * t
    return rgb, e_min, e_max


def main():
    minlon, minlat, maxlon, maxlat = collect_bbox()
    dlon = maxlon - minlon
    dlat = maxlat - minlat
    minlon -= dlon * PAD_FRAC; maxlon += dlon * PAD_FRAC
    minlat -= dlat * PAD_FRAC; maxlat += dlat * PAD_FRAC
    print(f"KML bbox padded: lon[{minlon:.5f},{maxlon:.5f}] lat[{minlat:.5f},{maxlat:.5f}]")

    mosaic, (mlon0, mlat1, mlon1, mlat0) = fetch_otm_mosaic(minlon, minlat, maxlon, maxlat, ZOOM)
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
    cw, ch = cropped.size

    lat_mid = (c_minlat + c_maxlat) / 2
    span_x_m = (c_maxlon - c_minlon) * 111320 * math.cos(math.radians(lat_mid))
    span_y_m = (c_maxlat - c_minlat) * 110540
    target_w = TARGET_W
    target_h = int(round(target_w * span_y_m / span_x_m))
    base = cropped.resize((target_w, target_h), Image.LANCZOS).convert("RGBA")
    print(f"Render: {target_w}x{target_h} ({span_x_m:.0f}m x {span_y_m:.0f}m)")

    # Hypsometric tint
    dem, dem_geo = fetch_dem(minlon, minlat, maxlon, maxlat)
    dmlon0, dmlat1, dmlon1, dmlat0 = dem_geo
    dh, dw = dem.shape
    dx0 = max(0, int(math.floor((c_minlon - dmlon0) / (dmlon1 - dmlon0) * dw)))
    dx1 = min(dw, int(math.ceil((c_maxlon - dmlon0) / (dmlon1 - dmlon0) * dw)))
    dy0 = max(0, int(math.floor((dmlat1 - c_maxlat) / (dmlat1 - dmlat0) * dh)))
    dy1 = min(dh, int(math.ceil((dmlat1 - c_minlat) / (dmlat1 - dmlat0) * dh)))
    elev_crop = dem[dy0:dy1, dx0:dx1]
    elev_r = np.asarray(
        Image.fromarray(elev_crop).resize((target_w, target_h), Image.BICUBIC),
        dtype=np.float32,
    )
    elev_r = gaussian_filter(elev_r, sigma=1.5)
    rgb_hyp, e_min, e_max = hypsometric(elev_r)
    arr = np.asarray(base).astype(np.float32)
    blended = arr[..., :3] * (1 - HYPSO_BLEND) + rgb_hyp * HYPSO_BLEND
    otm_norm = arr[..., :3] / 255.0
    composited = blended * (1 - HYPSO_OTM_MULT) + (blended * otm_norm) * HYPSO_OTM_MULT
    arr[..., :3] = np.clip(composited, 0, 255)
    composed = Image.fromarray(arr.astype(np.uint8))

    # Soft vignette so the edges fade into the page
    W2, H2 = composed.size
    vignette = Image.new("L", (W2, H2), 255)
    vd = ImageDraw.Draw(vignette)
    for r in range(120):
        a = int(255 * (1 - r / 120))
        vd.rectangle((r, r, W2 - r, H2 - r), outline=a)
    vignette = vignette.filter(__import__('PIL.ImageFilter', fromlist=['ImageFilter']).GaussianBlur(40))

    out_path = OUT_DIR / "routes_context.png"
    composed.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"Wrote {out_path}")

    bounds = {
        "minLon": c_minlon, "maxLon": c_maxlon,
        "minLat": c_minlat, "maxLat": c_maxlat,
        "width": target_w, "height": target_h,
        "spanXMeters": span_x_m, "spanYMeters": span_y_m,
        "elevMin": float(e_min), "elevMax": float(e_max),
    }
    (OUT_DIR / "routes_context.json").write_text(json.dumps(bounds, indent=2))
    (OUT_DIR / "routes_context.js").write_text(
        "window.ROUTES_CONTEXT = " + json.dumps(bounds) + ";\n"
    )
    print(f"Wrote {OUT_DIR / 'routes_context.json'}")


if __name__ == "__main__":
    main()
