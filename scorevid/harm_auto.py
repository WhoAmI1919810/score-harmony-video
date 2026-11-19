# -*- coding: utf-8 -*-
"""由读谱结果（中间文件/omr/*.json）自动标和弦、调性、级数。
输出 中间文件/harm/auto.json：{小节: {"key": "Eb", "ks": -3, "chords": [[拍, 级数, 和弦名], ...], "bass": [..]}}
文字稿由 make_text.py 在此基础上生成，人工写的段落导语和说明另存在 数据/分析_人工.txt。

做法：
  · 每小节分前后两半；每行谱表在这一半没有新起音时，沿用它上一次的音（持续音）。
  · 和弦：12 个根音 × 9 种性质的模板，按"和弦音权重 − 非和弦音权重"打分，低音是根音加分。
  · 调性：24 个调的 Viterbi，观测 = 前后各 2 小节的音级分布与 Krumhansl 调性轮廓的相关 + 钢琴调号先验。
  · 级数：按所在调换算；副属（V/x、vii°7/x）、那不勒斯（N）、德国增六（Ger）单独认。
"""
import os, sys, json, glob
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID
import textdoc

OMR = os.path.join(MID, "omr")
OUTD = os.path.join(MID, "harm")
os.makedirs(OUTD, exist_ok=True)

MIN_CONF = 0.55
RARE_NEED = {"+": 0.80, "°": 0.75, "maj7": 0.75, "ø7": 0.70, "m7": 0.65}   # 少见的和弦性质：读谱有误时最容易冒出来，要求更高
QUAL = {  # 名称后缀, 音程, 复杂度罚分
    "": ((0, 4, 7), 0.0),
    "m": ((0, 3, 7), 0.0),
    "°": ((0, 3, 6), 0.25),
    "+": ((0, 4, 8), 0.45),
    "7": ((0, 4, 7, 10), 0.12),
    "m7": ((0, 3, 7, 10), 0.22),
    "ø7": ((0, 3, 6, 10), 0.22),
    "°7": ((0, 3, 6, 9), 0.12),
    "maj7": ((0, 4, 7, 11), 0.35),
}
KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
LET = "CDEFGAB"
LET_PC = [0, 2, 4, 5, 7, 9, 11]


def key_name(pc, minor):
    # 常用调名
    maj = {0: "C", 1: "Db", 2: "D", 3: "Eb", 4: "E", 5: "F", 6: "Gb", 7: "G", 8: "Ab", 9: "A", 10: "Bb", 11: "B"}
    mnr = {0: "c", 1: "c#", 2: "d", 3: "eb", 4: "e", 5: "f", 6: "f#", 7: "g", 8: "g#", 9: "a", 10: "bb", 11: "b"}
    return (mnr if minor else maj)[pc]


def key_ks(pc, minor):
    """调号（正 = 升号数，负 = 降号数）"""
    p = (pc + 3) % 12 if minor else pc
    order = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5]   # C G D A E B F# C# ...
    i = order.index(p)
    return i if i <= 6 else i - 12


def spell(pc, key_pc, minor, degree=None):
    """按调里的级数拼写根音字母。degree = 0..6（相对主音的级），None 时按调号习惯。"""
    tn = key_name(key_pc, minor)
    tl = LET.index(tn[0].upper())
    if degree is None:
        return (FLAT_NAMES if key_ks(key_pc, minor) <= 0 else SHARP_NAMES)[pc]
    L = LET[(tl + degree) % 7]
    alt = (pc - LET_PC[LET.index(L)] + 6) % 12 - 6
    if abs(alt) > 1:
        return FLAT_NAMES[pc] if key_ks(key_pc, minor) < 0 else SHARP_NAMES[pc]
    return L + ("#" if alt == 1 else "b" if alt == -1 else "")


# ---------------- 读入 ----------------
def load_notes():
    notes = []
    for fn in sorted(glob.glob(os.path.join(OMR, "p*_s*.json"))):
        notes += json.load(open(fn, encoding="utf-8"))
    return notes


