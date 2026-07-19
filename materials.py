"""
Material ruleset for Eamon's Bambu X1C (0.4mm hardened-capable nozzle assumed).
Tuned for the filament families he actually runs: PLA, PETG, ABS, ASA, TPU, CF.

Each entry carries:
  preset      : substring to resolve the Bambu/Orca filament preset for the X1C
  always_brim : force a brim regardless of geometry (warp-prone materials)
  brim_min    : minimum brim width (mm) when a brim is used
  warp        : warp risk 0-3 (drives draft-shield / brim escalation on tall parts)
  cautions    : material-specific gotchas surfaced in the report
  support     : the clean-release support recipe (see below)

The `support` recipe is what makes supports snap off cleanly AND leave a decent
underside. The two forces fight each other: a dense interface + tiny gap gives a
smooth surface but welds on; a big gap + sparse interface snaps off but looks
rougher. So per material:
  top_gap_layers : top Z gap expressed in LAYER HEIGHTS (kept a clean multiple so
                   the separation layer is consistent). Materials that fuse to
                   supports (PETG, TPU) get 2 layers; the rest get 1.
  bottom_gap     : Z gap where a support rests on the model from below (mm)
  iface_top      : dense interface layers under the overhang (surface vs. removal)
  iface_bottom   : interface layers where support meets the model below
  iface_spacing  : gap between interface lines (mm) - smaller = smoother + grippier
  xy             : horizontal gap between support and model walls (mm)
PLA releases so easily it can run a near-solid interface (0.20 spacing) for a
glassy underside and still pop off; PETG/TPU lean the other way.
"""

MATERIALS = {
    "PLA": dict(
        preset="Bambu PLA Basic @BBL X1C", always_brim=False, brim_min=3, warp=0,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=3, iface_bottom=2,
                     iface_spacing=0.20, xy=0.35),
        cautions=["Easiest case. Supports tuned dense-interface + 1-layer gap: smooth underside, still snaps off.",
                  "Watch heat creep on tiny parts (raise min layer time / slow small layers)."]),
    "PETG": dict(
        preset="Bambu PETG HF @BBL X1C", always_brim=False, brim_min=4, warp=1,
        support=dict(top_gap_layers=2, bottom_gap=0.25, iface_top=1, iface_bottom=1,
                     iface_spacing=0.50, xy=0.40),
        cautions=["PETG welds to supports - recipe uses a 2-layer gap + sparse interface so they actually pop off.",
                  "Prone to stringing: keep retraction tuned; the preset's defaults are a good start."]),
    "ABS": dict(
        preset="Bambu ABS @BBL X1C", always_brim=True, brim_min=5, warp=3,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=2,
                     iface_spacing=0.30, xy=0.35),
        cautions=["Warps hard: enclosure closed, minimal cooling, always a brim; draft shield if tall.",
                  "Keep the chamber warm - don't crack the door mid-print."]),
    "ASA": dict(
        preset="Bambu ASA @BBL X1C", always_brim=True, brim_min=5, warp=3,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=2,
                     iface_spacing=0.30, xy=0.35),
        cautions=["Same warp discipline as ABS; UV-stable so it's the better outdoor choice.",
                  "Low cooling; brim mandatory; watch first-layer adhesion on the smooth plate."]),
    "TPU": dict(
        preset="Bambu TPU 95A @BBL X1C", always_brim=False, brim_min=4, warp=0,
        support=dict(top_gap_layers=2, bottom_gap=0.30, iface_top=1, iface_bottom=1,
                     iface_spacing=0.60, xy=0.45),
        cautions=["Print SLOW (walls ~15-25 mm/s) and minimize retraction or it'll jam/ooze.",
                  "Supports on flexible TPU are miserable even tuned - reorient to avoid needing them.",
                  "Feed soft filament carefully (external spool safer than deep AMS routing)."]),
    "CF": dict(
        preset="Bambu PLA-CF @BBL X1C", always_brim=False, brim_min=3, warp=1,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=1,
                     iface_spacing=0.25, xy=0.40),
        cautions=["Abrasive: REQUIRES a hardened nozzle. Confirm the X1C has one before running CF.",
                  "CF blends are stiff/brittle - avoid sharp stress risers; supports snap off cleanly (brittle).",
                  "PA-CF/PET-CF variants want a dry filament + hotter chamber; swap the preset if not PLA-CF."]),
}

# stiffness (rigidity) and toughness (impact/ductility), 0-3, + a note
STRENGTH_TRAITS = {
    "PLA":  dict(stiffness=3, toughness=0,
                 note="Stiff but brittle: superb rigidity + dimensional accuracy, poor impact. Snaps rather than bends."),
    "PETG": dict(stiffness=2, toughness=3,
                 note="Tough + ductile: the best all-round pick for load-bearing/impact parts. Bends before it breaks."),
    "ABS":  dict(stiffness=2, toughness=2,
                 note="Moderate strength, decent impact, heat-resistant. Warp control is the real constraint."),
    "ASA":  dict(stiffness=2, toughness=2,
                 note="ABS-like strength + UV resistance: the outdoor structural choice."),
    "TPU":  dict(stiffness=0, toughness=3,
                 note="Flexible: 'strength' means tear resistance / durometer, not rigidity. Rigid infill does little; walls drive tear strength."),
    "CF":   dict(stiffness=3, toughness=0,
                 note="Very stiff + light but brittle and notch-sensitive. Great for rigidity, poor for impact; fewer walls already carry the load."),
}

ALIASES = {
    "pla": "PLA", "petg": "PETG", "pet-g": "PETG", "abs": "ABS", "asa": "ASA",
    "tpu": "TPU", "flex": "TPU", "cf": "CF", "carbon": "CF", "pla-cf": "CF",
    "pa-cf": "CF", "pet-cf": "CF", "pahtcf": "CF",
}

def resolve(name: str) -> str:
    key = ALIASES.get(name.strip().lower(), name.strip().upper())
    if key not in MATERIALS:
        raise SystemExit(f"Unknown material '{name}'. Known: {', '.join(MATERIALS)}")
    return key
