# -*- coding: utf-8 -*-
"""总谱读谱图（整个系统）：python3 fs_view.py 起小节 止小节 [上 下（系统高度比例，默认 0 1）] [宽=1900]
小节写 II-n 或连续编号；起止须在同一页同一系统。不印任何候选和弦，只印小节号和现在写的和弦（灰色，放在最上方，方便对照）。
→ 中间文件/总谱读谱/view.png"""
import os, sys, csv
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FONT_DIR
import glob
import textdoc
import make_text as mt


def bar(t):
    return textdoc.PART2_BAR - 1 + int(t[3:]) if t.upper().startswith("II-") else int(t.replace("I-", ""))


a, z = bar(sys.argv[1]), bar(sys.argv[2])
f0 = float(sys.argv[3]) if len(sys.argv) > 4 else 0.0
f1 = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
W = int(sys.argv[5]) if len(sys.argv) > 5 else 1900
rows = [r for r in csv.DictReader(open(os.path.join(DATA, "总谱小节位置.csv"), encoding="utf-8")) if a <= int(r["bar"]) <= z]
p, s = int(rows[0]["page"]), int(rows[0]["system"])
rows = [r for r in rows if int(r["page"]) == p and int(r["system"]) == s]
im = Image.open(os.path.join(MID, "总谱_deskew", f"p{p:03d}.png")).convert("RGB")
Y0, Y1 = int(rows[0]["y0"]) - 90, int(rows[0]["y1"]) + 60
y0, y1 = int(Y0 + (Y1 - Y0) * f0), int(Y0 + (Y1 - Y0) * f1)
x0 = max(0, int(rows[0]["x0"]) - (230 if int(rows[0]["x0"]) < 500 else 20)); x1 = int(rows[-1]["x1"]) + 10
c = im.crop((x0, max(0, y0), x1, min(im.height, y1)))
k = min(2.0, W / c.width)
c = c.resize((int(c.width * k), int(c.height * k)), Image.LANCZOS)
chords = {}
for fn in [os.path.join(DATA, "和弦_人工.txt")] + sorted(f for f in glob.glob(os.path.join(DATA, "和弦_*.txt")) if not f.endswith("和弦_人工.txt")):
    mt.CHORDS_TXT = fn; chords.update(mt.load_chords())
fb = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 26)
fs = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 17)
pad = 64
can = Image.new("RGB", (c.width, c.height + pad), "white"); can.paste(c, (0, pad)); d = ImageDraw.Draw(can)
for r in rows:
    bx = (int(r["x0"]) - x0) * k
    d.line([(bx, pad), (bx, can.height)], fill=(120, 120, 245), width=1)
    d.text((bx + 4, 0), textdoc.short_label(int(r["bar"])), fill=(40, 40, 220), font=fb)
    v = chords.get(int(r["bar"]))
    if v:
        d.text((bx + 4, 34), " | ".join(f"{q[0]:g} {q[2] or q[1]}" for q in v["chords"]), fill=(150, 150, 150), font=fs)
os.makedirs(os.path.join(MID, "总谱读谱"), exist_ok=True)
out = os.path.join(MID, "总谱读谱", "view.png"); can.save(out); print(out, can.size, "pdf 页", p)
