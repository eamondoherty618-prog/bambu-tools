#!/usr/bin/env python3
"""
bambu-calibrate: dial a specific spool in for dead-on fits and clean flow.
Generate a small test, print it, measure it with calipers, and the correction is
stored (calibration.json) so every future slice of that material applies it.

  bambu-calibrate fit  --material PETG                       # slice the fit test
  bambu-calibrate fit  --material PETG --nominal 6 --measured 5.86
  bambu-calibrate flow --material PETG                       # slice single-wall box
  bambu-calibrate flow --material PETG --measured 0.46       # measured wall thickness
  bambu-calibrate temp --material PETG --low 230 --high 260  # slice a temp tower
  bambu-calibrate temp --material PETG --set 245
  bambu-calibrate show [--material PETG]
"""
import argparse, os, sys, shutil, tempfile
import numpy as np, trimesh
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bambu_optimize as bo
import materials as M

OUT = os.path.expanduser("~/bambu-tools/sliced")
LINE_WIDTH = 0.42   # nozzle line width; single-wall target thickness

def slice_test(mesh, ov, mat, name):
    d = tempfile.mkdtemp(prefix="bambu_cal_")
    est = bo.orca_slice(mesh, ov, mat, "0.20", d, apply_cal=False)  # raw baseline
    if not est:
        sys.exit("slice failed (is OrcaSlicer installed?)")
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, name); shutil.copy(est["gcode"], dest)
    return dest, est

# ---------------- FIT (hole/peg dimensional accuracy) ----------------
HOLES = [3, 4, 5, 6, 8, 10]
def fit_model():
    plate = trimesh.creation.box((70, 30, 5)); plate.apply_translation((0, 0, 2.5))
    cuts = []
    for d, x in zip(HOLES, np.linspace(-28, 28, len(HOLES))):
        c = trimesh.creation.cylinder(radius=d/2, height=20, sections=max(48, int(d*16)))
        c.apply_translation((x, 0, 2.5)); cuts.append(c)
    return trimesh.boolean.difference([plate] + cuts)

def do_fit(a):
    if a.measured is None:
        dest, est = slice_test(fit_model(), {"enable_support": "0"}, a.material, f"CAL_fit_{a.material}.gcode")
        print(f"Fit test sliced -> {dest}   ({est['time']}, ~{est['grams']:.0f} g)")
        print(f"Print it, then caliper the holes. Left->right (mm): {', '.join(map(str, HOLES))}")
        print(f"Re-run with one hole:  bambu-calibrate fit --material {a.material} --nominal 6 --measured <caliper>")
        return
    comp = max(-0.5, min(0.5, round((a.nominal - a.measured) / 2, 3)))   # radial; + enlarges holes
    bo.save_calibration(a.material, xy_hole_compensation=comp)
    verb = "enlarge" if comp > 0 else "shrink"
    print(f"{a.material}: {a.nominal} mm hole printed {a.measured} mm -> xy_hole_compensation {comp:+.3f} "
          f"({verb} holes {abs(comp)*2:.2f} mm). Saved - future slices apply it automatically.")

# ---------------- FLOW (extrusion multiplier) ----------------
def flow_model():
    return trimesh.creation.box((25, 25, 8))
def do_flow(a):
    if a.measured is None:
        ov = {"wall_loops": "1", "top_shell_layers": "0", "bottom_shell_layers": "0",
              "sparse_infill_density": "0%", "enable_support": "0"}
        dest, est = slice_test(flow_model(), ov, a.material, f"CAL_flow_{a.material}.gcode")
        print(f"Flow test (single-wall box) sliced -> {dest}   ({est['time']})")
        print(f"Print it, caliper the WALL thickness (target {LINE_WIDTH} mm - average a few spots).")
        print(f"Re-run:  bambu-calibrate flow --material {a.material} --measured <caliper>")
        return
    cur = bo.load_calibration().get(a.material, {}).get("flow_ratio")
    if cur is None:
        fil = bo.orca_flatten("filament", bo.ORCA_FILAMENT[a.material]).get("filament_flow_ratio", ["0.98"])
        cur = float(fil[0])
    new = round(cur * LINE_WIDTH / a.measured, 3)
    bo.save_calibration(a.material, flow_ratio=new)
    print(f"{a.material}: wall {a.measured} mm vs {LINE_WIDTH} mm target -> flow_ratio {cur:.3f} -> {new:.3f}. Saved.")

# ---------------- TEMP (temperature tower) ----------------
def inject_temps(gcode, temps, band_mm=10):
    out, band = [], -1
    for line in gcode.splitlines(keepends=True):
        out.append(line)
        if line.startswith("; Z_HEIGHT:"):
            b = int(float(line.split(":")[1]) // band_mm)
            if b != band and b < len(temps):
                band = b; out.append(f"M104 S{temps[b]}\n")
    return "".join(out)

def do_temp(a):
    if a.set is not None:
        bo.save_calibration(a.material, nozzle_temperature=a.set)
        print(f"{a.material}: nozzle_temperature set to {a.set} C. Saved.")
        return
    temps = list(range(a.high, a.low - 1, -5))     # hot at the base, cooler going up
    d = tempfile.mkdtemp(prefix="bambu_cal_")
    est = bo.orca_slice(trimesh.creation.box((25, 25, len(temps) * 10)),
                        {"enable_support": "0", "sparse_infill_density": "10%"},
                        a.material, "0.20", d, apply_cal=False)
    if not est:
        sys.exit("slice failed")
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"CAL_temp_{a.material}.gcode")
    open(dest, "w").write(inject_temps(open(est["gcode"]).read(), temps))
    print(f"Temp tower sliced -> {dest}   ({est['time']})")
    print("Height -> temperature (each band 10 mm):")
    for i, t in enumerate(temps):
        print(f"   {i*10:>3}-{(i+1)*10:>3} mm : {t} C")
    print(f"Print it, pick the best-looking band, then:  bambu-calibrate temp --material {a.material} --set <temp>")

def do_show(a):
    cal = bo.load_calibration()
    if not cal:
        print("No spool calibration saved yet."); return
    for mat, v in cal.items():
        if a.material and mat != a.material:
            continue
        print(f"{mat}: " + ", ".join(f"{k}={val}" for k, val in v.items()))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit");  f.add_argument("--material", required=True)
    f.add_argument("--nominal", type=float, default=6); f.add_argument("--measured", type=float); f.set_defaults(fn=do_fit)
    fl = sub.add_parser("flow"); fl.add_argument("--material", required=True)
    fl.add_argument("--measured", type=float); fl.set_defaults(fn=do_flow)
    t = sub.add_parser("temp");  t.add_argument("--material", required=True)
    t.add_argument("--low", type=int, default=230); t.add_argument("--high", type=int, default=260)
    t.add_argument("--set", type=int); t.set_defaults(fn=do_temp)
    sh = sub.add_parser("show"); sh.add_argument("--material"); sh.set_defaults(fn=do_show)
    a = ap.parse_args()
    if getattr(a, "material", None):
        a.material = M.resolve(a.material)
    a.fn(a)

if __name__ == "__main__":
    main()
