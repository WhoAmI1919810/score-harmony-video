# -*- coding: utf-8 -*-
"""找乐谱页上的排练号方框（空心矩形，里面是数字），按横坐标归到小节。用来在两份总谱之间核对小节编号：
排练号在两版里是同一处，旧总谱的小节编号已逐页核对过。
python3 rehearsal.py 页图目录 小节位置.csv 输出.csv [起页 止页]   （输出列 page,x,y,w,h,bar,dx）
两份谱都跑一次，再用 compare_rehearsal.py 比较：排练号归到的小节号应当一致，不一致的地方就是某一份多了或少了小节。
页图目录里的文件名是 pNNN.png（去斜后的页），小节坐标和页图同一尺度。"""
import os, sys, csv, glob
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA

PAGES, BARS, OUTCSV = sys.argv[1], sys.argv[2], sys.argv[3]
rows = list(csv.DictReader(open(BARS, encoding="utf-8")))
bypage = {}
for r in rows:
    bypage.setdefault(int(r["page"]), []).append(r)
pages = sorted(bypage)
if len(sys.argv) > 5:
    pages = [p for p in pages if int(sys.argv[4]) <= p <= int(sys.argv[5])]


def boxes(ink, sp):
    lab, n = ndi.label(ink)
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        h = sl[0].stop - sl[0].start; w = sl[1].stop - sl[1].start
        if not (3.0 * sp <= h <= 7 * sp and 2.8 * sp <= w <= 13 * sp):
            continue
        c = lab[sl] == i
        t = max(2, int(sp * 0.35))
        edges = [c[:t].any(0).mean(), c[-t:].any(0).mean(), c[:, :t].any(1).mean(), c[:, -t:].any(1).mean()]
        fill = c.mean()
        if min(edges) > 0.85 and fill < 0.45:
            inner = ink[sl][t + 1:-t - 1, t + 1:-t - 1]
            if inner.size and inner.mean() > 0.04:          # 里面有数字
                out.append((sl[1].start, sl[0].start, w, h))
    return out


res = []
for p in pages:
    fn = os.path.join(PAGES, f"p{p:03d}.png")
    if not os.path.exists(fn):
        continue
    ink = np.array(Image.open(fn).convert("L")) < 128
    rs = bypage[p]
    # 谱线间距：用小节框高度估不准，直接从谱线投影估
    prof = ink[:, ink.shape[1] // 3: 2 * ink.shape[1] // 3].mean(1)
    peaks = np.where((prof > 0.5) & (prof >= np.roll(prof, 1)) & (prof >= np.roll(prof, -1)))[0]
    d = np.diff(peaks); d = d[(d > 5) & (d < 40)]
    sp = float(np.median(d)) if len(d) else 14.0
    for (x, y, w, h) in boxes(ink, sp):
        cx, cy = x + w / 2, y + h / 2
        cand = [r for r in rs if int(r["y0"]) - 10 * sp <= cy <= int(r["y1"]) + 2 * sp]
        if not cand:
            continue
        r = min(cand, key=lambda r: (abs(int(r["x0"]) - cx), abs(int(r["y0"]) - cy)))
        res.append(dict(page=p, x=x, y=y, w=w, h=h, bar=int(r["bar"]), dx=round(cx - int(r["x0"]))))
    print(p, sum(1 for q in res if q["page"] == p), end="; ", flush=True)
out = OUTCSV
with open(out, "w", newline="", encoding="utf-8") as f:
    wr = csv.DictWriter(f, fieldnames=["page", "x", "y", "w", "h", "bar", "dx"]); wr.writeheader(); wr.writerows(res)
print("\n写出", out, len(res), "个框，涉及", len({q["bar"] for q in res}), "个小节")