def bar_segments(notes, nseg=2):
    """返回 {bar: [ {pc: 权重}, ... nseg ]}、{bar: [低音 midi, ...]}、{bar: 钢琴调号}"""
    by_bar = {}
    for n in notes:
        by_bar.setdefault(n["bar"], []).append(n)
    segs, basses, kss = {}, {}, {}
    last_staff = {}       # (staff 序号从下往上数) → (所在段, 上一次的音)
    prev_seg = None
    for bar in sorted(by_bar):
        ns = by_bar[bar]
        nst = max(n.get("nstaves", 2) for n in ns)
        # 钢琴两行 = 系统最下两行
        ks_list = [n["ks"] for n in ns]
        kss[bar] = max(set(ks_list), key=ks_list.count) if ks_list else 0
        out, bs = [], []
        for si in range(nseg):
            lo, hi = si / nseg, (si + 1) / nseg
            w = np.zeros(12)
            cur = [n for n in ns if lo - 0.03 <= n["pos"] < hi - 0.03 or (si == 0 and n["pos"] < 0)]
            staves_here = set(n["staff"] for n in cur)
            held = []
            seg_id = (bar, si)
            for st_from_bottom, (sid, prev, age) in last_staff.items():
                st = nst - st_from_bottom
                if st not in staves_here and sid == prev_seg:
                    held += prev
            for n in cur:
                wt = 1.0 + (0.6 if n.get("hollow") else 0) + (0.4 if n["staff"] >= nst - 1 else 0)
                w[n["midi"] % 12] += wt
            for n in held:
                w[n["midi"] % 12] += 0.6
            allp = cur + held
            pb = [n for n in allp if n["staff"] == nst]
            bass = min((n["midi"] for n in (pb or allp)), default=None)
            out.append(w); bs.append(bass)
            # 更新持续音：每行最后一个起音位置上的音
            for st in staves_here:
                g = [n for n in cur if n["staff"] == st]
                lastpos = max(n["pos"] for n in g)
                last_staff[nst - st] = (seg_id, [n for n in g if abs(n["pos"] - lastpos) < 0.03], 0)
            # 本段没有新音的行：持续音最多再延续一段（共一小节；休止符读不出来，不能一直延续）
            for k_, (sid, prev, age) in list(last_staff.items()):
                if sid == prev_seg and (nst - k_) not in staves_here and age < 1:
                    last_staff[k_] = (seg_id, prev, age + 1)
            prev_seg = seg_id
        segs[bar] = out; basses[bar] = bs
    return segs, basses, kss


# ---------------- 和弦 ----------------
def best_chord(w, bass, only=None):
    """返回 (置信度 0–1, 根音, 性质)。置信度 = 和弦音所占权重比例（减去缺音、复杂度的罚分）。"""
    tot = w.sum()
    if tot < 1.0:
        return None
    best = None
    for root in range(12):
        for q, (ivs, pen) in QUAL.items():
            if only is not None and q not in only:
                continue
            pcs = [(root + i) % 12 for i in ivs]
            inw = sum(min(w[p], 0.45 * tot) for p in pcs)
            sc = inw / tot
            if w[pcs[1]] < 0.05 * tot:             # 没有三音：不像这个和弦
                sc -= 0.25
            if w[pcs[0]] < 0.05 * tot:
                sc -= 0.3
            if len(ivs) == 4:
                sc -= 0.10                            # 七和弦要明显好于三和弦才用
                if w[pcs[3]] < 0.15 * tot:
                    sc -= 0.3
            sc -= 0.25 * pen
            if bass is not None:
                if bass % 12 == root:
                    sc += 0.12
                elif bass % 12 not in pcs:
                    sc -= 0.08
            if best is None or sc > best[0]:
                best = (sc, root, q)
    return best


# ---------------- 调性 ----------------
def key_track(segs, kss, bars):
    K = 24
    def prof(k):
        pc, mn = k % 12, k >= 12
        p = np.roll(KK_MIN if mn else KK_MAJ, pc)
        return (p - p.mean()) / p.std()
    P = np.array([prof(k) for k in range(K)])
    H = {b: sum(segs[b]) for b in bars}
    obs = np.zeros((len(bars), K))
    for i, b in enumerate(bars):
        h = np.zeros(12)
        for j in range(max(0, i - 2), min(len(bars), i + 3)):
            h += H[bars[j]] * (1.0 if j == i else 0.6)
        if h.sum() < 1e-6:
            continue
        hz = (h - h.mean()) / (h.std() + 1e-9)
        corr = P @ hz / 12
        ks = kss.get(b, 0)
        def kd(k):
            a = key_ks(k % 12, k >= 12)
            d = abs(a - ks)
            return min(d, 12 - d)          # 6 个升号 = 6 个降号（F# = Gb）
        prior = np.array([0.35 if kd(k) == 0 else (0.12 if kd(k) == 1 else 0.0) for k in range(K)])
        obs[i] = corr + prior + np.array([0.06 if k < 12 else 0.0 for k in range(K)])   # 同调号时略偏向大调
    sw = 0.8
    V = obs[0].copy(); back = []
    for i in range(1, len(bars)):
        m = V.max()
        stay = V
        bp = np.where(stay >= m - sw, np.arange(K), V.argmax())
        V = np.maximum(stay, m - sw) + obs[i]
        back.append(bp)
    k = int(V.argmax()); path = [k]
    for bp in reversed(back):
        k = int(bp[k]); path.append(k)
    path.reverse()
    return {b: (k % 12, k >= 12) for b, k in zip(bars, path)}


