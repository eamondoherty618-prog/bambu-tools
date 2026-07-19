#!/usr/bin/env python3
"""
bambu-optimize: pick slicer settings for a part from its geometry + the chosen material.

Usage:
    bambu_optimize.py PART.{stl,3mf,obj,step} --material PETG [--quality 0.20]
                      [--infill 15] [--slice] [--outdir DIR]

What it does:
  1. Loads the mesh (STEP is tessellated by Bambu Studio first).
  2. Analyzes geometry: overhangs, flat ceilings, bed contact, tallness.
  3. Combines that with the material ruleset -> concrete process overrides + rationale.
  4. Writes a Bambu process-preset override JSON that inherits the stock X1C process.
  5. Prints the exact Bambu Studio headless-slice command; with --slice, runs it and
     reports the time/filament estimate.
"""
import argparse, glob, json, os, shutil, subprocess, sys, tempfile, time, uuid
import numpy as np, trimesh
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import materials as M

STUDIO = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
PROFILES = "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL"

# How much load the part must take -> the structural knobs. Walls carry load far
# more efficiently than infill, so they scale first; infill has diminishing
# returns past ~50%. Gyroid is isotropic (strong in every direction) so it takes
# over once strength matters.
STRENGTH = {
    "cosmetic":   dict(level=1, walls=2, infill=10, pattern="grid",   top=3, bottom=3),
    "standard":   dict(level=2, walls=3, infill=15, pattern="grid",   top=4, bottom=3),
    "functional": dict(level=3, walls=4, infill=25, pattern="gyroid", top=5, bottom=4),
    "high":       dict(level=4, walls=5, infill=40, pattern="gyroid", top=6, bottom=5),
    "max":        dict(level=5, walls=6, infill=55, pattern="gyroid", top=7, bottom=6),
}
STRENGTH_ALIAS = {"display": "cosmetic", "normal": "standard", "default": "standard",
                  "structural": "high", "load-bearing": "max", "loadbearing": "max",
                  "1": "cosmetic", "2": "standard", "3": "functional", "4": "high", "5": "max"}

def resolve_strength(name):
    key = STRENGTH_ALIAS.get(name.strip().lower(), name.strip().lower())
    if key not in STRENGTH:
        sys.exit(f"Unknown strength '{name}'. Use: {', '.join(STRENGTH)} (or 1-5).")
    return key

def guarded(cmd, secs=180):
    return subprocess.run(["perl", "-e", f"alarm {secs}; exec @ARGV", *cmd],
                          capture_output=True, text=True)

def resolve_preset(kind, needle):
    """Find a system preset json under profiles/BBL/<kind> by substring."""
    hits = [p for p in glob.glob(f"{PROFILES}/{kind}/*.json")
            if needle.lower() in os.path.basename(p).lower()]
    hits.sort(key=len)  # prefer the tightest match
    return hits[0] if hits else None

def load_mesh(path):
    if path.lower().endswith((".step", ".stp")):
        import cascadio  # OpenCASCADE tessellator; Studio's CLI can't read STEP
        glb = os.path.join(tempfile.mkdtemp(prefix="bambu_step_"), "out.glb")
        cascadio.step_to_glb(path, glb, tol_linear=0.05, tol_angular=0.3)
        obj = trimesh.load(glb, force="mesh")
        mesh = obj if isinstance(obj, trimesh.Trimesh) else obj.to_geometry()
        mesh.apply_scale(1000.0)   # cascadio emits meters; STEP is millimeters
    else:
        scene = trimesh.load(path, force="scene")
        parts = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
        mesh = trimesh.util.concatenate(parts)
    mesh.merge_vertices()          # stitch per-patch verts so it's watertight/volume-sane
    mesh.apply_translation(-mesh.bounds[0])   # drop min corner to z=0
    return mesh

