#!/usr/bin/env python3
"""
bambu-preflight: verify the printer's ACTUAL state over Bambu's cloud MQTT before
you print - so a sliced job can't quietly mismatch what's loaded.

Checks the loaded spool type (external spool + every AMS tray) and the nozzle
diameter/hardness against what a slice was prepared for. A filament-profile vs.
loaded-spool mismatch is what failed a print at layer 13; this hard-fails instead.

    bambu-preflight                      # report printer state
    bambu-preflight --material PETG-CF   # verify state matches that material
    bambu-preflight --material PETG-CF --nozzle 0.6

Exit code 0 = OK, 1 = mismatch/blocker, 2 = couldn't reach the printer.

NOTE: this only READS. Starting a print from a third-party client is rejected by
current X1C firmware (err 84033543 "mqtt message verify failed") on both LAN and
cloud - the print-start stays a human step in Bambu Studio.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bambu_cloud
import materials as M

# nozzle types the printer reports that are hard enough for abrasive filament
HARDENED_NOZZLES = ("hx", "hardened", "steel", "tungsten")

def printer_state(serial=None):
    """{online, state, nozzle_diameter, nozzle_type, spools[], error} or None.
    `serial` selects a printer by full serial or any substring (e.g. the last 3
    digits). With several printers bound and no serial given, this refuses to
    guess - verifying the wrong machine is exactly the silent failure to avoid."""
    tok = bambu_cloud.read_token()
    uid = str(bambu_cloud.api("/v1/user-service/my/profile", tok)["uid"])
    devs = bambu_cloud.api("/v1/iot-service/api/user/bind", tok).get("devices", [])
    if not devs:
        return None
    if serial:
        hits = [d for d in devs if serial.lower() in str(d.get("dev_id", "")).lower()]
        if not hits:
            have = ", ".join(f'{d.get("name")} ({d.get("dev_id")})' for d in devs)
            raise SystemExit(f"No bound printer matches serial '{serial}'. Account has: {have}")
        if len(hits) > 1:
            raise SystemExit(f"Serial '{serial}' matches {len(hits)} printers; be more specific.")
        dev = hits[0]
    elif len(devs) > 1:
        have = ", ".join(f'{d.get("name")} ({d.get("dev_id")})' for d in devs)
        raise SystemExit(f"{len(devs)} printers bound - pass --serial to pick one. Have: {have}")
    else:
        dev = devs[0]
    p = bambu_cloud.status_once(uid, dev["dev_id"], tok) or {}
    spools = []
    ams_blk = p.get("ams") or {}
    # which feed is actually selected: 254 = external spool, 255 = none,
    # 0..n = global AMS tray index (unit * 4 + slot)
    try:
        tray_now = int(ams_blk.get("tray_now", 255))
    except (TypeError, ValueError):
        tray_now = 255
    vt = p.get("vt_tray") or {}
    if vt.get("tray_type"):
        spools.append({"where": "external spool", "type": vt["tray_type"],
                       "active": tray_now == 254})
    for unit in ams_blk.get("ams") or []:
        try:
            unit_id = int(unit.get("id", 0))
        except (TypeError, ValueError):
            unit_id = 0
        for t in unit.get("tray", []):
            if t.get("tray_type"):
                try:
                    gidx = unit_id * 4 + int(t.get("id", 0))
                except (TypeError, ValueError):
                    gidx = -1
                spools.append({"where": f"AMS slot {t.get('id')}", "type": t["tray_type"],
                               "active": gidx == tray_now})
    return {"name": dev.get("name"), "serial": dev["dev_id"], "online": dev.get("online"),
            "state": p.get("gcode_state"), "nozzle_diameter": p.get("nozzle_diameter"),
            "nozzle_type": p.get("nozzle_type"), "spools": spools,
            "error": p.get("print_error"), "raw": p}

def check(st, material=None, nozzle=None):
    """Returns (problems, notes). Empty problems == good to print."""
    problems, notes = [], []
    if not st:
        return (["No printer bound to this Bambu account."], notes)
    if not st["online"]:
        problems.append("Printer is offline (cloud reports not connected).")
    if st["state"] in ("RUNNING", "PREPARE", "SLICING", "PAUSE"):
        problems.append(f"Printer is busy: {st['state']}.")
    elif st["state"] in ("FINISH", "FAILED"):
        notes.append(f"Printer state: {st['state']} - CHECK THE PLATE IS CLEAR "
                     "(the printer cannot see a part still sitting on it).")
    elif st["state"]:
        notes.append(f"Printer state: {st['state']}")

    nd = st.get("nozzle_diameter")
    if nd is None:
        if nozzle:
            problems.append(f"Printer did not report a nozzle diameter, so a {nozzle} mm "
                            "slice can't be verified. Confirm the installed nozzle by hand.")
        else:
            notes.append("Nozzle: not reported.")
    elif nozzle and abs(float(nd) - float(nozzle)) > 0.01:
        problems.append(f"NOZZLE MISMATCH: sliced for {nozzle} mm, printer reports {nd} mm. "
                        f"Re-slice with --nozzle {nd}.")
    else:
        notes.append(f"Nozzle: {nd} mm ({st.get('nozzle_type') or 'type unknown'})")

    if material:
        mrule = M.MATERIALS[material]
        want = mrule["spool_type"].upper()
        loaded = [s["type"].upper() for s in st["spools"]]
        if not loaded:
            problems.append("No filament detected (no AMS tray or external spool reported).")
        elif want not in loaded:
            problems.append(f"FILAMENT MISMATCH: sliced for {want}, printer has "
                            f"{', '.join(loaded) or 'nothing'} loaded. "
                            f"Load {want} or re-slice for what's loaded.")
        else:
            hit = next(s for s in st["spools"] if s["type"].upper() == want)
            if hit.get("active"):
                notes.append(f"Filament: {want} on the {hit['where']} (active feed) - matches.")
            else:
                active = next((s for s in st["spools"] if s.get("active")), None)
                notes.append(f"Filament: {want} is on the {hit['where']}.")
                problems.append(
                    f"{want} is loaded but the ACTIVE feed is "
                    f"{(active['type'] + ' on the ' + active['where']) if active else 'unknown'}. "
                    "Select the right slot/spool on the printer before printing.")
        if mrule.get("hardened"):
            nt = (st.get("nozzle_type") or "").strip().lower()
            if not nt:
                problems.append(f"{material} is abrasive and needs a hardened nozzle, but the "
                                "printer reported no nozzle type. Verify by hand before printing.")
            elif not any(h in nt for h in HARDENED_NOZZLES):
                problems.append(f"{material} is abrasive and needs a hardened nozzle; printer "
                                f"reports '{st.get('nozzle_type')}'. Verify before printing.")
            else:
                notes.append(f"Abrasive-safe nozzle required: '{st.get('nozzle_type')}' OK.")
        notes.append(f"Plate to use: {mrule.get('plate', M.DEFAULT_PLATE)}")
    if st.get("error"):
        notes.append(f"Last print_error code: {st['error']}")
    return problems, notes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--material")
    ap.add_argument("--nozzle")
    ap.add_argument("--serial", help="pick a printer by serial (or its last digits)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    mat = M.resolve(a.material) if a.material else None
    try:
        st = printer_state(a.serial)
    except Exception as e:
        print(f"Could not reach the printer: {e}"); sys.exit(2)
    if a.json:
        probs = check(st, mat, a.nozzle)[0]
        print(json.dumps({"state": st, "problems": probs}, indent=1, default=str))
        sys.exit(1 if probs else 0)
    problems, notes = check(st, mat, a.nozzle)
    if st:
        print(f"\n  {st['name']}  ({st['serial']})")
    for n in notes:
        print(f"   - {n}")
    if problems:
        print("\n  NOT READY:")
        for p in problems:
            print(f"   ! {p}")
        sys.exit(1)
    print("\n  READY - printer state matches the slice.")
    print("   Send the G-code from Bambu Studio / Handy and press print there:")
    print("   third-party print-start is rejected by firmware (err 84033543).")

if __name__ == "__main__":
    main()
