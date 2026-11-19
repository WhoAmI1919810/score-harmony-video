# -*- coding: utf-8 -*-
"""【旧方法，只留作 align_lab.py 的评测对照，不要用它出时间轴（会整段偏几十秒到两分钟）】马勒八对齐第一版：把每小节 4 个名义拍的读谱音级模板对到录音色度上，写 数据/小节时间.csv 与 中间文件/align/beats.csv。

马勒八速度变化很大（同样 4 个名义拍，快板一小节约 1 秒，慢板 8 秒以上），所以不用速度表：
每个拍是一个状态，录音每 0.2 秒一帧，只能"停在本拍"或"进到下一拍"（自由速度的 DTW）。
两部分分开对；数据/对齐锚点.csv 里人工确认的小节作为固定点，把每部分再切成几段。
最短拍长 MIN_BEAT 秒（防止和弦模板对不上时一下滑过很多小节）。

用法：python3 align_legacy.py [--force]      已有 小节时间.csv 时默认不覆盖（结果写到 中间文件/align/小节时间_自动.csv）
"""
import os, sys, csv
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, TIMES_CSV, BARS_CSV, MUSIC_START, MUSIC_END, PART2_START
import textdoc
from align_base import omr_beat_chroma, audio_features, fmt_time, load_anchors, ALIGN, run_pass

FR = 0.2
NB = textdoc.BEATS_PER_BAR
MIN_BEAT = 0.2          # 秒；= 1 帧


def templates(bars):
    oc = omr_beat_chroma()
    T, idx = [], []
    last = np.ones(12) / np.sqrt(12)
    for b in bars:
        for k in range(NB):
            o = oc.get((b, float(1 + k)))
            if o is not None and o.sum() > 0:
                o = np.sqrt(o)
                h = o.copy()
                for p in range(12):
                    h[(p + 7) % 12] += 0.20 * o[p]
                    h[(p + 4) % 12] += 0.08 * o[p]
                h /= np.linalg.norm(h)
                last = h
            T.append(last); idx.append((b, 1 + k))
    return np.array(T), idx


SUB = int(os.environ.get("ALIGN_SUB", "1"))                 # 每拍拆成 2 个子状态：每拍至少停 2 帧（0.4 秒），防止对不上时一下滑过很多小节
BAND = 150.0            # 秒：第 i 拍的时间离"均速"位置不超过这么多
SOFT = 40.0             # 秒：离"均速"位置每偏 SOFT 秒，每帧加 ALPHA 的代价（软约束，速度可以变，但不能停在几拍上不走）
ALPHA = float(os.environ.get("ALIGN_ALPHA", "3"))


def hmm_align(T, A, ta, tb):
    """T: 拍模板 M×12；A: 色度 N×12（整段）；返回每拍开始时间。带宽约束 + 每拍最短停留。"""
    j0, j1 = int(round(ta / FR)), int(round(tb / FR))
    X = A[j0:j1]
    M0, N = len(T), len(X)
    if M0 == 0:
        return np.array([])
    if N < M0 * SUB + 2:
        return ta + np.arange(M0) * (tb - ta) / M0
    TT = np.repeat(T, SUB, axis=0)
    M = len(TT)
    S = TT @ X.T
    # 每帧在所有拍之间标准化：只看"这一拍比别的拍更像这一帧"多少，泛泛都像的模板不占便宜
    S = (S - S.mean(0, keepdims=True)) / (S.std(0, keepdims=True) + 1e-6)
    S = (S - S.mean(1, keepdims=True))
    C = (-S).astype(np.float32)
    C -= C.min()
    band = int(BAND / FR)
    lin = np.arange(M) * (N / M)
    jj = np.arange(N)
    INF = np.float32(1e9)
    D = np.full(M, INF, np.float32); D[0] = C[0, 0]
    adv = np.zeros((N, M), bool)
    for j in range(1, N):
        mv = np.concatenate([[INF], D[:-1]])
        a = mv < D
        dev = (lin - j) * FR / SOFT
        D = np.where(a, mv, D) + C[:, j] + ALPHA * dev * dev
        out = np.abs(lin - j) > band
        D[out] = INF
        adv[j] = a
    i = M - 1
    start = np.zeros(M, int)
    for j in range(N - 1, 0, -1):
        if adv[j, i]:
            start[i] = j
            i -= 1
            if i == 0:
                break
    if i != 0 or D[M - 1] >= INF:
        print("    （回溯失败，均分）")
        return ta + np.arange(M0) * (tb - ta) / M0
    return ta + start[::SUB] * FR


