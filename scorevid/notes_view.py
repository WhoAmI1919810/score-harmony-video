# -*- coding: utf-8 -*-
"""读谱辅助（半自动）：在指定谱表上找符头，按谱号在符头旁标出"写谱音名"（不含调号/临时记号），
并画淡色音高参考线。用来核对自己读的音，不保证全对（文字、附点、装饰音可能误报，挤在一起的和弦音可能漏报）。

用法：python3 notes_view.py 起小节 止小节 谱表序号[,..] 谱号[,..] [--zoom 2] [--out x.png]
  谱表序号：该系统里从上往下数，从 1 开始；谱号：treble / alto / tenor / bass
  （写谱音高；移调乐器、八度记谱请自行换算；调号与临时升降号也请自己看）
"""
import sys, os, csv, json, argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BARS_CSV, MID, FONT_DIR

NAMES = ["C", "D", "E", "F", "G", "A", "B"]
BOTTOM = {"treble": (2, 4), "alto": (3, 3), "tenor": (1, 3), "bass": (4, 2)}   # 最下一条线：E4 F3 D3 G2


def pitch_name(clef, k):
    bl, bo = BOTTOM[clef]
    idx = bl + k
    return NAMES[idx % 7] + str(bo + idx // 7)


def remove_lines(reg, line_rows, maxrun=4):
    """去掉谱线/加线：每一列里长度 ≤ maxrun、并且落在谱线位置 ±2 像素内的墨迹竖段。"""
    out = reg.copy()
    H, W = reg.shape
    near = np.zeros(H, bool)
    for y in line_rows:
        for d in range(-2, 3):
            if 0 <= y + d < H:
                near[y + d] = True
    for x in range(W):
        col = reg[:, x]
        if not col.any():
            continue
        d = np.diff(np.concatenate([[0], col.astype(np.int8), [0]]))
        starts = np.where(d == 1)[0]; ends = np.where(d == -1)[0]
        for s, e in zip(starts, ends):
            if e - s <= maxrun and near[s:e].any():
                out[s:e, x] = False
    return out


def refine_lines(ink, lines, x0, x1):
    """在这一段小节范围里重新量谱线的位置（扫描页会有轻微弯曲），再按等距拟合。"""
    seg = ink[:, x0:x1]
    lines = [int(round(v)) for v in lines]
    hor = ndi.binary_opening(seg[max(0, lines[0] - 12):lines[-1] + 12], structure=np.ones((1, 25), bool))
    prof = hor.sum(1).astype(float)
    base = max(0, lines[0] - 12)
    ys = []
    for y in lines:
        lo, hi = y - 5 - base, y + 6 - base
        w = prof[lo:hi]
        if w.max() <= 0:
            ys.append(float(y)); continue
        w = np.where(w >= 0.5 * w.max(), w, 0)
        ys.append(base + lo + float((w * np.arange(len(w))).sum() / w.sum()))
    i = np.arange(5)
    A = np.vstack([np.ones(5), i]).T
    c, sp = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
    return [c + sp * k for k in range(5)]


def detect(ink, lines, x0, x1, clef, refined=False):
    if not refined:
        lines = refine_lines(ink, lines, x0, x1)
    sp = (lines[-1] - lines[0]) / 4.0
    half = sp / 2.0
    top = int(lines[0] - 9 * half); bot = int(lines[-1] + 9 * half)
    reg = ink[top:bot, x0:x1]
    line_rows = [int(round(lines[-1] - k * half - top)) for k in range(-12, 22, 2)]
    clean = remove_lines(reg, line_rows)
    # 谱表外的加线：较长的细横线（≥1.7 个间距），先整条扣掉，再竖向闭运算把被切开的符头接回去
    staff_top = int(lines[0] - top) - 3; staff_bot = int(lines[-1] - top) + 3
    hor = ndi.binary_opening(reg, structure=np.ones((1, int(1.7 * sp)), bool))
    thin = hor & ~ndi.binary_opening(hor, structure=np.ones((5, 1), bool))
    thin[staff_top:staff_bot] = False
    clean = clean & ~ndi.binary_dilation(thin, structure=np.ones((3, 1), bool))
    clean = ndi.binary_closing(clean, structure=np.ones((7, 1), bool))
    # 空心符头：在原图（带谱线）里找小的封闭白洞（符头的"眼"），填上
    holes = ndi.binary_fill_holes(reg) & ~reg
    hl, hn = ndi.label(holes)
    if hn:
        sizes = ndi.sum(holes, hl, index=np.arange(1, hn + 1))
        objs = ndi.find_objects(hl)
        keep = np.zeros(hn + 1, bool)
        for j, (sz, sl) in enumerate(zip(sizes, objs), start=1):
            hh = sl[0].stop - sl[0].start; ww = sl[1].stop - sl[1].start
            if 6 <= sz <= 0.6 * sp * sp and hh <= 0.75 * sp and ww <= 1.2 * sp:
                keep[j] = True
        small = keep[hl]
        # 洞周围一圈也算符头（谱线去掉时可能被切开）
        small = ndi.binary_dilation(small, iterations=2) & (reg | small)
    else:
        small = np.zeros_like(reg)
    filled = ndi.binary_fill_holes(clean | small)
    dt = ndi.distance_transform_edt(filled)
    seeds = dt >= 0.36 * sp
    lab, n = ndi.label(seeds)
    found = []
    for i in range(1, n + 1):
        m = lab == i
        ys, xs = np.where(m)
        h = ys.max() - ys.min() + 1; w = xs.max() - xs.min() + 1
        if h > 1.4 * sp or w > 2.2 * sp:          # 太大：横梁、粗线、文字团
            continue
        mx = dt[m].max()
        if mx < 0.42 * sp or mx > 0.85 * sp:
            continue
        core = m & (dt >= 0.75 * mx)
        cy = np.average(np.where(core)[0], weights=dt[core]) + top
        cx = np.average(np.where(core)[1], weights=dt[core]) + x0
        k = (lines[-1] - cy) / half
        kr = int(round(k))
        found.append((cx, cy, kr, k - kr, pitch_name(clef, kr)))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("b0", type=int); ap.add_argument("b1", type=int)
    ap.add_argument("staves"); ap.add_argument("clefs")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = {int(r["bar"]): r for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))}
    r0, r1 = rows[a.b0], rows[a.b1]
    assert (r0["page"], r0["system"]) == (r1["page"], r1["system"]), "起止小节不在同一系统"
    page, sysn = int(r0["page"]), int(r0["system"])
    staves = json.load(open(os.path.join(MID, "staves.json")))[str(page)][sysn - 1]
    # 谱表序号也可以写成 @y（这一行谱表第一条线的大致 y 坐标，校正后页面像素），用于自动识别漏掉的谱表
    idxs = [x if x.startswith("@") else int(x) for x in a.staves.split(",")]
    clefs = a.clefs.split(",")
    if len(clefs) == 1:
        clefs = clefs * len(idxs)
    gray = Image.open(os.path.join(MID, "pages_deskew", f"p{page:03d}.png")).convert("L")
    ink = np.array(gray) < 140
    img = gray.convert("RGB")
    left = int(r0["x0"]) - 10; right = int(r1["x1"]) + 10
    font = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 12)
    fnote = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 15)
    fontb = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 24)
    pieces = []
    for si, clef in zip(idxs, clefs):
        base = staves[si - 1] if isinstance(si, int) else [float(si[1:]) + 12.8 * k for k in range(5)]
        lines = refine_lines(ink, base, left, right)
        sp = (lines[-1] - lines[0]) / 4.0; half = sp / 2
        top = int(lines[0] - 9 * half); bot = int(lines[-1] + 9 * half)
        notes = detect(ink, lines, left, right, clef, refined=True)
        z = a.zoom
        crop = img.crop((left, top, right, bot)).resize((int((right - left) * z), int((bot - top) * z)), Image.LANCZOS)
        d = ImageDraw.Draw(crop, "RGBA")
        lab = Image.new("RGB", (72, crop.height), "white"); dl = ImageDraw.Draw(lab)
        for k in range(-8, 17):
            y = (lines[-1] - k * half - top) * z
            on_line = (k % 2 == 0)
            d.line([(0, y), (crop.width, y)], fill=(255, 0, 0, 55) if on_line else (0, 110, 255, 35), width=1)
            dl.text((4 if on_line else 38, y), pitch_name(clef, k), fill=(200, 0, 0) if on_line else (0, 90, 220), font=font, anchor="lm")
        for b in range(a.b0, a.b1 + 1):
            x = (int(rows[b]["x0"]) - left) * z
            d.text((x + 4, 2), f"m{b}", fill=(200, 0, 0), font=fontb)
        for (cx, cy, kr, frac, name) in notes:
            X = (cx - left) * z; Y = (cy - top) * z
            col = (0, 150, 0) if abs(frac) < 0.3 else (230, 120, 0)
            d.ellipse([X - 3, Y - 3, X + 3, Y + 3], outline=col)
            d.text((X + 0.75 * sp * z, Y - 0.55 * sp * z), name, fill=col, font=fnote, anchor="lm")
        row = Image.new("RGB", (crop.width + 72, crop.height), "white")
        row.paste(lab, (0, 0)); row.paste(crop, (72, 0))
        pieces.append(row)
    W = max(p.width for p in pieces); H = sum(p.height for p in pieces) + 6 * len(pieces)
    out = Image.new("RGB", (W, H), (120, 120, 120)); y = 0
    for p in pieces:
        out.paste(p, (0, y)); y += p.height + 6
    fn = a.out or f"notes_{a.b0}-{a.b1}.png"
    out.save(fn); print(fn, out.size)


if __name__ == "__main__":
    main()
