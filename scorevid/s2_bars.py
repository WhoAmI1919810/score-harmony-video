# -*- coding: utf-8 -*-
"""第 2 步：校正扫描页的倾斜，找出谱表、系统和小节线，写出 数据/小节位置.csv。

小节位置.csv 每行一个小节：
    bar,page,system,x0,x1,y0,y1
bar 从 0 开始（0 = 弱起小节）；page 是 PDF 页码；坐标是校正后页面图（中间文件/pages_deskew）上的像素。
x0/x1 是这一小节左右两条小节线，y0/y1 是所在系统最上一条和最下一条谱线。
自动识别若有错，可直接改 CSV；若 CSV 已存在且被手改过，用 --force 才会覆盖。

同时在 中间文件/bars_debug/ 输出每页的核对图（小节框 + 小节号）。
"""
import os, sys, csv
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
from common import PAGES_DIR, MID, BARS_CSV, FIRST_PAGE, LAST_PAGE, FONT_DIR

DESKEW_DIR = os.path.join(MID, "pages_deskew")
DEBUG_DIR = os.path.join(MID, "bars_debug")
os.makedirs(DESKEW_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# 印刷谱上标出的系统起始小节号（用来核对自动数出的小节）。弱起算第 0 小节。
PRINTED_SYSTEM_STARTS = {}   # 人声缩谱没有印小节号
LAST_BAR = None


def estimate_skew(ink, nstrip=24, rng=1.0, step=0.01):
    """横线（谱线）的倾斜角（度）：行投影在各竖条之间错位对齐时最尖锐。正值 = 向右下倾。"""
    H, W = ink.shape
    xs = np.linspace(0, W, nstrip + 1).astype(int)
    profs = [ink[:, xs[i]:xs[i + 1]].sum(1).astype(float) for i in range(nstrip)]
    xc = [(xs[i] + xs[i + 1]) / 2 - W / 2 for i in range(nstrip)]
    r = np.arange(H)
    best = None
    for ang in np.arange(-rng, rng + 1e-9, step):
        t = np.tan(np.radians(ang))
        tot = np.zeros(H)
        for p, x in zip(profs, xc):
            tot += np.interp(r + x * t, r, p, left=0, right=0)
        score = (tot ** 2).sum()
        if best is None or score > best[0]:
            best = (score, ang)
    return best[1]


def deskew_page(pno):
    """扫描页常是"错切"而不是旋转：谱线斜了而小节线基本竖直。
    分别估计谱线的斜度（th）和竖线的斜度（tv），用仿射变换各自拉正。"""
    cached = os.path.join(DESKEW_DIR, f"p{pno:03d}.png")
    if os.path.exists(cached) and "--redeskew" not in sys.argv:
        return Image.open(cached).convert("L"), (0.0, 0.0)
    src = Image.open(os.path.join(PAGES_DIR, f"p{pno:03d}.png")).convert("L")
    ink = np.array(src) < 128
    H, W = ink.shape
    ah = estimate_skew(ink)
    # 竖线：只看长竖线（≥ 60 像素的竖向连续墨迹），转置后同样估计
    vert = ndi.binary_opening(ink, structure=np.ones((61, 1), bool))
    av = estimate_skew(vert.T)
    th, tv = np.tan(np.radians(ah)), np.tan(np.radians(av))
    if abs(ah) < 0.005 and abs(av) < 0.005:
        out = src.copy()
    else:
        # 输出 (x, y) 取输入 (x + (y-H/2)*tv, y + (x-W/2)*th)
        out = src.transform((W, H), Image.AFFINE,
                            (1, tv, -H / 2 * tv, th, 1, -W / 2 * th),
                            resample=Image.BICUBIC, fillcolor=255)
    out.save(os.path.join(DESKEW_DIR, f"p{pno:03d}.png"))
    return out, (ah, av)


def find_staves(ink):
    """返回 [(top_line_y, bottom_line_y, [5 条线的 y])]"""
    H, W = ink.shape
    op = ndi.binary_opening(ink, structure=np.ones((1, 61), bool))
    prof = op.sum(1).astype(float)
    sm = np.convolve(prof, [0.5, 1, 0.5], mode="same")
    thr = 0.15 * W
    peaks = [r for r in range(1, H - 1) if sm[r] >= thr and sm[r] >= sm[r - 1] and sm[r] > sm[r + 1]]
    # 合并太近的峰：谱线略弯时一条线在投影上分成两个相距几像素的峰，取加权中心
    groups = []
    for r in peaks:
        if groups and r - groups[-1][-1] < 6:
            groups[-1].append(r)
        else:
            groups.append([r])
    # 两种取法都做候选：最强的峰（有符杠贴着谱线时更准）和加权中心（谱线分成两个峰时更准）
    strongest = [max(g, key=lambda r: sm[r]) for g in groups]
    cents = [int(round(sum(r * sm[r] for r in g) / sum(sm[r] for r in g))) for g in groups]
    for g, c in zip(groups, cents):
        sm[c] = max(sm[c], max(sm[r] for r in g))
    merged = sorted(set(strongest) | set(cents) | set(peaks))
    # 五条等距的峰（中间允许夹着连线、符杠造成的杂峰）
    pk = np.array(merged)
    cands = []
    for y0 in merged:
        best = None
        for d in np.arange(10, 24.01, 0.5):
            five = [y0]
            for k in range(1, 5):
                c = pk[np.abs(pk - (y0 + k * d)) <= 3]
                if not len(c):
                    break
                five.append(int(c[np.argmin(np.abs(c - (y0 + k * d)))]))
            if len(five) == 5:
                dd = np.diff(five)
                if dd.min() >= 9 and dd.max() - dd.min() <= 4:
                    sc = sum(sm[f] for f in five) - 50 * (dd.max() - dd.min())
                    if best is None or sc > best[0]:
                        best = (sc, five)
        if best:
            cands.append(best)
    # 按分数从高到低取互不重叠的五线组（连线、加线、符杠造成的假线组分数低）
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for sc, five in cands:
        if all(five[-1] + 3 < f[0] or five[0] > f[-1] + 3 for f in chosen):
            chosen.append(five)
    staves = []
    for five in sorted(chosen):
        m = np.zeros(W, int)
        for ly in five:
            m += op[max(0, ly - 3):ly + 4].any(0)
        mm = ndi.binary_closing(np.pad(m >= 3, 200), structure=np.ones(301, bool))[200:-200]
        lab, nl = ndi.label(mm)
        if nl:
            sizes = ndi.sum(mm, lab, np.arange(1, nl + 1))
            mm = lab == (1 + int(np.argmax(sizes)))
        xs = np.where(mm)[0]
        if len(xs):
            # 谱号、调号很密的地方，长横线过滤会断开：沿五条谱线本身往左延伸（五条里至少四条有墨迹，允许 40 像素的缺口）
            # 扫描页左边常有弯曲，谱线上下漂几个像素；密集和弦处长横线过滤会断开：向左、向右沿每条线跟踪
            def track(x_start, step):
                cur = []
                for ly in five:
                    best = ly
                    for d in sorted(range(-12, 13), key=abs):
                        y = ly + d
                        if 0 <= y < H and ink[y, max(0, x_start - 30):x_start + 30].mean() > 0.8:
                            best = y; break
                    cur.append(best)
                x_end = x_start; gap = 0; x = x_start + step
                while 0 < x < W - 1:
                    hit = 0
                    for i, ly in enumerate(cur):
                        c = ink[max(0, ly - 2):ly + 3, x]
                        if c.any():
                            hit += 1
                            ys_ = np.where(c)[0] + max(0, ly - 2)
                            cur[i] = int(ys_[np.argmin(np.abs(ys_ - ly))])
                    if hit >= 4:
                        x_end = x; gap = 0
                    else:
                        gap += 1
                        if gap > 40:
                            break
                    x += step
                return x_end
            x_left = track(int(xs[0]), -1)
            x_right = track(int(xs[-1]), 1)
            staves.append((five[0], five[-1], five, x_left, x_right))
    return staves


def vertical_cover(ink, y0, y1, tol=2):
    """每一列在 [y0,y1] 范围内（允许左右 tol 像素）是否被墨迹覆盖到 ≥92%。"""
    band = ink[y0:y1 + 1]
    if tol:
        band = ndi.maximum_filter1d(band.astype(np.uint8), size=2 * tol + 1, axis=1).astype(bool)
    return band.mean(0) >= 0.92


def find_systems(ink, staves):
    """相邻两谱表之间若有一条竖线（系统左端的总谱线）贯通，就属于同一系统。
    返回 (systems, sys_left)：systems 是谱表序号的分组，sys_left 是每个系统左端总谱线的 x。"""
    H, W = ink.shape
    x_lo, x_hi = int(0.04 * W), int(0.30 * W)
    systems = [[0]]
    links = []
    for k in range(1, len(staves)):
        prev_b = staves[k - 1][1]
        cur_t = staves[k][0]
        band = ink[prev_b:cur_t + 1, x_lo - 1:x_hi + 1]
        band = band[:, :-2] | band[:, 1:-1] | band[:, 2:]
        cover = band.mean(0)
        j = int(np.argmax(cover))
        if cover[j] > 0.97:
            systems[-1].append(k)
            links.append(x_lo + j)
        else:
            systems.append([k])
    # 每个系统的左端：谱表内也贯通的最左一列
    sys_left = []
    for sidx in systems:
        best = None
        for x in range(x_lo, x_hi):
            ok = all(ink[staves[k][0]:staves[k][1] + 1, max(0, x - 1):x + 2].any(1).mean() > 0.95 for k in sidx)
            if ok:
                best = x
                break
        sys_left.append(best if best is not None else min(staves[k][3] for k in sidx))
    return systems, sys_left


def find_barlines(ink, staves, sys_idx, sys_left, drift=7):
    """小节线：同一 x（允许上下谱表之间漂移 ±drift 像素）贯穿绝大多数谱表，
    并且在同一乐器组内跨过谱表之间的空隙（符干不会跨空隙）。"""
    H, W = ink.shape
    covs = np.array([vertical_cover(ink, staves[k][0], staves[k][1], tol=2) for k in sys_idx])
    wide = ndi.maximum_filter1d(covs.astype(np.uint8), size=2 * drift + 1, axis=1).astype(bool)
    frac = wide.mean(0)
    # 谱表之间空隙的贯通情况
    gaps = []
    for a, b in zip(sys_idx[:-1], sys_idx[1:]):
        g0, g1 = staves[a][1], staves[b][0]
        band = ink[g0:g1 + 1]
        band = ndi.maximum_filter1d(band.astype(np.uint8), size=7, axis=1).astype(bool)
        gaps.append(band.mean(0) >= 0.85)
    gaps = np.array(gaps) if gaps else np.zeros((0, W), bool)
    gwide = ndi.maximum_filter1d(gaps.astype(np.uint8), size=2 * drift + 1, axis=1).astype(bool) if len(gaps) else gaps
    gfrac = gwide.mean(0) if len(gaps) else np.ones(W)
    # 人声缩谱：人声各行小节线分开画，钢琴大谱表（系统最下两行）的小节线跨过中间空隙；
    # 钢琴的小节线有时是虚线（只在人声行上是实线）。
    n = len(sys_idx)
    gpiano = gwide[-1] if len(gaps) else np.ones(W, bool)
    if n >= 6:
        ok_mask = frac >= 0.70
    elif n >= 3:
        ok_mask = (frac >= 0.99) | ((frac >= (n - 1) / n - 0.01) & gpiano)
    else:
        ok_mask = (frac >= 0.99) & gpiano
    xl = sys_left - 8
    xr = max(staves[k][4] for k in sys_idx) + 12
    ok = ok_mask.copy()
    ok[:max(0, xl)] = False
    ok[min(W, xr):] = False
    xs = np.where(ok)[0]
    groups = []
    for x in xs:
        if groups and x - groups[-1][-1] <= 3:
            groups[-1].append(x)
        else:
            groups.append([x])
    lines = []
    for g in groups:
        lo, hi = g[0] - drift, g[-1] + drift
        # 每个谱表在这一段里真正被覆盖的列，取中心后平均
        cs = []
        for row in covs:
            cx = np.where(row[max(0, lo):hi + 1])[0]
            if len(cx):
                cs.append(lo + (cx[0] + cx[-1]) / 2)
        c = float(np.median(cs)) if cs else (g[0] + g[-1]) / 2
        lines.append((c, c))
    # 拍号的两个数字也会竖着贯穿谱表：小节线左右两侧（谱线之外）基本是空白，拍号两侧有墨迹
    def dense(c):
        nd = 0
        for k in sys_idx:
            ls = staves[k][2]
            sp = (ls[-1] - ls[0]) / 4
            rows = [y for y in range(ls[0] + 2, ls[-1] - 1) if min(abs(y - l) for l in ls) > 2]
            o = max(4, int(0.25 * sp)); w = max(8, int(0.6 * sp))
            L = ink[rows, max(0, int(c) - o - w):max(1, int(c) - o)].any(1).mean()
            Rr = ink[rows, int(c) + o:int(c) + o + w].any(1).mean()
            if min(L, Rr) > 0.35:
                nd += 1
        return nd >= 0.5 * len(sys_idx)
    sp0 = (staves[sys_idx[0]][2][-1] - staves[sys_idx[0]][2][0]) / 4
    # 只在系统开头（谱号、调号之后的拍号）检查；行中换拍号紧跟小节线，下面合并时会留左边那条
    lines = [l for l in lines if l[0] <= xl + 30 or l[0] > xl + 15 * sp0 or not dense(l[0])]
    merged = []
    for l in lines:
        if merged and l[0] - merged[-1][1] <= 50:
            # 双小节线、紧跟小节线的拍号（两个数字也会贯穿各行）：留最左一条
            merged[-1] = (merged[-1][0], merged[-1][0])
        else:
            merged.append(l)
    # 虚线小节线（钢琴部分常用）：在很宽的"小节"里找每行谱表都有一截竖线、且两侧空白的列
    def dotted_lines(xa, xb):
        found = []
        cov = []
        for k in sys_idx:
            ls = staves[k][2]
            band = ink[ls[0]:ls[-1] + 1, xa:xb]
            band = ndi.maximum_filter1d(band.astype(np.uint8), size=3, axis=1).astype(bool)
            cov.append(band.mean(0))
        cov = np.array(cov)
        gcov = []
        for k1, k2 in zip(sys_idx[:-1], sys_idx[1:]):
            g0, g1 = staves[k1][2][-1] + 4, staves[k2][2][0] - 4
            if g1 - g0 < 10:
                continue
            band = ink[g0:g1, xa:xb]
            band = ndi.maximum_filter1d(band.astype(np.uint8), size=3, axis=1).astype(bool)
            gcov.append(band.mean(0))
        gmin = np.array(gcov).min(0) if gcov else np.ones(xb - xa)
        ok = (cov.min(0) >= 0.30) & (cov.mean(0) >= 0.40) & (gmin >= 0.25)
        xs = np.where(ok)[0]
        grp = []
        for x in xs:
            if grp and x - grp[-1][-1] <= 3:
                grp[-1].append(x)
            else:
                grp.append([x])
        for g in grp:
            c = xa + (g[0] + g[-1]) / 2
            if len(g) > 8:
                continue                      # 太宽：是符头、和弦块，不是线
            if not dense(c):
                found.append((c, c))
        return found
    extra = []
    pairs = list(zip(merged, merged[1:]))
    if len(merged) <= 2:          # 整个系统一条内部小节线都没找到：多半是虚线小节线
        pairs = [((float(min(staves[k][3] for k in sys_idx)), 0), (float(max(staves[k][4] for k in sys_idx)), 0))]
    for (a0, _), (a1, _) in pairs:
        if a1 - a0 > 700 and len(merged) <= 2:
            extra += [l for l in dotted_lines(int(a0) + 60, int(a1) - 40)]
    if extra:
        merged = sorted(merged + extra)
    # 太窄的"小节"（< 100 像素）是误判：去掉里面那条线
    k = 1
    while k < len(merged):
        if merged[k][0] - merged[k - 1][0] < 100 and len(merged) > 2:
            del merged[k]
        else:
            k += 1
    # 系统两端：谱表开头没有贯通竖线、或最后一行谱表比别的行短时，补上两端
    x_start = min(staves[k][3] for k in sys_idx)
    x_end = max(staves[k][4] for k in sys_idx)
    if not merged or merged[0][0] > x_start + 40:
        merged.insert(0, (float(x_start), float(x_start)))
    if merged[-1][0] < x_end - 160:
        merged.append((float(x_end), float(x_end)))
    return merged, frac


# ---------- 识别之后的修正 ----------
def count_heads(ink, staves, sidx, xa, xb):
    """[xa, xb) 里各行谱表上的符头数（读谱程序的符头识别；与升降号重叠的不算）。"""
    import omr
    n = 0
    for k in sidx:
        ln = staves[k][2]
        try:
            lines, sp, top, reg, clean = omr._clean_region(ink, ln, int(xa), int(xb))
            tp = _acc_tpls(sp)
            accs = omr.find_accidentals(clean, sp, tp)
            accs_abs = [(ax + int(xa), ay + top, kk, sc) for (ax, ay, kk, sc) in accs]
            heads = omr.detect_heads(ink, ln, int(xa), int(xb), accs_abs)[0]
        except Exception:
            continue
        n += sum(1 for h in heads if xa + 0.3 * sp < h[0] < xb - 0.3 * sp)
    return n


_TPL_CACHE = {}


def _acc_tpls(sp):
    key = round(sp, 1)
    if key not in _TPL_CACHE:
        import omr_page as omr8
        _TPL_CACHE[key] = omr8.acc_templates(sp)
    return _TPL_CACHE[key]


def is_double(ink, staves, sidx, x):
    """x 附近（±30 像素）是否有两条贯穿谱表的竖线（双小节线、终止线）。逐行谱表看（各行之间允许错开几像素）。"""
    x = int(x)
    xa, xb = max(0, x - 30), x + 31
    nd = 0
    for k in sidx:
        ls = staves[k][2]
        ok = ink[ls[0]:ls[-1] + 1, xa:xb].mean(0) >= 0.85
        runs = int(ok[0]) + int(np.sum(ok[1:] & ~ok[:-1]))
        nd += runs >= 2
    return nd >= 0.7 * len(sidx)


def count_stems(ink, staves, sidx, xa, xb):
    """[xa, xb) 里（去掉两边的小节线）长度超过 3.3 个间距的竖线段数。"""
    n = 0
    for k in sidx:
        ls = staves[k][2]
        sp = (ls[-1] - ls[0]) / 4
        y0 = max(0, int(ls[0] - 4 * sp)); y1 = int(ls[-1] + 4 * sp)
        reg = ink[y0:y1, int(xa) + 12:int(xb) - 8]
        if reg.shape[1] <= 0:
            continue
        v = ndi.binary_opening(reg, structure=np.ones((int(3.3 * sp), 1), bool)).any(0)
        n += ndi.label(v)[1]
    return n


def dotted_between(ink, staves, k1, k2, xa, xb):
    """一对上下相邻谱表（钢琴大谱表）之间的虚线小节线：两行谱表内都有一截竖线、中间空隙里也有一串点。"""
    out = []
    covs = []
    for k in (k1, k2):
        ls = staves[k][2]
        band = ink[ls[0]:ls[-1] + 1, xa:xb]
        band = ndi.maximum_filter1d(band.astype(np.uint8), size=3, axis=1).astype(bool)
        covs.append(band.mean(0))
    g0, g1 = staves[k1][2][-1] + 4, staves[k2][2][0] - 4
    if g1 - g0 < 10:
        return out
    gb = ndi.maximum_filter1d(ink[g0:g1, xa:xb].astype(np.uint8), size=3, axis=1).astype(bool).mean(0)
    ok = (np.minimum(covs[0], covs[1]) >= 0.30) & ((covs[0] + covs[1]) / 2 >= 0.45) & (gb >= 0.25)
    xs = np.where(ok)[0]
    grp = []
    for x in xs:
        if grp and x - grp[-1][-1] <= 3:
            grp[-1].append(x)
        else:
            grp.append([x])
    for g in grp:
        if len(g) <= 8:
            c = int(xa + (g[0] + g[-1]) / 2)
            # 钢琴大谱表的小节线在两行之间是连续的
            col = ink[g0:g1, c - 3:c + 4].any(1)
            if col.mean() >= 0.85:
                out.append(xa + (g[0] + g[-1]) / 2)
    return out


def refine_system(ink, staves, sidx, xs, log):
    """xs: 这一系统的小节线 x（含两端）。
    1) 太窄、又没有符头的"小节"：系统末尾的是预告调号/拍号 → 去掉；系统中间的是换调号、换拍号 → 并入后一小节。
    2) 比同系统其他小节宽很多的小节：在钢琴大谱表之间找虚线小节线补上。"""
    xs = list(xs)
    if len(xs) < 2:
        return xs
    sp = (staves[sidx[0]][2][-1] - staves[sidx[0]][2][0]) / 4
    # 0) 系统开头太窄的"小节"（系统竖线/括号与谱号前的线头之间），放不下任何内容
    while len(xs) > 2 and xs[1] - xs[0] < 6 * sp:
        log.append(f"去掉系统开头的窄条 x={xs[0]}–{xs[1]}")
        del xs[0]
    # 1) 窄、左边是双小节线：系统末尾的是预告调号/拍号 → 去掉；系统中间的是换调号、换拍号 → 右边那条线是假的，并入后一小节
    k = 1
    while k < len(xs):
        ws = np.diff(xs)
        med = float(np.median(ws[1:])) if len(ws) > 2 else float(np.median(ws))
        w = xs[k] - xs[k - 1]
        last = (k == len(xs) - 1)
        if k - 1 > 0 and (w < 0.6 * med or (last and w < 0.95 * med and count_stems(ink, staves, sidx, xs[k - 1], xs[k]) == 0)) \
                and is_double(ink, staves, sidx, xs[k - 1]):
            if last or count_stems(ink, staves, sidx, xs[k - 1], xs[k]) <= 1:
                log.append(("去掉末尾的预告记号" if last else "并掉换调号/拍号处的假小节线") + f" x={xs[k - 1]}–{xs[k]}")
                del xs[k]
                continue
        k += 1
    # 1b) 系统最后一个"小节"特别窄、左边又不是双小节线：那条线是符干或符杠，去掉
    if len(xs) >= 4:
        ws = np.diff(xs); med = float(np.median(ws[1:]))
        if ws[-1] < 0.4 * med and not is_double(ink, staves, sidx, xs[-2]):
            log.append(f"去掉末尾的假小节线 x={xs[-2]}")
            del xs[-2]
    # 2) 宽小节里的虚线小节线
    ws = np.diff(xs)
    if len(ws) >= 3:
        med = float(np.median(ws[1:]))
    elif len(ws) >= 1:
        med = float(np.median(ws))
    else:
        return xs
    added = []
    for j in range(len(xs) - 1):
        a, b = xs[j], xs[j + 1]
        w = b - a
        if j == 0 and len(ws) >= 2:
            continue                    # 系统第一小节含谱号、调号，本来就宽
        lim = 1.6 * med if len(ws) >= 3 else 900
        if w < lim:
            continue
        cand = []
        bottom = sidx[-3:] if len(sidx) >= 3 else sidx
        for k1, k2 in zip(bottom[:-1], bottom[1:]):
            cand += dotted_between(ink, staves, k1, k2, int(a + (8 * sp if j == 0 else 3 * sp)), int(b - 3 * sp))
        cand = sorted(cand)
        merged = []
        for c in cand:
            if merged and c - merged[-1] < 4 * sp:
                continue
            merged.append(c)
        # 每段都不能太短
        pts = [a] + merged + [b]
        if merged and min(np.diff(pts)) >= max(6 * sp, 0.35 * med):
            added += merged
            log.append(f"补虚线小节线 {len(merged)} 条于 x={a}–{b}")
    xs = sorted(xs + [int(round(c)) for c in added])
    # 最后再查一次：末尾特别窄、左边不是双小节线的"小节"（补虚线时可能把符干当成了线）
    if len(xs) >= 4:
        ws = np.diff(xs); med = float(np.median(ws[1:]))
        if ws[-1] < 0.4 * med and not is_double(ink, staves, sidx, xs[-2]):
            log.append(f"去掉末尾的假小节线 x={xs[-2]}")
            del xs[-2]
    return xs


EDITS = []
EDITS_TXT = os.path.join(os.path.dirname(BARS_CSV), "小节修正.txt")


def load_edits():
    """数据/小节修正.txt：按谱面位置写的人工修正（不按小节号，重新识别后仍然有效）。
       去线 页 y x    去掉这一页、纵坐标 y 所在系统里离 x 最近的小节线（两个小节合并）
       加线 页 y x    在这里加一条小节线（一个小节拆成两个）
       坐标是校正后谱页（中间文件/pages_deskew，2700×3600）上的像素。"""
    out = []
    if os.path.exists(EDITS_TXT):
        for l in open(EDITS_TXT, encoding="utf-8"):
            t = l.split("#")[0].split()
            if len(t) == 4 and t[0] in ("去线", "加线"):
                out.append((t[0], int(t[1]), int(t[2]), int(t[3])))
    return out


def apply_edits(pno, staves, found, edits, log):
    for op, p, y, x in edits:
        if p != pno:
            continue
        hit = None
        for f in found:
            y0 = staves[f[0][0]][0] - 60; y1 = staves[f[0][-1]][1] + 60
            if y0 <= y <= y1:
                hit = f; break
        if hit is None:
            log.append(f"人工修正没对上系统：{op} p{p} y={y} x={x}")
            continue
        xs = hit[1]
        if op == "去线":
            k = min(range(1, len(xs) - 1), key=lambda i: abs(xs[i] - x), default=None)
            if k is None or abs(xs[k] - x) > 40:
                log.append(f"人工修正没找到小节线：{op} p{p} y={y} x={x}")
                continue
            log.append(f"人工去线 x={xs[k]}")
            del xs[k]
        else:
            if any(abs(v - x) < 20 for v in xs):
                continue
            xs.append(int(x)); xs.sort()
            log.append(f"人工加线 x={x}")


def main():
    force = "--force" in sys.argv
    if os.path.exists(BARS_CSV) and not force:
        print(f"{BARS_CSV} 已存在（可能被手改过）；要重新识别请加 --force")
        return
    try:
        font = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 34)
    except Exception:
        font = ImageFont.load_default()
    rows = []
    bar = 1
    problems = []
    global EDITS
    EDITS = load_edits()
    staves_json = {}
    for pno in range(FIRST_PAGE, LAST_PAGE + 1):
        img, ang = deskew_page(pno)
        ink = np.array(img) < 128
        staves = [st for st in find_staves(ink) if st[4] - st[3] > 0.55 * ink.shape[1]]
        systems, sys_left = find_systems(ink, staves)
        # 单独一行的"系统"：小节线和相邻（上或下）的多行系统对得上 → 并入（系统竖线没连上的情形）；
        # 对不上的是乐器提示小谱表（如钟），不算
        bl_all = [[int(round((a + b) / 2)) for a, b in find_barlines(ink, staves, g, sys_left[i])[0]]
                  for i, g in enumerate(systems)]
        def fits(single_xs, multi_xs):
            inner = multi_xs[1:]
            return len(inner) >= 1 and all(any(abs(x - y) <= 15 for y in single_xs) for x in inner)
        absorbed = set()
        for i, g in enumerate(systems):
            if len(g) != 1:
                continue
            for j in (i + 1, i - 1):
                if 0 <= j < len(systems) and len(systems[j]) >= 2 and fits(bl_all[i], bl_all[j]):
                    systems[j] = sorted(systems[j] + g)
                    sys_left[j] = min(sys_left[j], sys_left[i])
                    absorbed.add(i)
                    break
        keep = [i for i, g in enumerate(systems) if len(g) >= 2 and i not in absorbed]
        systems = [systems[i] for i in keep]; sys_left = [sys_left[i] for i in keep]
        printed = PRINTED_SYSTEM_STARTS.get(pno, [])
        staves_json[pno] = [[[int(v) for v in staves[k][2]] for k in sidx] for sidx in systems]
        if printed and len(systems) != len(printed):
            problems.append(f"p{pno}: 找到 {len(systems)} 个系统，印刷谱应为 {len(printed)} 个")
        dbg = img.convert("RGB")
        d = ImageDraw.Draw(dbg, "RGBA")
        # 人声与钢琴之间的竖线有时没连上，一个系统被拆成上下两块：小节线位置一一对齐的相邻块合并
        found = []
        for si, sidx in enumerate(systems):
            lines, frac = find_barlines(ink, staves, sidx, sys_left[si])
            xs = [int(round((a + b) / 2)) for a, b in lines]
            if found and len(found[-1][1]) == len(xs) and len(xs) >= 2 and \
                    max(abs(p - q) for p, q in zip(found[-1][1], xs)) <= 15:
                found[-1][0].extend(sidx)
                continue
            found.append([list(sidx), xs])
        for f in found:
            lg = []
            f[1] = refine_system(ink, staves, f[0], f[1], lg)
            for m in lg:
                problems.append(f"p{pno}: {m}")
        lg = []
        apply_edits(pno, staves, found, EDITS, lg)
        for m in lg:
            problems.append(f"p{pno}: {m}")
        systems = [f[0] for f in found]
        staves_json[pno] = [[[int(v) for v in staves[k][2]] for k in sidx] for sidx in systems]
        for si, (sidx, xs) in enumerate(found):
            y0 = staves[sidx[0]][0]
            y1 = staves[sidx[-1]][1]
            if si < len(printed) and bar != printed[si]:
                problems.append(f"p{pno} 系统{si + 1}: 自动数到第 {bar} 小节，印刷谱为 {printed[si]}")
                bar = printed[si]
            for j in range(len(xs) - 1):
                x0, x1 = xs[j], xs[j + 1]
                rows.append(dict(bar=bar, page=pno, system=si + 1, x0=x0, x1=x1, y0=y0, y1=y1))
                col = (255, 80, 0, 50) if bar % 2 == 0 else (0, 120, 255, 50)
                d.rectangle([x0, y0, x1, y1], fill=col)
                d.text((x0 + 6, y0 - 44), str(bar), fill=(220, 0, 0), font=font)
                bar += 1
            for x in xs:
                d.line([(x, y0 - 10), (x, y1 + 10)], fill=(255, 0, 0, 160), width=3)
            for k in sidx:
                for ly in staves[k][2]:
                    d.line([(0, ly), (40, ly)], fill=(0, 160, 0, 255), width=2)
        dbg.resize((dbg.width // 2, dbg.height // 2), Image.LANCZOS).save(os.path.join(DEBUG_DIR, f"p{pno:03d}.png"))
        print(f"p{pno}: 谱线斜 {ang[0]:+.2f}° 竖线斜 {ang[1]:+.2f}°, 谱表 {len(staves)}, 系统 {len(systems)} → 到第 {bar - 1} 小节")
    if LAST_BAR is not None and bar - 1 != LAST_BAR:
        problems.append(f"最后一小节自动编号为 {bar - 1}，应为 {LAST_BAR}")
    import json
    with open(os.path.join(MID, "staves.json"), "w", encoding="utf-8") as f:
        json.dump(staves_json, f)
    with open(BARS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bar", "page", "system", "x0", "x1", "y0", "y1"])
        w.writeheader()
        w.writerows(rows)
    print("写出", BARS_CSV, len(rows), "小节")
    if problems:
        print("需要核对：")
        for p in problems:
            print("  -", p)


if __name__ == "__main__":
    main()
