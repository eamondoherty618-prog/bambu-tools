#!/usr/bin/env python3
"""
Install a tuned PETG-CF filament preset + matching process preset for the
X1C with the 0.6 mm hardened HX01 nozzle into Bambu Studio, select them as
the current presets, and relaunch Studio (it only reads presets at launch).

  ./bambu-studio-petgcf            # install + select + relaunch
  ./bambu-studio-petgcf --no-relaunch

Both presets are plain User presets that *inherit* Bambu's stock ones, so a
Studio update to the stock profiles flows through; only the overrides below
are pinned. Re-run any time to re-install (files are overwritten in place).

Why these numbers (Bambu PETG-CF, 0.6 HX01, textured PEI):
  filament  260 C nozzle (stock 255): 0.6 nozzle at 0.24 mm layers pushes
            ~8 mm^3/s; a bit more heat = better layer welding on CF.
            80/75 C bed (stock 70): the extra bed heat is what fixed the
            mid-print lift on the earlier PETG-CF jobs. 3 layers fan-off,
            then 10-40 %: CF surfaces look best with little cooling.
            12 mm^3/s cap (stock 11.5) is safe on the X1C hotend.
  process   0.24 mm layers, 0.3 first layer, 4 walls Arachne, 5 top / 4
            bottom, 25 % gyroid, 5 mm outer brim, slow outer walls (80),
            slow tops (70), slow first layer (25), overhangs crawl, tree-slim
            supports only where critical with a 2-layer release gap.
"""
import argparse
import glob
import json
import os
import subprocess
import time
import uuid

STUDIO = os.path.expanduser("~/Library/Application Support/BambuStudio")
STUDIO_USER = f"{STUDIO}/user"
SYS = f"{STUDIO}/system/BBL"
CONF = f"{STUDIO}/BambuStudio.conf"

FIL_BASE = "Bambu PETG-CF @BBL X1C"                 # system filament (compat: 0.6/0.8 X1C)
PROC_BASE = "0.24mm Standard @BBL X1C 0.6 nozzle"   # system process
MACHINE = "Bambu Lab X1 Carbon 0.6 nozzle"

FIL_NAME = "PETG-CF HX01 0.6 @X1C"
PROC_NAME = "0.24mm PETG-CF HX01 0.6 @X1C"

FILAMENT_OVERRIDES = {
    "nozzle_temperature": ["260", "260"],
    "nozzle_temperature_initial_layer": ["260", "260"],
    "textured_plate_temp_initial_layer": ["80"],
    "textured_plate_temp": ["75"],
    "hot_plate_temp_initial_layer": ["80"],
    "hot_plate_temp": ["75"],
    "eng_plate_temp_initial_layer": ["80"],
    "eng_plate_temp": ["75"],
    "close_fan_the_first_x_layers": ["3"],
    "fan_min_speed": ["10"],
    "fan_max_speed": ["40"],
    "fan_cooling_layer_time": ["30"],
    "slow_down_layer_time": ["8"],
    "overhang_fan_speed": ["90"],
    "additional_cooling_fan_speed": ["0"],
    "filament_max_volumetric_speed": ["12", "20"],
    "filament_flow_ratio": ["0.95"],
}

PROCESS_OVERRIDES = {
    # shells
    "wall_loops": "4",
    "top_shell_layers": "5",
    "bottom_shell_layers": "4",
    "wall_generator": "arachne",
    "precise_outer_wall": "1",
    "only_one_wall_top": "1",
    "top_surface_pattern": "monotonic",
    "seam_position": "aligned",
    "seam_slope_type": "external",
    "elefant_foot_compensation": "0.2",
    "reduce_crossing_wall": "1",
    "infill_wall_overlap": "20%",
    # infill
    "sparse_infill_density": "25%",
    "sparse_infill_pattern": "gyroid",
    # adhesion
    "brim_type": "outer_only",
    "brim_width": "5",
    "brim_object_gap": "0.1",
    # speeds  [standard hotend, high-flow hotend]
    "initial_layer_speed": ["25", "25"],
    "initial_layer_infill_speed": ["40", "40"],
    "outer_wall_speed": ["80", "80"],
    "inner_wall_speed": ["120", "120"],
    "small_perimeter_speed": ["50%", "50%"],
    "sparse_infill_speed": ["150", "150"],
    "internal_solid_infill_speed": ["120", "120"],
    "top_surface_speed": ["70", "70"],
    "gap_infill_speed": ["40", "40"],
    "bridge_speed": ["25", "25"],
    "overhang_2_4_speed": ["35", "35"],
    "overhang_3_4_speed": ["12", "12"],
    "overhang_4_4_speed": ["8", "8"],
    "overhang_totally_speed": ["8", "8"],
    "support_speed": ["100", "100"],
    "support_interface_speed": ["60", "60"],
    # accelerations
    "default_acceleration": ["6000", "6000"],
    "outer_wall_acceleration": ["3000", "3000"],
    "top_surface_acceleration": ["1500", "1500"],
    "initial_layer_acceleration": ["500", "500"],
    # supports: on, but only where the part would actually fail, clean release
    "enable_support": "1",
    "support_type": "tree(auto)",
    "support_style": "tree_slim",
    "support_critical_regions_only": "1",
    "support_top_z_distance": "0.48",
    "support_bottom_z_distance": "0.24",
    "support_interface_top_layers": "1",
    "support_interface_bottom_layers": "1",
    "support_interface_spacing": "0.5",
    "support_interface_pattern": "rectilinear",
    "support_object_xy_distance": "0.4",
    "thick_bridges": "0",
    "ironing_type": "no",
}


