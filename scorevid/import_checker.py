# -*- coding: utf-8 -*-
"""把在线校对站导出的 小节时间.csv 写回工程。
新格式（带 页,x0,x1,y0,y1,部分,原小节 列）：整张小节表按它重建——可以有合并、拆分、删除、补上的小节、改过的阴影。
旧格式（只有 小节,开始,备注）：只改时间，交给 import_times_only.py。

新格式要做的事：
  1. 备份 数据/小节位置.csv、数据/小节时间.csv、数据/两部分.txt、数据/分析_人工.txt、数据/调号修正.txt；
  2. 写新的 小节位置.csv（系统号按 staves.json 里谱表的纵向范围对上；用户新画、对不上任何系统的框给新的系统号）；
  3. 写 小节时间.csv、对齐锚点.csv（已确认的小节）、两部分.txt；
  4. 段落、曲式、调号修正的小节号按谱面位置换成新编号（renumber.py）；
  5. 之后运行 bash <工具包>/build.sh text（读谱结果会按位置自动重新分配到新小节），不要再跑 align。
用法：python3 import_checker.py 小节时间.csv"""
import os, sys, csv, json, re, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, BARS_CSV, TIMES_CSV, AUDIO_START
import renumber


def parse_t(v):
    x = 0.0
    for p in v.strip().split(":"):
        x = x * 60 + float(p)
    return x - AUDIO_START


def fmt(t):
    t += AUDIO_START
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def main():
    src = sys.argv[1]
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    if not rows or "页" not in rows[0]:
        print("旧格式（只有时间），改用 import_times_only.py")
        os.execvp(sys.executable, [sys.executable, os.path.join(os.path.dirname(__file__), "import_times_only.py"), src])
    rows.sort(key=lambda r: int(r["小节"]))
    times = [parse_t(r["开始"]) for r in rows]
    assert all(b > a for a, b in zip(times, times[1:])), "时间不是递增的"
    tag = time.strftime("%m%d_%H%M%S")
    bak = os.path.join(MID, f"导入前备份_{tag}")
    os.makedirs(bak, exist_ok=True)
    for f in (BARS_CSV, TIMES_CSV, os.path.join(DATA, "两部分.txt"), os.path.join(DATA, "分析_人工.txt"),
              os.path.join(DATA, "调号修正.txt"), os.path.join(DATA, "对齐锚点.csv")):
        if os.path.exists(f):
            shutil.copy(f, bak)
    old_bars = os.path.join(bak, os.path.basename(BARS_CSV))
    # 系统号：按 staves.json 里每个系统谱表的纵向范围
    stj = json.load(open(os.path.join(MID, "staves.json")))
    extra = {}
    out = []
    for i, r in enumerate(rows, start=1):
        p = int(r["页"]); y0 = int(r["y0"]); y1 = int(r["y1"])
        best, bo = None, 0
        for si, sy in enumerate(stj.get(str(p), []), start=1):
            a, b = sy[0][0], sy[-1][-1]
            ov = min(b, y1) - max(a, y0)
            if ov > bo:
                best, bo = si, ov
        if best is None:
            key = (p, round(y0 / 50))
            if key not in extra:
                extra[key] = len(stj.get(str(p), [])) + 1 + sum(1 for k in extra if k[0] == p)
            best = extra[key]
        out.append(dict(bar=i, page=p, system=best, x0=int(r["x0"]), x1=int(r["x1"]), y0=y0, y1=y1))
    with open(BARS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bar", "page", "system", "x0", "x1", "y0", "y1"])
        w.writeheader(); w.writerows(out)
    conf = [i for i, r in enumerate(rows, start=1) if "确认" in (r.get("备注") or "")]
    with open(TIMES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["小节", "开始", "备注"])
        for i, t in enumerate(times, start=1):
            w.writerow([i, fmt(t), "已确认" if i in conf else ""])
    with open(os.path.join(DATA, "对齐锚点.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["小节", "开始", "备注"])
        for i in conf:
            w.writerow([i, fmt(times[i - 1]), "校对站确认"])
    p2 = next((i for i, r in enumerate(rows, start=1) if str(r.get("部分", "1")).strip() == "2"), None)
    open(os.path.join(DATA, "两部分.txt"), "w", encoding="utf-8").write(
        "# 小节连续编号：第二部分第一小节的编号、最后一小节编号\n"
        f"PART2_BAR = {p2}\nLAST_BAR = {len(rows)}\n")
    # 小节号重编：按谱面位置
    m = renumber.build(old_bars, BARS_CSV)
    json.dump(m, open(os.path.join(MID, "小节编号_旧到新.json"), "w"))
    p = os.path.join(DATA, "分析_人工.txt"); lines = []
    for line in open(p, encoding="utf-8"):
        mm = re.match(r"^\[(曲式|段落)\] (\d+)-(\d+)( \|.*)$", line.rstrip("\n"))
        if mm:
            line = f"[{mm.group(1)}] {renumber.fwd(m, int(mm.group(2)))}-{renumber.back(m, int(mm.group(3)))}{mm.group(4)}\n"
        mm = re.match(r"^\[说明\] (\d+)( \|.*)$", line.rstrip("\n"))
        if mm:
            line = f"[说明] {renumber.fwd(m, int(mm.group(1)))}{mm.group(2)}\n"
        lines.append(line)
    s = re.sub(r"第一部分 1–\d+，第二部分 \d+–\d+；第二部分第 n 小节 = \d+ \+ n",
               f"第一部分 1–{p2 - 1}，第二部分 {p2}–{len(rows)}；第二部分第 n 小节 = {p2 - 1} + n", "".join(lines))
    open(p, "w", encoding="utf-8").write(s)
    p = os.path.join(DATA, "调号修正.txt")
    if os.path.exists(p):
        lines = []
        for line in open(p, encoding="utf-8"):
            mm = re.match(r"^(\d+)-(\d+)(\s+-?\d+.*)$", line.rstrip("\n"))
            if mm:
                line = f"{renumber.fwd(m, int(mm.group(1)))}-{renumber.back(m, int(mm.group(2)))}{mm.group(3)}\n"
            lines.append(line)
        open(p, "w", encoding="utf-8").write("".join(lines))
    changed = sum(1 for r in rows if "小节" in (r.get("备注") or ""))
    print(f"写回 {len(rows)} 小节（第二部分从 {p2} 起），改过结构的 {changed} 个，确认 {len(conf)} 个；备份在 {bak}")
    if extra:
        print("新画的、对不上谱表的系统：", sorted(extra))
    print("下一步：bash <工具包>/build.sh text（不要跑 align）")


if __name__ == "__main__":
    main()
