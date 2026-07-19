#!/usr/bin/env python3
"""
bambu-watch: watch the X1C over Bambu's cloud and push a phone notification (via
ntfy.sh) when the current print finishes or fails. Reading status is NOT gated by
Bambu's auth system, so this works from anywhere.

    bambu-watch [--topic NTFY_TOPIC] [--interval SECONDS] [--forever]

Start it after you send a print (from Bambu Handy/Studio), then walk away.
Subscribe on your phone: install the free "ntfy" app and add the topic.

NOTE: actually *starting* a print from a third-party tool is blocked by Bambu's
2025 authorization system (needs Bambu Connect + signed commands), so this only
watches + notifies; it can't launch the job.
"""
import argparse, ssl, time, urllib.request, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bambu_cloud

def default_topic():
    """Your ntfy topic acts like a password, so it's kept out of the repo:
    env BAMBU_NTFY_TOPIC > ~/bambu-tools/ntfy_topic.txt > a generic fallback."""
    env = os.environ.get("BAMBU_NTFY_TOPIC")
    if env:
        return env.strip()
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ntfy_topic.txt")
    if os.path.exists(f):
        return open(f).read().strip()
    return "bambu-x1c-please-change-me"

def ntfy(topic, title, msg, priority="default", tags=""):
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=msg.encode(),
        headers={"Title": title, "Priority": priority, "Tags": tags})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print("  ntfy failed:", e); return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default=default_topic())
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--forever", action="store_true",
                    help="keep watching for further prints instead of exiting after one")
    args = ap.parse_args()

    tok = bambu_cloud.read_token()
    uid = str(bambu_cloud.api("/v1/user-service/my/profile", tok)["uid"])
    dev = bambu_cloud.api("/v1/iot-service/api/user/bind", tok)["devices"][0]
    serial = dev["dev_id"]
    print(f"watching {dev.get('name')} -> phone alerts on ntfy.sh/{args.topic}")
    print("(subscribe in the ntfy app; Ctrl-C to stop)")

    last, notified = None, False
    while True:
        p = bambu_cloud.status_once(uid, serial, tok)
        state = p.get("gcode_state")
        pct = p.get("mc_percent")
        job = p.get("subtask_name") or "print"
        if state != last:
            print(time.strftime("%H:%M:%S"), state or "offline", f"{pct}%" if pct is not None else "")
            last = state
        if state in ("RUNNING", "PREPARE", "SLICING", "PAUSE"):
            notified = False
        if state in ("FINISH", "FAILED") and not notified:
            if state == "FINISH":
                ntfy(args.topic, "Print done ✅", f"{job} finished on the X1C.", "high", "white_check_mark,printer")
            else:
                ntfy(args.topic, "Print FAILED ❌", f"{job} failed (error {p.get('print_error')}).",
                     "urgent", "x,printer")
            print("  notified.")
            notified = True
            if not args.forever:
                break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
