# -*- coding: utf-8 -*-
"""第 4 步：把总谱的小节对到录音上，写出 数据/小节时间.csv。

做法：文字稿里每一拍的和弦（低音 + 和弦音 + 旋律音）做成 12 维音级模板，
和录音的色度特征（chroma）做动态时间规整（DTW）。第一遍用速度记号估的速度展开，
第二遍用第一遍得到的速度再展开、收紧约束。

小节时间.csv 的格式（人可以直接改）：
    小节,开始,备注
    0,1:13:13.70,
    1,1:13:16.20,
"开始"写的是在整个 MP3 里的时间（h:mm:ss.ss），方便边听原录音边改。
改过的 CSV 不会被覆盖：脚本发现 CSV 已存在时，只把自动结果写到 中间文件/align/小节时间_自动.csv，
除非加 --force。

另外输出 中间文件/align/beats.csv（每一拍的时间，渲染时用来让和弦在小节内按实际拍点切换）
和 中间文件/align/check_*.png（核对图：上半是录音色度，下半是谱面模板，竖线是小节线）。
"""
import os, sys, csv, json
import numpy as np
from common import MID, TIMES_CSV, HARMONY_TXT, AUDIO_START, MUSIC_START, MUSIC_END
import textdoc

ALIGN = os.path.join(MID, "align")
os.makedirs(ALIGN, exist_ok=True)
FEAT = os.path.join(MID, "audio", "features.npz")

# 速度记号估出来的大致速度（四分音符/分钟），只用于第一遍的展开；DTW 会自己修正。
TEMPO_GUIDE = [
    (0, 46), (41, 54), (51, 60), (74, 76), (79, 120), (83, 150), (88, 90), (90, 40), (92, 46),
    (124, 54), (132, 60), (157, 72), (182, 110), (192, 80), (195, 120), (198, 48), (213, 54),
    (234, 100), (243, 50), (245, 40), (250, 30), (252, 40), (276, 40), (284, 46), (304, 40), (308, 34),
    (316, 60), (328, 40),
]
FINAL_BAR_SECONDS = 26.0        # 最后一小节 "Lange"（长音）在这个录音里约 26 秒（含余响）
FR = 0.2                        # DTW 的帧长（秒）


def fmt_time(t):
    t = t + AUDIO_START
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def parse_time(s):
    s = s.strip()
    if not s:
        return None
    parts = s.split(":")
    v = 0.0
    for p in parts:
        v = v * 60 + float(p)
    return v - AUDIO_START


OMR_WEIGHT = 0.6        # 读谱得到的实际音高模板所占的比重（其余是文字稿里的和弦）
OMR_LATE_FROM = 168     # 从这一小节起文字稿的和弦待复核，几乎只用读谱结果
OMR_WEIGHT_LATE = 0.95


def omr_beat_chroma():
    """omr.py 读出的音 → {(小节, 拍): 12 维向量}。音从起点一直响到同一行谱表的下一个音或小节末。"""
    d = os.path.join(MID, "omr")
    out = {}
    if not os.path.isdir(d):
        return out
    notes = []
    for fn in os.listdir(d):
        if fn.startswith("p") and fn.endswith(".json"):
            notes += json.load(open(os.path.join(d, fn)))
    by = {}
    for n in notes:
        by.setdefault((n["bar"], n["staff"], n.get("inst", "")), []).append(n)
    for (bar, staff, inst), ns in by.items():
        nb, first = textdoc.bar_beats(bar)
        ns.sort(key=lambda n: n["pos"])
        onsets = sorted(set(round(min(max(n["pos"], 0.0), 0.999), 3) for n in ns))
        for n in ns:
            p0 = round(min(max(n["pos"], 0.0), 0.999), 3)
            later = [o for o in onsets if o > p0 + 0.02]
            p1 = later[0] if later else 1.0
            w = 1.0 if abs(n.get("off", 0)) < 0.3 else 0.4
            for k in range(nb):
                b0, b1 = k / nb, (k + 1) / nb
                ov = max(0.0, min(p1, b1) - max(p0, b0)) * nb
                if ov > 0:
                    v = out.setdefault((bar, first + k), np.zeros(12))
                    v[n["midi"] % 12] += w * ov
    return out


