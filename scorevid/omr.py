# -*- coding: utf-8 -*-
"""半自动读谱：按 数据/读谱配置.txt 里每个系统每行谱表的乐器（谱号、移调、调号），
识别符头与临时记号（♯ ♭ ♮，小节内延续），算出每个音的实际音高。

用法：
  python3 omr.py 页码 [系统号]            识别并写出 中间文件/omr/pNNN_sK.json 与核对图 pNNN_sK.png
  python3 omr.py all                      全部系统
  python3 omr.py bar 起小节 [止小节]      打印这些小节里每个起音点的实际音高（按横向位置聚类）

配置格式（数据/读谱配置.txt）：
  [p214 s1]
  行号 乐器名 谱号 移调半音 调号 [@小节:clef=谱号] [@小节:ks=调号] ...
  谱号：treble alto tenor bass perc（perc 不读音高）；调号：+2 = 两个升号，-3 = 三个降号，0 = 无
  移调：写谱→实际的半音数，如 降B单簧管 -2、F 圆号 -7、F 小号 +5、低音提琴 -12、短笛 +12
"""
import os, sys, re, csv, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
from scipy.signal import fftconvolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BARS_CSV, MID, DATA, FONT_DIR
import notes_view as nv

CFG = os.path.join(DATA, "读谱配置.txt")
OMR = os.path.join(MID, "omr")
os.makedirs(OMR, exist_ok=True)
TPL = os.path.join(OMR, "templates.npz")

LETTERS = "CDEFGAB"
SEMI = [0, 2, 4, 5, 7, 9, 11]
BOTTOM = {"treble": (2, 4), "alto": (3, 3), "tenor": (1, 3), "bass": (4, 2)}
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def midi_name(m):
    return f"{NAMES[m % 12]}{m // 12 - 1}"


STEPS = {0: 0, -2: -1, 3: 2, -7: -4, 5: 3, 12: 7, -12: -7, -3: -2, -14: -8}


def spelled(letter, octv, alt, trans):
    """写谱音（字母、八度、升降）按移调乐器的音程换成实际音的拼法，如 Horn in F 写谱 C5 → F4。"""
    li = LETTERS.index(letter) + 7 * octv + STEPS.get(trans, 0)
    L2 = LETTERS[li % 7]; o2 = li // 7
    written = 12 * (octv + 1) + SEMI[LETTERS.index(letter)] + alt
    a2 = written + trans - (12 * (o2 + 1) + SEMI[LETTERS.index(L2)])
    acc = "#" * a2 if a2 > 0 else "b" * (-a2)
    return f"{L2}{acc}{o2}"


# ---------------- 配置 ----------------
def load_config():
    cfg = {}
    cur = None
    for raw in open(CFG, encoding="utf-8"):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^\[p(\d+)\s+s(\d+)\]$", line)
        if m:
            cur = (int(m.group(1)), int(m.group(2)))
            cfg[cur] = {}
            continue
        toks = line.split()
        idx = int(toks[0])
        name, clef, trans, ks = toks[1], toks[2], int(toks[3]), int(toks[4])
        changes = []
        for t in toks[5:]:
            mm = re.match(r"^@(\d+):(clef|ks|trans)=(\S+)$", t)
            if mm:
                changes.append((int(mm.group(1)), mm.group(2), mm.group(3)))
        cfg[cur][idx] = dict(name=name, clef=clef, trans=trans, ks=ks, changes=sorted(changes))
    return cfg


def staff_state(st, bar):
    clef, ks, trans = st["clef"], st["ks"], st["trans"]
    for b, k, v in st["changes"]:
        if bar >= b:
            if k == "clef":
                clef = v
            elif k == "ks":
                ks = int(v)
            else:
                trans = int(v)
    return clef, ks, trans


def ks_alter(ks):
    alt = {}
    if ks > 0:
        for L in SHARP_ORDER[:ks]:
            alt[L] = 1
    elif ks < 0:
        for L in FLAT_ORDER[:-ks]:
            alt[L] = -1
    return alt


