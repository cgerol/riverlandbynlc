"""Convert the architect's Rhino-exported OBJ into a web-ready GLB.

  - Loads `assets/3d export.obj` (in Cyprus Local Transverse Mercator coords)
  - Re-centers the model so the project is at world origin
  - Drops Y so the ground sits at Y=0
  - Exports as `assets/masterplan/masterplan.glb` (binary glTF, ~3-10× smaller)

Run:  python build_masterplan_glb.py
"""

from pathlib import Path
import sys
import trimesh
import numpy as np

SRC = Path("assets/3d export.obj")
DST = Path("assets/masterplan/masterplan.glb")


def main():
    if not SRC.exists():
        print(f"ERROR: missing {SRC}")
        sys.exit(1)

    print(f"Loading {SRC}  ({SRC.stat().st_size//1024//1024} MB)...")
    scene = trimesh.load(str(SRC), force="scene")

    # Get bounding box of the entire scene
    bounds = scene.bounds  # [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    size = bounds[1] - bounds[0]
    print(f"Bounds: min={bounds[0]} max={bounds[1]}")
    print(f"Size:   {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} m")

    # Translation to center the project at origin (XZ plane).  Y kept so the
    # lowest point of the model sits at Y=0 (ground level).
    cx = (bounds[0][0] + bounds[1][0]) / 2
    cz = (bounds[0][2] + bounds[1][2]) / 2
    cy = bounds[0][1]   # lowest Y -> 0
    T = np.eye(4)
    T[0, 3] = -cx
    T[1, 3] = -cy
    T[2, 3] = -cz
    scene.apply_transform(T)

    print("After centering:")
    print(f"  bounds min={scene.bounds[0]}")
    print(f"  bounds max={scene.bounds[1]}")

    DST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Exporting {DST}...")
    scene.export(str(DST))
    print(f"Wrote {DST}  ({DST.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