def main():
    force = "--force" in sys.argv
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    A, e = audio_features()
    db = 20 * np.log10(e + 1e-9)
    # 第一部分结束：第二部分开始前最后一个响的帧
    k2 = int(PART2_START / FR)
    loud = np.where(db[:k2] > db.max() - 50)[0]
    end1 = (loud[-1] + 1) * FR if len(loud) else PART2_START - 3
    p2 = textdoc.PART2_BAR
    anchors = load_anchors()
    anchors.setdefault(bars[0], MUSIC_START)
    anchors.setdefault(p2, PART2_START)
    T, idx = templates(bars)
    first_state = {}
    for s, (b, k) in enumerate(idx):
        first_state.setdefault(b, s)
    # 段：锚点之间；第一部分末尾到 end1，第二部分末尾到 MUSIC_END
    keys = sorted(b for b in anchors if b in first_state)
    segs = []
    for a, b2 in zip(keys, keys[1:] + [None]):
        s0 = first_state[a]
        s1 = first_state[b2] if b2 is not None else len(idx)
        ta = anchors[a]
        if b2 is None:
            tb = MUSIC_END
        elif b2 == p2:
            tb = end1
        else:
            tb = anchors[b2]
        segs.append((s0, s1, ta, tb))
    st = np.zeros(len(idx))
    for s0, s1, ta, tb in segs:
        st[s0:s1] = hmm_align(T[s0:s1], A, ta, tb)
        print(f"  段 {textdoc.bar_label(idx[s0][0])} 起 {s1 - s0} 拍  {fmt_time(ta)}–{fmt_time(tb)}", flush=True)
    # 第二遍：第一遍只用来估局部速度（每拍时长取前后 ±60 拍的中位数），
    # 再用限制斜率的 DTW（局部速度只能在估计值的 0.5–2 倍之间）重新对齐。
    if "--one-pass" not in sys.argv:
        bd = np.diff(np.concatenate([st, [MUSIC_END]]))
        st2 = np.zeros(len(idx))
        for s0, s1, ta, tb in segs:
            d = bd[s0:s1].copy()
            d[-1] = max(d[-1], 0.2)
            sm = np.array([np.median(d[max(0, k - 60):k + 61]) for k in range(len(d))])
            sm *= (tb - ta) / sm.sum()
            bt, cost = run_pass(list(T[s0:s1]), list(sm), A, int(round(ta / FR)), int(round(tb / FR)) - 1,
                                [(1, 1), (1, 2), (2, 1)])
            bt[0] = ta
            dd = np.diff(np.concatenate([bt, [tb]]))
            dd = np.clip(dd, 0.4 * sm, 2.5 * sm)
            dd *= (tb - ta) / dd.sum()
            st2[s0:s1] = ta + np.concatenate([[0], np.cumsum(dd)[:-1]])
            print(f"  第二遍：{s1 - s0} 拍，平均代价 {cost:.3f}", flush=True)
        st = st2
    with open(os.path.join(ALIGN, "beats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["bar", "beat", "time"])
        for (b, k), t in zip(idx, st):
            w.writerow([b, float(k), f"{t:.3f}"])
    rows = []
    times = np.arange(len(A)) * FR
    for b in bars:
        s = first_state[b]
        t0 = st[s]
        s_end = first_state.get(b + 1, len(idx))
        t1 = st[s_end] if s_end < len(idx) else MUSIC_END
        sel = (times >= t0) & (times < max(t1, t0 + FR))
        sim = float((A[sel] @ T[s:s_end].mean(0)).mean()) if sel.any() else 0.0
        rows.append([b, fmt_time(t0), f"{sim:.2f}"])
    out_auto = os.path.join(ALIGN, "小节时间_自动.csv")
    for path in [out_auto] + ([TIMES_CSV] if (force or not os.path.exists(TIMES_CSV)) else []):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["小节", "开始", "备注"]); w.writerows(rows)
        print("写出", path)
    np.save(os.path.join(ALIGN, "music_span.npy"), np.array([MUSIC_START, MUSIC_END]))


if __name__ == "__main__":
    main()
