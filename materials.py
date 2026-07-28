"""
Material ruleset for Eamon's Bambu X1C (0.6mm HARDENED nozzle - HX01 - confirmed
over cloud MQTT; the printer reports nozzle_diameter 0.6). Filament families he
actually runs, with PETG-CF as the workhorse for in-vehicle parts.

Each entry carries:
  preset       : Bambu/Orca filament preset name for the X1C (nozzle-agnostic name)
  spool_type   : what the loaded spool must report over MQTT (AMS/vt_tray tray_type)
  plate        : bed type to pin in the slice (Textured PEI plate = his plate)
  always_brim  : force a brim regardless of geometry (warp-prone / adhesion-critical)
  brim_min     : minimum brim width (mm) when a brim is used
  warp         : warp risk 0-3 (drives draft-shield / brim escalation on tall parts)
  first_layer  : conservative first-layer speed override (mm/s), or None to keep preset
  hardened     : True if the material REQUIRES a hardened nozzle (abrasive)
  cautions     : material-specific gotchas surfaced in the report
  support      : the clean-release support recipe (see below)

The `support` recipe makes supports snap off cleanly AND leave a decent underside.
Materials that fuse to supports (PETG, PETG-CF, TPU) get a 2-layer top gap + sparse
interface; the rest get 1 layer + a denser interface for a smoother face.
  top_gap_layers / bottom_gap / iface_top / iface_bottom / iface_spacing / xy
"""

DEFAULT_PLATE = "Textured PEI Plate"

MATERIALS = {
    "PLA": dict(
        preset="Bambu PLA Basic @BBL X1C", spool_type="PLA", plate=DEFAULT_PLATE,
        always_brim=False, brim_min=3, warp=0, first_layer=None, hardened=False,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=3, iface_bottom=2,
                     iface_spacing=0.20, xy=0.35),
        cautions=["Easiest case. Supports: dense interface + 1-layer gap - smooth underside, still snaps off.",
                  "Softens ~55 C: never for anything that lives in a hot car/truck cab."]),
    "PETG": dict(
        preset="Bambu PETG HF @BBL X1C", spool_type="PETG", plate=DEFAULT_PLATE,
        always_brim=False, brim_min=4, warp=1, first_layer=None, hardened=False,
        support=dict(top_gap_layers=2, bottom_gap=0.25, iface_top=1, iface_bottom=1,
                     iface_spacing=0.50, xy=0.40),
        cautions=["PETG welds to supports - 2-layer gap + sparse interface so they pop off.",
                  "Prone to stringing: keep retraction tuned."]),
    "ABS": dict(
        preset="Bambu ABS @BBL X1C", spool_type="ABS", plate=DEFAULT_PLATE,
        always_brim=True, brim_min=5, warp=3, first_layer=None, hardened=False,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=2,
                     iface_spacing=0.30, xy=0.35),
        cautions=["Warps hard: enclosure closed, minimal cooling, always a brim; draft shield if tall.",
                  "Keep the chamber warm - don't crack the door mid-print."]),
    "ASA": dict(
        preset="Bambu ASA @BBL X1C", spool_type="ASA", plate=DEFAULT_PLATE,
        always_brim=True, brim_min=5, warp=3, first_layer=None, hardened=False,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=2,
                     iface_spacing=0.30, xy=0.35),
        cautions=["Same warp discipline as ABS; UV-stable so it's the outdoor choice.",
                  "Low cooling; brim mandatory; watch first-layer adhesion."]),
    "TPU": dict(
        preset="Bambu TPU 95A @BBL X1C", spool_type="TPU", plate=DEFAULT_PLATE,
        always_brim=False, brim_min=4, warp=0, first_layer=None, hardened=False,
        support=dict(top_gap_layers=2, bottom_gap=0.30, iface_top=1, iface_bottom=1,
                     iface_spacing=0.60, xy=0.45),
        cautions=["Print SLOW (walls ~15-25 mm/s) and minimize retraction or it jams/oozes.",
                  "Reorient to avoid supports - they're miserable on flexible TPU."]),
    "PLA-CF": dict(
        preset="Bambu PLA-CF @BBL X1C", spool_type="PLA-CF", plate=DEFAULT_PLATE,
        always_brim=False, brim_min=3, warp=1, first_layer=30, hardened=True,
        support=dict(top_gap_layers=1, bottom_gap=0.20, iface_top=2, iface_bottom=1,
                     iface_spacing=0.25, xy=0.40),
        cautions=["Abrasive: REQUIRES a hardened nozzle.",
                  "Softens ~55 C - do NOT use for in-vehicle parts (cab heat ~80 C). Use PETG-CF instead.",
                  "Stiff + brittle: avoid sharp stress risers; supports snap off cleanly."]),
    "PETG-CF": dict(
        preset="Bambu PETG-CF @BBL X1C", spool_type="PETG-CF", plate="Textured PEI Plate",
        always_brim=True, brim_min=5, warp=1, first_layer=30, hardened=True,
        support=dict(top_gap_layers=2, bottom_gap=0.25, iface_top=1, iface_bottom=1,
                     iface_spacing=0.50, xy=0.40),
        cautions=["The workhorse for in-vehicle parts: survives ~80 C cab heat where PLA-CF fails at ~55 C.",
                  "Abrasive: REQUIRES a hardened nozzle (your HX01 0.6 qualifies).",
                  "Textured PEI plate @ 70 C, nozzle ~255 C, conservative first layer - a plate/temp",
                  "mismatch is what failed the layer-13 print; this profile pins all three."]),
}

