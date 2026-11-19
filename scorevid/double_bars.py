# -*- coding: utf-8 -*-
"""标出每个小节的左边是不是双小节线（换调号、换段落只在双小节线处）。
系统第一小节看上一系统最后一条线（预告调号去掉后，那条线就是双小节线）。
输出 数据/双小节线.json：{小节: true/false}
用法：python3 double_bars.py"""
import os, sys, csv, json
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, BARS_CSV
import s2_bars as sb


def main():
    rows = list(csv.DictReader(open(BARS_CSV, encoding="utf-8")))
    st = json.load(open(os.path.join(MID, "staves.json")))
    out = {}
    cache = {}
    prev = None
    for r in rows:
        b = int(r["bar"]); p = int(r["page"]); s = int(r["system"])
        if p not in cache:
            cache.clear()
            cache[p] = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("L")) < 128
        ink = cache[p]
        if s - 1 >= len(st.get(str(p), [])):          # 校对时新画的系统，没有谱表数据
            out[b] = prev is None or not (prev["page"] == r["page"] and prev["system"] == r["system"])
            prev = r
            continue
        lines = st[str(p)][s - 1]
        staves = [(l[0], l[-1], l) for l in lines]
        sidx = list(range(len(staves)))
        if prev is None:
            out[b] = True
        elif prev["page"] == r["page"] and prev["system"] == r["system"]:
            out[b] = bool(sb.is_double(ink, staves, sidx, int(r["x0"])))
        else:
            # 上一系统的最后一条线
            pp = int(prev["page"]); ps = int(prev["system"])
            pink = ink if pp == p else np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{pp:03d}.png")).convert("L")) < 128
            pl = st[str(pp)][ps - 1]
            pst = [(l[0], l[-1], l) for l in pl]
            out[b] = bool(sb.is_double(pink, pst, list(range(len(pst))), int(prev["x1"])))
        prev = r
    json.dump(out, open(os.path.join(DATA, "双小节线.json"), "w"), indent=0)
    print("双小节线：", sum(out.values()), "处 /", len(out), "小节")


if __name__ == "__main__":
    main()
