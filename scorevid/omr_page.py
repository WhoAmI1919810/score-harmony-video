# -*- coding: utf-8 -*-
"""人声缩谱自动读谱：不用手写读谱配置，每行谱表自动认谱号（含行中换谱号）、调号（含行中换调号）。
人声缩谱全部是实际音高，男高音谱的八度差不影响音级，统一不移调。

用法：
  python3 omr_page.py templates          重建谱号模板（取第 1 页的高音、低音谱号）
  python3 omr_page.py 页码 [系统号]       读一页 / 一个系统，写 中间文件/omr/pNNN_sK.json 与核对图
  python3 omr_page.py all [起页 止页]     全部
  python3 omr_page.py bar 起小节 [止小节] 打印起音点音高（同 omr.py）
"""
import os, sys, json
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.signal import fftconvolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, WORK
import omr

TPL8 = os.path.join(omr.OMR, "templates8.npz")
from common import OMR_TEMPLATES
M3_TPL = OMR_TEMPLATES   # 谱号模板（assets/omr_templates.npz），可在 project.json 的 omr_templates 换
from common import cfg
M3_SP = 12.8          # assets/omr_templates.npz（取自另一份扫描）的谱线间距，还原号模板按它缩放
# 谱号、升降号模板从本谱自己的页面上截（字形每个版本不同）。位置写在 project.json 的 omr.*；
# 默认值是马勒八人声缩谱（U.E.）的位置，换谱子一定要重新量：打开 中间文件/pages_deskew/pNNN.png 找一处清楚的谱号和调号。
_O = cfg("omr", {}) or {}
CLEF_SP = 20.3        # 谱号模板所在谱表的间距（只作记录）
CLEF_LOG = []


def build_templates():
    import s2_bars as sb
    cp = int(_O.get("clef_page", 1))
    a = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{cp:03d}.png")).convert("L")) < 140
    st = sb.find_staves(a)
    x0 = int(_O.get("clef_x0", 586))                     # 谱号左边缘大致 x
    k_tr, k_bs = _O.get("clef_staves", [0, 3])            # 这一页第几行谱表（从 0 数）是高音谱号 / 低音谱号
    out = {}
    for k, name, up, dn in ((k_tr, "treble", 2.2, 2.6), (k_bs, "bass", 0.4, 0.4)):
        lines, sp, top, reg, clean = omr._clean_region(a, st[k][2], x0, x0 + 300)
        r0 = int(lines[0] - up * sp - top); r1 = int(lines[-1] + dn * sp - top)
        c = clean[r0:r1, 3:80].copy()
        lab, n = ndi.label(c)
        if n:
            sz = ndi.sum(c, lab, np.arange(1, n + 1))
            keep = np.zeros(n + 1, bool); keep[1:] = sz >= 25
            c = keep[lab]
        cols = np.where(c.any(0))[0]
        c = c[:, max(0, cols[0] - 2):cols[-1] + 3]
        out[name] = c.astype(np.float32)
        out[name + "_off"] = np.array([lines[0] - top - r0, sp])   # 模板里第一条谱线的行
    # 升降号：取本谱自己的字形（位置见 project.json 的 omr.flat_boxes / sharp_boxes）；还原号沿用 assets 里的模板（按间距缩放）
    st = json.load(open(os.path.join(MID, "staves.json")))
    def grab(page, sysi, staff, boxes):
        a2 = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("L")) < 140
        xs = [b[0] for b in boxes]
        lines, sp, top, reg, clean = omr._clean_region(a2, st[str(page)][sysi][staff], min(xs) - 30, max(xs) + 60)
        H = max(b[3] for b in boxes) + 4; W = max(b[2] for b in boxes) + 4
        acc = np.zeros((H, W), np.float32)
        for (x, y, w, h) in boxes:
            c = clean[y - top - 2:y - top - 2 + H, x - (min(xs) - 30) - 2:x - (min(xs) - 30) - 2 + W]
            acc[:c.shape[0], :c.shape[1]] += c
        return acc / len(boxes), sp
    # 每个框 (x, y, 宽, 高)：调号里一个个降号 / 升号的外框（页面像素）。默认是马勒八缩谱第 1 页三个降号、第 31 页两个升号。
    fb = _O.get("flat_boxes", {"page": 1, "system": 0, "staff": 0, "boxes": [[671, 670, 20, 57], [690, 643, 20, 52], [706, 686, 21, 53]]})
    sb_ = _O.get("sharp_boxes", {"page": 31, "system": 0, "staff": 0, "boxes": [[350, 312, 25, 64], [373, 342, 25, 66]]})
    fl, fsp = grab(fb["page"], fb["system"], fb["staff"], [tuple(b) for b in fb["boxes"]])
    sh, ssp = grab(sb_["page"], sb_["system"], sb_["staff"], [tuple(b) for b in sb_["boxes"]])
    out["flat"] = fl; out["flat_sp"] = np.array(fsp)
    out["sharp"] = sh; out["sharp_sp"] = np.array(ssp)
    z = np.load(M3_TPL)
    out["natural"] = z["natural"]; out["natural_sp"] = np.array(M3_SP)
    np.savez(TPL8, **out)
    return out


