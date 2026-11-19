# -*- coding: utf-8 -*-
"""把校对页保存的时间轴写回 数据/小节时间.csv（先备份到 中间文件/小节时间_导入前_时间.csv）。
输入：校对页数据库文档 timeline/current 的 JSON（由 Claude 用 ArtifactData 读出存成文件），
      或者校对页「复制 CSV」得到的 CSV 文本文件。
用法：python3 import_times_only.py 文件.json|文件.csv
被确认的小节同时写进 数据/对齐锚点.csv，以后重新自动对齐时也保持不动。"""
import os, sys, csv, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import TIMES_CSV, MID, AUDIO_START


def fmt(t):
    t += AUDIO_START
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def parse(v):
    x = 0.0
    for p in v.strip().split(":"):
        x = x * 60 + float(p)
    return x - AUDIO_START


src = sys.argv[1]
anchors = []
if src.endswith(".json"):
    d = json.load(open(src, encoding="utf-8"))
    d = d.get("data", d)
    times = [float(v) for v in d["times"]]
    anchors = [int(a) for a in d.get("anchors", [])]
else:
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    rows = sorted(rows, key=lambda r: int(r["小节"]))
    times = [parse(r["开始"]) for r in rows]
    barnums = [int(r["小节"]) for r in rows]
    anchors = [int(r["小节"]) for r in rows if "确认" in (r.get("备注") or "")]
old = {int(r["小节"]): parse(r["开始"]) for r in csv.DictReader(open(TIMES_CSV, encoding="utf-8"))}
if src.endswith(".json"):
    barnums = sorted(old)
    anchors = [barnums[i] for i in anchors]       # 在线版存的是序号
times = dict(zip(barnums, times))
assert len(times) == len(old), f"小节数不对：{len(times)} vs {len(old)}"
tl = [times[n] for n in sorted(times)]
assert all(b > a for a, b in zip(tl, tl[1:])), "时间不是递增的"
bak = os.path.join(MID, f"小节时间_导入前_{time.strftime('%m%d_%H%M%S')}.csv")
shutil.copy(TIMES_CSV, bak)
with open(TIMES_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["小节", "开始", "备注"])
    for n in sorted(times):
        w.writerow([n, fmt(times[n]), "已确认" if n in anchors else ""])
changed = [n for n in times if abs(times[n] - old[n]) > 0.005]
print(f"写出 {TIMES_CSV}；改动 {len(changed)} 个小节，确认 {len(anchors)} 个；备份 {bak}")
if anchors:
    ap = os.path.join(os.path.dirname(TIMES_CSV), "对齐锚点.csv")
    rows = {}
    for r in csv.DictReader(open(ap, encoding="utf-8")):
        rows[int(r["小节"])] = [r["小节"], r["开始"], r.get("备注", "")]
    for n in anchors:
        rows[n] = [str(n), fmt(times[n]), "校对页确认"]
    with open(ap, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["小节", "开始", "备注"])
        for n in sorted(rows):
            w.writerow(rows[n])
    print(f"锚点更新：{ap}")