def beat_list(doc):
    """返回 [(bar, beat_in_bar, template12, 和弦签名)]，按时间顺序。"""
    omr_ch = omr_beat_chroma()
    out = []
    last_pcs, last_bass, last_mel = [2, 6, 9], 2, None
    for bar in range(0, textdoc.LAST_BAR + 1):
        nb, first = textdoc.bar_beats(bar)
        b = doc.bars.get(bar)
        for k in range(nb):
            beat = first + k
            pcs, bass, mel = last_pcs, last_bass, last_mel
            if b:
                for c in b.chords:
                    if c.beat <= beat + 1e-6:
                        if c.pcs:
                            pcs, bass = c.pcs, c.bass
                        elif c.roman in ("—", "-"):
                            pcs, bass = [], None
                for (bt, m) in b.melody:
                    if bt <= beat + 1e-6:
                        mel = m % 12
            v = np.zeros(12)
            for p in pcs:
                v[p] += 1.0
            if bass is not None:
                v[bass] += 0.6
            if mel is not None:
                v[mel] += 0.6
            h = v.copy()
            for p in range(12):
                h[(p + 7) % 12] += 0.20 * v[p]
                h[(p + 4) % 12] += 0.08 * v[p]
            n = np.linalg.norm(h)
            h = h / n if n > 0 else np.ones(12) / np.sqrt(12)
            o = omr_ch.get((bar, float(beat)))
            if o is not None and o.sum() > 0:
                o = np.sqrt(o)
                oh = o.copy()
                for p in range(12):
                    oh[(p + 7) % 12] += 0.20 * o[p]
                    oh[(p + 4) % 12] += 0.08 * o[p]
                oh /= np.linalg.norm(oh)
                wgt = OMR_WEIGHT_LATE if bar >= OMR_LATE_FROM else OMR_WEIGHT
                h = (1 - wgt) * h + wgt * oh
                h /= np.linalg.norm(h)
            out.append((bar, beat, h, (tuple(sorted(pcs)), bass)))
            last_pcs, last_bass, last_mel = pcs, bass, mel
    return out


def guide_tempo(bar):
    t = TEMPO_GUIDE[0][1]
    for b, v in TEMPO_GUIDE:
        if bar >= b:
            t = v
    return t


def audio_features():
    f = np.load(FEAT)
    ch = f["chroma"].astype(np.float64)
    ch = ch - ch.min(1, keepdims=True)
    k = int(round(FR / float(f["hop"])))
    n = len(ch) // k
    ch = ch[:n * k].reshape(n, k, 12).mean(1)
    # 0.6 秒平滑
    ker = np.ones(3) / 3
    ch = np.stack([np.convolve(ch[:, i], ker, mode="same") for i in range(12)], 1)
    e = f["energy"][:n * k].reshape(n, k).mean(1)
    nrm = np.linalg.norm(ch, axis=1, keepdims=True)
    ch = ch / np.maximum(nrm, 1e-9)
    return ch, e


def find_music_span(e):
    db = 20 * np.log10(e + 1e-9)
    loud = np.where(db > db.max() - 45)[0]
    return int(loud[0]), int(loud[-1])


def dtw(C, steps):
    """C: M×N 代价。steps: [(di,dj)]，每一步只加终点代价。返回路径 [(i,j)]。"""
    M, N = C.shape
    INF = 1e18
    maxdi = max(s[0] for s in steps)
    D = np.full((maxdi + 1, N), INF)
    P = np.zeros((M, N), np.int8)
    rows = {}
    for i in range(M):
        cur = np.full(N, INF)
        if i == 0:
            cur[0] = C[0, 0]
        else:
            best = np.full(N, INF); arg = np.zeros(N, np.int8)
            for si, (di, dj) in enumerate(steps):
                if i - di < 0:
                    continue
                prev = rows[i - di]
                cand = np.full(N, INF)
                cand[dj:] = prev[:N - dj]
                better = cand < best
                best[better] = cand[better]; arg[better] = si
            cur = best + C[i]
            P[i] = arg
        rows[i] = cur
        if i - maxdi - 1 in rows:
            del rows[i - maxdi - 1]
    # 回溯
    i, j = M - 1, N - 1
    path = [(i, j)]
    while i > 0 or j > 0:
        di, dj = steps[P[i, j]]
        i -= di; j -= dj
        if i < 0 or j < 0:
            break
        path.append((i, j))
    return path[::-1]


def run_pass(templates, beat_dur, A, j0, j1, steps):
    lens = np.maximum(1, np.round(np.array(beat_dur) / FR).astype(int))
    S = np.repeat(np.array([t for t in templates]), lens, axis=0)
    starts = np.concatenate([[0], np.cumsum(lens)[:-1]])
    Aseg = A[j0:j1 + 1]
    C = 1.0 - S @ Aseg.T
    path = dtw(C.astype(np.float32), steps)
    pi = np.array([p[0] for p in path]); pj = np.array([p[1] for p in path])
    # 每个谱面帧对应的录音帧（取平均）
    M = len(S)
    amap = np.zeros(M)
    for i in range(M):
        sel = pj[pi == i]
        amap[i] = sel.mean() if len(sel) else np.nan
    idx = np.arange(M)
    ok = ~np.isnan(amap)
    amap = np.interp(idx, idx[ok], amap[ok])
    # 拍的开始：谱面帧起点对应的录音帧（取该拍第一帧与上一拍最后一帧之间）
    bt = []
    for s in starts:
        a = amap[s - 1] if s > 0 else amap[0]
        b = amap[s]
        bt.append(((a + b) / 2 if s > 0 else b) + j0)
    cost = C[pi, pj].mean()
    return np.array(bt) * FR, cost


