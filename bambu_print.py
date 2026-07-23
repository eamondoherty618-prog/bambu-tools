#!/usr/bin/env python3
"""
bambu-print: send a sliced .gcode to the X1C over Bambu cloud, from anywhere.

    bambu-print sliced/part.gcode           # stage: wrap + upload + preflight
    bambu-print sliced/part.gcode --go      # actually start the print
    bambu-print sliced/part.gcode --go --ams  # feed from AMS (default: external spool)

What it does:
  1. Wraps the raw G-code into a minimal Bambu .gcode.3mf container (the
     cloud print command only accepts 3mf, not bare gcode).
  2. Uploads it to a public Supabase storage bucket - the printer streams
     it straight from that URL.
  3. Preflight over cloud MQTT: refuses to start unless the printer is
     IDLE/FINISH/FAILED. FINISH still means CHECK THE PLATE IS CLEAR -
     the printer can't see the part sitting on it.
  4. --go publishes the project_file command, then tails status until the
     job actually starts (or reports why not).

Physical checklist the tool cannot verify - on you:
  plate clear + correct plate in + glue if nylon + the right filament
  loaded (and DRY for PA6/PAHT).
"""
import argparse, hashlib, json, os, ssl, subprocess, sys, time, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bambu_cloud import read_token, api, status_once, fmt, BROKER
import paho.mqtt.client as mqtt
import certifi

FRONTEND = os.path.expanduser("~/123-mobile-track/frontend")
BUCKET = "bambu-prints"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="gcode" ContentType="text/x.gcode"/></Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>"""
MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build/></model>"""
SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Type" value="slicer"/><header_item key="X-BBL-Client-Version" value="01.10.00.00"/></header>
  <plate><metadata key="index" value="1"/><metadata key="printer_model_id" value="BL-P001"/><metadata key="nozzle_diameters" value="0.4"/><metadata key="gcode_file" value="Metadata/plate_1.gcode"/></plate>
