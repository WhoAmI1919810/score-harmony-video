# -*- coding: utf-8 -*-
"""对齐方法的评测：用用户校对过的小节时间当标准答案，比较不同对齐方法的误差。
标准答案：数据/已校范围.txt 里用户确认过的小节（真实项目里用户校对一段，就能拿那一段评测）。
评测时每部分只给起点（和终点），不给中间锚点。
用法：python3 align_lab.py 方法名 ...        方法见 METHODS"""
import os, sys, csv, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, TIMES_CSV, BARS_CSV, MUSIC_START, MUSIC_END, PART2_START
import textdoc
from align_base import omr_beat_chroma, ALIGN

FEAT = os.path.join(MID, "audio", "features.npz")
NB = 4


def parse_time(v):
    x = 0.0
    for p in v.split(":"):
        x = x * 60 + float(p)
    return x


def ground_truth():
    T = {int(r["小节"]): parse_time(r["开始"]) for r in csv.DictReader(open(TIMES_CSV, encoding="utf-8-sig"))}
    import align_dtw                                  # 延迟导入（align_dtw 也导入本模块）
    gt = align_dtw.verified(textdoc.PART2_BAR, max(T))
    return T, (gt or set(T))


def load_feats(fr):
    f = np.load(FEAT)
    hop = float(f["hop"])
    k = int(round(fr / hop))
    def pool(x):
        n = len(x) // k
        return x[:n * k].reshape(n, k, *x.shape[1:]).mean(1)
    return dict(chroma=pool(f["chroma"].astype(np.float64)), pitch=pool(f["pitch"].astype(np.float64)),
                energy=pool(f["energy"].astype(np.float64)), flux=pool(f["flux"].astype(np.float64)), fr=fr)


def omr_notes():
    import json, glob
    notes = []
    for fn in glob.glob(os.path.join(MID, "omr", "p*_s*.json")):
        notes += json.load(open(fn))
    return notes


def beat_pitch(bars):
    """每个名义拍的 84 维（MIDI 24..107）音高向量：音从起点响到同一行谱表的下一个起音或小节末。
    另返回每拍的起音数。"""
    notes = omr_notes()
    by = {}
    for n in notes:
        by.setdefault((n["bar"], n["staff"]), []).append(n)
    P = {}; ON = {}
    for (bar, staff), ns in by.items():
        ns.sort(key=lambda n: n["pos"])
        onsets = sorted(set(round(min(max(n["pos"], 0.0), 0.999), 3) for n in ns))
        for n in ns:
            p0 = round(min(max(n["pos"], 0.0), 0.999), 3)
            later = [o for o in onsets if o > p0 + 0.02]
            p1 = later[0] if later else 1.0
            m = n["midi"]
            if not (24 <= m < 108):
                continue
            ON[(bar, int(p0 * NB))] = ON.get((bar, int(p0 * NB)), 0) + 1
            for k in range(NB):
                b0, b1 = k / NB, (k + 1) / NB
                ov = max(0.0, min(p1, b1) - max(p0, b0)) * NB
                if ov > 0:
                    v = P.setdefault((bar, k), np.zeros(84))
                    v[m - 24] += ov
    return P, ON


def templates(bars, kind="chroma", harm=(1.0, 0.5, 0.33, 0.25)):
    idx = [(b, k) for b in bars for k in range(NB)]
    if kind == "chroma":
        oc = omr_beat_chroma()
        T = []
        last = np.ones(12) / np.sqrt(12)
        for b, k in idx:
            o = oc.get((b, float(1 + k)))
            if o is not None and o.sum() > 0:
                o = np.sqrt(o); h = o.copy()
                for p in range(12):
                    h[(p + 7) % 12] += 0.20 * o[p]; h[(p + 4) % 12] += 0.08 * o[p]
                last = h / np.linalg.norm(h)
            T.append(last)
        return np.array(T), idx
    P, ON = beat_pitch(bars)
    T = []
    last = np.ones(84) / np.sqrt(84)
    hs = [0, 12, 19, 24, 28, 31]
    for b, k in idx:
        v = P.get((b, k))
        if v is not None and v.sum() > 0:
            v = np.sqrt(v)
            h = np.zeros(84)
            for i in np.nonzero(v)[0]:
                for w, d in zip(harm + (0.2, 0.15), hs):
                    if i + d < 84:
                        h[i + d] += w * v[i]
            last = h / np.linalg.norm(h)
        T.append(last)
    return np.array(T), idx