# first-layer squish compensation (elephant's foot), mm, per material
ELEPHANT_FOOT = {"PLA": 0.15, "PETG": 0.20, "ABS": 0.15, "ASA": 0.15, "TPU": 0.10,
                 "PLA-CF": 0.15, "PETG-CF": 0.20}

# stiffness (rigidity) and toughness (impact/ductility), 0-3, + a note
STRENGTH_TRAITS = {
    "PLA":  dict(stiffness=3, toughness=0,
                 note="Stiff but brittle: superb rigidity, poor impact. Snaps rather than bends."),
    "PETG": dict(stiffness=2, toughness=3,
                 note="Tough + ductile: the best all-round pick for load-bearing/impact parts."),
    "ABS":  dict(stiffness=2, toughness=2,
                 note="Moderate strength, decent impact, heat-resistant. Warp control is the constraint."),
    "ASA":  dict(stiffness=2, toughness=2,
                 note="ABS-like strength + UV resistance: the outdoor structural choice."),
    "TPU":  dict(stiffness=0, toughness=3,
                 note="Flexible: 'strength' means tear resistance, not rigidity."),
    "PLA-CF": dict(stiffness=3, toughness=0,
                 note="Very stiff + light but brittle and heat-limited (~55 C). Not for vehicles."),
    "PETG-CF": dict(stiffness=3, toughness=1,
                 note="Stiff, light, and heat-tolerant (~80 C+): the pick for structural in-vehicle parts."),
}

ALIASES = {
    "pla": "PLA", "petg": "PETG", "pet-g": "PETG", "abs": "ABS", "asa": "ASA",
    "tpu": "TPU", "flex": "TPU",
    "pla-cf": "PLA-CF", "placf": "PLA-CF",
    "petg-cf": "PETG-CF", "petgcf": "PETG-CF", "petg cf": "PETG-CF",
    # bare "cf"/"carbon" -> PETG-CF: his actual workhorse (heat-tolerant, in-vehicle)
    "cf": "PETG-CF", "carbon": "PETG-CF",
}

def resolve(name: str) -> str:
    key = ALIASES.get(name.strip().lower(), name.strip().upper())
    if key not in MATERIALS:
        raise SystemExit(f"Unknown material '{name}'. Known: {', '.join(MATERIALS)}")
    return key