# ---------------- 级数 ----------------
MAJ_DEG = {0: "I", 2: "ii", 4: "iii", 5: "IV", 7: "V", 9: "vi", 11: "vii°"}
MIN_DEG = {0: "i", 2: "ii°", 3: "III", 5: "iv", 7: "V", 8: "VI", 10: "VII", 11: "vii°"}
NUM = {0: "I", 1: "II", 2: "II", 3: "III", 4: "III", 5: "IV", 6: "IV", 7: "V", 8: "VI", 9: "VI", 10: "VII", 11: "VII"}
DEG_IDX = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 5, 9: 5, 10: 6, 11: 6}


def is_diatonic(iv, q, minor):
    tri = {"": "maj", "7": "maj", "maj7": "maj", "m": "min", "m7": "min", "°": "dim", "ø7": "dim", "°7": "dim", "+": "aug"}[q]
    if not minor:
        ok = {0: "maj", 2: "min", 4: "min", 5: "maj", 7: "maj", 9: "min", 11: "dim"}
        if q == "7" and iv != 7:
            return False
    else:
        ok = {0: "min", 2: "dim", 3: "maj", 5: "min", 7: "maj", 8: "maj", 10: "maj", 11: "dim"}
        if q == "7" and iv not in (7, 10):
            return False
    if q == "°7" and iv != 11:
        return False
    return ok.get(iv) == tri


def roman_for(root, q, bass, key_pc, minor, nxt=None):
    iv = (root - key_pc) % 12
    seventh = q in ("7", "m7", "ø7", "°7", "maj7")
    upper = q in ("", "7", "+", "maj7")
    fig64 = bass is not None and q in ("", "m") and (bass - root) % 12 == 7
    # 德国增六：降 VI 级上的属七和弦，后面接 V 或 I64
    if q == "7" and iv == 8 and (nxt is None or (nxt - key_pc) % 12 in (7, 0)):
        return "Ger", spell(root, key_pc, minor, 5) + "7"
    if q == "" and iv == 1:
        return "N", spell(root, key_pc, minor, 1)
    if is_diatonic(iv, q, minor):
        base = (MIN_DEG if minor else MAJ_DEG)[iv]
        if q == "°7":
            base = "vii°"
        if q == "ø7":
            base = base.rstrip("°") + "ø"
        r = base + ("maj7" if q == "maj7" else ("7" if seventh else "")) + ("64" if fig64 and base in ("I", "i", "IV", "iv", "V", "v") else "")
        return r, spell(root, key_pc, minor, DEG_IDX[iv]) + q
    # 副属：大三 / 属七 → V/x；减三 / 减七 → vii°/x
    if q in ("", "7"):
        t = (root + 5) % 12
        tiv = (t - key_pc) % 12
        if tiv != 0 and tiv in (MIN_DEG if minor else MAJ_DEG) and not (MIN_DEG if minor else MAJ_DEG)[tiv].endswith("°"):
            tgt = (MIN_DEG if minor else MAJ_DEG)[tiv]
            return f"V{'7' if q == '7' else ''}/{tgt}", spell(root, key_pc, minor, (DEG_IDX[tiv] + 4) % 7) + q
    if q in ("°", "°7", "ø7"):
        t = (root + 1) % 12
        tiv = (t - key_pc) % 12
        tbl = MIN_DEG if minor else MAJ_DEG
        if tiv in tbl and not tbl[tiv].endswith("°"):
            sym = {"°": "vii°", "°7": "vii°7", "ø7": "viiø7"}[q]
            if tiv == 0:
                return sym, spell(root, key_pc, minor, 6) + q
            return f"{sym}/{tbl[tiv]}", spell(root, key_pc, minor, (DEG_IDX[tiv] + 6) % 7) + q
    # 其余：按与主音的音程写变化级
    ref = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    d = DEG_IDX[iv]
    if minor and iv in (4, 9, 11):
        d = {4: 2, 9: 5, 11: 6}[iv]
    alt = (iv - ref[d] + 6) % 12 - 6
    acc = "b" if alt == -1 else "#" if alt == 1 else ""
    if abs(alt) > 1:
        acc = ""
    num = ["I", "II", "III", "IV", "V", "VI", "VII"][d]
    if not upper:
        num = num.lower()
    suf = {"°": "°", "+": "+", "°7": "°7", "ø7": "ø7", "m7": "7", "7": "7", "maj7": "maj7", "": "", "m": ""}[q]
    return acc + num + suf, spell(root, key_pc, minor, d) + q


