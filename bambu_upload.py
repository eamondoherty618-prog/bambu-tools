#!/usr/bin/env python3
"""bambu-upload FILE... [--serial 562] [--ip A.B.C.D]
Upload sliced G-code to a Bambu printer's SD card over LAN FTPS (implicit TLS on port 990), using the LAN access
code fetched live from the cloud bind API (nothing is written to disk). Without --ip the local /24 is scanned for
port 990 and each candidate is tried with the access code; the one that accepts it is the right printer.
Print START stays manual (printer touchscreen: Files -> SD card), firmware rejects third-party starts (err 84033543).
"""
import argparse, ftplib, os, socket, ssl, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import bambu_cloud as bc


class ImplicitFTPS(ftplib.FTP_TLS):
    """ftplib with implicit TLS (wrap the control socket on connect). TLS 1.2 so the data channel can resume the session."""
    def __init__(self, *a, **k):
        self._sock = None
        super().__init__(*a, **k)

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, v):
        if v is not None and not isinstance(v, ssl.SSLSocket):
            v = self.context.wrap_socket(v)
        self._sock = v


def ctx12():
    c = ssl._create_unverified_context()
    c.maximum_version = ssl.TLSVersion.TLSv1_2
    return c


def access_code(suffix):
    tok = bc.read_token()
    devs = bc.api("/v1/iot-service/api/user/bind", tok).get("devices", [])
    hits = [d for d in devs if d["dev_id"].endswith(suffix)]
    if len(hits) != 1:
        sys.exit("serial %r matches %d bound printers: %s" % (suffix, len(hits), [(d["dev_id"][-3:], d.get("name")) for d in devs]))
    return hits[0]["dev_access_code"], hits[0].get("name", "")


def local_prefixes():
    out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    pre = []
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("inet ") and not ln.startswith("inet 127."):
            ip = ln.split()[1]
            p = ip.rsplit(".", 1)[0]
            if p not in pre:
                pre.append(p)
    return pre


def port_open(ip, port=990, t=0.6):
    s = socket.socket(); s.settimeout(t)
    try:
        s.connect((ip, port)); return True
    except OSError:
        return False
    finally:
        s.close()


def scan():
    cands = []
    for p in local_prefixes():
        ips = ["%s.%d" % (p, i) for i in range(1, 255)]
        with ThreadPoolExecutor(64) as ex:
            cands += [ip for ip, ok in zip(ips, ex.map(port_open, ips)) if ok]
    return cands


def login(ip, code):
    f = ImplicitFTPS(context=ctx12(), timeout=20)
    f.connect(ip, 990)
    f.login("bblp", code)
    f.prot_p()
    return f


def upload_ftplib(f, path, name):
    with open(path, "rb") as fh:
        f.storbinary("STOR " + name, fh, blocksize=65536)


def curl(ip, code, *args):
    """curl does the transfers (ftplib's data channel fails 'session reuse required' on this firmware). Credential via stdin."""
    cfg = 'user = "bblp:%s"\n' % code
    r = subprocess.run(["curl", "-sS", "--insecure", "--max-time", "600", "-K", "-", *args], input=cfg, text=True, capture_output=True)
    return r.returncode, r.stdout, r.stderr.strip()


def upload_curl(ip, code, path, name):
    rc, _, err = curl(ip, code, "-T", path, "ftps://%s:990/%s" % (ip, name))
    if rc:
        hint = ""
        if "553" in err:
            hint = ("\n    553 = the printer refused to create the file: no SD card mounted, or FTP writes are blocked because\n"
                    "    LAN 'Developer Mode' is off on this firmware (printer screen: Settings -> Network/LAN mode).")
        raise RuntimeError((err or "curl exit %d" % rc) + hint)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--serial", default=None, help="printer serial or its last digits (required if >1 printer is bound)")
    ap.add_argument("--ip", default=None, help="printer LAN IP (skips the scan)")
    a = ap.parse_args()
    for p in a.files:
        if not os.path.isfile(p):
            sys.exit("no such file: " + p)
    code, pname = access_code(a.serial or "")
    ips = [a.ip] if a.ip else scan()
    if not ips:
        sys.exit("no host answers on port 990 in %s - is the Mac on the printer's LAN?" % local_prefixes())
    f = ip = None
    for cand in ips:
        try:
            f = login(cand, code); ip = cand; break
        except Exception as e:
            print("  %s: %s" % (cand, str(e).strip()[:80]))
    if f is None:
        sys.exit("no printer on %s accepted the access code for %s" % (ips, pname))
    print("printer %s at %s (FTPS login ok)" % (pname, ip))
    rc, listing, err = curl(ip, code, "ftps://%s:990/" % ip)
    print("  SD root: %s" % (", ".join(l.split()[-1] for l in listing.splitlines()[:12]) or "(empty - is the SD card in?)"))
    for p in a.files:
        name = os.path.basename(p).replace(" ", "_")
        size = os.path.getsize(p)
        try:
            upload_curl(ip, code, p, name)
        except RuntimeError as e:
            sys.exit("  FAILED %s: %s" % (name, e))
        print("  uploaded %-45s %7.1f MB" % (name, size / 1e6))
    try:
        f.quit()
    except Exception:
        pass
    print("Start it on the printer touchscreen: Files -> SD card -> the file above.")


if __name__ == "__main__":
    main()
