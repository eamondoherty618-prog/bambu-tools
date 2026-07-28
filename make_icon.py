#!/usr/bin/env python3
"""
Generate the Dock icon for "Optimize for X1C.app".

    venv/bin/python make_icon.py            # writes icon.png + AppIcon.icns
    ./install_icon.sh                       # drops it into the .app and refreshes the Dock

Design: a nozzle laying a bright filament trace over a layered part, on a dark
squircle. Kept to big shapes and high contrast so it still reads at 32 px.
Drawn at 4x and downsampled for clean edges.
"""
from PIL import Image, ImageDraw
import os

S = 1024          # final size
SS = 4            # supersample factor
W = S * SS

BG_TOP    = (34, 41, 51)
BG_BOT    = (16, 20, 26)
FILAMENT  = (0, 200, 120)      # bright green extrusion
FIL_DARK  = (0, 150, 92)
NOZZLE    = (214, 220, 228)
NOZZLE_SH = (150, 158, 168)
PLATE     = (92, 102, 116)

img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- background squircle with a vertical gradient ---
grad = Image.new("RGB", (1, W))
gd = ImageDraw.Draw(grad)
for y in range(W):
    t = y / W
    gd.point((0, y), fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
grad = grad.resize((W, W))
mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=int(W * 0.225), fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)

cx = W // 2

# --- the layered part being printed: stacked bars, widest at the bottom ---
layer_h   = int(W * 0.060)
gap       = int(W * 0.018)
base_y    = int(W * 0.775)
widths    = [0.56, 0.52, 0.45, 0.38, 0.30]      # bottom -> top
for i, wfrac in enumerate(widths):
    hw = int(W * wfrac / 2)
    y1 = base_y - i * (layer_h + gap)
    y0 = y1 - layer_h
    shade = FILAMENT if i % 2 == 0 else FIL_DARK
    d.rounded_rectangle([cx - hw, y0, cx + hw, y1], radius=layer_h // 2, fill=shade)

# --- build plate under it ---
pw = int(W * 0.70 / 2)
py = base_y + int(W * 0.028)
d.rounded_rectangle([cx - pw, py, cx + pw, py + int(W * 0.030)],
                    radius=int(W * 0.015), fill=PLATE)

# --- nozzle above, laying the next layer ---
top_layer_y = base_y - (len(widths) - 1) * (layer_h + gap) - layer_h
noz_bot = top_layer_y - int(W * 0.045)
body_hw = int(W * 0.115)
tip_hw  = int(W * 0.030)
body_top = noz_bot - int(W * 0.165)
# tapered body
d.polygon([(cx - body_hw, body_top), (cx + body_hw, body_top),
           (cx + tip_hw, noz_bot), (cx - tip_hw, noz_bot)], fill=NOZZLE)
# heater block
blk_hw = int(W * 0.140)
d.rounded_rectangle([cx - blk_hw, body_top - int(W * 0.075),
                     cx + blk_hw, body_top + int(W * 0.012)],
                    radius=int(W * 0.020), fill=NOZZLE_SH)
# filament strand from tip to the layer below
d.rounded_rectangle([cx - int(W * 0.016), noz_bot,
                     cx + int(W * 0.016), top_layer_y + int(W * 0.004)],
                    radius=int(W * 0.016), fill=FILAMENT)

img = img.resize((S, S), Image.LANCZOS)
here = os.path.dirname(os.path.abspath(__file__))
png = os.path.join(here, "icon.png")
img.save(png)

# --- build the .icns ---
iconset = os.path.join(here, "AppIcon.iconset")
os.makedirs(iconset, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    img.resize((size, size), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}.png")
    img.resize((size * 2, size * 2), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}@2x.png")
os.system(f'iconutil -c icns "{iconset}" -o "{os.path.join(here, "AppIcon.icns")}"')
print("wrote icon.png and AppIcon.icns")