# ---------------- 模板 ----------------
def _clean_region(a, ln, x0, x1):
    lines = nv.refine_lines(a, ln, x0, x1)
    sp = (lines[-1] - lines[0]) / 4
    top = int(lines[0] - 5 * sp); bot = int(lines[-1] + 5 * sp)
    reg = a[top:bot, x0:x1]
    line_rows = [int(round(lines[-1] - k * sp / 2 - top)) for k in range(-14, 24, 2)]
    clean = nv.remove_lines(reg, line_rows, maxrun=3)
    return lines, sp, top, reg, clean


def build_templates():
    st = json.load(open(os.path.join(MID, "staves.json")))
    def grab(page, sysi, staff, boxes):
        a = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("L")) < 140
        ln = st[str(page)][sysi][staff]
        xs = [b[0] for b in boxes]
        lines, sp, top, reg, clean = _clean_region(a, ln, min(xs) - 40, max(xs) + 60)
        out = []
        for (x, y, w, h) in boxes:
            pad = 3
            c = clean[y - top - pad:y - top + h + pad, x - (min(xs) - 40) - pad:x - (min(xs) - 40) + w + pad]
            out.append(c.astype(np.float32))
        H = max(o.shape[0] for o in out); W = max(o.shape[1] for o in out)
        acc = np.zeros((H, W), np.float32)
        for o in out:
            acc[:o.shape[0], :o.shape[1]] += o
        return acc / len(out)
    sharp = grab(208, 0, 0, [(439, 382, 16, 39), (454, 398, 15, 42)])
    flat = grab(216, 0, 9, [(305, 1352, 13, 33), (319, 1334, 14, 33), (334, 1357, 13, 35), (347, 1339, 13, 33)])
    nat = None
    st208 = st["208"]
    nat_boxes = [(1, 0, (1969, 1405, 11, 42)), (1, 1, (557, 1527, 11, 41)), (1, 2, (1678, 1631, 11, 41)),
                 (1, 2, (1286, 1632, 10, 41)), (1, 5, (1968, 1978, 12, 41)), (2, 4, (2249, 2697, 10, 41))]
    ns = []
    for sysi, staff, b in nat_boxes:
        ns.append(grab(208, sysi, staff, [b]))
    H = max(n.shape[0] for n in ns); W = max(n.shape[1] for n in ns)
    nat = np.zeros((H, W), np.float32)
    for n in ns:
        nat[:n.shape[0], :n.shape[1]] += n
    nat /= len(ns)
    np.savez(TPL, sharp=sharp, flat=flat, natural=nat)
    return dict(sharp=sharp, flat=flat, natural=nat)


def load_templates():
    if not os.path.exists(TPL):
        return build_templates()
    z = np.load(TPL)
    return {k: z[k] for k in ("sharp", "flat", "natural")}


def ncc_map(img, tpl):
    """归一化互相关（模板中心对齐到输出坐标）。"""
    t = tpl - tpl.mean()
    tn = np.sqrt((t ** 2).sum()) + 1e-9
    img = img.astype(np.float32)
    k = np.ones(tpl.shape, np.float32)
    s1 = fftconvolve(img, k, mode="same")
    s2 = fftconvolve(img ** 2, k, mode="same")
    n = tpl.size
    var = np.maximum(s2 - s1 ** 2 / n, 1e-6)
    num = fftconvolve(img, t[::-1, ::-1], mode="same")
    return num / (np.sqrt(var) * tn)


def find_accidentals(clean, sp, tpls, thr=0.56):
    """返回 [(x, y_note, kind, score)]，坐标相对 clean 区域。y_note 是这个记号所指的音的纵坐标。
    竖线太长（符干、小节线）的位置不算临时记号。"""
    found = []
    # 每列从每个像素起向上/向下的连续墨迹长度 → 每个像素所在竖段的长度
    vlen = np.zeros(clean.shape, np.int32)
    lab, n = ndi.label(clean, structure=np.array([[0, 1, 0], [0, 1, 0], [0, 1, 0]]))
    if n:
        sizes = ndi.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
        vlen = np.concatenate([[0], sizes]).astype(np.int32)[lab]
    longv = vlen > 3.7 * sp
    for kind, tpl in tpls.items():
        m = ncc_map(clean, tpl)
        mx = ndi.maximum_filter(m, size=(int(sp * 1.2), int(sp * 0.8)))
        ys, xs = np.where((m >= thr) & (m == mx))
        # 降号所指的音在符号的圆圈处（模板中心偏下）
        if kind == "flat":
            hole = ndi.binary_fill_holes(tpl > 0.5) & ~(tpl > 0.5)
            hy = np.where(hole)[0].mean() if hole.any() else tpl.shape[0] * 0.7
            dy = hy - tpl.shape[0] / 2
        else:
            dy = 0
        for y, x in zip(ys, xs):
            xa, xb = max(0, int(x - 0.45 * sp)), int(x + 0.45 * sp)
            ya, yb = max(0, int(y - 1.2 * sp)), int(y + 1.2 * sp)
            if longv[ya:yb, xa:xb].any():
                continue
            found.append([x, y + dy, kind, float(m[y, x])])
    # 不同种类之间的非极大抑制
    found.sort(key=lambda f: -f[3])
    keep = []
    for f in found:
        if all(abs(f[0] - g[0]) > 0.6 * sp or abs(f[1] - g[1]) > 1.0 * sp for g in keep):
            keep.append(f)
    return keep


