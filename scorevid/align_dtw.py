# -*- coding: utf-8 -*-
"""对齐（第二版，在马勒八上验证）：在用户已校的小节之间重排其余小节。

为什么换方法（align_lab.py 用用户校对结果评测）：旧方法第一遍假设全曲速度均匀，速度变化极大，
第一遍误差中位 35~111 秒，第二遍只能局部修正，留下几十秒的整片偏移。
新方法：
  1. 每个名义拍一个状态，录音每 0.2 秒一帧，每帧"停在本拍"或"进入下一拍"，不加任何速度假设；
     代价 = 0.7 × 音高谱（84 个半音，读谱音高 + 泛音）余弦距离 + 0.3 × 色度余弦距离。
  2. 按第一遍的局部速度展开谱面，做限制斜率的 DTW 精修，精修结果离第一遍不超过 ±2 秒。
固定点：数据/已校范围.txt 里的小节，时间保持不动（加 --with-confirmed 时，小节时间.csv 里标"已确认"的也算）。
输出：数据/小节时间.csv（先备份）、中间文件/align/beats.csv。
用法：python3 align_dtw.py"""
import os, sys, csv, time, shutil
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, TIMES_CSV, BARS_CSV, MUSIC_START, MUSIC_END, PART2_START
import textdoc
import align_lab as L

W_PITCH = 0.7
GUARD = 2.0
RANGES_TXT = os.path.join(DATA, "已校范围.txt")


def fmt(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def parse_bar(tok, p2):
    tok = tok.strip()
    if tok.upper().startswith("II-"):
        return p2 + int(tok[3:]) - 1
    if tok.upper().startswith("I-"):
        return int(tok[2:])
    return int(tok)


def verified(p2, last):
    """数据/已校范围.txt：每行 起-止，小节号写 I-n / II-n 或连续编号，"末尾" 表示最后一小节。"""
    out = set()
    if os.path.exists(RANGES_TXT):
        for l in open(RANGES_TXT, encoding="utf-8"):
            l = l.split("#")[0].strip()
            if not l:
                continue
            a, b = l.split("~")
            a = parse_bar(a, p2); b = last if b.strip() == "末尾" else parse_bar(b, p2)
            out |= set(range(a, b + 1))
    return out


def main():
    p2 = textdoc.PART2_BAR
    rows = list(csv.DictReader(open(TIMES_CSV, encoding="utf-8-sig")))
    T = {int(r["小节"]): L.parse_time(r["开始"]) for r in rows}
    conf = {int(r["小节"]) for r in rows if "确认" in (r.get("备注") or "")}
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    assert bars == sorted(T), "小节时间.csv 和 小节位置.csv 的小节数不一致"
    # 固定点只认 已校范围.txt：校对页上拖动过的小节会自动标"已确认"，范围外的确认标记可能只是拖动时挤出来的
    fixed = verified(p2, bars[-1]) & set(bars)
    if "--with-confirmed" in sys.argv:
        fixed |= conf & set(bars)
    print(f"固定点 {len(fixed)} 个小节（已校范围{' + 已确认' if '--with-confirmed' in sys.argv else ''}），重排 {len(bars) - len(fixed)} 个")
    F = L.load_feats(0.2)
    Xp = L.audio_vecs(F, "pitch"); Xc = L.audio_vecs(F, "chroma")
    Tp, idx = L.templates(bars, "pitch"); Tc, _ = L.templates(bars, "chroma")
    Fp = dict(F); Fp["X"] = Xp
    anc = {b: T[b] for b in fixed}
    segs = L.segments(idx, T, F, anc)
    st = np.zeros(len(idx))
    t0 = time.time()
    for s0, s1, ta, tb in segs:
        j0, j1 = int(round(ta / 0.2)), int(round(tb / 0.2))
        if j1 - j0 < (s1 - s0) + 1:
            st[s0:s1] = ta + np.arange(s1 - s0) * (tb - ta) / (s1 - s0)
            continue
        C = W_PITCH * L.cost_matrix(Tp[s0:s1], Xp[j0:j1], "cos") + (1 - W_PITCH) * L.cost_matrix(Tc[s0:s1], Xc[j0:j1], "cos")
        st[s0:s1] = ta + L.dtw_free(C) * 0.2
    r = L.refine(st, Fp, Tp, segs, win=60)
    st = np.clip(r, st - GUARD, st + GUARD)
    # 固定点的小节开始时间保持不动；拍点保持递增
    first = {}
    for s, (b, k) in enumerate(idx):
        first.setdefault(b, s)
    for b in fixed:
        st[first[b]] = T[b]
    for s in range(1, len(st)):
        if st[s] <= st[s - 1] + 0.02:
            st[s] = st[s - 1] + 0.02
    for b in fixed:
        assert abs(st[first[b]] - T[b]) < 0.03, f"固定点 {b} 被挤动了"
    print(f"对齐用时 {time.time() - t0:.0f} 秒")
    bak = os.path.join(MID, f"小节时间_重排前_{time.strftime('%m%d_%H%M%S')}.csv")
    shutil.copy(TIMES_CSV, bak)
    with open(TIMES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["小节", "开始", "备注"])
        for b in bars:
            w.writerow([b, fmt(st[first[b]]), "已确认" if b in fixed else ""])
    with open(os.path.join(L.ALIGN, "beats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["bar", "beat", "time"])
        for (b, k), t in zip(idx, st):
            w.writerow([b, float(k + 1), f"{t:.3f}"])
    moved = [b for b in bars if b not in fixed and abs(st[first[b]] - T[b]) > 1.0]
    print(f"写出 {TIMES_CSV}；未固定的小节里移动超过 1 秒的 {len(moved)} 个；备份 {bak}")


if __name__ == "__main__":
    main()
