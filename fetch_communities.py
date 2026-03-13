"""
Fetch administrative community boundaries around Pyrgos Limassol from OSM Overpass API.
Converts boundary polygons to SVG coordinates matching the project's map projection.

This script queries the Overpass API for each community relation and outputs SVG paths.
Run: python fetch_communities.py > communities.svg
"""
import json, urllib.request, urllib.parse, sys, time

W, E, N, S = 32.84, 33.46, 34.82, 34.55
VW, VH = 1000, 562

def to_svg(lon, lat):
    x = (lon - W) / (E - W) * VW
    y = (N - lat) / (N - S) * VH
    return round(x, 1), round(y, 1)

API = "https://overpass-api.de/api/interpreter"

COMMUNITIES = {
    "Pyrgos":       {"rel_id": 13033863, "greek": "Πύργος Λεμεσού", "color": "#e8d5b7"},
    "Moni":         {"rel_id": 13036131, "greek": "Μόνη",           "color": "#d4e8c7"},
    "Parekklisia":  {"rel_id": 8433097,  "greek": "Παρεκκλησιά",    "color": "#c7dae8"},
    "Mouttayiaka":  {"rel_id": 8422878,  "greek": "Μουτταγιάκα",    "color": "#e8c7d4"},
    "Agios Tychon": {"rel_id": 8430116,  "greek": "Άγιος Τύχων",    "color": "#d4c7e8"},
    "Armenochori":  {"rel_id": 8432091,  "greek": "Αμαθούντα Αρμενοχώρι", "color": "#e8e0c7"},
    "Foinikaria":   {"rel_id": 8432350,  "greek": "Αμαθούντα Φοινικάρια", "color": "#c7e8d4"},
    "Akrounta":     {"rel_id": 8438116,  "greek": "Αμαθούντα Ακρούντα",   "color": "#e8c7c7"},
    "Monagrouli":   {"rel_id": 13036323, "greek": "Μοναγρούλι",     "color": "#c7e8e8"},
}

def fetch_overpass(query, label=""):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(API, data)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        return result.get("elements", [])
    except Exception as e:
        print(f"[{label}] Error: {e}", file=sys.stderr)
        return []

def _close(p1, p2, tol=0.0005):
    return abs(p1[0]-p2[0]) < tol and abs(p1[1]-p2[1]) < tol

def assemble_polygon(relation):
    outer_ways = []
    for member in relation.get("members", []):
        role = member.get("role", "")
        if role == "outer" and member.get("type") == "way" and "geometry" in member:
            coords = [(g["lon"], g["lat"]) for g in member["geometry"]]
            outer_ways.append(coords)
    if not outer_ways:
        for member in relation.get("members", []):
            if member.get("type") == "way" and "geometry" in member:
                coords = [(g["lon"], g["lat"]) for g in member["geometry"]]
                outer_ways.append(coords)
    if not outer_ways:
        return None

    ring = list(outer_ways[0])
    remaining = list(outer_ways[1:])
    for _ in range(len(remaining) * 3 + 10):
        if not remaining:
            break
        found = False
        for i, way in enumerate(remaining):
            if _close(ring[-1], way[0]):
                ring.extend(way[1:]); remaining.pop(i); found = True; break
            elif _close(ring[-1], way[-1]):
                ring.extend(list(reversed(way))[1:]); remaining.pop(i); found = True; break
            elif _close(ring[0], way[-1]):
                ring = list(way[:-1]) + ring; remaining.pop(i); found = True; break
            elif _close(ring[0], way[0]):
                ring = list(reversed(way))[:-1] + ring; remaining.pop(i); found = True; break
        if not found:
            break
    return ring

def centroid(coords):
    cx = sum(p[0] for p in coords) / len(coords)
    cy = sum(p[1] for p in coords) / len(coords)
    return (round(cx, 1), round(cy, 1))

def simplify(coords, n=100):
    if len(coords) <= n:
        return coords
    step = max(1, len(coords) // n)
    r = coords[::step]
    if coords[-1] != r[-1]:
        r.append(coords[-1])
    return r

# Fetch and process
community_data = {}
for name, info in COMMUNITIES.items():
    rel_id = info["rel_id"]
    print(f"Fetching {name} ({rel_id})...", file=sys.stderr)
    elems = fetch_overpass(f"[out:json][timeout:30];rel({rel_id});out geom;", name)
    for el in elems:
        if el.get("type") == "relation" and "members" in el:
            poly = assemble_polygon(el)
            if poly and len(poly) >= 3:
                community_data[name] = poly
                print(f"  {name}: {len(poly)} points", file=sys.stderr)
            break
    time.sleep(2)

# Output
print("<!-- Community boundary polygons from OSM Overpass API -->")
print(f"<!-- {len(community_data)} communities found -->")
print()

for name in sorted(community_data.keys()):
    poly = community_data[name]
    s = simplify(poly, 100)
    pts = [to_svg(lon, lat) for lon, lat in s]
    cx, cy = centroid(pts)
    path = f"M {pts[0][0]},{pts[0][1]} " + " ".join(f"L {x},{y}" for x, y in pts[1:]) + " Z"
    fill = COMMUNITIES[name]["color"]
    css_id = name.lower().replace(" ", "-")
    greek = COMMUNITIES[name]["greek"]

    print(f"<!-- {name} ({greek}): {len(s)} pts, centroid=({cx},{cy}) -->")
    print(f'<path class="community-boundary" id="community-{css_id}"')
    print(f'  d="{path}"')
    print(f'  fill="{fill}" fill-opacity="0.3" stroke="#8b7355" stroke-width="0.8" stroke-opacity="0.6" />')
    print()

print("\n<!-- Community labels -->")
for name in sorted(community_data.keys()):
    poly = community_data[name]
    s = simplify(poly, 100)
    pts = [to_svg(lon, lat) for lon, lat in s]
    cx, cy = centroid(pts)
    greek = COMMUNITIES[name]["greek"]
    print(f'<text x="{cx}" y="{cy}" text-anchor="middle" font-size="7" fill="#5a4a3a" font-weight="500" font-family="sans-serif" opacity="0.8">{name}</text>')
    print(f'<text x="{cx}" y="{cy+9}" text-anchor="middle" font-size="5" fill="#7a6a5a" font-style="italic" font-family="sans-serif" opacity="0.7">{greek}</text>')

print(f"\nDone: {', '.join(sorted(community_data.keys()))}", file=sys.stderr)
