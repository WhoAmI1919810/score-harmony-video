# 总谱小节识别与页首小节号（数据/总谱页首小节.txt）对照：python3 fs_check.py [csv...]
# 不给参数时合并 中间文件/总谱/部分识别_*.csv（后一个文件的编号接在前一个后面）
import os, sys, csv, glob, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FULL_LAST, cfg
import textdoc
TOTAL = int(cfg("total_bars") or textdoc.LAST_BAR or 0)   # 全曲小节数：project.json 的 total_bars，或 数据/两部分.txt 的 LAST_BAR
P2 = textdoc.PART2_BAR or 1
files = sys.argv[1:] or sorted(glob.glob(os.path.join(MID, "总谱", "部分识别_*.csv")))
rows = []
for fn in files:
    rs = list(csv.DictReader(open(fn, encoding="utf-8")))
    base = len(rows)
    for r in rs:
        r["bar"] = str(base + int(r["bar"]) - int(rs[0]["bar"]) + 1); rows.append(r)
cnt = {}
for r in rows:
    cnt[int(r["page"])] = cnt.get(int(r["page"]), 0) + 1
truth = {}
for l in open(os.path.join(DATA, "总谱页首小节.txt"), encoding="utf-8"):
    l = l.split("#")[0].split()
    if len(l) == 2:
        m = re.match(r"II-(\d+)", l[1])
        truth[int(l[0])] = P2 - 1 + int(m.group(1)) if m else int(l[1])   # II-n = 第二部分第 n 小节
truth[FULL_LAST + 1] = TOTAL + 1
ks = sorted(truth)
print("识别总数", len(rows), "应为", TOTAL)
bad = 0
for a, b in zip(ks, ks[1:]):
    want = truth[b] - truth[a]
    got = sum(cnt.get(p, 0) for p in range(a, b))
    if got != want:
        bad += 1
        print(f"pdf {a}-{b-1}: 识别 {got}，应 {want}（{got-want:+d}）  各页 " + " ".join(str(cnt.get(p, 0)) for p in range(a, b)))
print("不符的区间", bad)
