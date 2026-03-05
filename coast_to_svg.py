import json, math

with open('C:/Users/const/riverlandbynlc/osm_coast.json') as f:
    data = json.load(f)

W, E = 32.84, 33.46
N, S = 34.82, 34.55

def to_svg(lon, lat):
    x = (lon - W) / (E - W) * 1000
    y = (N - lat) / (N - S) * 562
    return round(x, 1), round(y, 1)

def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

# Get all ways with coordinates
ways = []
for el in data.get('elements', []):
    if 'geometry' in el and len(el['geometry']) >= 3:
        coords = [(g['lon'], g['lat']) for g in el['geometry']]
        ways.append(coords)

print(f"Total ways: {len(ways)}")

# Chain ways using nearest-endpoint matching with tolerance
TOLERANCE = 0.001  # ~100m

def chain_all():
    remaining = list(range(len(ways)))
    chains = []

    while remaining:
        # Start a new chain with the first remaining way
        idx = remaining.pop(0)
        chain = list(ways[idx])
        changed = True

        while changed:
            changed = False
            chain_start = chain[0]
            chain_end = chain[-1]

            best_append = None
            best_append_dist = TOLERANCE
            best_prepend = None
            best_prepend_dist = TOLERANCE

            for i, ri in enumerate(remaining):
                w = ways[ri]
                w_start = w[0]
                w_end = w[-1]

                # Can we append this way? (chain_end matches w_start)
                d = dist(chain_end, w_start)
                if d < best_append_dist:
                    best_append_dist = d
                    best_append = (i, False)  # not reversed

                # chain_end matches w_end -> append reversed
                d = dist(chain_end, w_end)
                if d < best_append_dist:
                    best_append_dist = d
                    best_append = (i, True)

                # Can we prepend? (chain_start matches w_end)
                d = dist(chain_start, w_end)
                if d < best_prepend_dist:
                    best_prepend_dist = d
                    best_prepend = (i, False)

                # chain_start matches w_start -> prepend reversed
                d = dist(chain_start, w_start)
                if d < best_prepend_dist:
                    best_prepend_dist = d
                    best_prepend = (i, True)

            if best_append is not None:
                idx_in_remaining, reverse = best_append
                ri = remaining.pop(idx_in_remaining)
                w = ways[ri]
                if reverse:
                    w = list(reversed(w))
                chain.extend(w[1:])
                changed = True
            elif best_prepend is not None:
                idx_in_remaining, reverse = best_prepend
                ri = remaining.pop(idx_in_remaining)
                w = ways[ri]
                if reverse:
                    w = list(reversed(w))
                chain = w + chain[1:]
                changed = True

        chains.append(chain)

    return chains

chains = chain_all()
chains.sort(key=lambda c: -len(c))

for i, c in enumerate(chains[:5]):
    lon_range = (min(p[0] for p in c), max(p[0] for p in c))
    lat_range = (min(p[1] for p in c), max(p[1] for p in c))
    svg_x = (to_svg(lon_range[0], 34.7)[0], to_svg(lon_range[1], 34.7)[0])
    print(f"Chain {i}: {len(c)} pts, lon {lon_range[0]:.4f}-{lon_range[1]:.4f} (SVG x {svg_x[0]:.0f}-{svg_x[1]:.0f})")

# Use the longest chain that spans most of the map
main_chain = chains[0]

# If other chains extend the range, merge them
for c in chains[1:]:
    if len(c) >= 20:
        c_min_lon = min(p[0] for p in c)
        c_max_lon = max(p[0] for p in c)
        main_min = min(p[0] for p in main_chain)
        main_max = max(p[0] for p in main_chain)
        # If this chain extends beyond the main chain
        if c_max_lon > main_max + 0.01 or c_min_lon < main_min - 0.01:
            # Append or prepend
            if c_min_lon > main_max - 0.02:
                main_chain = main_chain + c
            elif c_max_lon < main_min + 0.02:
                main_chain = c + main_chain

print(f"\nMerged chain: {len(main_chain)} points")
svg_range = (to_svg(min(p[0] for p in main_chain), 34.7)[0],
             to_svg(max(p[0] for p in main_chain), 34.7)[0])
print(f"SVG X range: {svg_range[0]:.0f} - {svg_range[1]:.0f}")

# Simplify to ~100 points
total = len(main_chain)
step = max(1, total // 100)
simplified = main_chain[::step]
if main_chain[-1] not in simplified:
    simplified.append(main_chain[-1])

svg_pts = [to_svg(lon, lat) for lon, lat in simplified]

# Output coastline path
parts = [f"M {svg_pts[0][0]},{svg_pts[0][1]}"]
for x, y in svg_pts[1:]:
    parts.append(f"L {x},{y}")

print(f"\n=== COASTLINE ({len(svg_pts)} pts) ===")
print(" ".join(parts))

# Land path
last = svg_pts[-1]
first = svg_pts[0]
lp = [f"M 0,0 L 1000,0 L 1000,{last[1]}"]
for x, y in reversed(svg_pts):
    lp.append(f"L {x},{y}")
lp.append(f"L 0,{first[1]} Z")
print(f"\n=== LAND PATH ===")
print(" ".join(lp))

print("\n=== LOCATIONS ===")
for name, lon, lat in [
    ("Cape Gata", 32.958, 34.572), ("Lady's Mile", 33.005, 34.625),
    ("Limassol", 33.040, 34.670), ("Marina", 33.050, 34.667),
    ("Dasoudi", 33.087, 34.690), ("Germasogeia", 33.110, 34.700),
    ("Ag.Tychonas", 33.140, 34.705), ("Pyrgos", 33.120, 34.735),
    ("Gov.Beach", 33.230, 34.710), ("Mari", 33.300, 34.722),
    ("Zygi", 33.337, 34.725),
]:
    sx, sy = to_svg(lon, lat)
    print(f"  {name}: ({sx}, {sy})")