_T = None


def T():
    global _T
    if _T is None:
        if not os.path.exists(TPL8):
            build_templates()
        z = np.load(TPL8)
        _T = {k: z[k] for k in z.files}
    return _T


def scaled(img, f):
    h, w = img.shape
    im = Image.fromarray((img * 255).astype(np.uint8)).resize((max(3, int(round(w * f))), max(3, int(round(h * f)))),
                                                               Image.BILINEAR)
    return np.asarray(im, np.float32) / 255.0


def acc_templates(sp):
    t = T()
    return {k: (scaled(t[k], sp / float(t[k + "_sp"])) > 0.45).astype(np.float32) for k in ("sharp", "flat", "natural")}


def ncc(img, tpl):
    return omr.ncc_map(img.astype(np.float32), tpl)


def find_clefs(clean, sp, line0, x_from, thr_override=None, x_to=None):
    """在 clean（去谱线后的区域）里找谱号。返回 [(x, 'treble'|'bass', 分数, 大小)]，x 相对区域左边。
    谱号竖直位置是固定的（相对第一条谱线），所以只看那一行的相关值。"""
    t = T()
    out = []
    for name in ("treble", "bass"):
        off, tsp = t[name + "_off"]
        for size in (1.0, 0.78):
            f = sp * size / tsp
            tp = scaled(t[name], f)
            m = ncc(clean, tp)
            # 模板中心行应在：第一条谱线 + (模板中心 - 模板第一条谱线)
            # 小号谱号与谱线位置的关系：低音谱号顶在第一线，高音谱号的圈绕第二线 → 都按比例算
            cy = line0 + (tp.shape[0] / 2 - off * f)
            if name == "treble" and size < 1:
                cy = line0 + (tp.shape[0] / 2 - off * f) + (1 - size) * 2.2 * sp
            rows = [int(round(cy)) + d for d in range(-int(0.5 * sp), int(0.5 * sp) + 1)]
            rows = [r for r in rows if 0 <= r < m.shape[0]]
            if not rows:
                continue
            prof = m[rows].max(0)
            prof[:max(0, int(x_from))] = -1
            if x_to is not None:
                prof[int(x_to):] = -1
            thr = 0.50 if size == 1.0 else 0.52
            if thr_override is not None:
                thr = thr_override
            mx = ndi.maximum_filter1d(prof, size=int(3 * sp))
            for x in np.where((prof >= thr) & (prof == mx))[0]:
                out.append([int(x), name, float(prof[x]), size])
    out.sort(key=lambda o: -o[2])
    keep = []
    for o in out:
        if all(abs(o[0] - k[0]) > 1.6 * sp for k in keep):
            keep.append(o)
    return sorted(keep)


