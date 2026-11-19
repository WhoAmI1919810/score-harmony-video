# -*- coding: utf-8 -*-
"""小节重新识别后，把旧编号映射到新编号（按页、纵坐标、小节中点）。
用法：python3 renumber.py 旧小节位置.csv 新小节位置.csv → 打印/写出 中间文件/小节编号_旧到新.json"""
import csv, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID


def build(old_csv, new_csv):
    old = list(csv.DictReader(open(old_csv, encoding="utf-8")))
    new = list(csv.DictReader(open(new_csv, encoding="utf-8")))
    bypage = {}
    for q in new:
        bypage.setdefault(int(q["page"]), []).append(q)
    m = {}
    for r in old:
        p = int(r["page"]); x = (int(r["x0"]) + int(r["x1"])) / 2
        cands = [q for q in bypage.get(p, []) if abs(int(q["y0"]) - int(r["y0"])) < 60
                 or int(q["y0"]) - 60 <= int(r["y0"]) <= int(q["y1"])]
        hit = [q for q in cands if int(q["x0"]) - 3 <= x < int(q["x1"]) + 3]
        m[int(r["bar"])] = int(hit[0]["bar"]) if hit else None
    return m


def fwd(m, n):
    while n in m and m[n] is None:
        n += 1
    return m.get(n, n)


def back(m, n):
    while n in m and m[n] is None:
        n -= 1
    return m.get(n, n)


if __name__ == "__main__":
    m = build(sys.argv[1], sys.argv[2])
    json.dump(m, open(os.path.join(MID, "小节编号_旧到新.json"), "w"))
    print("无对应（旧的假小节）：", [k for k, v in m.items() if v is None])
