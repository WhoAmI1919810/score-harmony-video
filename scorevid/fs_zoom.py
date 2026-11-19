# -*- coding: utf-8 -*-
"""总谱放大核对：python3 fs_zoom.py 起小节 止小节 [y0比例 y1比例] [倍数=1.6]
→ 中间文件/总谱核对图/zoom.png。起止小节须在同一总谱页的同一系统；顶上逐行写每小节现在的和弦。
y0 y1 是系统高度里的比例（0 = 系统顶，1 = 系统底），用来分段看（如 0 0.5、0.5 1）。"""
import os, sys, csv
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FONT_DIR
import textdoc
from make_text import load_chords
a, z = int(sys.argv[1]), int(sys.argv[2])
fy0 = float(sys.argv[3]) if len(sys.argv) > 4 else 0.0
fy1 = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
k = float(sys.argv[5]) if len(sys.argv) > 5 else 1.6
rows = [r for r in csv.DictReader(open(os.path.join(DATA, "总谱小节位置.csv"), encoding="utf-8")) if a <= int(r["bar"]) <= z]
p = int(rows[0]["page"]); s = int(rows[0]["system"])
rows = [r for r in rows if int(r["page"]) == p and int(r["system"]) == s]
im = Image.open(os.path.join(MID, "总谱_deskew", f"p{p:03d}.png")).convert("RGB")   # 小节坐标量在去斜页上
im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
from common import FULL_UPSCALE
dw = float(FULL_UPSCALE)
X0 = int(rows[0]["x0"]) / dw - 30; X1 = int(rows[-1]["x1"]) / dw + 10
Y0s, Y1s = int(rows[0]["y0"]) / dw - 30, int(rows[0]["y1"]) / dw + 30
Y0 = Y0s + (Y1s - Y0s) * fy0; Y1 = Y0s + (Y1s - Y0s) * fy1
if fy0 == 0:
    X0 = max(0, min(X0, 0)) if int(rows[0]["bar"]) == a and rows[0] is rows[0] else X0
crop = im.crop((int(max(0, X0)), int(max(0, Y0)), int(min(im.width, X1)), int(min(im.height, Y1))))
crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
ch = load_chords()
f1 = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 22)
f2 = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 18)
nl = max(len(ch.get(int(r["bar"]), {"chords": []})["chords"]) for r in rows)
pad = 34 + 24 * nl
can = Image.new("RGB", (crop.width, crop.height + pad), "white"); can.paste(crop, (0, pad))
d = ImageDraw.Draw(can)
for r in rows:
    b = int(r["bar"]); x0 = (int(r["x0"]) / dw - max(0, X0)) * k; x1 = (int(r["x1"]) / dw - max(0, X0)) * k
    d.line([(x0, pad), (x0, can.height)], fill=(60, 90, 230), width=1)
    d.text((x0 + 3, 2), textdoc.short_label(b), font=f1, fill=(40, 70, 220))
    for i, c in enumerate(ch.get(b, {"chords": []})["chords"]):
        d.text((x0 + 3, 30 + 24 * i), f"{c[0]:g} {c[1]} {c[2]}", font=f2, fill=(170, 70, 0))
out = os.path.join(MID, "总谱核对图", "zoom.png"); os.makedirs(os.path.dirname(out), exist_ok=True)
can.save(out); print(out, can.size, "页", p, "系统", s)