def analyze(mesh):
    ext = mesh.extents
    area = mesh.area_faces
    nz = mesh.face_normals[:, 2]
    incl = np.degrees(np.arccos(np.clip(np.abs(nz), 0, 1)))  # 0=flat overhang, 90=vertical wall
    tri_z = mesh.triangles[:, :, 2].min(axis=1)
    on_bed = tri_z < 0.4
    down = (nz < -0.1) & (~on_bed)
    up_flat = (nz > 0.98) & (tri_z > 0.4)     # horizontal top surfaces (ironing candidates)
    a = lambda m: float(area[m].sum())
    return dict(
        x=ext[0], y=ext[1], z=ext[2],
        volume=mesh.volume / 1000.0,
        tris=len(area),
        watertight=mesh.is_watertight,
        surface=float(area.sum()),
        bed_contact=a(tri_z < 0.4),
        down_area=a(down),
        steep30=a(down & (incl < 30)),
        steep45=a(down & (incl < 45)),
        flat_ceiling=a(down & (incl < 10)),
        flat_top=a(up_flat),
        worst=float(incl[down].min()) if down.any() else float("nan"),
        tallness=ext[2] / max(min(ext[0], ext[1]), 1e-6),
    )

def decide(g, mat_key, strength, layer_h, infill_override=None, fast=False):
    m = M.MATERIALS[mat_key]
    t = M.STRENGTH_TRAITS[mat_key]
    s = STRENGTH[strength]
    sup = m["support"]
    why, ov = [], {}

    need = g["steep45"] > 150 or g["flat_ceiling"] > 50
    if need:
        clean_ceilings = g["flat_ceiling"] > 300 or g["flat_ceiling"] > 0.12 * g["surface"]
        # tree hugs organic/curved parts and clears easily; normal + solid interface
        # gives flat ceilings a clean face
        stype = "normal(auto)" if clean_ceilings else "tree(auto)"
        style = "snug" if clean_ceilings else "organic"
        top_z = round(sup["top_gap_layers"] * layer_h, 2)          # clean multiple of layer height
        iface_top = sup["iface_top"] + (1 if clean_ceilings else 0)  # denser under flat ceilings
        ov.update({
            "enable_support": "1",
            "support_type": stype,
            "support_style": style,
            "support_threshold_angle": "30",
            "support_top_z_distance": f"{top_z:.2f}",
            "support_bottom_z_distance": f'{sup["bottom_gap"]:.2f}',
            "support_interface_top_layers": str(iface_top),
            "support_interface_bottom_layers": str(sup["iface_bottom"]),
            "support_interface_spacing": f'{sup["iface_spacing"]:.2f}',
            "support_interface_pattern": "rectilinear",
            "support_object_xy_distance": f'{sup["xy"]:.2f}',
            "support_base_pattern": "rectilinear",
        })
        why.append(f'{g["steep45"]:.0f} mm2 of <45 overhang'
                   + (f' incl. {g["flat_ceiling"]:.0f} mm2 of near-flat ceilings' if g["flat_ceiling"] > 50 else '')
                   + f' -> {stype} ({style}) supports, threshold 30.')
        why.append(f'Clean-release tuning for {mat_key}: {top_z:.2f} mm top gap '
                   f'({sup["top_gap_layers"]} layer{"s" if sup["top_gap_layers"] > 1 else ""} @ {layer_h:.2f}), '
                   f'{iface_top} interface layer(s) @ {sup["iface_spacing"]:.2f} mm spacing, '
                   f'{sup["xy"]:.2f} mm side gap, rectilinear interface -> snaps off, smooth underside.')
        if stype == "tree(auto)":
            why.append('Organic tree supports: minimal contact + easy peel on a curved/distributed part; '
                       'try --orient or lay a flat face down to cut them further.')
    else:
        ov["enable_support"] = "0"
        why.append(f'Worst overhang {g["worst"]:.0f} deg from flat, only {g["steep45"]:.0f} mm2 sub-45 '
                   f'-> prints unsupported.')

    small_foot = g["bed_contact"] < 250
    tall = g["tallness"] > 3
    brim = m["always_brim"] or small_foot or tall or (mat_key in ("PETG", "CF") and g["bed_contact"] < 500)
    if brim:
        w = m["brim_min"] + (2 if (tall or m["warp"] >= 3) else 0)
        ov.update({"brim_type": "outer_only", "brim_width": str(w)})
        reasons = []
        if m["always_brim"]: reasons.append(f"{mat_key} warps")
        if small_foot: reasons.append(f'only {g["bed_contact"]:.0f} mm2 bed contact')
        if tall: reasons.append(f'tall (H/W {g["tallness"]:.1f})')
        if not reasons: reasons.append(f'{mat_key} adhesion insurance on a small footprint')
        why.append(f'{w} mm outer brim ({"; ".join(reasons)}).')
        if tall and m["warp"] >= 3:
            why.append(f'{mat_key} + tall: enable a draft shield and keep the chamber closed.')
    else:
        ov["brim_type"] = "no_brim"

    # --- strength: walls / infill / pattern / shells, then material modifiers ---
    walls, infill, pattern = s["walls"], s["infill"], s["pattern"]
    top, bot = s["top"], s["bottom"]
    if mat_key in ("PETG", "ABS", "ASA") and s["level"] >= 3:
        infill = max(infill - 5, 10)
        why.append(f'{mat_key} is tough/ductile -> {infill}% infill carries the load a stiffer, more '
                   f'brittle resin would need more of.')
    if mat_key == "CF" and s["level"] >= 3:
        walls = max(walls - 1, 2)
        why.append('CF is very stiff -> one fewer wall still carries it (and saves abrasive-nozzle time).')
    if mat_key == "TPU":
        infill, pattern = min(infill, 20), "gyroid"
        why.append('TPU: infill capped + gyroid - rigid infill does little for a flexible part; '
                   'gyroid gives even give in every direction.')
    if infill_override is not None:
        infill = infill_override
    ov.update({"wall_loops": str(walls), "sparse_infill_density": f"{infill}%",
               "sparse_infill_pattern": pattern,
               "top_shell_layers": str(top), "bottom_shell_layers": str(bot)})
    why.append(f'Strength "{strength}": {walls} walls, {infill}% {pattern} infill, '
               f'{top}/{bot} top/bottom shells.')

    if s["level"] >= 3 and t["toughness"] <= 1 and t["stiffness"] >= 2:
        why.append(f'! {mat_key}: {t["note"]} Fine for static/stiffness loads; for impact or snap-risk '
                   f'parts prefer PETG/ABS/PA-CF.')
    if s["level"] >= 3:
        why.append('! Anisotropy: FDM is ~40-50% weaker between layers (Z) than within them. Orient the '
                   'part so the main load runs in-plane (X/Y), not across layers, and avoid tall thin necks. '
                   'Use --orient or lay the load axis flat.')
    if s["level"] >= 4:
        why.append('! Interlayer bond: for max Z-strength nudge the nozzle +5-10 C and ease off cooling a '
                   'touch (better layer welding) - do it on the filament preset, not here.')
    if mat_key == "TPU" and s["level"] >= 4:
        why.append('! High strength + TPU is a mismatch: pick a higher durometer (95A+/HF) rather than '
                   'cranking walls and infill.')

    # --- Tier 1: surface finish (automatic) ---
    ov["wall_generator"] = "arachne"            # variable-width walls: cleaner thin features + text
    ov["seam_position"] = "back"                # hide the Z-seam at the rear
    ov["top_surface_pattern"] = "monotonic"     # uniform top sheen
    if not fast:
        ov["seam_slope_type"] = "external"      # scarf seam: taper the seam so it disappears
        if g["flat_top"] > 150:
            ov.update({"ironing_type": "top", "ironing_spacing": "0.10"})
            why.append(f'Surface: {g["flat_top"]:.0f} mm2 of flat top -> ironing ON (glassy finish); '
                       'Arachne walls, seam to the back + scarf, monotonic top.')
        else:
            why.append('Surface: Arachne walls, seam to the back + scarf seam, monotonic top.')
    else:
        why.append('Surface (fast): Arachne walls, seam to the back, monotonic top (ironing/scarf off).')

    # --- Tier 2: dimensional accuracy ---
    ov["elefant_foot_compensation"] = f"{M.ELEPHANT_FOOT[mat_key]:.2f}"
    cal = load_calibration().get(mat_key, {})
    if "xy_hole_compensation" in cal:
        ov["xy_hole_compensation"] = f'{cal["xy_hole_compensation"]:.3f}'
    if "xy_contour_compensation" in cal:
        ov["xy_contour_compensation"] = f'{cal["xy_contour_compensation"]:.3f}'
    if cal:
        bits = [f'{k.split("_")[1]} {cal[k]}' for k in
                ("xy_hole_compensation", "flow_ratio", "nozzle_temperature") if k in cal]
        why.append(f'Calibrated for this spool: {", ".join(bits)}.')
    else:
        why.append(f'Dimensional: {M.ELEPHANT_FOOT[mat_key]:.2f}mm elephant-foot comp. Run '
                   f'`bambu-calibrate fit --material {mat_key}` to dial in hole/peg fit for this spool.')

    return ov, why, m

