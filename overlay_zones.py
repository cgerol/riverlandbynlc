"""Warp the painted zones image onto the HD masterplan using homography,
then detect zone outlines directly in HD pixel coordinates."""

from PIL import Image, ImageDraw
import math, json

def compute_homography(src_pts, dst_pts):
    n = len(src_pts)
    mat = [[0]*8 for _ in range(2*n)]
    rhs = [0]*(2*n)
    for i in range(n):
        x, y = src_pts[i]; u, v = dst_pts[i]
        mat[2*i] = [-x, -y, -1, 0, 0, 0, u*x, u*y]
        rhs[2*i] = -u
        mat[2*i+1] = [0, 0, 0, -x, -y, -1, v*x, v*y]
        rhs[2*i+1] = -v
    aug = [mat[i]+[rhs[i]] for i in range(2*n)]
    for col in range(min(8, 2*n)):
        mx, mr = abs(aug[col][col]), col
        for r in range(col+1, 2*n):
            if abs(aug[r][col]) > mx: mx, mr = abs(aug[r][col]), r
        aug[col], aug[mr] = aug[mr], aug[col]
        if abs(aug[col][col]) < 1e-10: continue
        for r in range(col+1, 2*n):
            f = aug[r][col] / aug[col][col]
            for j in range(col, 9): aug[r][j] -= f * aug[col][j]
    h = [0]*8
    for i in range(7, -1, -1):
        if abs(aug[i][i]) < 1e-10: continue
        h[i] = aug[i][8]
        for j in range(i+1, 8): h[i] -= aug[i][j] * h[j]
        h[i] /= aug[i][i]
    return [[h[0],h[1],h[2]], [h[3],h[4],h[5]], [h[6],h[7],1.0]]

def apply_H(H, x, y):
    w = H[2][0]*x + H[2][1]*y + H[2][2]
    if abs(w) < 1e-10: return (0, 0)
    return ((H[0][0]*x + H[0][1]*y + H[0][2])/w, (H[1][0]*x + H[1][1]*y + H[1][2])/w)

def invert_H(H):
    """Invert 3x3 homography matrix."""
    a,b,c = H[0]; d,e,f = H[1]; g,h,i = H[2]
    det = a*(e*i-f*h) - b*(d*i-f*g) + c*(d*h-e*g)
    if abs(det) < 1e-10: return None
    inv = [
        [(e*i-f*h)/det, (c*h-b*i)/det, (b*f-c*e)/det],
        [(f*g-d*i)/det, (a*i-c*g)/det, (c*d-a*f)/det],
        [(d*h-e*g)/det, (b*g-a*h)/det, (a*e-b*d)/det]
    ]
    return inv

def flood_regions(pset, min_sz=30):
    visited = set(); regions = []
    for s in pset:
        if s in visited: continue
        r = set(); q = [s]
        while q:
            p = q.pop()
            if p in visited: continue
            visited.add(p); r.add(p)
            x,y = p
            for nx,ny in [(x+1,y),(x-1,y),(x,y+1),(x,y-1),(x+1,y+1),(x-1,y-1),(x+1,y-1),(x-1,y+1)]:
                if (nx,ny) in pset and (nx,ny) not in visited: q.append((nx,ny))
        if len(r)>=min_sz: regions.append(r)
    regions.sort(key=len, reverse=True)
    return regions

def contour(pset, step=3):
    rows = {}
    for x,y in pset:
        if y not in rows: rows[y]=[x,x]
        else: rows[y][0]=min(rows[y][0],x); rows[y][1]=max(rows[y][1],x)
    sr = sorted(rows)
    left = [(rows[y][0],y) for y in sr[::step]]
    right = [(rows[y][1],y) for y in sr[::-step]]
    return left + right

