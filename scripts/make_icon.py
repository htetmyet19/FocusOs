"""Draw the FocusOs app icon (tracker/dashboard/focusos.ico).

Same mark as the dashboard's favicon: a lavender ring with a violet arc from
12 o'clock to about 4 o'clock, on a deep-violet rounded square so it reads on
both light and dark taskbars. Needs Pillow (dev only):  pip install pillow
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "tracker" / "dashboard" / "focusos.ico"
S = 1024                                   # draw big, scale down = smooth edges

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill="#1E1650")

box = [S * 0.19, S * 0.19, S * 0.81, S * 0.81]
w = int(S * 0.13)
d.ellipse(box, outline="#3A2F80", width=w)                 # the full ring (track)
d.arc(box, start=-90, end=18, fill="#8B71FF", width=w)      # the arc: 12 o'clock -> ~4 o'clock
# round caps on the arc ends (PIL arcs have square ends)
cx = cy = S / 2
for ang in (-90, 18):
    a = math.radians(ang)
    x, y = cx + (S * 0.31 - w / 2) * math.cos(a), cy + (S * 0.31 - w / 2) * math.sin(a)
    d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="#8B71FF")

img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(OUT.with_suffix(".png"))
print(f"wrote {OUT}")
