# -*- coding: utf-8 -*-
"""读谱之后的调号统一：同一系统里各行谱表的调号应当相同（人声缩谱全是实际音高）。
个别行把调号少数、多数或没认出来时，用这个系统里出现最多的调号代替，再按写谱音名 + 临时记号重算实际音高。
行中换调号（ks_changes）之后的音不动。
用法：python3 fix_ks.py        处理 中间文件/omr/ 下全部 pNNN_sK.json（读 omr/stage1/，先运行 fix_clef.py）"""
import os, sys, json, glob, shutil
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omr

OMR = omr.OMR


def consensus(kss):
    c = Counter(kss)
    top = max(c.values())
    cands = [k for k, v in c.items() if v == top]
    return max(cands, key=abs)


def smooth(ks_bar, short=8, long_under=13):
    """读错的调号多是零星几小节：
    一串连续的短段（每段 < short 小节、合计 < 2*short）夹在两个相同调号的长段之间 → 改成两边的调号；
    少于 long_under 小节、且比两边少记号（同号或为 0）的段 → 也改（读谱常漏掉后面的升降号）。"""
    bars = sorted(ks_bar)

    def runs_of():
        rs = []
        for b in bars:
            if rs and rs[-1][0] == ks_bar[b]:
                rs[-1][1].append(b)
            else:
                rs.append([ks_bar[b], [b]])
        return rs

    for _ in range(5):
        rs = runs_of()
        changed = False
        i = 1
        while i < len(rs) - 1:
            # 从 i 起连续的短段
            j = i
            tot = 0
            while j < len(rs) - 1 and len(rs[j][1]) < short and tot + len(rs[j][1]) < 2 * short:
                tot += len(rs[j][1]); j += 1
            if j > i and rs[i - 1][0] == rs[j][0] and len(rs[i - 1][1]) >= short:
                for k in range(i, j):
                    for b in rs[k][1]:
                        ks_bar[b] = rs[i - 1][0]
                changed = True
                i = j
                continue
            k_run = rs[i][0]; kl = rs[i - 1][0]; kr = rs[i + 1][0]
            if len(rs[i][1]) < long_under and kl == kr and abs(k_run) < abs(kl) and (k_run == 0 or (k_run > 0) == (kl > 0)):
                for b in rs[i][1]:
                    ks_bar[b] = kl
                changed = True
            i += 1
        if not changed:
            break
    return ks_bar


def main():
    # 输入：fix_clef.py 的输出 omr/stage1/（谱号已修正）；输出覆盖 omr/pNNN_sK.json
    files = {}
    for src in sorted(glob.glob(os.path.join(OMR, "stage1", "p*_s*.json"))):
        files[os.path.join(OMR, os.path.basename(src))] = json.load(open(src, encoding="utf-8"))
    per = {}
    for notes in files.values():
        for n in notes:
            per.setdefault(n["bar"], {}).setdefault(n["staff"], []).append(n["ks"])

    def pick(vals):
        # 读谱常常少数升降号（后面几个没认出），很少多数：取至少四分之一读数支持的、记号最多的调号
        c = Counter(vals)
        need = max(2, int(0.25 * len(vals) + 0.999))
        ok = [k for k, v in c.items() if v >= need and k != 0]
        if ok:
            sgn = Counter(1 if k > 0 else -1 for k in vals if k != 0).most_common(1)[0][0]
            same = [k for k in ok if (k > 0) == (sgn > 0)]
            if same:
                return max(same, key=abs)
        return consensus(vals)

    # 每个小节：各行在这一小节用的调号（行内众数）。
    # 这份谱里调号只在双小节线处改变（数据/双小节线.json，由 double_bars.py 生成）：
    # 两条双小节线之间的一整段取同一个调号——把这段里每小节每行的读数放在一起投票。
    dbl_p = os.path.join(__import__("common").DATA, "双小节线.json")
    dbl = {int(k): v for k, v in json.load(open(dbl_p)).items()} if os.path.exists(dbl_p) else {}
    bars_all = sorted(per)
    segs = []
    for b in bars_all:
        if not segs or dbl.get(b, False):
            segs.append([b])
        else:
            segs[-1].append(b)
    ks_bar = {}
    prev_k = None
    for sg in segs:
        vals = []
        for b in sg:
            vals += [Counter(v).most_common(1)[0][0] for v in per[b].values()]
        k = pick(vals) if vals else (prev_k if prev_k is not None else 0)
        # 双小节线也可能只是换拍号：仍有三成读数是上一段的调号，就算没换
        if prev_k is not None and k != prev_k and vals and vals.count(prev_k) >= 0.3 * len(vals):
            k = prev_k
        prev_k = k
        for b in sg:
            ks_bar[b] = k
    if not dbl:
        ks_bar = smooth(ks_bar)
    # 人工核对过的修正
    ov = os.path.join(__import__("common").DATA, "调号修正.txt")
    if os.path.exists(ov):
        for l in open(ov, encoding="utf-8"):
            l = l.split("#")[0].split()
            if len(l) == 2:
                a, z = (int(x) for x in l[0].split("-"))
                for b in range(a, z + 1):
                    if b in ks_bar:
                        ks_bar[b] = int(l[1])
    nfix = 0
    for fn, notes in files.items():
        for n in notes:
            if n["ks"] != ks_bar[n["bar"]]:
                n["ks"] = ks_bar[n["bar"]]; nfix += 1
        carry = {}
        for n in sorted(notes, key=lambda n: (n["staff"], n["x"])):
            L, octv = n["written"][0], int(n["written"][1:])
            k = (n["staff"], n["bar"], L, octv)
            if n["acc"]:
                carry[k] = {"sharp": 1, "flat": -1, "natural": 0}[n["acc"]]
            alt = carry.get(k, omr.ks_alter(n["ks"]).get(L, 0))
            n["midi"] = 12 * (octv + 1) + omr.SEMI[omr.LETTERS.index(L)] + alt
            n["name"] = omr.spelled(L, octv, alt, 0)
        json.dump(notes, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    runs = []
    for b in sorted(ks_bar):
        if runs and runs[-1][1] == ks_bar[b]:
            runs[-1][2] = b
        else:
            runs.append([b, ks_bar[b], b])
    print(f"统一调号：改了 {nfix} 个音；调号分段：" + " ".join(f"{a}-{z}:{k:+d}" for a, k, z in runs))


if __name__ == "__main__":
    main()