</config>"""


def wrap_3mf(gcode_path, out_path):
    g = open(gcode_path, "rb").read()
    gmd5 = hashlib.md5(g).hexdigest().upper()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", MODEL)
        z.writestr("Metadata/plate_1.gcode", g)
        z.writestr("Metadata/plate_1.gcode.md5", gmd5)
        z.writestr("Metadata/slice_info.config", SLICE_INFO)
    return hashlib.md5(open(out_path, "rb").read()).hexdigest().upper()


def supabase_creds():
    # Portable config: point these at ANY Supabase project's storage — the
    # printer just needs a public URL it can stream the 3mf from.
    env_url = os.environ.get("BAMBU_UPLOAD_SUPABASE_URL")
    env_key = os.environ.get("BAMBU_UPLOAD_SUPABASE_KEY")
    if env_url and env_key:
        return env_url.rstrip("/"), env_key

    # Fallback (author's machine): read the same project the fleet app uses.
    url = None
    try:
        for line in open(os.path.join(FRONTEND, ".env.local")):
            if line.startswith("NEXT_PUBLIC_SUPABASE_URL="):
                url = line.split("=", 1)[1].strip()
    except OSError:
        url = None
    key = subprocess.run(
        ["bash", "-lc", f"source ~/.nvm/nvm.sh >/dev/null 2>&1; cd '{FRONTEND}' && netlify env:get SUPABASE_SERVICE_ROLE_KEY 2>/dev/null | tail -1"],
        capture_output=True, text=True).stdout.strip()
    if not url or not key or " " in key or len(key) < 20:
        sys.exit("No upload host configured. Set BAMBU_UPLOAD_SUPABASE_URL and "
                 "BAMBU_UPLOAD_SUPABASE_KEY (service key) to any Supabase project — "
                 "bambu-print stores the .gcode.3mf in a public bucket the printer can stream.")
    return url, key


def http(method, url, key, data=None, ctype="application/json"):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}", "apikey": key,
                                          "Content-Type": ctype, "x-upsert": "true"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        return urllib.request.urlopen(req, timeout=120, context=ctx).read()
    except urllib.error.HTTPError as e:
        return e.read()


def upload(path):
    url, key = supabase_creds()
    http("POST", f"{url}/storage/v1/bucket", key,
         json.dumps({"id": BUCKET, "name": BUCKET, "public": True}).encode())  # 409 if exists = fine
    name = f"{int(time.time())}-{os.path.basename(path).replace(' ', '_')}"
    resp = http("POST", f"{url}/storage/v1/object/{BUCKET}/{name}", key,
                open(path, "rb").read(), "application/octet-stream")
    if b"error" in resp and b"Key" not in resp:
        sys.exit(f"upload failed: {resp[:300]}")
    return f"{url}/storage/v1/object/public/{BUCKET}/{name}"


def send_print(uid, serial, tok, url3mf, md5, name, use_ams):
    cmd = {"print": {
        "sequence_id": "1", "command": "project_file",
        "param": "Metadata/plate_1.gcode",
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "subtask_name": name, "file": "", "url": url3mf, "md5": md5,
        "timelapse": False, "bed_type": "auto",
        "bed_levelling": True, "flow_cali": True, "vibration_cali": True,
        "layer_inspect": True, "use_ams": bool(use_ams),
    }}
    done = {"ok": False, "reply": None}
    def on_connect(c, u, f, rc, props=None):
        if getattr(rc, "value", rc) == 0:
            c.subscribe(f"device/{serial}/report")
            c.publish(f"device/{serial}/request", json.dumps(cmd))
            done["ok"] = True
    def on_message(c, u, msg):
        try:
            d = json.loads(msg.payload.decode(errors="replace"))
        except Exception:
            return
        p = d.get("print", {})
        # the ack for our command carries the same command name + a result field
        if p.get("command") == "project_file":
            done["reply"] = p
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bp-{uid}-{int(time.time())}")
    c.username_pw_set(f"u_{uid}", tok)
    c.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(BROKER, 8883, 30); c.loop_start()
    end = time.time() + 25
    while time.time() < end and done["reply"] is None:
        time.sleep(0.2)
    c.loop_stop(); c.disconnect()
    reply = done["reply"]
    if reply is not None:
        print(f"printer reply: {json.dumps(reply)[:400]}")
        if reply.get("result") == "failed":
            if "verify" in str(reply.get("reason", "")):
                sys.exit(
                    "\nREJECTED by firmware: this X1C only accepts print-start commands signed by\n"
                    "official Bambu clients (Studio/Handy) - third-party cloud MQTT can watch but\n"
                    "not start jobs. Print this exact file from Bambu Studio instead (File > Open\n"
                    "the .gcode > Print plate), or enable LAN/Developer mode and send from a\n"
                    "machine on the printer's LAN.")
            sys.exit(f"print command failed: {reply.get('reason', 'unknown')}")
    return done["ok"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gcode")
    ap.add_argument("--go", action="store_true", help="actually start the print")
    ap.add_argument("--ams", action="store_true", help="feed from AMS (default: external spool)")
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    name = args.name or os.path.splitext(os.path.basename(args.gcode))[0]
    tok = read_token()
    uid = str(api("/v1/user-service/my/profile", tok)["uid"])
    dev = api("/v1/iot-service/api/user/bind", tok)["devices"][0]
    serial = dev["dev_id"]

    print(f"printer : {dev.get('name')} ({dev.get('dev_product_name')}) online={dev.get('online')}")
    st = status_once(uid, serial, tok)
    state = st.get("gcode_state", "?")
    print(f"state   : {fmt(st)}")
    if state in ("RUNNING", "PREPARE", "PAUSE", "SLICING"):
        sys.exit("REFUSING: printer is busy. Wait for the current job (bambu-watch).")
    if state == "FINISH":
        print("NOTE    : last job FINISHED - make sure the plate is CLEAR before --go.")

    out3mf = os.path.splitext(args.gcode)[0] + ".gcode.3mf"
    md5 = wrap_3mf(args.gcode, out3mf)
    print(f"wrapped : {out3mf} ({os.path.getsize(out3mf)//1024} KB)")
    url = upload(out3mf)
    print(f"uploaded: {url}")

    if not args.go:
        print(f"\nStaged, not started. To print:\n  bambu-print '{args.gcode}' --go{' --ams' if args.ams else ''}")
        return

    if not send_print(uid, serial, tok, url, md5, name, args.ams):
        sys.exit("MQTT publish failed")
    print("print command sent - waiting for the printer to pick it up...")
    for _ in range(18):  # ~3 min: download + bed level happen before RUNNING
        time.sleep(10)
        st = status_once(uid, serial, tok)
        print(f"  {fmt(st)}")
        if st.get("gcode_state") in ("RUNNING", "PREPARE"):
            print("STARTED. Watch it: bambu-watch")
            return
    print("No RUNNING state seen yet - check the printer screen / bambu-watch.")


if __name__ == "__main__":
    main()
