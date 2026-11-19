# 找漏掉的小节线：每个小节内部（离两边 60 像素以上）找竖直墨迹覆盖率最高的列。python3 fs_missing.py 页...（先跑一次 fs_fix.py 生成 中间文件/总谱/_合并后.csv）
import os, sys, csv, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID
from PIL import Image
rows = list(csv.DictReader(open(os.path.join(MID, "总谱", "_合并后.csv"), encoding="utf-8")))
for p in map(int, sys.argv[1:]):
    ink = np.array(Image.open(os.path.join(MID, "总谱_deskew", f"p{p:03d}.png")).convert("L")) < 128
    out = []
    for r in rows:
        if int(r["page"]) != p:
            continue
        x0, x1, y0, y1 = (int(r[k]) for k in ("x0", "x1", "y0", "y1"))
        cov = ink[y0:y1, :].mean(axis=0)
        cov3 = np.maximum(np.maximum(cov[:-2], cov[1:-1]), cov[2:])
        # 边上的小节线覆盖率作参照
        ref = max(cov3[max(x1 - 8, 0):x1 + 8].max(), 1e-6)
        seg = cov3[x0 + 60:x1 - 60]
        if len(seg) == 0:
            continue
        j = int(seg.argmax()) + x0 + 61
        out.append((float(seg.max()) / ref, j, r["bar"], x0, x1))
    out.sort(reverse=True)
    print(p, [(round(a, 2), j, b, x0, x1) for a, j, b, x0, x1 in out[:3]])
