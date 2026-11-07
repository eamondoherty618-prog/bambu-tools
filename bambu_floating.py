"""Find floating regions in a print-oriented mesh the way a slicer sees them: slice the STL at every layer, and flag any
island whose footprint does not touch the layer below (first layer excluded). Studio's "object has floating regions"
warning is exactly this; the output says WHERE, which Studio only shows by clicking through the preview.
    bambu-floating PART.stl [--layer 0.30] [--xy 0.05]
--xy is how far an island may overhang the layer below and still count as supported (a 45 deg overhang at 0.3 layers is
0.3; keep it small - the point is to catch islands, not overhangs). Exit 1 if any floating island is found."""
import sys, argparse, numpy as np, trimesh
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

def layer_polys(mesh, z):
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return []
    # a FIXED frame for every layer: to_2D() alone fits its own frame per section (it mirrored alternate layers)
    planar, _ = sec.to_2D(to_2D=trimesh.geometry.plane_transform([0, 0, z], [0, 0, 1]))
    out = []
    for p in planar.polygons_full:
        if p.area > 0.02:
            out.append(p)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl"); ap.add_argument("--layer", type=float, default=0.30); ap.add_argument("--xy", type=float, default=0.05)
    a = ap.parse_args()
    m = trimesh.load(a.stl, force="mesh")
    z0, z1 = m.bounds[0][2], m.bounds[1][2]
    m.apply_translation([0, 0, -z0]); z1 -= z0
    b = m.bounds; print(f"  mesh x {b[0][0]:.2f}..{b[1][0]:.2f}  y {b[0][1]:.2f}..{b[1][1]:.2f}  (z moved to start at 0)")
    n = int(np.ceil(z1 / a.layer))
    below = None; bad = []
    for i in range(n):
        z = min((i + 0.5) * a.layer, z1 - 1e-3)
        polys = layer_polys(m, z)
        if i > 0 and polys:
            sup = unary_union(below).buffer(a.xy) if below else None
            for p in polys:
                if sup is None or not p.intersects(sup):
                    b = p.bounds
                    bad.append((i + 1, z, p.area, b))
        below = polys
    print(f"{a.stl}: {n} layers at {a.layer} mm, z 0..{z1:.2f}")
    if not bad:
        print("  no floating islands"); return 0
    print(f"  {len(bad)} floating island(s):")
    for layer, z, area, b in bad:
        print(f"    layer {layer:4d} z {z:6.2f}  area {area:6.2f} mm2  x {b[0]:7.2f}..{b[2]:7.2f}  y {b[1]:7.2f}..{b[3]:7.2f}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