def sys_index(kind):
    idx = {}
    for p in glob.glob(f"{SYS}/{kind}/*.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("name"):
            idx[d["name"]] = d
    return idx


def resolve(idx, name, key):
    seen = set()
    while name and name in idx and name not in seen:
        seen.add(name)
        if key in idx[name]:
            return idx[name][key]
        name = idx[name].get("inherits")
    return None


def account_dirs(kind):
    out = {}
    for d in glob.glob(f"{STUDIO_USER}/*/{kind}"):
        u = os.path.basename(os.path.dirname(d))
        if u.isdigit():
            out[d] = u
    return out


def write_preset(kind, doc, base_id, prefix):
    for d, u in account_dirs(kind).items():
        json.dump(doc, open(os.path.join(d, doc["name"] + ".json"), "w"), indent=4)
        with open(os.path.join(d, doc["name"] + ".info"), "w") as f:
            f.write(f"sync_info = \nuser_id = {u}\nsetting_id = {prefix}{uuid.uuid4().hex[:16]}\n"
                    f"base_id = {base_id}\nupdated_time = {int(time.time())}\n")
        print(f"  {kind}: {d.split('/user/')[1]}/{doc['name']}.json")


def build_filament():
    idx = sys_index("filament")
    base = idx.get(FIL_BASE)
    if not base:
        raise SystemExit(f"system filament '{FIL_BASE}' not found")
    doc = {"type": "filament", "from": "User", "name": FIL_NAME, "inherits": FIL_BASE,
           "filament_settings_id": [FIL_NAME],
           "version": resolve(idx, FIL_BASE, "version") or "2.5.0.14"}
    v = resolve(idx, FIL_BASE, "filament_extruder_variant")
    if v is not None:
        doc["filament_extruder_variant"] = v
    doc.update(FILAMENT_OVERRIDES)
    return doc, base["setting_id"]


def build_process():
    idx = sys_index("process")
    base = idx.get(PROC_BASE)
    if not base:
        raise SystemExit(f"system process '{PROC_BASE}' not found")
    doc = {"type": "process", "from": "User", "name": PROC_NAME, "inherits": PROC_BASE,
           "print_settings_id": PROC_NAME,
           "version": resolve(idx, PROC_BASE, "version") or "2.5.0.14"}
    for k in ("print_extruder_id", "print_extruder_variant"):
        v = resolve(idx, PROC_BASE, k)
        if v is not None:
            doc[k] = v
    doc.update(PROCESS_OVERRIDES)
    return doc, base["setting_id"]


def studio_running():
    return subprocess.run(["pgrep", "-f", "BambuStudio.app/Contents/MacOS"],
                          capture_output=True).returncode == 0


def quit_studio(timeout=20):
    if not studio_running():
        return True
    subprocess.run(["osascript", "-e", 'quit app "BambuStudio"'], capture_output=True)
    for _ in range(timeout * 4):
        if not studio_running():
            return True
        time.sleep(0.25)
    return False


def select_in_conf():
    c = json.load(open(CONF))
    p = c.setdefault("presets", {})
    p["machine"] = MACHINE
    p["process"] = PROC_NAME
    fils = p.get("filaments") or [FIL_BASE]
    fils[0] = FIL_NAME
    p["filaments"] = fils
    json.dump(c, open(CONF, "w"), indent=4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-relaunch", action="store_true")
    a = ap.parse_args()

    fil, fil_base_id = build_filament()
    proc, proc_base_id = build_process()

    was_running = studio_running()
    clean = quit_studio() if was_running else True
    if was_running and not clean:
        print("! Bambu Studio did not quit (unsaved project prompt?). Installing presets anyway;\n"
              "  quit and reopen Studio yourself to see them. Not touching the selected-preset\n"
              "  config while Studio is open.")

    print("installing:")
    write_preset("filament", fil, fil_base_id, "PFUS")
    write_preset("process", proc, proc_base_id, "PPUS")

    if clean:
        select_in_conf()
        print(f"selected: {MACHINE} / {PROC_NAME} / {FIL_NAME}")
        if not a.no_relaunch:
            subprocess.run(["open", "-a", "BambuStudio"])
            print("relaunched Bambu Studio")


if __name__ == "__main__":
    main()