STUDIO_USER = os.path.expanduser("~/Library/Application Support/BambuStudio/user")

def target_uid():
    """The Bambu account this printer is bound to. Cached in uid.txt; first time
    it's fetched from the cloud via the logged-in Studio token."""
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uid.txt")
    if os.path.exists(cache):
        u = open(cache).read().strip()
        if u.isdigit():
            return u
    try:
        import bambu_cloud
        u = bambu_cloud.get_uid()
        open(cache, "w").write(u)
        return u
    except Exception:
        return None

def studio_user_process_dir():
    """The logged-in account's user/<uid>/process folder."""
    uid = target_uid()
    if uid and os.path.isdir(f"{STUDIO_USER}/{uid}/process"):
        return f"{STUDIO_USER}/{uid}/process", uid
    # fallback: the folder with the most existing presets (the one actually used)
    best = None
    for d in glob.glob(STUDIO_USER + "/*/process"):
        u = os.path.basename(os.path.dirname(d))
        if not u.isdigit():
            continue
        n = len(glob.glob(d + "/*.json"))
        if best is None or n > best[0]:
            best = (n, d, u)
    return (best[1], best[2]) if best else (None, None)

def install_preset(base_process_name, overrides, preset_name):
    """Drop a User process preset (+ .info sidecar) into Studio so it appears in
    the process dropdown. Returns the folder it went to, or None if not found."""
    dpath, uid = studio_user_process_dir()
    if not dpath:
        return None
    version, base_id = "2.5.0.14", "GP004"          # sane fallbacks
    for j in glob.glob(dpath + "/*.json"):           # copy from a sibling on the same base
        try:
            d = json.load(open(j, encoding="utf-8"))
        except Exception:
            continue
        if d.get("inherits") == base_process_name:
            version = d.get("version", version)
            info = j[:-5] + ".info"
            if os.path.exists(info):
                for line in open(info):
                    if line.strip().startswith("base_id"):
                        base_id = line.split("=", 1)[1].strip() or base_id
            break
    doc = {"type": "process", "from": "User", "name": preset_name,
           "inherits": base_process_name, "print_settings_id": preset_name,
           "version": version}
    doc.update(overrides)
    json.dump(doc, open(os.path.join(dpath, preset_name + ".json"), "w"), indent=1)
    with open(os.path.join(dpath, preset_name + ".info"), "w") as f:
        f.write(f"sync_info = \nuser_id = {uid}\nsetting_id = PPUS{uuid.uuid4().hex[:16]}\n"
                f"base_id = {base_id}\nupdated_time = {int(time.time())}\n")
    return dpath

DEFAULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults.json")

def load_defaults():
    try:
        return json.load(open(DEFAULTS_FILE))
    except Exception:
        return {}

CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")

def load_calibration():
    try:
        return json.load(open(CALIBRATION_FILE))
    except Exception:
        return {}

def save_calibration(material, **values):
    d = load_calibration()
    d.setdefault(material, {}).update(values)
    json.dump(d, open(CALIBRATION_FILE, "w"), indent=1)
    return d[material]

def save_defaults(**kw):
    d = load_defaults(); d.update(kw)
    json.dump(d, open(DEFAULTS_FILE, "w"), indent=1)

def ask(label, options, default=None):
    """Simple numbered menu for interactive use. Enter = default (last used)."""
    print(f"\n{label}")
    for i, o in enumerate(options, 1):
        print(f"  {i}) {o}" + ("   <- Enter for this (last used)" if o == default else ""))
    raw = input("  choose a number (or Enter): ").strip()
    if not raw and default:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw

def open_in_studio(part):
    """Restart Bambu Studio (it only reads presets at launch) and open the part."""
    running = subprocess.run(["pgrep", "-f", "BambuStudio.app/Contents/MacOS"],
                             capture_output=True).returncode == 0
    if running:
        subprocess.run(["osascript", "-e", 'quit app "BambuStudio"'], capture_output=True)
        for _ in range(60):
            if subprocess.run(["pgrep", "-f", "BambuStudio.app/Contents/MacOS"],
                              capture_output=True).returncode != 0:
                break
            time.sleep(0.25)
    subprocess.run(["open", "-a", "BambuStudio", part])

