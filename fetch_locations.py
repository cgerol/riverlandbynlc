import json, urllib.request, urllib.parse

# Map projection: same as coast_to_svg.py
W, E, N, S = 32.84, 33.46, 34.82, 34.55
VW, VH = 1000, 562

def to_svg(lon, lat):
    x = (lon - W) / (E - W) * VW
    y = (N - lat) / (N - S) * VH
    return round(x, 1), round(y, 1)

# === Overpass queries for different location types ===
API = "https://overpass-api.de/api/interpreter"
bbox = f"{S},{W},{N},{E}"

# Query 1: A1 motorway within our bounds
q_highway = f"""
[out:json][timeout:25];
way["ref"="A1"]["highway"="motorway"]({bbox});
out body; >; out skel qt;
"""

# Query 2: Key POIs - hospitals, ports, hotels
q_pois = f"""
[out:json][timeout:25];
(
  node["amenity"="hospital"]({bbox});
  way["amenity"="hospital"]({bbox});
  node["tourism"="hotel"]({bbox});
  way["tourism"="hotel"]({bbox});
  node["man_made"="lighthouse"]({bbox});
  node["leisure"="marina"]({bbox});
  way["leisure"="marina"]({bbox});
  node["harbour"="yes"]({bbox});
  way["landuse"="port"]({bbox});
  node["aeroway"="aerodrome"](34.4,32.3,35.2,33.8);
);
out center;
"""

# Query 3: Motorway junctions / exits
q_junctions = f"""
[out:json][timeout:25];
node["highway"="motorway_junction"]({bbox});
out body;
"""

def fetch(query, label):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(API, data)
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    print(f"\n=== {label} ({len(result['elements'])} elements) ===")
    return result["elements"]

# --- Fetch Junctions ---
junctions = fetch(q_junctions, "MOTORWAY JUNCTIONS")
for el in junctions:
    name = el.get("tags", {}).get("name", el.get("tags", {}).get("ref", "?"))
    lon, lat = el["lon"], el["lat"]
    sx, sy = to_svg(lon, lat)
    if 0 <= sx <= 1000 and 0 <= sy <= 562:
        print(f"  Junction: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})  [{lat:.4f}, {lon:.4f}]")

# --- Fetch POIs ---
pois = fetch(q_pois, "POIs (hospitals, hotels, marina, ports, airports)")
hotels = []
hospitals = []
marinas = []
airports = []
ports = []
for el in pois:
    tags = el.get("tags", {})
    name = tags.get("name", tags.get("name:en", "?"))
    if "center" in el:
        lon, lat = el["center"]["lon"], el["center"]["lat"]
    elif "lon" in el:
        lon, lat = el["lon"], el["lat"]
    else:
        continue
    sx, sy = to_svg(lon, lat)

    amenity = tags.get("amenity", "")
    tourism = tags.get("tourism", "")
    leisure = tags.get("leisure", "")
    aeroway = tags.get("aeroway", "")
    landuse = tags.get("landuse", "")
    harbour = tags.get("harbour", "")

    if aeroway == "aerodrome":
        airports.append((name, sx, sy, lon, lat))
        print(f"  Airport: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})")
    elif amenity == "hospital" and 0 <= sx <= 1000:
        hospitals.append((name, sx, sy))
        print(f"  Hospital: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})")
    elif tourism == "hotel" and 0 <= sx <= 1000 and 0 <= sy <= 562:
        hotels.append((name, sx, sy))
        print(f"  Hotel: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})")
    elif leisure == "marina" and 0 <= sx <= 1000:
        marinas.append((name, sx, sy))
        print(f"  Marina: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})")
    elif landuse == "port" or harbour == "yes":
        if 0 <= sx <= 1000:
            ports.append((name, sx, sy))
            print(f"  Port: {name:30s} → SVG({sx:6.1f}, {sy:6.1f})")

# --- Fetch A1 highway ---
hw_elements = fetch(q_highway, "A1 MOTORWAY")
nodes = {}
ways = []
for el in hw_elements:
    if el["type"] == "node":
        nodes[el["id"]] = (el["lon"], el["lat"])
    elif el["type"] == "way":
        ways.append(el)

print("\n=== A1 HIGHWAY PATH (sampled points) ===")
all_hw_pts = []
for w in ways:
    for nid in w.get("nodes", []):
        if nid in nodes:
            lon, lat = nodes[nid]
            sx, sy = to_svg(lon, lat)
            if 0 <= sx <= 1000 and 0 <= sy <= 562:
                all_hw_pts.append((sx, sy, lon, lat))

# Sort by x
all_hw_pts.sort(key=lambda p: p[0])
# Sample every Nth point
step = max(1, len(all_hw_pts) // 30)
sampled = all_hw_pts[::step]
if all_hw_pts and sampled[-1] != all_hw_pts[-1]:
    sampled.append(all_hw_pts[-1])

hw_path_parts = []
for i, (sx, sy, lon, lat) in enumerate(sampled):
    prefix = "M" if i == 0 else "L"
    hw_path_parts.append(f"{prefix} {sx},{sy}")

print(f"Total A1 points in bounds: {len(all_hw_pts)}")
print(f"Sampled: {len(sampled)} points")
print(f"SVG path: {' '.join(hw_path_parts)}")

# --- Summary of key locations for the map ---
print("\n\n=== SUMMARY: KEY LOCATIONS FOR MAP ===")
# Filter notable hotels (> 3 stars, known names)
notable_hotels = [h for h in hotels if any(k in h[0].lower() for k in ['four season', 'amathus', 'raphael', 'mediterranean', 'parklane', 'park lane', 'elysium', 'crowne', 'holiday inn', 'hilton', 'atlantica', 'columbia'])]
if not notable_hotels:
    notable_hotels = sorted(hotels, key=lambda h: h[1])[:8]  # just take first 8 by position

print("\nNotable Hotels:")
for name, sx, sy in notable_hotels:
    print(f"  {name:35s} → ({sx}, {sy})")

print("\nHospitals:")
for name, sx, sy in hospitals:
    print(f"  {name:35s} → ({sx}, {sy})")

print("\nMarinas:")
for name, sx, sy in marinas:
    print(f"  {name:35s} → ({sx}, {sy})")

print("\nPorts:")
for name, sx, sy in ports:
    print(f"  {name:35s} → ({sx}, {sy})")

print("\nAirports:")
for name, sx, sy, lon, lat in airports:
    print(f"  {name:35s} → ({sx}, {sy}) [{'ON MAP' if 0<=sx<=1000 and 0<=sy<=562 else 'OFF MAP'}]")