# ---------------- 识别 ----------------
def detect_heads(a, ln, x0, x1, accs_abs):
    """符头：实心（距离变换）+ 空心（封闭小洞）。要求有符干、或在五线内、或有加线；与临时记号重叠的去掉。
    返回 [(cx, cy, k, frac, lines, sp)]，k = 相对最下一条线的级数。"""
    lines, sp, top, reg, clean = _clean_region(a, ln, x0, x1)
    half = sp / 2
    cand = []
    for (cx, cy, kr, frac, _) in nv.detect(a, ln, x0, x1, "treble"):
        cand.append([cx, cy, "f"])
    # 空心符头：先闭运算补上扫描造成的小缺口，再找封闭小洞；被谱线切成上下两半的洞合并
    reg_c = ndi.binary_closing(reg, structure=np.ones((3, 3), bool))
    holes = ndi.binary_fill_holes(reg_c) & ~reg_c
    hl, hn = ndi.label(holes)
    hs = []
    if hn:
        for i, sl in enumerate(ndi.find_objects(hl), start=1):
            hh = sl[0].stop - sl[0].start; ww = sl[1].stop - sl[1].start
            area = int((hl[sl] == i).sum())
            if 0.04 * sp * sp <= area <= 0.75 * sp * sp and ww <= 1.3 * sp and hh <= 0.85 * sp and ww >= 0.2 * sp:
                ys, xs = np.where(hl[sl] == i)
                hs.append([xs.mean() + sl[1].start + x0, ys.mean() + sl[0].start + top, area])
    merged = []
    for h in sorted(hs, key=lambda h: (h[0], h[1])):
        for m in merged:
            if abs(m[0] - h[0]) < 0.5 * sp and abs(m[1] - h[1]) < 0.7 * sp:
                tot = m[2] + h[2]
                m[0] = (m[0] * m[2] + h[0] * h[2]) / tot; m[1] = (m[1] * m[2] + h[1] * h[2]) / tot; m[2] = tot
                break
        else:
            merged.append(list(h))
    for h in merged:
        if h[2] >= 0.12 * sp * sp:
            cand.append([h[0], h[1], "h"])
    # 去重
    cand.sort(key=lambda c: (c[0], c[1]))
    heads = []
    for c in cand:
        dup = False
        for h in heads:
            if abs(h[0] - c[0]) < 0.55 * sp and abs(h[1] - c[1]) < 0.4 * sp:
                dup = True; break
        if not dup:
            heads.append(c)
    stems = ndi.binary_opening(clean, structure=np.ones((int(2.4 * sp), 1), bool))
    hor = ndi.binary_opening(reg, structure=np.ones((1, int(1.6 * sp)), bool))
    st_top = lines[0] - 0.7 * sp; st_bot = lines[-1] + 0.7 * sp
    out = []
    for cx, cy, kind in heads:
        ix = int(cx - x0); iy = int(cy - top)
        if iy < 0 or iy >= reg.shape[0]:
            continue
        # 与临时记号重叠
        if any(abs(cx - ax) < 0.75 * sp and abs(cy - ay) < 1.2 * sp for (ax, ay, _k, _s) in accs_abs):
            continue
        xa, xb = max(0, int(ix - 0.95 * sp)), int(ix + 0.95 * sp)
        ya, yb = max(0, int(iy - 0.6 * sp)), int(iy + 0.6 * sp)
        has_stem = stems[ya:yb, xa:xb].any()
        in_staff = st_top <= cy <= st_bot
        has_ledger = (not in_staff) and hor[ya:yb, xa:xb].any()
        if kind == "f" and not has_stem:
            continue                                   # 实心符头一定有符干（休止符、拍号、文字没有）
        if kind == "h" and not (has_stem or in_staff or has_ledger):
            continue
        k_f = (lines[-1] - cy) / half
        k = int(round(k_f))
        out.append((cx, cy, k, k_f - k, kind))
    return out, lines, sp, top, clean