ORCA = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
ORCA_PROFILES = "/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL"
# material -> OrcaSlicer filament preset (Orca's names differ slightly from Studio's)
ORCA_FILAMENT = {"PLA": "Bambu PLA Basic @BBL X1C", "PETG": "Bambu PETG HF @BBL X1C",
                 "ABS": "Bambu ABS @BBL X1C", "ASA": "Bambu ASA @BBL X1C",
                 "TPU": "Bambu TPU 95A @BBL X1C", "CF": "Bambu PLA-CF @BBL X1C"}
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "CF": 1.30}  # g/cm3

def orca_flatten(kind, leaf):
    """Merge a preset's whole inherits chain into one self-contained dict.
    Orca's CLI won't resolve inheritance for a leaf preset (bed size lives in
    parents), so we flatten it ourselves."""
    idx = {}
    for p in glob.glob(f"{ORCA_PROFILES}/{kind}/*.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("name"):
            idx[d["name"]] = d
    chain, name = [], leaf
    while name and name in idx:
        chain.append(idx[name]); name = idx[name].get("inherits")
    merged = {}
    for d in reversed(chain):                    # root first; leaf keys win
        merged.update({k: v for k, v in d.items() if k != "inherits"})
    return merged

def orca_slice(mesh, ov, mat_key, quality, outdir, apply_cal=True):
    """Slice headlessly with OrcaSlicer. Returns {gcode, time, cm3, grams} or None.
    apply_cal=False skips stored spool calibration (used by the calibration tool
    itself, which needs a raw baseline)."""
    if not os.path.exists(ORCA):
        return None
    m = mesh.copy()
    m.apply_translation(-m.bounds[0])            # sit on bed
    c = m.bounds.mean(axis=0)
    m.apply_translation([128 - c[0], 128 - c[1], 0])   # center on the 256mm plate
    stl = os.path.join(outdir, "part.stl"); m.export(stl)

    mach = orca_flatten("machine", "Bambu Lab X1 Carbon 0.4 nozzle")   # keep its real name
    mfile = os.path.join(outdir, "orca_machine.json"); json.dump(mach, open(mfile, "w"))
    proc = orca_flatten("process", f"{quality}mm Standard @BBL X1C")
    proc.update(ov); proc["name"] = f"auto_{mat_key}"; proc["from"] = "User"
    pfile = os.path.join(outdir, "orca_process.json"); json.dump(proc, open(pfile, "w"))

    # filament: apply any measured spool calibration (flow ratio / temperature)
    cal = load_calibration().get(mat_key, {}) if apply_cal else {}
    fil_over = {}
    if "flow_ratio" in cal:
        fr = f'{cal["flow_ratio"]:.3f}'; fil_over["filament_flow_ratio"] = [fr, fr]
    if "nozzle_temperature" in cal:
        tt = str(int(cal["nozzle_temperature"])); fil_over["nozzle_temperature"] = [tt, tt]
    stock_fil = f"{ORCA_PROFILES}/filament/{ORCA_FILAMENT[mat_key]}.json"
    if fil_over:
        # inherit the stock preset (Orca resolves filament inheritance, and this
        # keeps per-plate compatibility) and just layer the calibration on top
        base = json.load(open(stock_fil, encoding="utf-8"))
        fild = {"type": "filament", "from": "User", "name": f"cal_{mat_key}",
                "inherits": ORCA_FILAMENT[mat_key]}
        for k in ("compatible_printers", "compatible_printers_condition", "version"):
            if base.get(k):
                fild[k] = base[k]
        fild.update(fil_over)
        fil = os.path.join(outdir, "orca_filament.json"); json.dump(fild, open(fil, "w"))
    else:
        fil = stock_fil
        if not os.path.exists(fil):
            return None
    out = os.path.join(outdir, "orca_out"); os.makedirs(out, exist_ok=True)
    guarded([ORCA, stl, "--load-settings", f"{mfile};{pfile}", "--load-filaments", fil,
             "--slice", "0", "--arrange", "1", "--outputdir", out], 300)
    gc = glob.glob(out + "/*.gcode")
    if not gc:
        return None
    txt = open(gc[0], errors="replace").read()
    import re
    tm = re.search(r'total estimated time:\s*([^\n;]+)', txt)
    cm3 = re.search(r'filament used \[cm3\]\s*=\s*([\d.]+)', txt)
    vol = float(cm3.group(1)) if cm3 else 0.0
    return {"gcode": gc[0], "time": (tm.group(1).strip() if tm else "?"),
            "cm3": vol, "grams": vol * DENSITY.get(mat_key, 1.24)}

def write_machine_override(base_machine, part, outdir):
    """User machine that inherits the stock X1C and adds the multi-extruder
    nozzle field current Studio builds require at slice time."""
    base = json.load(open(base_machine, encoding="utf-8"))
    name = f"X1C_auto_{part}"
    doc = {"type": "machine", "from": "User", "name": name,
           "inherits": base.get("name"),
           "nozzle_volume_type": ["Standard"],
           "default_nozzle_volume_type": ["Standard"]}
    if base.get("version"):
        doc["version"] = base["version"]
    p = os.path.join(outdir, f"{part}.machine.json")
    json.dump(doc, open(p, "w"), indent=1)
    return p, name

def write_override(base_process, overrides, part, outdir, machine_name):
    base = json.load(open(base_process, encoding="utf-8"))
    doc = {"type": "process", "from": "User",
           "name": f"auto_{part}", "inherits": base.get("name")}
    # a User preset made via `inherits` doesn't carry the parent's printer
    # compatibility, so the CLI rejects it -> copy those fields forward and
    # register our custom machine name as compatible.
    for k in ("compatible_printers", "compatible_printers_condition", "version"):
        if base.get(k):
            doc[k] = base[k]
    cp = list(doc.get("compatible_printers", []))
    if machine_name not in cp:
        cp.append(machine_name)
    doc["compatible_printers"] = cp
    doc.update(overrides)
    p = os.path.join(outdir, f"{part}.process.json")
    json.dump(doc, open(p, "w"), indent=1)
    return p

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part")
    ap.add_argument("--material", default=None)
    ap.add_argument("--strength", default=None,
                    help="cosmetic | standard | functional | high | max  (or 1-5)")
    ap.add_argument("--quality", default="0.20")
    ap.add_argument("--infill", type=int, default=None,
                    help="override the strength-derived infill %%")
    ap.add_argument("--no-slice", action="store_true",
                    help="skip auto-slicing with OrcaSlicer (just recommend settings)")
    ap.add_argument("--fast", action="store_true",
                    help="skip the time-costly quality extras (ironing, scarf seam)")
    ap.add_argument("--no-install", action="store_true",
                    help="don't install the preset into Bambu Studio")
    ap.add_argument("--open", action="store_true",
                    help="after installing, (re)launch Bambu Studio with the part open")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    # ask for anything not supplied (drag-and-drop launcher relies on this);
    # Enter repeats whatever you picked last time
    prev = load_defaults()
    material = args.material or ask("Material?", list(M.MATERIALS),
                                    default=prev.get("material", "PETG"))
    strength = args.strength or ask("Strength needed?", list(STRENGTH),
                                    default=prev.get("strength", "standard"))
    mat = M.resolve(material)
    strength = resolve_strength(strength)
    save_defaults(material=mat, strength=strength)
    outdir = args.outdir or tempfile.mkdtemp(prefix="bambu_opt_")
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.part))[0].replace(" ", "_")

    mesh = load_mesh(args.part)
    g = analyze(mesh)
    ov, why, mrule = decide(g, mat, strength, float(args.quality), args.infill, args.fast)

    print(f"\n=== {os.path.basename(args.part)}  |  material: {mat}  |  strength: {strength} ===")
    print(f"  size {g['x']:.1f} x {g['y']:.1f} x {g['z']:.1f} mm | {g['volume']:.1f} cm3 | "
          f"{g['tris']:,} tris | {'watertight' if g['watertight'] else 'NOT watertight (repair!)'}")
    print(f"  bed contact ~{g['bed_contact']:.0f} mm2 | downward {g['down_area']:.0f} mm2 "
          f"({100*g['down_area']/g['surface']:.0f}%) | steep<30 {g['steep30']:.0f} | "
          f"flat ceilings {g['flat_ceiling']:.0f} mm2 | tallness {g['tallness']:.1f}")
    print("\n  DECISIONS")
    for w in why:
        print(f"   - {w}")
    print("\n  SETTINGS (process overrides on '0.20mm Standard @BBL X1C'):")
    for k, v in ov.items():
        print(f"     {k:28} = {v}")
    print("\n  MATERIAL CAUTIONS")
    for c in mrule["cautions"]:
        print(f"   ! {c}")

    # --- auto-slice with OrcaSlicer: real time/filament estimate + printable gcode ---
    if not args.no_slice:
        print("\n  SLICING with OrcaSlicer ...")
        est = orca_slice(mesh, ov, mat, args.quality, outdir)
        if est:
            dest_dir = os.path.expanduser("~/bambu-tools/sliced")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, f"{name} {mat} {strength}.gcode")
            shutil.copy(est["gcode"], dest)
            print(f'   PRINT TIME : {est["time"]}')
            print(f'   FILAMENT   : {est["cm3"]:.1f} cm3  (~{est["grams"]:.0f} g of {mat})')
            print(f'   G-code     : {dest}')
        else:
            print("   (OrcaSlicer unavailable or slice failed; settings above still stand)")

    base_process_name = f"{args.quality}mm Standard @BBL X1C"

    # also drop a matching Studio preset in, for anyone who wants to tweak in the GUI
    preset_name = f"X1C {name} {mat} {strength}"
    if not args.no_install:
        install_preset(base_process_name, ov, preset_name)

    print("\n  TO PRINT")
    if not args.no_slice:
        print("   Your sliced G-code is ready (path above). Send it to the X1C by dragging")
        print("   the .gcode into Bambu Studio (or Bambu Handy) and hitting print.")
        print(f'   To tweak first: open the part in Studio, pick filament "{mrule["preset"]}"')
        print(f'   and process preset "{preset_name}", then Slice.')
    else:
        print(f'   Open the part in Bambu Studio, pick filament "{mrule["preset"]}" and process')
        print(f'   preset "{preset_name}", then Slice.')
    if args.open:
        open_in_studio(args.part)

if __name__ == "__main__":
    main()
