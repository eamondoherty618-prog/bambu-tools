#!/usr/bin/env python3
"""
bambu_cloud: live status of the home X1C via Bambu's cloud MQTT broker.
Works from anywhere (no LAN / VLAN access needed) as long as Bambu Studio is
logged in on this Mac. Reuses that session token; no separate login.

    bambu_cloud.py            # one-shot status
    bambu_cloud.py --watch    # poll every 20s until Ctrl-C
"""
import argparse, json, ssl, struct, sys, time, urllib.request
import paho.mqtt.client as mqtt
import certifi

COOKIES = f"{__import__('os').path.expanduser('~')}/Library/HTTPStorages/com.bambulab.bambu-studio.binarycookies"
BROKER = "us.mqtt.bambulab.com"

def read_token():
    data = open(COOKIES, "rb").read()
    npg = struct.unpack(">i", data[4:8])[0]
    sizes = [struct.unpack(">i", data[8+4*i:12+4*i])[0] for i in range(npg)]
    off = 8 + 4*npg
    for size in sizes:
        page = data[off:off+size]; off += size
        n = struct.unpack("<i", page[4:8])[0]
        for i in range(n):
            co = struct.unpack("<i", page[8+4*i:12+4*i])[0]
            c = page[co:]; clen = struct.unpack("<i", c[0:4])[0]; c = c[:clen]
            _url, no, _path, vo = struct.unpack("<4i", c[16:32])
            name = c[no:c.index(b"\x00", no)].decode(errors="replace")
            if name == "token":
                return c[vo:c.index(b"\x00", vo)].decode(errors="replace")
    sys.exit("No Bambu token in cookies - open Bambu Studio and log in.")

def get_uid():
    return str(api("/v1/user-service/my/profile", read_token())["uid"])

def api(path, tok):
    req = urllib.request.Request("https://api.bambulab.com" + path,
                                 headers={"Authorization": f"Bearer {tok}", "User-Agent": "BambuStudio"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    return json.load(urllib.request.urlopen(req, timeout=15, context=ctx))

def status_once(uid, serial, tok):
    got = {"d": None}
    def on_connect(c, u, f, rc, props=None):
        if getattr(rc, "value", rc) == 0:
            c.subscribe(f"device/{serial}/report")
            c.publish(f"device/{serial}/request",
                      json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
    def on_message(c, u, msg):
        if got["d"] is None:
            got["d"] = json.loads(msg.payload.decode(errors="replace"))
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bt-{uid}-{int(time.time())}")
    c.username_pw_set(f"u_{uid}", tok)
    c.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(BROKER, 8883, 30); c.loop_start()
    end = time.time() + 12
    while time.time() < end and got["d"] is None:
        time.sleep(0.2)
    c.loop_stop(); c.disconnect()
    return (got["d"] or {}).get("print", {})

def fmt(p):
    if not p:
        return "no telemetry (printer offline or idle-quiet)"
    return (f"{p.get('gcode_state','?'):8} | {p.get('subtask_name') or p.get('gcode_file','-')} | "
            f"{p.get('mc_percent','?')}% L{p.get('layer_num','?')}/{p.get('total_layer_num','?')} | "
            f"{p.get('mc_remaining_time','?')}min left | "
            f"noz {p.get('nozzle_temper','?')}/{p.get('nozzle_target_temper','?')} "
            f"bed {p.get('bed_temper','?')}/{p.get('bed_target_temper','?')} | "
            f"err {p.get('print_error','?')}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()
    tok = read_token()
    prof = api("/v1/user-service/my/profile", tok)
    uid = str(prof["uid"])
    dev = api("/v1/iot-service/api/user/bind", tok)["devices"][0]
    serial = dev["dev_id"]
    print(f"# {dev.get('name')} ({dev.get('dev_product_name')})  online={dev.get('online')}  uid={uid}")
    while True:
        print(time.strftime("%H:%M:%S "), fmt(status_once(uid, serial, tok)), flush=True)
        if not args.watch:
            break
        time.sleep(20)

if __name__ == "__main__":
    main()