ANCHORS_CSV = os.path.join(os.path.dirname(TIMES_CSV), "对齐锚点.csv")


def load_anchors():
    """数据/对齐锚点.csv：人工确认过的"某小节在录音里的开始时间"。对齐时分段进行，锚点之间各自做 DTW。"""
    out = {}
    if os.path.exists(ANCHORS_CSV):
        for r in csv.DictReader(open(ANCHORS_CSV, encoding="utf-8")):
            t = parse_time(r["开始"])
            if t is not None:
                out[int(r["小节"])] = t
    return out


def align_segment(beats, i0, i1, ta, tb, A):
    """把 beats[i0:i1] 对到录音 [ta, tb)。返回每拍开始时间。"""
    seg = beats[i0:i1]
    dur = np.array([60.0 / guide_tempo(b) for (b, bt, *_) in seg])
    dur *= (tb - ta) / dur.sum()
    if len(seg) == 1:
        return np.array([ta])
    j0, j1 = int(round(ta / FR)), max(int(round(ta / FR)) + 1, int(round(tb / FR)) - 1)
    temps = [b[2] for b in seg]
    bt1, _ = run_pass(temps, list(dur), A, j0, j1, [(1, 1), (1, 2), (2, 1)])
    bt1[0] = ta
    # 限制：每拍时长在期望值的 0.5–2 倍之间，再按总长归一
    d = np.diff(np.concatenate([bt1, [tb]]))
    d = np.clip(d, 0.5 * dur, 2.0 * dur)
    d *= (tb - ta) / d.sum()
    # 和弦不变的一串拍子：录音里没有可对的变化，DTW 的分配是任意的。
    # 保留这一串的总长，内部按速度表的比例重新分配。
    k = 0
    while k < len(seg):
        m = k
        while m + 1 < len(seg) and seg[m + 1][3] == seg[k][3]:
            m += 1
        if m > k:
            tot = d[k:m + 1].sum()
            d[k:m + 1] = dur[k:m + 1] * tot / dur[k:m + 1].sum()
        k = m + 1
    return ta + np.concatenate([[0], np.cumsum(d)[:-1]])


def main():
    force = "--force" in sys.argv
    src = HARMONY_TXT
    for a in sys.argv[1:]:
        if a.endswith(".txt"):
            src = a
    doc = textdoc.parse(src)
    beats = beat_list(doc)
    A, e = audio_features()
    t_start, t_end = MUSIC_START, MUSIC_END
    anchors = load_anchors()
    anchors.setdefault(0, t_start)
    print(f"音乐范围：{fmt_time(t_start)} – {fmt_time(t_end)}；锚点 {len(anchors)} 个（{ANCHORS_CSV}）")
    first_beat = {}
    for i, (bar, beat, *_) in enumerate(beats):
        first_beat.setdefault(bar, i)
    keys = sorted(b for b in anchors if b in first_beat)
    bounds = [(first_beat[b], anchors[b]) for b in keys] + [(len(beats), t_end)]
    bt = np.zeros(len(beats))
    for (i0, ta), (i1, tb) in zip(bounds[:-1], bounds[1:]):
        bt[i0:i1] = align_segment(beats, i0, i1, ta, tb, A)
    with open(os.path.join(ALIGN, "beats.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bar", "beat", "time"])
        for (bar, beat, *_), t in zip(beats, bt):
            w.writerow([bar, beat, f"{t:.3f}"])
    bar_start = {}
    for (bar, beat, *_), t in zip(beats, bt):
        bar_start.setdefault(bar, t)
    times = np.arange(len(A)) * FR
    sims = {}
    for bi, (bar, beat, tpl, *_) in enumerate(beats):
        t0 = bt[bi]; t1 = bt[bi + 1] if bi + 1 < len(bt) else t_end
        sel = (times >= t0) & (times < max(t1, t0 + FR))
        if sel.any():
            sims.setdefault(bar, []).append(float((A[sel] @ tpl).mean()))
    rows = []
    for bar in sorted(bar_start):
        sm = np.mean(sims.get(bar, [0]))
        rows.append([bar, fmt_time(bar_start[bar]), f"{sm:.2f}"])
    out_auto = os.path.join(ALIGN, "小节时间_自动.csv")
    for path in ([out_auto] + ([TIMES_CSV] if (force or not os.path.exists(TIMES_CSV)) else [])):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["小节", "开始", "吻合度"])
            w.writerows(rows)
        print("写出", path)
    if os.path.exists(TIMES_CSV) and not force:
        print(f"{TIMES_CSV} 已存在，未覆盖（自动结果在 {out_auto}；要覆盖加 --force）")
    np.save(os.path.join(ALIGN, "music_span.npy"), np.array([t_start, t_end]))
    low = sorted(rows, key=lambda r: float(r[2]))[:15]
    print("吻合度最低的小节：", ", ".join(f"{r[0]}({r[2]})" for r in low))


if __name__ == "__main__":
    main()
