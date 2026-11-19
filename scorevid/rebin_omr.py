# -*- coding: utf-8 -*-
"""小节位置改了以后（合并、拆分、补小节、删小节），把读谱结果里每个音重新分到新小节：
按 页 / 系统 / 横坐标 找它所在的新小节；所在小节的左右边界变了的，重算它在小节里的相对位置 pos。
读谱原始结果在 中间文件/omr/raw/，它对应的小节位置存在 omr/raw/小节位置.csv；
本脚本把 raw 里的音改成按当前 数据/小节位置.csv 编号，并更新那份 小节位置.csv。
系统划分变了的页（谱表增减）不能这样处理，要重新读谱（omr_page.py 该页）后把新结果拷进 raw。
用法：python3 rebin_omr.py            （fix_clef.py 发现 raw 的小节位置过期时会自动调用）"""
import os, sys, csv, json, glob, re, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BARS_CSV
import omr

RAW = os.path.join(omr.OMR, "raw")
RAW_CSV = os.path.join(RAW, "小节位置.csv")


def rows_of(path):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out[int(r["bar"])] = dict(bar=int(r["bar"]), page=int(r["page"]), system=int(r["system"]),
                                  x0=int(r["x0"]), x1=int(r["x1"]))
    return out


def up_to_date():
    return os.path.exists(RAW_CSV) and open(RAW_CSV, "rb").read() == open(BARS_CSV, "rb").read()


def main():
    if up_to_date():
        print("raw 读谱结果的小节编号已是最新")
        return
    if not os.path.exists(RAW_CSV):
        raise SystemExit(f"缺 {RAW_CSV}：不知道 raw 读谱结果按哪一版小节编号，无法重新分配")
    old = rows_of(RAW_CSV)
    new = omr.load_rows()                      # 含 play0
    bysys = {}
    for r in new.values():
        bysys.setdefault((r["page"], r["system"]), []).append(r)
    moved = recomputed = lost = 0
    for fn in sorted(glob.glob(os.path.join(RAW, "p*_s*.json"))):
        p, s = (int(x) for x in re.findall(r"\d+", os.path.basename(fn)))
        notes = json.load(open(fn, encoding="utf-8"))
        rs = sorted(bysys.get((p, s), []), key=lambda r: r["x0"])
        keep = []
        for n in notes:
            hit = next((r for r in rs if r["x0"] <= n["x"] < r["x1"]), None)
            if hit is None:
                lost += 1
                continue
            o = old.get(n["bar"])
            same = o is not None and abs(o["x0"] - hit["x0"]) <= 3 and abs(o["x1"] - hit["x1"]) <= 3
            if n["bar"] != hit["bar"]:
                moved += 1
            if not same:
                p0 = hit["play0"]
                n["pos"] = round(float((n["x"] - p0) / max(1.0, hit["x1"] - p0)), 3)
                recomputed += 1
            n["bar"] = hit["bar"]
            keep.append(n)
        json.dump(keep, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    shutil.copy(BARS_CSV, RAW_CSV)
    print(f"重新分配：改编号 {moved} 个音，重算位置 {recomputed} 个，落在小节外丢掉 {lost} 个")


if __name__ == "__main__":
    main()