def audio_vecs(F, kind):
    if kind == "chroma":
        X = F["chroma"].copy()
        X -= X.min(1, keepdims=True)
    else:
        X = F["pitch"].copy()
        X -= np.median(X, 1, keepdims=True)
        X = np.maximum(X, 0)
    ker = np.ones(3) / 3
    X = np.stack([np.convolve(X[:, i], ker, mode="same") for i in range(X.shape[1])], 1)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
    return X


# ---------------- 对齐方法 ----------------
def dtw_free(C, min_stay=1):
    """状态 i（拍）× 帧 j；每帧要么停在本拍、要么进入下一拍；起点 (0,0) 终点 (M-1,N-1)。返回每拍开始帧。"""
    M, N = C.shape
    INF = 1e18
    D = np.full(M, INF); D[0] = C[0, 0]
    adv = np.zeros((N, M), bool)
    for j in range(1, N):
        mv = np.concatenate([[INF], D[:-1]])
        a = mv < D
        D = np.where(a, mv, D) + C[:, j]
        adv[j] = a
    i = M - 1; start = np.zeros(M, int)
    for j in range(N - 1, 0, -1):
        if adv[j, i]:
            start[i] = j; i -= 1
            if i == 0:
                break
    return start


def cost_matrix(T, X, norm="z"):
    S = T @ X.T
    if norm == "z":
        S = (S - S.mean(0, keepdims=True)) / (S.std(0, keepdims=True) + 1e-6)
        S = S - S.mean(1, keepdims=True)
        C = -S; C -= C.min()
    elif norm == "cos":
        C = 1 - S
    return C


def run(method, F, T, idx, segs, **kw):
    fr = F["fr"]
    st = np.zeros(len(idx))
    for s0, s1, ta, tb in segs:
        j0, j1 = int(round(ta / fr)), int(round(tb / fr))
        X = F["X"][j0:j1]
        TT = T[s0:s1]
        sub = kw.get("sub", 1)
        TT2 = np.repeat(TT, sub, axis=0)
        C = cost_matrix(TT2, X, kw.get("norm", "cos"))
        if kw.get("dur_pen"):
            pass
        start = dtw_free(C)
        st[s0:s1] = ta + start[::sub] * fr
    return st


def refine(st, F, T, segs, win=60, lo=0.4, hi=2.5):
    """第二遍：按第一遍得到的局部速度（每拍时长取前后 ±win 拍的中位数）展开谱面，做限制斜率的 DTW。"""
    from align_base import dtw as _dtw
    fr = F["fr"]
    bd = np.diff(np.concatenate([st, [st[-1] + 1]]))
    out = np.zeros(len(st))
    for s0, s1, ta, tb in segs:
        d = bd[s0:s1].copy(); d[-1] = max(d[-1], fr)
        sm = np.array([np.median(d[max(0, k - win):k + win + 1]) for k in range(len(d))])
        sm = np.maximum(sm, fr)
        sm *= (tb - ta) / sm.sum()
        lens = np.maximum(1, np.round(sm / fr).astype(int))
        S = np.repeat(T[s0:s1], lens, axis=0)
        starts = np.concatenate([[0], np.cumsum(lens)[:-1]])
        j0, j1 = int(round(ta / fr)), int(round(tb / fr))
        X = F["X"][j0:j1]
        C = (1.0 - S @ X.T).astype(np.float32)
        path = _dtw(C, [(1, 1), (1, 2), (2, 1)])
        pi = np.array([q[0] for q in path]); pj = np.array([q[1] for q in path])
        Mm = len(S)
        amap = np.full(Mm, np.nan)
        for i in range(Mm):
            sel = pj[pi == i]
            if len(sel):
                amap[i] = sel.mean()
        ii = np.arange(Mm); ok = ~np.isnan(amap)
        amap = np.interp(ii, ii[ok], amap[ok])
        bt = np.array([(amap[s - 1] + amap[s]) / 2 if s > 0 else amap[0] for s in starts]) * fr + ta
        bt[0] = ta
        dd = np.diff(np.concatenate([bt, [tb]])); dd = np.clip(dd, lo * sm, hi * sm); dd *= (tb - ta) / dd.sum()
        out[s0:s1] = ta + np.concatenate([[0], np.cumsum(dd)[:-1]])
    return out


