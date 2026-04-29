"""Export 3D-scene assets for the Three.js masterplan viewer.

Pipeline:
  1. Parse rv1.kml -> parcel polygon + padded bbox
  2. Fetch AWS Terrarium DEM tiles, build elevation grid
  3. Save heightmap as 1024x1024 grayscale PNG (normalized elev->0..255)
  4. Query OpenStreetMap (Overpass API) for roads, buildings, trees,
     water within the bbox
  5. Emit scene.json + scene.js (the latter so the viewer works under file://)

Output: assets/masterplan/3d/
  heightmap.png
  scene.json
  scene.js  (window.MASTERPLAN_SCENE = {...})
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
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).parent
KML_PATH = ROOT / "assets" / "rv1.kml"
OUT_DIR = ROOT / "assets" / "masterplan" / "3d"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAD_FRAC = 0.18                # extra padding so the scene has horizon context
DEM_ZOOM = 15                  # AWS Terrarium tile zoom (max 15 globally)
HEIGHTMAP_SIZE = 1024          # px (square), oversampled from DEM via Lanczos
ELEV_SMOOTH_SIGMA = 1.0        # post-resample smoothing on the heightmap
USER_AGENT = "riverland-3d-builder/1.0"
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


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
            pts.append((float(parts[0]), float(parts[1])))
    return pts


# ---------- Web Mercator ----------
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


# ---------- DEM ----------
def fetch_dem(minlon, minlat, maxlon, maxlat, z=DEM_ZOOM):
    x0f, y1f = lonlat_to_tile(minlon, minlat, z)
    x1f, y0f = lonlat_to_tile(maxlon, maxlat, z)
    tx0, tx1 = int(math.floor(x0f)), int(math.ceil(x1f))
    ty0, ty1 = int(math.floor(y0f)), int(math.ceil(y1f))
    nx, ny = tx1 - tx0, ty1 - ty0
    print(f"DEM tiles z={z}: {nx}x{ny}={nx*ny}")
    TS = 256
    mosaic = np.empty((ny * TS, nx * TS), dtype=np.float32)
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            sys.stdout.write(f"\r  fetching DEM {j*nx+i+1}/{nx*ny}")
            sys.stdout.flush()
            url = TERRARIUM_URL.format(z=z, x=tx, y=ty)
            r = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
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


def crop_and_resample(elev, mosaic_geo, target_bbox, size):
    """Crop the DEM mosaic to target_bbox and resample to (size, size)."""
    mlon0, mlat1, mlon1, mlat0 = mosaic_geo
    minlon, minlat, maxlon, maxlat = target_bbox
    H, W = elev.shape
    cx0 = max(0, int(math.floor((minlon - mlon0) / (mlon1 - mlon0) * W)))
    cx1 = min(W, int(math.ceil((maxlon - mlon0) / (mlon1 - mlon0) * W)))
    cy0 = max(0, int(math.floor((mlat1 - maxlat) / (mlat1 - mlat0) * H)))
    cy1 = min(H, int(math.ceil((mlat1 - minlat) / (mlat1 - mlat0) * H)))
    crop = elev[cy0:cy1, cx0:cx1]
    img = Image.fromarray(crop)
    resized = np.asarray(img.resize((size, size), Image.LANCZOS), dtype=np.float32)
    return gaussian_filter(resized, sigma=ELEV_SMOOTH_SIGMA)


# ---------- Overpass (OSM) ----------
def fetch_osm(minlon, minlat, maxlon, maxlat):
    q = f"""
