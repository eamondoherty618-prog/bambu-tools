"""drive.py front | activate PID | click X Y [PID] | shot PATH  (logical screen coords; click refuses unless Studio is frontmost)"""
import sys, time, subprocess
from AppKit import NSWorkspace, NSRunningApplication, NSApplicationActivateIgnoringOtherApps
import Quartz
def front():
    a = NSWorkspace.sharedWorkspace().frontmostApplication(); return a.localizedName(), a.processIdentifier()
cmd = sys.argv[1]
if cmd == "front":
    print(*front())
elif cmd == "activate":
    pid = int(sys.argv[2]); app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    print("activate ->", app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)); time.sleep(1.5); print(*front())
elif cmd == "click":
    x, y = float(sys.argv[2]), float(sys.argv[3]); name, pid = front()
    if name.replace(" ", "") != "BambuStudio" or (len(sys.argv) > 4 and pid != int(sys.argv[4])):
        print("REFUSED: frontmost is", name, pid); sys.exit(2)
    pt = Quartz.CGPointMake(x, y)
    for t, b in ((Quartz.kCGEventMouseMoved, 0), (Quartz.kCGEventLeftMouseDown, 1), (Quartz.kCGEventLeftMouseUp, 1)):
        e = Quartz.CGEventCreateMouseEvent(None, t, pt, Quartz.kCGMouseButtonLeft); Quartz.CGEventPost(Quartz.kCGHIDEventTap, e); time.sleep(0.08)
    print("clicked", x, y, "in", name, pid)
elif cmd == "shot":
    r = subprocess.run(["screencapture", "-x", "-C", sys.argv[2]], capture_output=True, text=True); print("shot rc", r.returncode, r.stderr.strip())
if cmd == "move":
    x, y = float(sys.argv[2]), float(sys.argv[3])
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft)); print("moved", x, y)