def read_system(page, sysn, rows, staves_all, a):
    sysrows = sorted([r for r in rows.values() if r["page"] == page and r["system"] == sysn], key=lambda r: r["bar"])
    if not sysrows:
        return [], []
    x_sys = sysrows[0]["x0"]; x_end = sysrows[-1]["x1"]
    stv = staves_all[str(page)][sysn - 1]
    notes, info, states = [], [], []
    x_sys_bar = x_sys
    for si, ln in enumerate(stv, start=1):
        # 这一行谱表自己的起点：五条线里至少四条连续有墨迹（系统括号常在谱表左边）
        x_sys = x_sys_bar
        ls_ = [int(round(v)) for v in ln]
        for xx in range(int(x_sys_bar), int(x_sys_bar) + 400):
            cnt = sum(a[max(0, y - 2):y + 3, xx].any() for y in ls_)
            cnt2 = sum(a[max(0, y - 2):y + 3, xx + 4].any() for y in ls_)
            if cnt >= 4 and cnt2 >= 4:
                x_sys = xx
                break
        x0 = int(x_sys) + 2; x1 = int(x_end)
        lines, sp, top, reg, clean = omr._clean_region(a, ln, x0, x1)
        line0 = lines[0] - top
        tpls = acc_templates(sp)
        accs = omr.find_accidentals(clean, sp, tpls)
        accs_abs = [(ax + x0, ay + top, k, sc) for (ax, ay, k, sc) in accs]
        heads, lines, sp, top, clean = omr.detect_heads(a, ln, x0, x1, accs_abs)
        heads = sorted(heads, key=lambda h: h[0])
        clefs = find_clefs(clean, sp, line0, 0)
        # 系统开头的谱号
        start = [c for c in clefs if c[0] + x0 < x_sys + 4 * sp]
        if start:
            clef0 = max(start, key=lambda c: c[2])[1]
        else:
            # 没过阈值：在行首比较高音、低音谱号模板，取相关更高的那个
            weak = [c for c in find_clefs(clean, sp, line0, 0, thr_override=-1.0, x_to=int(4.5 * sp)) if c[3] == 1.0]
            if weak:
                c = max(weak, key=lambda c: c[2])
                clef0 = c[1]
                CLEF_LOG.append(f"p{page} s{sysn} 行{si}: 开头谱号不清楚，按相关较高的 {clef0}（{c[2]:.2f}）")
            else:
                clef0 = "treble"
                CLEF_LOG.append(f"p{page} s{sysn} 行{si}: 开头谱号没认出，按高音谱号")
        clef_changes = [(c[0] + x0, c[1]) for c in clefs
                        if c[0] + x0 >= x_sys + 4 * sp and (c[3] < 1.0 or c[2] > 0.62)]
        # 开头调号：谱号之后数升降号
        zone0 = x_sys + 3.0 * sp                      # 谱号宽约 3 个间距（谱号的圈常被误认成符头）
        first_head = next((h[0] for h in heads if h[0] > zone0 + 0.6 * sp), x_end)
        ks_acc = [ac for ac in accs_abs if zone0 - 0.5 * sp <= ac[0] <= zone0 + 8.5 * sp]   # 位置顺序检查代替'第一个符头之前'
        # 调号必须按固定的位置顺序（降号 B E A D G C F，升号 F C G D A E B），间隔 < 1.6 sp
        half = sp / 2
        def on_note(ac):
            """这个记号右边紧挨着同一高度的符头：是音符的临时记号，不是调号"""
            return any(0.4 * sp <= h[0] - ac[0] <= 2.2 * sp and abs(h[1] - ac[1]) <= 0.45 * sp for h in heads)
        accs_free = [ac for ac in accs_abs if not on_note(ac)]
        ks_acc = [ac for ac in ks_acc if -2.5 <= (lines[-1] - ac[1]) / half <= 10.5 and not on_note(ac)]
        ks_acc.sort(key=lambda ac: ac[0])
        off = 0 if clef0 == "treble" else -2
        PAT = {"flat": [4, 7, 3, 6, 2, 5, 1], "sharp": [8, 5, 9, 6, 3, 7, 4]}
        chain = []
        kind0 = ks_acc[0][2] if ks_acc else None
        if kind0 in PAT:
            for ac in ks_acc:
                if ac[2] != kind0 or len(chain) >= 7:
                    break
                if chain and ac[0] - chain[-1][0] > 1.6 * sp:
                    break
                kk = (lines[-1] - ac[1]) / half
                if chain:
                    # 只比相对位置（降号的"所指音高"估计可能整体偏一级）
                    want = PAT[kind0][len(chain)] - PAT[kind0][0]
                    if abs((kk - k_first) - want) > 0.8:
                        break
                else:
                    k_first = kk
                    abs_ok = abs(kk - (PAT[kind0][0] + off)) <= 1.6
                chain.append(ac)
            if chain and len(chain) < 2 and abs(k_first - (PAT[kind0][0] + off)) > 0.8:
                chain = []                      # 只有一个记号、位置又不对：不当调号
        n_sh = sum(1 for ac in chain if ac[2] == "sharp"); n_fl = sum(1 for ac in chain if ac[2] == "flat")
        ks0 = n_sh if n_sh >= n_fl else -n_fl
        ks_end = max([ac[0] for ac in chain], default=zone0)
        x_music = max(ks_end + 0.8 * sp, x_sys + 3.4 * sp)
        # 行中换调号：只认双小节线之后、按调号固定位置排开的一串升降号（和弦前的临时记号是竖着叠的，不算）
        ks_changes = []
        L5 = [int(round(v)) for v in lines]
        def double_bar(bx):
            xa = max(0, int(bx) - 30)
            ok = a[L5[0]:L5[-1] + 1, xa:int(bx) + 31].mean(0) >= 0.85
            return int(ok[0]) + int(np.sum(ok[1:] & ~ok[:-1])) >= 2
        for r in sysrows[1:]:
            bx = r["x0"]
            if not double_bar(bx):
                continue
            cl = sorted([ac for ac in accs_free if bx + 0.3 * sp <= ac[0] <= bx + 9 * sp
                         and -2.5 <= (lines[-1] - ac[1]) / half <= 10.5], key=lambda ac: ac[0])
            # 开头的还原号（取消旧调号）跳过
            while cl and cl[0][2] == "natural":
                cl = cl[1:]
            # 去掉还原号后再找：可能整串都是还原号（改成 C 大调）
            nat_only = not cl and any(ac[2] == "natural" for ac in accs_abs if bx + 0.3 * sp <= ac[0] <= bx + 9 * sp)
            if nat_only:
                ks_changes.append((r["bar"], 0, bx + 0.3 * sp)); continue
            if not cl or cl[0][2] not in PAT:
                continue
            kind_ = cl[0][2]
            chain_ = []
            for ac in cl:
                if ac[2] != kind_ or len(chain_) >= 7:
                    break
                if chain_ and not (0.5 * sp <= ac[0] - chain_[-1][0] <= 1.6 * sp):
                    break
                kk = (lines[-1] - ac[1]) / half
                if chain_:
                    if abs((kk - k0_) - (PAT[kind_][len(chain_)] - PAT[kind_][0])) > 0.8:
                        break
                else:
                    k0_ = kk
                    if abs(kk - (PAT[kind_][0] + off)) > 1.6:
                        break
                chain_.append(ac)
            if len(chain_) >= 2 or (len(chain_) == 1 and abs(k0_ - (PAT[kind_][0] + off)) <= 0.8):
                ks_new = len(chain_) if kind_ == "sharp" else -len(chain_)
                ks_changes.append((r["bar"], ks_new, max(ac[0] for ac in chain_)))
        info.append(dict(staff=si, clef=clef0, ks=ks0, clef_changes=clef_changes,
                         ks_changes=[(b, k) for b, k, _ in ks_changes], sp=round(float(sp), 2)))
        # 区域上下各多取了 5 个间距，会读进相邻谱表的音：只留离本行比离别的行近的符头
        mids = [(l_[0] + l_[-1]) / 2 for l_ in stv]
        me = mids[si - 1]
        heads = [h for h in heads if all(abs(h[1] - me) <= abs(h[1] - m_) for m_ in mids)]
        states.append((si, sp, heads, accs_abs, clef0, clef_changes, ks0, ks_changes, x_music))
    # 拍号：数字被当成"符头"时，各行在同一 x、同样的谱表位置（k 值）上都有；真和弦各行的 k 不一样。
    # 只看系统开头（调号之后）和每条小节线之后 3 个间距内。
    ts_x = []
    if states:
        sp_m = float(np.median([st_[1] for st_ in states]))
        starts = [None] + [r["x0"] for r in sysrows[1:]]
        for bx0 in starts:
            per = []
            for (si, sp, heads, *_r) in states:
                bx = (_r[-1] - 0.8 * sp) if bx0 is None else bx0
                g = [h for h in heads if bx + 0.2 * sp <= h[0] <= bx + 3.6 * sp]
                per.append(g)
            xs = sorted(h[0] for g in per for h in g)
            for x in xs:
                pats = []
                for g in per:
                    ks_ = tuple(sorted(int(h[2]) for h in g if abs(h[0] - x) < 0.6 * sp_m))
                    if ks_:
                        pats.append(ks_)
                if len(pats) >= max(2, 0.6 * len(states)):
                    allk = [k_ for pt in pats for k_ in set(pt)]
                    common = max(set(allk), key=allk.count)
                    if os.environ.get("TSDEBUG"):
                        print("ts?", bx0, int(x), len(pats), len(states), common, sum(1 for pt in pats if common in pt))
                    if sum(1 for pt in pats if any(abs(k_ - common) <= 1 for k_ in pt)) >= 0.7 * len(pats) and all(abs(x - t) > sp_m for t in ts_x):
                        ts_x.append(x)
                        break
    for (si, sp, heads, accs_abs, clef0, clef_changes, ks0, ks_changes, x_music) in states:
        for t in ts_x:
            if t < x_music + 3 * sp:
                x_music = max(x_music, t + 1.2 * sp)
        carry = {}
        for (cx, cy, k, frac, kind) in heads:
            if cx < x_music:
                continue
            if any(abs(cx - t) < 0.9 * sp for t in ts_x):
                continue
            if any(lo <= cx <= hi for (xc, _c) in clef_changes for lo, hi in [(xc - 1.2 * sp, xc + 1.2 * sp)]):
                continue
            bar = None
            for r in sysrows:
                if r["x0"] <= cx < r["x1"]:
                    bar = r["bar"]; r_ = r; break
            if bar is None:
                continue
            clef = clef0
            for xc, c in clef_changes:
                if cx > xc:
                    clef = c
            ks = ks0
            for b, kk, xe in ks_changes:
                if bar > b or (bar == b and cx > xe):
                    ks = kk
            bl, bo = omr.BOTTOM[clef]
            idx = bl + k
            L = omr.LETTERS[idx % 7]; octv = bo + idx // 7
            acc = None; best = None
            for (axa, aya, kind_a, sc) in accs_abs:
                if cx - 3.4 * sp <= axa <= cx - 0.55 * sp and abs(aya - cy) <= 0.3 * sp:
                    d = cx - axa
                    if best is None or d < best:
                        best, acc = d, kind_a
            key = (L, octv)
            if acc:
                carry[(bar, key)] = {"sharp": 1, "flat": -1, "natural": 0}[acc]
            alt = carry.get((bar, key), omr.ks_alter(ks).get(L, 0))
            midi = 12 * (octv + 1) + omr.SEMI[omr.LETTERS.index(L)] + alt
            p0 = max(r_["play0"], x_music) if r_ is sysrows[0] else r_["play0"]
            pos = (cx - p0) / max(1.0, r_["x1"] - p0)
            notes.append(dict(staff=si, inst=f"行{si}", bar=bar, x=float(cx), y=float(cy), pos=round(float(pos), 3),
                              written=f"{L}{octv}", acc=acc or "", midi=int(midi), off=round(float(frac), 2),
                              hollow=(kind == "h"), name=omr.spelled(L, octv, alt, 0), ks=ks, clef=clef,
                              nstaves=len(stv)))
    return notes, info