[out:json][timeout:60];
(
  way["highway"]({minlat},{minlon},{maxlat},{maxlon});
  way["building"]({minlat},{minlon},{maxlat},{maxlon});
  way["leisure"]({minlat},{minlon},{maxlat},{maxlon});
  way["landuse"]({minlat},{minlon},{maxlat},{maxlon});
  way["natural"]({minlat},{minlon},{maxlat},{maxlon});
  way["waterway"]({minlat},{minlon},{maxlat},{maxlon});
  node["natural"="tree"]({minlat},{minlon},{maxlat},{maxlon});
);
out geom;
"""
    print("Querying Overpass…")
    r = requests.post(OVERPASS_URL, data={"data": q},
                      headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    data = r.json()

    roads, buildings, trees, water, vegetation = [], [], [], [], []
    for el in data.get("elements", []):
        if el["type"] == "node" and el.get("tags", {}).get("natural") == "tree":
            trees.append({"lon": el["lon"], "lat": el["lat"]})
        elif el["type"] == "way":
            tags = el.get("tags", {})
            geom = el.get("geometry", [])
            if not geom:
                continue
            pts = [[g["lon"], g["lat"]] for g in geom]
            if "highway" in tags:
                roads.append({"points": pts, "kind": tags["highway"], "name": tags.get("name", "")})
            elif "building" in tags:
                buildings.append({"points": pts, "kind": tags.get("building", "yes")})
            elif tags.get("natural") in ("water", "wood", "scrub", "tree_row"):
                if tags["natural"] == "water":
                    water.append({"points": pts})
                else:
                    vegetation.append({"points": pts, "kind": tags["natural"]})
            elif tags.get("waterway"):
                water.append({"points": pts, "kind": tags["waterway"]})
            elif tags.get("landuse") in ("vineyard", "orchard", "farmland", "forest", "grass", "meadow"):
                vegetation.append({"points": pts, "kind": tags["landuse"]})
            elif tags.get("leisure") in ("park", "garden", "pitch"):
                vegetation.append({"points": pts, "kind": tags["leisure"]})

    print(f"  roads={len(roads)}  buildings={len(buildings)}  trees={len(trees)} "
          f" water={len(water)}  vegetation={len(vegetation)}")
    return {"roads": roads, "buildings": buildings, "trees": trees,
            "water": water, "vegetation": vegetation}


# ---------- Main ----------
def main():
    poly_lonlat = parse_kml(KML_PATH)
    lons = [p[0] for p in poly_lonlat]
    lats = [p[1] for p in poly_lonlat]
    minlon, maxlon = min(lons), max(lons)
    minlat, maxlat = min(lats), max(lats)
    dlon, dlat = maxlon - minlon, maxlat - minlat
    bb = (minlon - dlon * PAD_FRAC, minlat - dlat * PAD_FRAC,
          maxlon + dlon * PAD_FRAC, maxlat + dlat * PAD_FRAC)
    print(f"Padded bbox: lon[{bb[0]:.5f},{bb[2]:.5f}] lat[{bb[1]:.5f},{bb[3]:.5f}]")

    # 1. DEM heightmap
    elev_mosaic, mosaic_geo = fetch_dem(*bb)
    elev = crop_and_resample(elev_mosaic, mosaic_geo, bb, HEIGHTMAP_SIZE)
    e_min, e_max = float(elev.min()), float(elev.max())
    print(f"Heightmap {HEIGHTMAP_SIZE}x{HEIGHTMAP_SIZE}  elev {e_min:.1f}–{e_max:.1f} m")

    # Save heightmap as 16-bit PNG (encoded as RG: R = high byte, G = low byte)
    norm = (elev - e_min) / max(1e-6, e_max - e_min)
    h16 = np.clip((norm * 65535).round(), 0, 65535).astype(np.uint16)
    rgb = np.zeros((HEIGHTMAP_SIZE, HEIGHTMAP_SIZE, 3), dtype=np.uint8)
    rgb[..., 0] = (h16 >> 8).astype(np.uint8)   # high byte
    rgb[..., 1] = (h16 & 0xFF).astype(np.uint8) # low byte
    Image.fromarray(rgb, "RGB").save(OUT_DIR / "heightmap.png", optimize=True)

    # 2. OSM features
    try:
        osm = fetch_osm(*bb)
    except Exception as exc:
        print(f"OSM fetch failed: {exc}; using empty scene")
        osm = {"roads": [], "buildings": [], "trees": [], "water": [], "vegetation": []}

    # 3. Compose scene metadata
    lat_mid = (bb[1] + bb[3]) / 2
    span_x_m = (bb[2] - bb[0]) * 111320 * math.cos(math.radians(lat_mid))
    span_y_m = (bb[3] - bb[1]) * 110540
    scene = {
        "bounds": {
            "minLon": bb[0], "minLat": bb[1], "maxLon": bb[2], "maxLat": bb[3],
            "spanXMeters": span_x_m, "spanYMeters": span_y_m,
        },
        "elev": {"min": e_min, "max": e_max,
                 "encoding": "rg16", "size": HEIGHTMAP_SIZE},
        "parcel": [{"lon": lon, "lat": lat} for lon, lat in poly_lonlat],
        "osm": osm,
    }
    (OUT_DIR / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    (OUT_DIR / "scene.js").write_text(
        "window.MASTERPLAN_SCENE = " + json.dumps(scene) + ";\n", encoding="utf-8"
    )
    print(f"Wrote {OUT_DIR/'heightmap.png'}")
    print(f"Wrote {OUT_DIR/'scene.json'}")
    print(f"Wrote {OUT_DIR/'scene.js'}")
    print(f"Terrain {span_x_m:.0f} m × {span_y_m:.0f} m")


if __name__ == "__main__":
    main()
