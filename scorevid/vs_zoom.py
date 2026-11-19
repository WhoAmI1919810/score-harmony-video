# -*- coding: utf-8 -*-
"""放大看几个小节：python3 vs_zoom.py 起小节 止小节 [行数=3]  → 中间文件/核对图/vs_zoom.png（带读谱音名）"""
import os, sys, csv, json
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, BARS_CSV, FONT_DIR
a, z = int(sys.argv[1]), int(sys.argv[2]); nrows = int(sys.argv[3]) if len(sys.argv) > 3 else 3
rows = [r for r in csv.DictReader(open(BARS_CSV, encoding="utf-8")) if a <= int(r["bar"]) <= z]
st = json.load(open(os.path.join(MID, "staves.json")))
nf = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 17)
bf = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 30)
out = []
for key in sorted({(int(r["page"]), int(r["system"])) for r in rows}):
    p, s = key
    rs = [r for r in rows if (int(r["page"]), int(r["system"])) == key]
    img = Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("RGB")
    d = ImageDraw.Draw(img)
    fn = os.path.join(MID, "omr", f"p{p:03d}_s{s}.json")
    sy = st[str(p)][s - 1]
    for n in (json.load(open(fn)) if os.path.exists(fn) else []):
        if n["staff"] > len(sy) - nrows:
            d.text((n["x"] + 9, n["y"] - 10), (n.get("name") or "").replace("b", "♭").replace("#", "♯"),
                   fill=(200, 0, 0) if n.get("acc") else (0, 110, 0), font=nf)
    x0 = min(int(r["x0"]) for r in rs) - 30; x1 = max(int(r["x1"]) for r in rs) + 10
    take = sy[-nrows:]; sp = (take[0][-1] - take[0][0]) / 4
    y0 = int(take[0][0] - 5 * sp) - 40; y1 = int(sy[-1][-1] + 6 * sp)
    for r in rs:
        d.line([(int(r["x0"]), y0 + 40), (int(r["x0"]), y1)], fill=(60, 60, 230), width=2)
        d.text((int(r["x0"]) + 6, y0), r["bar"], fill=(40, 40, 220), font=bf)
    c = img.crop((max(0, x0), max(0, y0), x1, y1))
    sc = min(1.6, 1800 / c.width)
    out.append(c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS))
W = max(c.width for c in out); H = sum(c.height + 10 for c in out)
sh = Image.new("RGB", (W, H), "white"); y = 0
for c in out:
    sh.paste(c, (0, y)); y += c.height + 10
os.makedirs(os.path.join(MID, "核对图"), exist_ok=True); sh.save(os.path.join(MID, "核对图", "vs_zoom.png")); print(os.path.join(MID, "核对图", "vs_zoom.png"))
print(sh.size)
