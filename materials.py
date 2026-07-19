"""
Material ruleset for Eamon's Bambu X1C (0.4mm hardened-capable nozzle assumed).
Tuned for the filament families he actually runs: PLA, PETG, ABS, ASA, TPU, CF blends.

Each entry carries:
  preset      : substring to resolve the Bambu system filament preset for the X1C
  z_gap       : support_top_z_distance (mm) - bigger = easier support removal, worse underside
  iface       : default support-interface layers (surface quality vs. removal effort)
  iface_space : support_interface_spacing (mm) - larger = easier peel (esp. PETG/TPU)
  cooling     : qualitative fan philosophy (drives the caution text; fan lives in filament preset)
  always_brim : force a brim regardless of geometry (warp-prone materials)
  brim_min    : minimum brim width (mm) when a brim is used
  warp        : warp risk 0-3 (drives draft-shield / brim escalation on tall parts)
  cautions    : material-specific gotchas surfaced in the report
"""

MATERIALS = {
    "PLA": dict(
        preset="Bambu PLA Basic @BBL X1C", z_gap=0.20, iface=2, iface_space=0.5,
        cooling="max", always_brim=False, brim_min=3, warp=0,
        cautions=["Easiest case. Watch for heat creep on tiny parts (add a min layer time / slow small layers)."]),
    "PETG": dict(
        preset="Bambu PETG HF @BBL X1C", z_gap=0.25, iface=1, iface_space=0.8,
        cooling="medium", always_brim=False, brim_min=4, warp=1,
        cautions=["PETG fuses to supports - wider Z-gap + sparse interface so they actually come off.",
                  "Prone to stringing: keep retraction tuned; the preset's defaults are a good start."]),
    "ABS": dict(
        preset="Bambu ABS @BBL X1C", z_gap=0.20, iface=2, iface_space=0.5,
        cooling="low", always_brim=True, brim_min=5, warp=3,
        cautions=["Warps hard: enclosure closed, minimal cooling, always a brim; draft shield if tall.",
                  "Keep chamber warm - don't crack the door mid-print."]),
    "ASA": dict(
        preset="Generic ASA @BBL X1C", z_gap=0.20, iface=2, iface_space=0.5,
        cooling="low", always_brim=True, brim_min=5, warp=3,
        cautions=["Same warp discipline as ABS; UV-stable so it's the better outdoor choice.",
                  "Low cooling; brim mandatory; watch first-layer adhesion on the smooth plate."]),
    "TPU": dict(
        preset="Bambu TPU 95A @BBL X1C", z_gap=0.30, iface=0, iface_space=1.0,
        cooling="medium", always_brim=False, brim_min=4, warp=0,
        cautions=["Print SLOW (walls ~15-25 mm/s) and minimize retraction or it'll jam/ooze.",
                  "Supports on TPU are miserable to remove - avoid needing them; reorient first.",
                  "Use the AMS with caution (soft filament); a spool holder / external feed is safer."]),
    "CF": dict(
        preset="Bambu PLA-CF @BBL X1C", z_gap=0.20, iface=1, iface_space=0.6,
        cooling="max", always_brim=False, brim_min=3, warp=1,
        cautions=["Abrasive: REQUIRES a hardened nozzle. Confirm the X1C has one before running CF.",
                  "CF blends are stiff/brittle - fewer walls needed for stiffness, but avoid sharp stress risers.",
                  "PA-CF/PET-CF variants want a dry filament + hotter chamber; swap the preset if not PLA-CF."]),
}

# Mechanical character, used by the --strength logic.
#   stiffness = resists bending/holds shape (rigidity)
#   toughness = absorbs impact / bends before breaking (ductility)
# both 0-3. `note` is surfaced when strength is functional or higher.
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
