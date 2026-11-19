# -*- coding: utf-8 -*-
"""总谱核对图：python3 fs_sheet.py 总谱页 → 中间文件/总谱核对图/fNNN_a.png、_b.png（左右两半，原分辨率）
每小节画边框，顶上写小节号和 数据/和弦_人工.txt 里现在的和弦。"""
import os, sys, csv
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FONT_DIR
import textdoc
from make_text import load_chords
p = int(sys.argv[1])
OUTD = os.path.join(MID, "总谱核对图"); os.makedirs(OUTD, exist_ok=True)
im = Image.open(os.path.join(MID, "总谱页", f"f{p:03d}.png")).convert("RGB")
W, H = im.size
ch = load_chords()
rows = [r for r in csv.DictReader(open(os.path.join(DATA, "总谱小节位置.csv"), encoding="utf-8")) if int(r["page"]) == p]
pad = 120
can = Image.new("RGB", (W, H + pad), "white"); can.paste(im, (0, pad))
d = ImageDraw.Draw(can)
f1 = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 22)
f2 = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 19)
from common import FULL_UPSCALE
dw = float(FULL_UPSCALE)   # 小节坐标量在放大去斜后的页上
for r in rows:
    b = int(r["bar"]); x0, x1 = int(r["x0"]) / dw, int(r["x1"]) / dw
    y0, y1 = int(r["y0"]) / dw + pad, int(r["y1"]) / dw + pad
    d.rectangle([x0, y0, x1, y1], outline=(40, 70, 220), width=2)
    sysno = int(r["system"])
    ty = 4 if sysno == 1 else y0 - 52
    d.text((x0 + 4, ty), textdoc.short_label(b), font=f1, fill=(40, 70, 220))
    v = ch.get(b)
    if v:
        s = " | ".join(f"{c[0]:g} {c[1]} {c[2]}" for c in v["chords"])
        d.text((x0 + 4, ty + 28), s, font=f2, fill=(170, 70, 0))
half = W // 2
can.crop((0, 0, half + 60, H + pad)).save(os.path.join(OUTD, f"f{p:03d}_a.png"))
can.crop((half - 60, 0, W, H + pad)).save(os.path.join(OUTD, f"f{p:03d}_b.png"))
print(OUTD, [int(r["bar"]) for r in rows][:1], [int(r["bar"]) for r in rows][-1:])
