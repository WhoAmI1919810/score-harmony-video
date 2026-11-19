# -*- coding: utf-8 -*-
"""重读和声用的缩谱图：不印任何候选和弦，只印小节号（读谱音名可选、淡色）。
每个系统截全部谱表，相邻系统拼在一张图里（图高不超过 2600）。输出 中间文件/重读图/pNNN_k.png
用法：python3 reread_sheets.py 起页 止页 [--names]"""
import os, sys, csv, json
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, BARS_CSV, FONT_DIR
import textdoc

OUT = os.path.join(MID, "重读图"); os.makedirs(OUT, exist_ok=True)
p0, p1 = int(sys.argv[1]), int(sys.argv[2]); NAMES = "--names" in sys.argv
rows = list(csv.DictReader(open(BARS_CSV, encoding="utf-8")))
st = json.load(open(os.path.join(MID, "staves.json")))
font = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 36)
nf = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 17)
for p in range(p0, p1 + 1):
    img = Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("RGB")
    d0 = ImageDraw.Draw(img)
    crops = []
    for si, sy in enumerate(st.get(str(p), []), start=1):
        rs = [r for r in rows if int(r["page"]) == p and int(r["system"]) == si]
        if not rs:
            continue
        if NAMES:
            fn = os.path.join(MID, "omr", f"p{p:03d}_s{si}.json")
            for n in (json.load(open(fn)) if os.path.exists(fn) else []):
                d0.text((n["x"] + 9, n["y"] - 10), (n.get("name") or "").replace("#", "♯").replace("b", "♭"),
                        fill=(220, 120, 120) if n.get("acc") else (110, 170, 110), font=nf)
        sp = (sy[0][-1] - sy[0][0]) / 4
        y0 = int(sy[0][0] - 7 * sp); y1 = int(sy[-1][-1] + 6 * sp)
        x0 = max(0, min(int(r["x0"]) for r in rs) - 150); x1 = min(img.width, max(int(r["x1"]) for r in rs) + 20)
        c0 = img.crop((x0, max(0, y0), x1, min(img.height, y1)))
        c = Image.new("RGB", (c0.width, c0.height + 46), "white"); c.paste(c0, (0, 46))
        d = ImageDraw.Draw(c)
        for r in rs:
            bx = int(r["x0"]) - x0
            d.line([(bx, 46), (bx, c.height)], fill=(90, 90, 240), width=1)
            lab = textdoc.short_label(int(r["bar"]))
            d.text((bx + 5, 2), lab, fill=(40, 40, 220), font=font)
        crops.append(c)
    groups, cur, h = [], [], 0
    for c in crops:
        if cur and h + c.height > 2600:
            groups.append(cur); cur, h = [], 0
        cur.append(c); h += c.height + 12
    if cur:
        groups.append(cur)
    for k, g in enumerate(groups, 1):
        W = max(c.width for c in g); H = sum(c.height + 12 for c in g)
        sh = Image.new("RGB", (W, H), "white"); y = 0
        for c in g:
            sh.paste(c, (0, y)); y += c.height + 12
        sh.save(os.path.join(OUT, f"p{p:03d}_{k}.png"))
    print(p, len(groups), end="; ")
