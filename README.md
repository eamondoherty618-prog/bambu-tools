# bambu-tools

Command-line helpers for a **Bambu Lab X1 Carbon** that pick good slicer settings
for a part automatically, slice it, and let you check the printer from anywhere.

You point it at a 3D model and tell it two things — the **material** and how
**strong** the part needs to be — and it:

1. **Measures the model's geometry** (overhangs, flat ceilings, how much of it
   touches the bed, how tall and tippy it is).
2. **Applies known-good rules** for your material and strength target to choose
   supports, brim, walls, infill, infill pattern, and shells — and explains *why*.
3. Adds **automatic surface polish** — ironing on flat tops, a hidden (back +
   scarf) seam, Arachne variable-width walls, and clean-releasing supports.
4. **Slices it with OrcaSlicer** and tells you the real **print time and filament**
   (grams), saving a ready G-code.
5. Optionally **installs the settings as a preset in Bambu Studio** so you can
   tweak in the GUI.

You can also **calibrate a specific spool** (`bambu-calibrate`) so holes/pegs fit
and flow is dialed in — those corrections then apply to every future slice.

It's not machine learning or a stress simulation — it's honest geometry
measurement plus a curated rule set, the same reasoning an experienced printer
applies, made automatic and consistent.

---

## Install

Requires macOS, Python 3, [Bambu Studio](https://bambulab.com/en/download/studio)
(used to read STEP files and, optionally, hold presets), and
[OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) (does the actual slicing —
Bambu Studio's command line can't headless-slice a single-extruder X1C).

```bash
git clone https://github.com/eamondoherty618-prog/bambu-tools.git
cd bambu-tools
./setup.sh          # creates a venv and installs the Python deps
```

---

## Use it

```bash
./bambu-optimize path/to/part.step --material PETG --strength functional
```

- **part** — `.stl`, `.3mf`, `.obj`, or `.step` (STEP is tessellated automatically).
- **`--material`** — `PLA`, `PETG`, `ABS`, `ASA`, `TPU`, or `CF`.
- **`--strength`** — `cosmetic`, `standard`, `functional`, `high`, or `max`
  (or `1`–`5`). Drives walls / infill / pattern / shells.
- Leave `--material`/`--strength` off and it asks with a menu (remembering your
  last choice). `--no-slice` skips OrcaSlicer; `--no-install` skips the Studio preset.

You get the analysis, the chosen settings with reasons, the print-time/filament
estimate, and a G-code saved to `sliced/`.

### Drag-and-drop (macOS)

Build the little app once and keep it in your Dock:

```bash
osacompile -o "Optimize for X1C.app" droplet.applescript
```

Then drag any model file onto its icon, answer the two menus, done.

### Calibrate a spool (optional, for the best quality)

Three quick test prints dial a specific spool in. Each one: slice it, print it,
measure with calipers, feed the number back. The correction is saved per material
and applied to every future slice automatically.

```bash
./bambu-calibrate fit  --material PETG                     # dimensional fit (holes/pegs)
./bambu-calibrate fit  --material PETG --nominal 6 --measured 5.86
./bambu-calibrate flow --material PETG                     # extrusion flow (single-wall box)
./bambu-calibrate flow --material PETG --measured 0.45
./bambu-calibrate temp --material PETG --low 230 --high 260   # temperature tower
./bambu-calibrate temp --material PETG --set 245
./bambu-calibrate show
```

`fit` fixes holes printing undersized (so parts snap together on the first try),
`flow` fixes over/under-extrusion, and `temp` finds the cleanest nozzle temp.
Corrections live in `calibration.json` (kept out of the repo — it's yours).

### Check the printer from anywhere

```bash
./bambu-status            # one snapshot of the printer's state
./bambu-status --watch    # live, every 20s
./bambu-watch             # notify your phone (via ntfy) when the print ends
```

These read the printer through **Bambu's cloud**, reusing the login token from
Bambu Studio on your Mac, so they work even when you're away from home.
For notifications, set your own ntfy topic (it acts like a password):

```bash
echo "my-private-topic-name" > ntfy_topic.txt   # or export BAMBU_NTFY_TOPIC=...
```

and subscribe to that topic in the free [ntfy](https://ntfy.sh) phone app.

---

## How the pieces fit

| File | What it does |
|------|--------------|
| `bambu_optimize.py` | Geometry analysis + rule engine + surface polish + OrcaSlicer slicing |
| `materials.py` | Per-material rules (PLA/PETG/ABS/ASA/TPU/CF): supports, brim, dims |
| `bambu_calibrate.py` | Per-spool fit / flow / temperature calibration test prints |
| `bambu_cloud.py` | Reads the printer's live state via Bambu's cloud MQTT |
| `bambu_watch.py` | Watches a print and sends a phone notification when it ends |

---

## Honest limitations

- **It can't start a print for you.** Since 2025 Bambu requires all print/control
  commands to be cryptographically signed via "Bambu Connect," so no third-party
  tool can launch a job. This project *reads* status (not gated) and slices;
  you send the file with Bambu Studio or the Bambu Handy app, and `bambu-watch`
  pings you when it's done.
- Tuned for the **X1 Carbon, 0.4 mm nozzle**. Other Bambu printers would need
  their own machine preset wired in.
- Orientation matters enormously for strength (parts are ~40–50 % weaker across
  layer lines), but the tool can't know your load direction — it advises, you decide.
- The rules are good opinionated defaults, not a physics simulation.

## License

MIT — see [LICENSE](LICENSE).

---

## What's new (2026-07)

**`bambu-print` — send a slice to the printer from anywhere** (cloud MQTT):

```bash
./bambu-print "sliced/part PETG functional.gcode"        # stage: wrap + upload + preflight
./bambu-print "sliced/part PETG functional.gcode" --go   # start the print
```

It wraps the raw G-code into a Bambu `.gcode.3mf`, uploads it to a public
Supabase bucket (set `BAMBU_UPLOAD_SUPABASE_URL` + `BAMBU_UPLOAD_SUPABASE_KEY`
to any Supabase project you own), preflights printer state over MQTT (refuses
while a job is running; warns after FINISH that the plate may not be clear),
then publishes the print command and tails status until the job starts.

> **Honest limitation:** current X1 firmware only accepts print-start commands
> cryptographically signed by official Bambu apps. `bambu-print` does everything
> up to that gate, detects the rejection (`mqtt message verify failed`), and
> tells you to press Send in Bambu Studio — or enable LAN/Developer mode and
> send from the printer's LAN, where no signature is required. Monitoring
> (`bambu-status`, `bambu-watch`) is unaffected.

**New slicer flags:**

- `--nozzle 0.2|0.4|0.6|0.8` — picks the matching machine + process presets.
- `--supports auto|off|on` — override the geometry-based support decision
  (parts with deliberate short bridges — snap windows, vents — print cleaner
  unsupported, and supports jammed inside a snap window ruin the fit).

**New material: `PA6-CF`** (aliases `pa6`, `nylon`) — correct Bambu/Orca
presets, density, and the nylon realities in the cautions (DRY the filament,
textured plate + glue, full cooldown before removal, optional anneal).

**Fixes:** sub-millimeter ceilings (debossed logos/engraving) no longer
trigger supports — they bridge themselves in one layer; previously the
analyzer would plan supports *inside the lettering*.
