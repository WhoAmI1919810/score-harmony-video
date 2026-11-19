# -*- coding: utf-8 -*-
"""读谱之后的谱号修正（在 fix_ks.py 之前运行）。
读谱日志里"开头谱号不清楚 / 没认出"的行：沿用相邻系统（先前一个、再后一个，行数相同）同一行的谱号，
按新谱号把这一行所有音的写谱音名重算一遍（谱表上的位置不变）。
输入 中间文件/omr/raw/（读谱原始输出的备份，第一次运行时建立），输出 中间文件/omr/stage1/。
用法：python3 fix_clef.py"""
import os, sys, re, json, glob, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, BARS_CSV
import omr

OMR = omr.OMR
RAW = os.path.join(OMR, "raw")
ST1 = os.path.join(OMR, "stage1")
THR = 0.40          # 相关低于这个值的谱号判断不可信


def main():
    os.makedirs(RAW, exist_ok=True); os.makedirs(ST1, exist_ok=True)
    # raw 里的小节编号过期（小节位置改过）→ 先按谱面位置重新分配
    import rebin_omr as rebin_omr8
    if os.path.exists(rebin_omr8.RAW_CSV) and not rebin_omr8.up_to_date():
        rebin_omr8.main()
    files = sorted(glob.glob(os.path.join(OMR, "p*_s*.json")))
    for fn in files:
        r = os.path.join(RAW, os.path.basename(fn))
        if not os.path.exists(r):
            shutil.copy(fn, r)
    if not os.path.exists(rebin_omr8.RAW_CSV):
        shutil.copy(BARS_CSV, rebin_omr8.RAW_CSV)
    # 谱号存疑的行：读谱日志 omr_*.log；同一页在较新的日志里重读过，以新的为准
    unsure = {}
    logs = sorted(glob.glob(os.path.join(MID, "omr_*.log")), key=os.path.getmtime)
    for p in logs:
        found = {}
        pages_here = set()
        for l in open(p, encoding="utf-8"):
            m0 = re.match(r"^p(\d+) s\d+: ", l)
            if m0:
                pages_here.add(int(m0.group(1)))
            m = re.search(r"p(\d+) s(\d+) 行(\d+): 开头谱号(不清楚，按相关较高的 \w+（(-?[\d.]+)）|没认出)", l)
            if m:
                sc = float(m.group(5)) if m.group(5) else -1.0
                if sc < THR:
                    found[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = sc
        for k in [k for k in unsure if k[0] in pages_here]:
            del unsure[k]
        unsure.update(found)
    unsure = set(unsure)
    # 每个系统每行的谱号（取这一行出现最多的开头谱号；行中换谱号不管）
    systems = []
    data = {}
    for fn in sorted(glob.glob(os.path.join(RAW, "p*_s*.json")),
                     key=lambda f: tuple(int(x) for x in re.findall(r"\d+", os.path.basename(f)))):
        p, s = (int(x) for x in re.findall(r"\d+", os.path.basename(fn)))
        notes = json.load(open(fn, encoding="utf-8"))
        data[(p, s)] = notes
        clefs = {}
        nst = 0
        for n in notes:
            nst = max(nst, n.get("nstaves", 0))
            clefs.setdefault(n["staff"], {}).setdefault(n["clef"], 0)
            clefs[n["staff"]][n["clef"]] += 1
        first = {st: max(c, key=c.get) for st, c in clefs.items()}
        systems.append(((p, s), nst, first))
    idx = {k: i for i, (k, _, _) in enumerate(systems)}
    nfix = 0; nchg = 0
    for (p, s), notes in data.items():
        i = idx[(p, s)]
        nst = systems[i][1]
        newclef = {}
        for st in {n["staff"] for n in notes}:
            if (p, s, st) not in unsure:
                continue
            cand = None
            for j in list(range(i - 1, max(-1, i - 4), -1)) + list(range(i + 1, min(len(systems), i + 4))):
                (pp, ss), n2, f2 = systems[j]
                if n2 == nst and st in f2 and (pp, ss, st) not in unsure:
                    cand = f2[st]; break
            if cand:
                newclef[st] = cand
        for n in notes:
            c = newclef.get(n["staff"])
            if not c or c == n["clef"]:
                continue
            # 按旧谱号把写谱音名还原成谱表位置，再按新谱号算
            bl0, bo0 = omr.BOTTOM[n["clef"]]
            L, octv = n["written"][0], int(n["written"][1:])
            pos = (octv - bo0) * 7 + omr.LETTERS.index(L) - bl0       # = k
            bl, bo = omr.BOTTOM[c]
            ii = bl + pos
            L2 = omr.LETTERS[ii % 7]; o2 = bo + ii // 7
            n["written"] = f"{L2}{o2}"; n["clef"] = c
            alt = {"sharp": 1, "flat": -1, "natural": 0}.get(n["acc"], omr.ks_alter(n["ks"]).get(L2, 0))
            n["midi"] = 12 * (o2 + 1) + omr.SEMI[omr.LETTERS.index(L2)] + alt
            n["name"] = omr.spelled(L2, o2, alt, 0)
            nchg += 1
        nfix += len(newclef)
        json.dump(notes, open(os.path.join(ST1, f"p{p:03d}_s{s}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"谱号存疑 {len(unsure)} 行，按相邻系统改了 {nfix} 行、{nchg} 个音")


if __name__ == "__main__":
    main()