def evaluate(st, idx, T_gt, gt, label=""):
    first = {}
    for s, (b, k) in enumerate(idx):
        first.setdefault(b, s)
    p2 = textdoc.PART2_BAR
    res = {}
    for name, sel in (("I", lambda b: b < p2), ("II", lambda b: b >= p2)):
        e = np.array([st[first[b]] - T_gt[b] for b in sorted(gt) if sel(b) and b in first])
        ae = np.abs(e)
        res[name] = (len(e), np.median(ae), np.mean(ae < 0.5), np.mean(ae < 1.5), np.mean(ae < 5), ae.max())
    s = "  ".join(f"{k}: n={v[0]} 中位 {v[1]:.2f}s ≤0.5s {v[2]*100:.0f}% ≤1.5s {v[3]*100:.0f}% ≤5s {v[4]*100:.0f}% 最大 {v[5]:.0f}s"
                  for k, v in res.items())
    print(f"{label:28s} {s}", flush=True)
    return res


def segments(idx, T_gt, F, extra_anchors=None):
    p2 = textdoc.PART2_BAR
    first = {}
    for s, (b, k) in enumerate(idx):
        first.setdefault(b, s)
    db = 20 * np.log10(F["energy"] + 1e-9)
    fr = F["fr"]
    k2 = int(PART2_START / fr)
    loud = np.where(db[:k2] > db.max() - 50)[0]
    end1 = (loud[-1] + 1) * fr
    anchors = {min(first): MUSIC_START, p2: PART2_START}
    if extra_anchors:
        anchors.update(extra_anchors)
    keys = sorted(anchors)
    segs = []
    for a, b2 in zip(keys, keys[1:] + [None]):
        s0 = first[a]; s1 = first[b2] if b2 is not None else len(idx)
        tb = MUSIC_END if b2 is None else (end1 if b2 == p2 else anchors[b2])
        segs.append((s0, s1, anchors[a], tb))
    return segs


if __name__ == "__main__":
    T_gt, gt = ground_truth()
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    for spec in sys.argv[1:]:
        if spec == "current":
            import align_legacy as align8
            from align_base import audio_features, run_pass
            A, e = audio_features()
            T, idx = align8.templates(bars)
            F = dict(energy=e, fr=0.2)
            segs = segments(idx, T_gt, F)
            t0 = time.time()
            st = np.zeros(len(idx))
            for s0, s1, ta, tb in segs:
                st[s0:s1] = align8.hmm_align(T[s0:s1], A, ta, tb)
            evaluate(st, idx, T_gt, gt, f"current 第一遍 ({time.time() - t0:.0f}s)")
            bd = np.diff(np.concatenate([st, [MUSIC_END]]))
            st2 = np.zeros(len(idx))
            for s0, s1, ta, tb in segs:
                d = bd[s0:s1].copy(); d[-1] = max(d[-1], 0.2)
                sm = np.array([np.median(d[max(0, k - 60):k + 61]) for k in range(len(d))])
                sm *= (tb - ta) / sm.sum()
                bt, cost = run_pass(list(T[s0:s1]), list(sm), A, int(round(ta / 0.2)), int(round(tb / 0.2)) - 1,
                                    [(1, 1), (1, 2), (2, 1)])
                bt[0] = ta
                dd = np.diff(np.concatenate([bt, [tb]])); dd = np.clip(dd, 0.4 * sm, 2.5 * sm); dd *= (tb - ta) / dd.sum()
                st2[s0:s1] = ta + np.concatenate([[0], np.cumsum(dd)[:-1]])
            evaluate(st2, idx, T_gt, gt, f"current 两遍 ({time.time() - t0:.0f}s)")
            continue
        if spec.startswith("refine"):
            # refine:第一遍特征:第二遍特征:fr2
            _, k1, k2, fr2 = spec.split(":"); fr2 = float(fr2)
            F1 = load_feats(0.2); F1["X"] = audio_vecs(F1, k1)
            T1, idx = templates(bars, k1)
            segs = segments(idx, T_gt, F1)
            t0 = time.time()
            st = run("free", F1, T1, idx, segs)
            F2 = load_feats(fr2); F2["X"] = audio_vecs(F2, k2)
            T2, _ = templates(bars, k2)
            st2 = refine(st, F2, T2, segs)
            evaluate(st2, idx, T_gt, gt, f"{spec} ({time.time() - t0:.0f}s)")
            continue
        kind, fr, sub = spec.split(":")
        fr = float(fr); sub = int(sub)
        F = load_feats(fr)
        F["X"] = audio_vecs(F, kind)
        T, idx = templates(bars, kind)
        segs = segments(idx, T_gt, F)
        t0 = time.time()
        st = run("free", F, T, idx, segs, sub=sub)
        evaluate(st, idx, T_gt, gt, f"{spec} ({time.time() - t0:.0f}s)")