def run(pages, write_png=False):
    rows = omr.load_rows()
    staves_all = json.load(open(os.path.join(MID, "staves.json")))
    allinfo = {}
    ip = os.path.join(omr.OMR, "systems8.json")
    if os.path.exists(ip):
        allinfo = json.load(open(ip, encoding="utf-8"))
    for page in pages:
        nsys = len(staves_all.get(str(page), []))
        if not nsys:
            continue
        a = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("L")) < 140
        for sysn in range(1, nsys + 1):
            notes, info = read_system(page, sysn, rows, staves_all, a)
            if not info:
                continue
            json.dump(notes, open(os.path.join(omr.OMR, f"p{page:03d}_s{sysn}.json"), "w"), ensure_ascii=False)
            allinfo[f"p{page:03d}_s{sysn}"] = info
            if write_png:
                omr.annotate(page, sysn, notes, rows, staves_all).save(os.path.join(omr.OMR, f"p{page:03d}_s{sysn}.png"))
            print(f"p{page} s{sysn}: {len(notes)} 音；" +
                  " ".join(f"{i['clef'][0]}{i['ks']:+d}" + ("*" if i["clef_changes"] or i["ks_changes"] else "")
                           for i in info), flush=True)
        json.dump(allinfo, open(ip, "w", encoding="utf-8"), ensure_ascii=False)
    for w in CLEF_LOG:
        print("  ", w)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit()
    if args[0] == "templates":
        build_templates(); print("ok")
    elif args[0] == "bar":
        b0 = int(args[1]); b1 = int(args[2]) if len(args) > 2 else b0
        omr.print_bars(b0, b1)
    elif args[0] == "all":
        p0 = int(args[1]) if len(args) > 1 else 1
        p1 = int(args[2]) if len(args) > 2 else 209
        run(range(p0, p1 + 1), write_png="--png" in args)
    else:
        run([int(args[0])], write_png=True)