def analyse(nseg=2):
    notes = load_notes()
    segs, basses, kss = bar_segments(notes, nseg)
    bars = sorted(segs)
    keys = key_track(segs, kss, bars)
    out = {}
    chords_raw = {}
    for b in bars:
        cs = []
        for si, w in enumerate(segs[b]):
            bc = best_chord(w, basses[b][si])
            cs.append(bc)
        chords_raw[b] = cs
    flat = [(b, si) for b in bars for si in range(nseg)]
    roots = {}
    for b, si in flat:
        c = chords_raw[b][si]
        roots[(b, si)] = c[1] if c else None
    prev_b = None
    for b in bars:
        kp, mn = keys[b]
        items = []
        for si in range(nseg):
            c = chords_raw[b][si]
            beat = 1 + si * textdoc.BEATS_PER_BAR / nseg
            if c is not None and c[1] is not None:
                need = RARE_NEED.get(c[2], MIN_CONF)
                if c[0] < need:
                    c = best_chord(segs[b][si], basses[b][si], only=("", "m", "7"))
            if c is None or c[0] < MIN_CONF:
                # 读谱结果不足以判断：标"—"（不硬给和弦）
                if items and items[-1][1] == "—":
                    continue
                if not items and out and out.get(prev_b) and out[prev_b]["chords"] and out[prev_b]["chords"][-1][1] == "—":
                    continue
                items.append([beat, "—", "", 0.0])
                continue
            _, root, q = c
            # 下一个和弦的根音（认德国增六用）
            nx = None
            idx = flat.index((b, si))
            for j in range(idx + 1, min(len(flat), idx + 4)):
                if roots.get(flat[j]) is not None and roots[flat[j]] != root:
                    nx = roots[flat[j]]; break
            rn, name = roman_for(root, q, basses[b][si], kp, mn, nx)
            if items and items[-1][1] == rn and items[-1][2] == name:
                continue
            items.append([beat, rn, name, round(float(c[0]), 2)])
        out[b] = dict(key=key_name(kp, mn), ks=kss[b], chords=items,
                      bass=[basses[b][si] for si in range(nseg)])
        prev_b = b
    # 四六和弦：只保留终止四六（下一个和弦是同一调的属和弦），其余是低音走动、分解和弦造成的，写成原位
    seq = [(b, i) for b in sorted(out) for i in range(len(out[b]["chords"]))]
    for j, (b, i) in enumerate(seq):
        c = out[b]["chords"][i]
        if c[1].endswith("64"):
            nxt = next((out[bb]["chords"][ii] for bb, ii in seq[j + 1:j + 4] if out[bb]["chords"][ii][1] != c[1]), None)
            if not (nxt and c[1] in ("I64", "i64") and nxt[1].split("/")[0] in ("V", "V7")):
                c[1] = c[1][:-2]
    # 去掉因此产生的相邻重复
    for b in out:
        cs = out[b]["chords"]; m = []
        for c in cs:
            if m and m[-1][1] == c[1] and m[-1][2] == c[2]:
                continue
            m.append(c)
        out[b]["chords"] = m
    json.dump(out, open(os.path.join(OUTD, "auto.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out


if __name__ == "__main__":
    out = analyse()
    a = int(sys.argv[1]) if len(sys.argv) > 1 else min(out, key=int)
    z = int(sys.argv[2]) if len(sys.argv) > 2 else a + 30
    for b in range(a, z + 1):
        if b in out:
            o = out[b]
            print(b, o["key"], o["ks"], " | ".join(f"{c[0]:g} {c[1]} {c[2]} ({c[3]})" for c in o["chords"]))