def anchored_eval(K_list=(30, 80, 200)):
    """模拟用户用法：每隔 K 个已校小节给一个确认点，量其余已校小节的误差（只量已校范围里的小节）。"""
    T_gt, gt = ground_truth()
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    p2 = textdoc.PART2_BAR
    eval_bars = sorted(gt)
    F = load_feats(0.2)
    Fs = {}
    for kind in ("chroma", "pitch"):
        G = dict(F); G["X"] = audio_vecs(F, kind); Fs[kind] = G
    Ts = {k: templates(bars, k) for k in ("chroma", "pitch")}
    import align_legacy as align8
    from align_base import audio_features
    A, e = audio_features()
    Tc, idx = align8.templates(bars)
    for K in K_list:
        anc = {b: T_gt[b] for b in eval_bars[::K]}
        held = set(eval_bars) - set(anc)
        segs = segments(idx, T_gt, F, anc)
        res = {}
        st = np.zeros(len(idx))
        for s0, s1, ta, tb in segs:
            st[s0:s1] = align8.hmm_align(Tc[s0:s1], A, ta, tb)
        res["旧·第一遍"] = st.copy()
        for kind in ("chroma", "pitch"):
            T, _ = Ts[kind]
            st = np.zeros(len(idx))
            for s0, s1, ta, tb in segs:
                j0, j1 = int(round(ta / 0.2)), int(round(tb / 0.2))
                C = cost_matrix(T[s0:s1], Fs[kind]["X"][j0:j1], "cos")
                st[s0:s1] = ta + dtw_free(C) * 0.2
            res["自由DTW·" + kind] = st.copy()
            res["自由DTW·" + kind + "+精修"] = refine(st, Fs["pitch"], Ts["pitch"][0], segs, win=min(60, K))
        first = {}
        for s, (b, k) in enumerate(idx):
            first.setdefault(b, s)
        for name, st in res.items():
            e_ = np.array([abs(st[first[b]] - T_gt[b]) for b in sorted(held)])
            print(f"K={K:3d} {name:22s} 中位 {np.median(e_):.2f}s ≤0.5s {np.mean(e_ < .5) * 100:.0f}% ≤1.5s {np.mean(e_ < 1.5) * 100:.0f}% ≤5s {np.mean(e_ < 5) * 100:.0f}% 最大 {e_.max():.1f}s", flush=True)


def blend_eval(K_list=(30, 80, 200), wts=(0.5, 0.7), guard=2.0):
    T_gt, gt = ground_truth()
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    p2 = textdoc.PART2_BAR
    eval_bars = sorted(gt)
    F = load_feats(0.2)
    Xp = audio_vecs(F, "pitch"); Xc = audio_vecs(F, "chroma")
    Tp, idx = templates(bars, "pitch"); Tc, _ = templates(bars, "chroma")
    Fp = dict(F); Fp["X"] = Xp
    first = {}
    for s, (b, k) in enumerate(idx):
        first.setdefault(b, s)
    for K in K_list:
        anc = {b: T_gt[b] for b in eval_bars[::K]}
        held = sorted(set(eval_bars) - set(anc))
        segs = segments(idx, T_gt, F, anc)
        for w in wts:
            st = np.zeros(len(idx))
            for s0, s1, ta, tb in segs:
                j0, j1 = int(round(ta / 0.2)), int(round(tb / 0.2))
                C = w * cost_matrix(Tp[s0:s1], Xp[j0:j1], "cos") + (1 - w) * cost_matrix(Tc[s0:s1], Xc[j0:j1], "cos")
                st[s0:s1] = ta + dtw_free(C) * 0.2
            r = refine(st, Fp, Tp, segs, win=min(60, K))
            g = np.clip(r, st - guard, st + guard)
            for name, x in (("混合", st), ("混合+精修", r), (f"混合+精修(限±{guard:g}s)", g)):
                e_ = np.array([abs(x[first[b]] - T_gt[b]) for b in held])
                print(f"K={K:3d} w={w} {name:16s} 中位 {np.median(e_):.2f}s ≤0.5s {np.mean(e_ < .5) * 100:.0f}% ≤1.5s {np.mean(e_ < 1.5) * 100:.0f}% ≤5s {np.mean(e_ < 5) * 100:.0f}% 最大 {e_.max():.1f}s", flush=True)
