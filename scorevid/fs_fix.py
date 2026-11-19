# 总谱小节：合并两段识别结果 + 应用 数据/总谱小节修正.txt → 数据/总谱小节位置.csv
#   格式同 小节修正.txt：去线 页 y x / 加线 页 y x（坐标是 中间文件/总谱_deskew 页图上的像素）
# 用法：python3 fs_fix.py [--write]（不加 --write 只打印核对结果）
import os, sys, csv, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA
EDITS = os.path.join(DATA, "总谱小节修正.txt")
OUT = os.path.join(DATA, "总谱小节位置.csv")
rows = []
for fn in sorted(glob.glob(os.path.join(MID, "总谱", "部分识别_*.csv"))):
    rows += list(csv.DictReader(open(fn, encoding="utf-8")))
for r in rows:
    for k in ("page", "system", "x0", "x1", "y0", "y1"):
        r[k] = int(r[k])
sysmap = {}
for r in rows:
    sysmap.setdefault((r["page"], r["system"]), []).append(r)
# 同一页上下相邻的两个"系统"小节线位置全都一样（差 12 像素以内）→ 其实是一个系统被谱表间的空隙断开，合并
for p in sorted({k[0] for k in sysmap}):
    ks = sorted(k for k in sysmap if k[0] == p)
    i = 0
    while i + 1 < len(ks):
        a, b = sysmap[ks[i]], sysmap[ks[i + 1]]
        if len(a) == len(b) and all(abs(x["x1"] - y["x1"]) <= 12 for x, y in zip(a[:-1], b[:-1])):
            for x, y in zip(a, b):
                x["y1"] = y["y1"]; x["x0"] = min(x["x0"], y["x0"])
            del sysmap[ks[i + 1]]; ks.pop(i + 1)
            print(f"p{p}: 合并系统 {ks[i][1]} 与下一个（小节线一致）")
        else:
            i += 1
edits = []
if os.path.exists(EDITS):
    for l in open(EDITS, encoding="utf-8"):
        t = l.split("#")[0].split()
        if len(t) == 4 and t[0] in ("去线", "加线"):
            edits.append((t[0], int(t[1]), int(t[2]), int(t[3])))
for op, p, y, x in edits:
    cands = [k for k in sysmap if k[0] == p and sysmap[k][0]["y0"] - 40 <= y <= sysmap[k][0]["y1"] + 40]
    if not cands:
        print("找不到系统", op, p, y, x); continue
    bars = sysmap[cands[0]]
    if op == "去线":
        k = min(range(len(bars) - 1), key=lambda i: abs(bars[i]["x1"] - x))
        bars[k]["x1"] = bars[k + 1]["x1"]; del bars[k + 1]
    else:
        k = next((i for i, b in enumerate(bars) if b["x0"] < x < b["x1"]), None)
        if k is None:
            print("加线位置不在小节里", p, y, x); continue
        nb = dict(bars[k]); nb["x0"] = x; bars[k]["x1"] = x; bars.insert(k + 1, nb)
out = []
for key in sorted(sysmap):
    out += sysmap[key]
for i, r in enumerate(out, 1):
    r["bar"] = i
from common import cfg
import textdoc
print("小节总数", len(out), "（应", int(cfg("total_bars") or textdoc.LAST_BAR or 0), "）")
if "--write" in sys.argv:
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bar", "page", "system", "x0", "x1", "y0", "y1"]); w.writeheader()
        for r in out:
            w.writerow({k: r[k] for k in w.fieldnames})
    print("写出", OUT)
tmp = os.path.join(MID, "总谱", "_合并后.csv")
with open(tmp, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["bar", "page", "system", "x0", "x1", "y0", "y1"]); w.writeheader()
    for r in out:
        w.writerow({k: r[k] for k in w.fieldnames})
os.system(f"python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fs_check.py')} {tmp} | tail -n +1")