KS_WARN = []


def read_system(page, sysn, cfg, tpls, rows, staves_all, a):
    sysrows = sorted([r for r in rows.values() if r["page"] == page and r["system"] == sysn], key=lambda r: r["bar"])
    x_sys = sysrows[0]["x0"]; x_end = sysrows[-1]["x1"]
    stv = staves_all[str(page)][sysn - 1]
    conf = cfg.get((page, sysn), {})
    notes = []
    for si, ln in enumerate(stv, start=1):
        st = conf.get(si)
        if st is None or st["clef"] == "perc":
            continue
        x0 = int(x_sys) + 2; x1 = int(x_end)
        lines, sp, top, reg, clean = _clean_region(a, ln, x0, x1)
        accs = find_accidentals(clean, sp, tpls)
        accs_abs = [(ax + x0, ay + top, k, sc) for (ax, ay, k, sc) in accs]
        heads, lines, sp, top, clean = detect_heads(a, ln, x0, x1, accs_abs)
        clef0, ks0, _ = staff_state(st, sysrows[0]["bar"])
        x_music = x_sys + (3.4 + 1.05 * abs(ks0) + 0.4) * sp      # 谱号+调号之后
        # 调号核对：谱号之后一段里数升降号
        ks_zone = [ac for ac in accs_abs if x_sys + 2.2 * sp <= ac[0] <= x_sys + (3.0 + 1.15 * max(abs(ks0), 1) + 1.0) * sp]
        n_sh = sum(1 for ac in ks_zone if ac[2] == "sharp"); n_fl = sum(1 for ac in ks_zone if ac[2] == "flat")
        auto = n_sh if n_sh >= n_fl else -n_fl
        if auto != ks0:
            KS_WARN.append(f"p{page} s{sysn} 行{si} {st['name']}: 配置调号 {ks0:+d}，谱上数到 {auto:+d}")
        carry = {}
        heads = sorted(heads, key=lambda h: h[0])
        for (cx, cy, k, frac, kind) in heads:
            if cx < x_music:
                continue
            bar = None
            for r in sysrows:
                if r["x0"] <= cx < r["x1"]:
                    bar = r["bar"]; break
            if bar is None:
                continue
            clef, ks, trans = staff_state(st, bar)
            bl, bo = BOTTOM[clef]
            idx = bl + k
            L = LETTERS[idx % 7]; octv = bo + idx // 7
            acc = None; best = None
            for (axa, aya, kind_a, sc) in accs_abs:
                if cx - 3.4 * sp <= axa <= cx - 0.55 * sp and abs(aya - cy) <= 0.3 * sp:
                    d = cx - axa
                    if best is None or d < best:
                        best, acc = d, kind_a
            key = (L, octv)
            if acc:
                carry[(bar, key)] = {"sharp": 1, "flat": -1, "natural": 0}[acc]
            alt = carry.get((bar, key), ks_alter(ks).get(L, 0))
            midi = 12 * (octv + 1) + SEMI[LETTERS.index(L)] + alt + trans
            r = next(r for r in sysrows if r["bar"] == bar)
            p0 = max(r["play0"], x_music) if r is sysrows[0] else r["play0"]
            pos = (cx - p0) / max(1.0, r["x1"] - p0)
            notes.append(dict(staff=si, inst=st["name"], bar=bar, x=float(cx), y=float(cy), pos=round(float(pos), 3),
                              written=f"{L}{octv}", acc=acc or "", midi=int(midi), off=round(float(frac), 2),
                              hollow=(kind == "h"), name=spelled(L, octv, alt, trans)))
    return notes