def simplify(pts, tol=5):
    if len(pts)<3: return pts
    def pd(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        if dx==0 and dy==0: return math.sqrt((p[0]-a[0])**2+(p[1]-a[1])**2)
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
        return math.sqrt((p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2)
    md,mi=0,0
    for i in range(1,len(pts)-1):
        d=pd(pts[i],pts[0],pts[-1])
        if d>md: md,mi=d,i
    if md>tol:
        l=simplify(pts[:mi+1],tol); r=simplify(pts[mi:],tol)
        return l[:-1]+r
    return [pts[0],pts[-1]]

def main():
    painted = Image.open('assets/masterplan zones - low res.jpeg').convert('RGB')
    pw, ph = painted.size
    hd = Image.open('assets/masterplan-zones.jpg').convert('RGB')
    hw, hh = hd.size
    print(f"Painted: {pw}x{ph}, HD: {hw}x{hh}")

    # Homography: painted -> HD (cropped)
    src = [(540,460), (140,1070), (755,1050), (845,500)]
    dst = [(500,85),  (175,1180), (650,1250), (770,260)]
    H = compute_homography(src, dst)
    H_inv = invert_H(H)

    # Warp painted image onto HD coordinate space
    print("Warping painted image onto HD...")
    warped = Image.new('RGBA', (hw, hh), (0,0,0,0))
    p_px = painted.load()
    w_px = warped.load()

    for y in range(hh):
        for x in range(hw):
            # Map HD pixel back to painted image
            sx, sy = apply_H(H_inv, x, y)
            sx, sy = int(sx), int(sy)
            if 0 <= sx < pw and 0 <= sy < ph:
                r, g, b = p_px[sx, sy]
                w_px[x, y] = (r, g, b, 180)  # semi-transparent

    warped.save('warped_overlay.png')
    print("Saved warped_overlay.png")

    # Create composite: HD + warped overlay
    composite = hd.copy().convert('RGBA')
    composite = Image.alpha_composite(composite, warped)
    composite.convert('RGB').save('composite_overlay.jpg', quality=90)
    print("Saved composite_overlay.jpg")

    # Now detect zones in the WARPED image (which is in HD coordinates)
    print("\nDetecting zones in warped image...")
    w_rgb = warped.convert('RGB')

    zones = {
        'family': {
            'colors': [(255,140,0),(255,165,0),(230,120,0),(255,120,0),(200,100,0),
                       (220,130,20),(240,150,30),(210,110,10),(180,90,0),(250,130,10),(190,80,0)],
            'threshold': 65
        },
        'premium': {
            'colors': [(80,0,120),(100,0,150),(60,0,100),(75,0,130),(90,10,140),
                       (50,0,90),(70,20,120),(110,0,160),(55,5,95),(85,15,135),(65,0,110)],
            'threshold': 60
        },
        'luxury': {
            'colors': [(255,255,0),(240,240,0),(220,220,0),(255,230,0),(200,200,0),
                       (230,230,10),(250,250,20),(210,210,30)],
            'threshold': 55
        },
        'wellness': {
            'colors': [(220,20,20),(200,0,0),(180,20,20),(255,0,0),(200,30,30),
                       (170,10,10),(230,40,40),(160,0,0)],
            'threshold': 55
        },
        'strategic': {
            'colors': [(0,0,0),(20,20,20),(30,30,30),(10,10,10),(40,40,40)],
            'threshold': 30
        },
        'green-area': {
            'colors': [(0,100,255),(0,120,255),(0,80,220),(30,100,230),(0,150,255),
                       (50,120,240),(20,90,210),(0,70,200),(10,110,240)],
            'threshold': 65
        },
    }

    w_data = list(w_rgb.getdata())
    results = {}

    for name, cfg in zones.items():
        print(f"\n--- {name.upper()} ---")
        matches = set()
        for y in range(hh):
            for x in range(hw):
                # Only process pixels that have content (from warped overlay)
                if warped.load()[x, y][3] < 50:  # skip transparent
                    continue
                p = w_data[y*hw+x]
                for c in cfg['colors']:
                    if math.sqrt(sum((a-b)**2 for a,b in zip(p,c))) < cfg['threshold']:
                        matches.add((x,y)); break

        print(f"  Pixels: {len(matches)}")
        if len(matches) < 30: continue

        regions = flood_regions(matches, 25)
        if not regions: continue

        for i,r in enumerate(regions[:3]):
            xs=[p[0] for p in r]; ys=[p[1] for p in r]
            print(f"  R{i}: {len(r)}px ({min(xs)},{min(ys)})-({max(xs)},{max(ys)})")

        use = regions[0]
        c = contour(use, step=2)
        s = simplify(c, tol=6)
        print(f"  Points: {len(c)} -> {len(s)}")

        # Clamp to image bounds
        s = [(max(0,min(hw-1,x)), max(0,min(hh-1,y))) for x,y in s]
        ps = ' '.join(f'{x},{y}' for x,y in s)
        results[name] = ps
        print(f"  -> {ps[:120]}...")

    # Create debug image with zones drawn on HD
    debug = hd.copy()
    draw = ImageDraw.Draw(debug, 'RGBA')
    clrs = {
        'family':(255,140,0,60), 'premium':(128,0,128,60), 'luxury':(255,215,0,60),
        'wellness':(220,20,60,60), 'strategic':(40,40,40,60), 'green-area':(0,150,255,60)
    }
    for name, ps in results.items():
        pts = [(int(x),int(y)) for x,y in (p.split(',') for p in ps.split())]
        if name in clrs and len(pts)>=3:
            draw.polygon(pts, fill=clrs[name], outline=clrs.get(name,(255,255,255,200))[:3])
    debug.save('debug_zones.jpg', quality=90)

    print("\n\n========== SVG POLYGON POINTS ==========\n")
    for name in ['family','premium','luxury','green-area','wellness','strategic']:
        if name in results:
            print(f'<!-- {name.upper()} -->')
            print(f'points="{results[name]}"')
        else:
            print(f'<!-- {name.upper()} - NOT DETECTED -->')
        print()

    with open('zone_coordinates.json','w') as f:
        json.dump(results, f, indent=2)

if __name__=='__main__':
    main()