def load_rows():
    rows = {}
    for r in csv.DictReader(open(BARS_CSV, encoding="utf-8")):
        rows[int(r["bar"])] = dict(bar=int(r["bar"]), page=int(r["page"]), system=int(r["system"]),
                                   x0=int(r["x0"]), x1=int(r["x1"]), y0=int(r["y0"]), y1=int(r["y1"]))
    sysb = {}
    for b, r in rows.items():
        sysb.setdefault((r["page"], r["system"]), []).append(b)
    for key, bs in sysb.items():
        bs.sort()
        ws = [rows[b]["x1"] - rows[b]["x0"] for b in bs[1:]]
        med = float(np.median(ws)) if ws else 180
        first = rows[bs[0]]
        head = max(0, (first["x1"] - first["x0"]) - med * 1.05)
        for b in bs:
            rows[b]["play0"] = rows[b]["x0"] + (head if b == bs[0] else 0) + 4
    return rows


def annotate(page, sysn, notes, rows, staves_all):
    img = Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("RGB")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 15)
    for n in notes:
        col = (0, 140, 0) if not n["acc"] else (210, 0, 0)
        if abs(n["off"]) > 0.3:
            col = (230, 120, 0)
        d.text((n["x"] + 7, n["y"] - 9), n.get("name", midi_name(n["midi"])), font=f, fill=col)
    sysrows = [r for r in rows.values() if r["page"] == page and r["system"] == sysn]
    y0 = min(r["y0"] for r in sysrows) - 120; y1 = max(r["y1"] for r in sysrows) + 80
    return img.crop((0, max(0, y0), img.width, min(img.height, y1)))


def run(pages_systems):
    cfg = load_config()
    tpls = load_templates()
    rows = load_rows()
    staves_all = json.load(open(os.path.join(MID, "staves.json")))
    for page, sysn in pages_systems:
        if (page, sysn) not in cfg:
            print(f"p{page} s{sysn}: 没有配置，跳过")
            continue
        a = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("L")) < 140
        notes = read_system(page, sysn, cfg, tpls, rows, staves_all, a)
        json.dump(notes, open(os.path.join(OMR, f"p{page:03d}_s{sysn}.json"), "w"), ensure_ascii=False)
        annotate(page, sysn, notes, rows, staves_all).save(os.path.join(OMR, f"p{page:03d}_s{sysn}.png"))
        print(f"p{page} s{sysn}: {len(notes)} 个音")
    for w in KS_WARN:
        print("  调号？", w)
    KS_WARN.clear()


def all_notes():
    out = []
    for fn in sorted(os.listdir(OMR)):
        if fn.endswith(".json") and fn.startswith("p"):
            out += json.load(open(os.path.join(OMR, fn)))
    return out


def print_bars(b0, b1):
    notes = [n for n in all_notes() if b0 <= n["bar"] <= b1]
    for bar in range(b0, b1 + 1):
        ns = sorted([n for n in notes if n["bar"] == bar], key=lambda n: n["pos"])
        # 按位置聚类
        groups = []
        for n in ns:
            if groups and n["pos"] - groups[-1][-1]["pos"] < 0.045:
                groups[-1].append(n)
            else:
                groups.append([n])
        print(f"== 第 {bar} 小节")
        for g in groups:
            ms = sorted(set(n["midi"] for n in g))
            pcs = sorted(set(m % 12 for m in ms))
            spell = {}
            for n in g:
                spell.setdefault(n["midi"], n.get("name", midi_name(n["midi"])))
            names = " ".join(spell[m] for m in ms)
            print(f"  {g[0]['pos']:.2f}: {names}   [{' '.join(NAMES[p] for p in pcs)}]")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit()
    if args[0] == "bar":
        b0 = int(args[1]); b1 = int(args[2]) if len(args) > 2 else b0
        print_bars(b0, b1)
    elif args[0] == "all":
        cfg = load_config()
        run(sorted(cfg))
    elif args[0] == "templates":
        build_templates(); print("templates rebuilt")
    else:
        page = int(args[0])
        cfg = load_config()
        if len(args) > 1:
            run([(page, int(args[1]))])
        else:
            run(sorted(k for k in cfg if k[0] == page))
