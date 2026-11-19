# -*- coding: utf-8 -*-
"""第 5 步：渲染视频。

画面（1920×1080，--scale 2 出 4K）：
  左：总谱页（随录音翻页），当前小节加底色，竖线光标随时间在小节里移动。
  右上：曲名、当前段落标题、调、段落导语。
  右中：和弦走带——罗马数字级数随时间从右往左流过，竖线是"现在"。
  右下：逐小节分析（和声 / 声部 / 视角），新的一条出现在最上面，上一条变暗下移。
  底部：全曲调性地图与播放位置。

用法：
  python3 s5_render.py                  渲染整部视频到 输出/
  python3 s5_render.py --preview 30.5   只出第 30.5 秒（相对截取的音频）的一帧 PNG
  选项：--text 文字稿.txt  --times 小节时间.csv  --scale 2  --fps 30  --out 文件.mp4
"""
import os, sys, csv, re, math, argparse, subprocess, functools
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from common import (MID, OUT, DATA, BARS_CSV, TIMES_CSV, HARMONY_TXT, FONT_DIR, FREEFONT_DIR, WORK,
                    AUDIO_WAV, AUDIO_FLAC, FF_THREADS, DEFAULT_JOBS, TITLE, TITLE_CARD, SUBTITLE, PERFORMER, OUTPUT_NAME,
                    FIRST_PAGE, LAST_PAGE, AUDIO_START, AUDIO_END, MUSIC_END, VIDEO_TAIL,
                    SCORE_BARS_CSV, SCORE_PAGES, SCORE_FIRST, SCORE_LAST, SCORE_TITLE)
import textdoc

DESKEW = SCORE_PAGES
WAV = AUDIO_WAV
if not os.path.exists(WAV):
    WAV = AUDIO_FLAC                                   # 本地渲染包里是无损压缩的 FLAC
FREEFONT = FREEFONT_DIR

def _find_ffmpeg():
    import shutil
    f = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if f:
        return f
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG = _find_ffmpeg()

# ---------------- 外观参数（1080p 下的像素） ----------------
BG = (18, 20, 24)
CARD = (25, 28, 34)
LINE = (44, 49, 58)
TXT = (236, 231, 223)
TXT2 = (160, 166, 176)
TXT3 = (104, 110, 120)
AMBER = (240, 180, 90)
CURSOR = (226, 86, 60)
TAG = {"和声": (240, 180, 90), "声部": (130, 200, 150), "视角": (180, 160, 230)}
PAPER = (247, 242, 232)
INK = (28, 27, 26)
SHADE = (232, 190, 110, 62)
FUNC_COL = {"T": (126, 172, 222), "S": (134, 196, 146), "D": (232, 146, 104)}   # 功能标记的颜色       # 谱上当前小节的浅色阴影（RGBA）

# TITLE、SUBTITLE、PERFORMER、TITLE_CARD 来自 project.json 的 text.*

LANE_PXS = 105          # 和弦走带：每秒多少像素
LANE_PLAY = 0.22        # 当前和弦在走带里的位置（宽度的比例）


class R:
    """所有尺寸都乘 SCALE。"""
    S = 1.0


def s(v):
    return int(round(v * R.S))


@functools.lru_cache(maxsize=None)
def font(name, size):
    paths = {
        "serif_sb": os.path.join(FONT_DIR, "SourceHanSerifCN-SemiBold.otf"),
        "serif_b": os.path.join(FONT_DIR, "SourceHanSerifCN-Bold.otf"),
        "serif_m": os.path.join(FONT_DIR, "SourceHanSerifCN-Medium.otf"),
        "serif_r": os.path.join(FONT_DIR, "SourceHanSerifCN-Regular.otf"),
        "sans_m": os.path.join(FONT_DIR, "SourceHanSansCN-Medium.otf"),
        "sans_r": os.path.join(FONT_DIR, "SourceHanSansCN-Regular.otf"),
        "sans_b": os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"),
        "acc": os.path.join(FREEFONT, "FreeSerif.ttf"),
        "accb": os.path.join(FREEFONT, "FreeSerifBold.ttf"),
    }
    return ImageFont.truetype(paths[name], s(size))


ACC = "♭♯♮𝄪𝄫"
WORDCH = re.compile(r"[A-Za-z0-9#♯♭♮𝄪𝄫\.\-–/()'+°ø%:]")


# ---------------- 富文本：音名升降号、内嵌级数 {V65} ----------------
def runs_of_word(word):
    """把一个西文词拆成 [(字体类别, 文本)]：升降号单独用 FreeSerif。"""
    out = []
    for ch in word:
        kind = "acc" if ch in ACC else "main"
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + ch)
        else:
            out.append((kind, ch))
    return out


@functools.lru_cache(maxsize=4096)
def roman_sprite(label, size, color, bold=True):
    """罗马数字级数 → (RGBA 图, 基线 y)。转位数字上下叠放。"""
    p = textdoc.roman_parts(label)
    H = s(size * 2.0); base = s(size * 1.38)
    img = Image.new("RGBA", (s(size * 8), H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fmain = font("serif_sb" if bold else "serif_m", size)
    fsmall = font("serif_sb" if bold else "serif_m", size * 0.50)
    facc = font("accb" if bold else "acc", size * 0.92)
    x = 0
    if label in ("—", "-", "N.C."):
        d.text((x, base), "—", font=fmain, fill=color, anchor="ls")
        x += fmain.getlength("—")
        return img.crop((0, 0, int(x) + 2, H)), base
    if not p:
        txt = label
        for kind, t in runs_of_word(txt):
            f = facc if kind == "acc" else fmain
            d.text((x, base), t, font=f, fill=color, anchor="ls")
            x += f.getlength(t)
        return img.crop((0, 0, int(x) + 2, H)), base

    def draw_one(pp, x, scale=1.0):
        fm = font("serif_sb" if bold else "serif_m", size * scale)
        figk = 0.46 if size >= 34 else 0.56
        fs = font("serif_sb" if bold else "serif_m", size * figk * scale)
        fa = font("accb" if bold else "acc", size * 0.92 * scale)
        if pp["acc"]:
            d.text((x, base), pp["acc"], font=fa, fill=color, anchor="ls")
            x += fa.getlength(pp["acc"]) + s(1)
        num = pp["num"]
        d.text((x, base), num, font=fm, fill=color, anchor="ls")
        x += fm.getlength(num) + size * 0.05 * R.S
        bb = fm.getbbox("V", anchor="ls"); cap = -bb[1]          # 大写字母高度（实测）
        db = fs.getbbox("8", anchor="ls"); dh = -db[1]           # 数字高度（实测）
        gap = max(s(2), dh * 0.16)
        top_y = base - cap + dh                                  # 上方数字顶端与大写字母顶端齐
        bot_y = max(base + s(1), top_y + dh + gap)               # 下方数字
        if pp["qual"]:
            fq = font("serif_sb" if bold else "serif_m", size * 0.56 * scale)
            d.text((x, top_y), pp["qual"], font=fq, fill=color, anchor="ls")
            qw = fq.getlength(pp["qual"]) + s(1)
        else:
            qw = 0
        figs = pp["figs"]
        if len(figs) == 1:
            d.text((x + qw, top_y), figs[0], font=fs, fill=color, anchor="ls")
            x += qw + fs.getlength(figs[0]) + s(2)
        elif len(figs) == 2:
            fx = x + qw
            d.text((fx, top_y), figs[0], font=fs, fill=color, anchor="ls")
            d.text((fx, bot_y), figs[1], font=fs, fill=color, anchor="ls")
            x = fx + max(fs.getlength(figs[0]), fs.getlength(figs[1])) + s(2)
        else:
            x += qw
        if pp["rest"]:
            fsa = font("accb" if bold else "acc", size * figk * scale)
            for k, t in runs_of_word(pp["rest"].replace("b", "♭").replace("#", "♯")):
                ff = fsa if k == "acc" else fs
                d.text((x, top_y), t, font=ff, fill=color, anchor="ls")
                x += ff.getlength(t)
            x += s(2)
        return x

    x = draw_one(p, 0)
    if p["sec"]:
        d.text((x, base), "/", font=fmain, fill=color, anchor="ls")
        x += fmain.getlength("/") + s(1)
        q = textdoc.roman_parts(p["sec"])
        if q:
            x = draw_one(q, x)
        else:
            d.text((x, base), p["sec"], font=fmain, fill=color, anchor="ls")
            x += fmain.getlength(p["sec"])
    return img.crop((0, 0, int(x) + 2, H)), base


def chord_name_display(name):
    name = name.strip("[]") if name else ""
    name = name.replace("#", "♯").replace("b", "♭") if name else ""
    # 'maj' 'dim' 'sus' 'add' 里的 b 不是降号：先换回去
    name = name.replace("♭5", "♭5")
    return re.sub(r"(?<=[a-z])♭", "b", name)



def draw_acc_text(d, xy, text, fname, size, fill, anchor="ls", bold_acc=False):
    """画一段文字，其中的 ♯ ♭ ♮ 用 FreeSerif（思源字体里的升降号太宽）。返回宽度。"""
    x, y = xy
    fm = font(fname, size)
    fa = font("accb" if bold_acc else "acc", size * 1.0)
    runs = runs_of_word(text)
    w = sum((fa if k == "acc" else fm).getlength(t) for k, t in runs)
    if anchor[0] == "r":
        x -= w
    elif anchor[0] == "m":
        x -= w / 2
    an = "l" + anchor[1]
    for k, t in runs:
        f = fa if k == "acc" else fm
        d.text((x, y), t, font=f, fill=fill, anchor=an)
        x += f.getlength(t)
    return w


def tokens(text):
    i = 0
    out = []
    while i < len(text):
        ch = text[i]
        if ch == "{":
            j = text.find("}", i)
            if j > i:
                out.append(("roman", text[i + 1:j])); i = j + 1; continue
        if ch == " ":
            out.append(("space", " ")); i += 1; continue
        if WORDCH.match(ch):
            j = i
            while j < len(text) and WORDCH.match(text[j]):
                j += 1
            out.append(("word", text[i:j])); i = j; continue
        out.append(("char", ch)); i += 1
    return out


NO_LINE_START = set("，。、；：！？）」』”’》〉…—,.;:!?)")


class Rich:
    """一段可换行的富文本。layout(width) 后 draw(img, x, y)。"""

    def __init__(self, text, size, color, fname="serif_m", line_gap=1.42):
        self.text = textdoc.pretty_notes(textdoc.simplify_text(text))
        self.size = size; self.color = color; self.fname = fname; self.line_gap = line_gap

    def _items(self):
        f = font(self.fname, self.size)
        fa = font("acc", self.size * 1.0)
        items = []
        for kind, t in tokens(self.text):
            if kind == "roman":
                spr, base = roman_sprite(t, self.size * 1.02, self.color, bold=False)
                items.append(("roman", (spr, base), spr.width))
            elif kind == "word":
                w = sum((fa if k == "acc" else f).getlength(x) for k, x in runs_of_word(t))
                items.append(("word", t, w))
            elif kind == "space":
                items.append(("space", " ", f.getlength(" ")))
            else:
                items.append(("char", t, f.getlength(t)))
        return items

    def layout(self, width):
        lines = [[]]; cur = 0
        for it in self._items():
            w = it[2]
            if cur + w > width and lines[-1]:
                if it[0] == "space":
                    continue
                if it[0] == "char" and it[1] in NO_LINE_START:
                    lines[-1].append(it); cur += w; continue
                lines.append([]); cur = 0
            lines[-1].append(it); cur += w
        self.lines = lines
        self.lh = s(self.size * self.line_gap)
        self.height = self.lh * len(lines)
        return self.height

    def draw(self, img, x, y, alpha=255):
        d = ImageDraw.Draw(img)
        f = font(self.fname, self.size)
        fa = font("acc", self.size * 1.0)
        col = self.color + (alpha,) if len(self.color) == 3 else self.color
        for li, line in enumerate(self.lines):
            bx = x; by = y + li * self.lh + s(self.size * 1.08)
            for kind, t, w in line:
                if kind == "roman":
                    spr, base = t
                    if alpha < 255:
                        spr = spr.copy(); spr.putalpha(spr.getchannel("A").point(lambda v: v * alpha // 255))
                    if img.mode == "RGBA":
                        img.alpha_composite(spr, (int(bx), int(by - base)))
                    else:
                        img.paste(spr, (int(bx), int(by - base)), spr)
                elif kind == "word":
                    for k, part in runs_of_word(t):
                        ff = fa if k == "acc" else f
                        d.text((bx, by), part, font=ff, fill=col, anchor="ls")
                        bx += ff.getlength(part)
                    continue
                elif kind == "char":
                    d.text((bx, by), t, font=f, fill=col, anchor="ls")
                bx += w


# ---------------- 数据 ----------------
def load_bars():
    rows = {}
    for r in csv.DictReader(open(SCORE_BARS_CSV, encoding="utf-8")):
        rows[int(r["bar"])] = dict(page=int(r["page"]), system=int(r["system"]), x0=int(r["x0"]), x1=int(r["x1"]),
                                   y0=int(r["y0"]), y1=int(r["y1"]))
    # 每个系统第一小节含谱号调号：光标从"正文"开始
    sysbars = {}
    for b, r in rows.items():
        sysbars.setdefault((r["page"], r["system"]), []).append(b)
    for key, bs in sysbars.items():
        bs.sort()
        ws = [rows[b]["x1"] - rows[b]["x0"] for b in bs[1:]]
        med = float(np.median(ws)) if ws else 180
        first = rows[bs[0]]
        head = max(0, (first["x1"] - first["x0"]) - med * 1.05)
        for b in bs:
            rows[b]["play0"] = rows[b]["x0"] + (head if b == bs[0] else 0) + 6
    return rows


def parse_time(v):
    v = v.strip()
    parts = v.split(":")
    t = 0.0
    for p in parts:
        t = t * 60 + float(p)
    return t - AUDIO_START


def load_times(path, fake=False):
    """返回 bar_start{bar: t}、beat_times{(bar, beat): t}、music_end。时间相对截取音频。"""
    if fake:
        bs = {0: 2.65}
        for b in range(1, textdoc.LAST_BAR + 1):
            bs[b] = 5.2 + (b - 1) * 4.1
        return bs, {}, bs[textdoc.LAST_BAR] + 26
    with open(path, encoding="utf-8-sig") as f:
        pairs = [(int(r["小节"]), parse_time(r["开始"])) for r in csv.DictReader(f)]
    bs = dict(pairs)
    last_bar = textdoc.LAST_BAR if textdoc.LAST_BAR is not None else max(bs, default=textdoc.FIRST_BAR - 1)
    expected = set(range(textdoc.FIRST_BAR, last_bar + 1))
    ordered = [bs[b] for b in sorted(bs)]
    if len(pairs) != len(bs) or set(bs) != expected:
        raise ValueError("小节时间表的小节编号与渲染工程不一致")
    if (not ordered or not all(math.isfinite(t) for t in ordered)
            or any(a >= b for a, b in zip(ordered, ordered[1:]))
            or ordered[-1] >= MUSIC_END):
        raise ValueError("小节时间须严格递增，并且末小节须早于乐曲结束")
    beats = {}
    bpath = os.path.join(MID, "align", "beats.csv")
    auto = os.path.join(MID, "align", "小节时间_自动.csv")
    auto_bs = {}
    if os.path.exists(auto):
        for r in csv.DictReader(open(auto, encoding="utf-8")):
            auto_bs[int(r["小节"])] = parse_time(r["开始"])
    if os.path.exists(bpath):
        for r in csv.DictReader(open(bpath, encoding="utf-8")):
            beats[(int(r["bar"]), float(r["beat"]))] = float(r["time"])
    end = MUSIC_END
    # 只有这一小节与下一小节的开始都和自动结果一致时，才用自动的拍点；否则拍点均分
    good = {}
    for b in bs:
        nb = b + 1
        ok = (b in auto_bs and auto_bs[b] == bs[b] and
              (nb not in bs or (nb in auto_bs and auto_bs[nb] == bs[nb])))
        good[b] = ok
    beats = {k: v for k, v in beats.items() if good.get(k[0])}
    return bs, beats, end


class Timeline:
    def __init__(self, bar_start, beat_times, music_end):
        self.bars = sorted(bar_start)
        self.start = bar_start
        self.beat_times = beat_times
        self.end_time = music_end
        self.t_list = [bar_start[b] for b in self.bars]

    def bar_end(self, b):
        i = self.bars.index(b)
        return self.start[self.bars[i + 1]] if i + 1 < len(self.bars) else self.end_time

    def bar_at(self, t):
        i = int(np.searchsorted(self.t_list, t, side="right")) - 1
        return self.bars[max(0, i)]

    def beat_time(self, b, beat):
        """小节 b 第 beat 拍（可为小数）的时间。"""
        nb, first = textdoc.bar_beats(b)
        t0, t1 = self.start[b], self.bar_end(b)
        if beat == first:
            return t0
        k = int(math.floor(beat + 1e-9))
        if (b, float(k)) in self.beat_times:
            ta = self.beat_times[(b, float(k))]
            nxt = (b, float(k + 1))
            tb = self.beat_times.get(nxt, t1 if k + 1 >= first + nb else None)
            if tb is not None:
                return ta + (tb - ta) * (beat - k)
        return t0 + (t1 - t0) * (beat - first) / nb

    def frac_in_bar(self, t, b):
        """t 在小节 b 里的位置（0..1），按拍点分段线性。"""
        nb, first = textdoc.bar_beats(b)
        pts = [self.beat_time(b, first + k) for k in range(nb)] + [self.bar_end(b)]
        for k in range(nb):
            if pts[k] <= t < pts[k + 1]:
                return (k + (t - pts[k]) / max(1e-6, pts[k + 1] - pts[k])) / nb
        return 0.0 if t < pts[0] else 1.0


# ---------------- 调性颜色 ----------------
FIFTHS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: 7, 8: 8, 3: 9, 10: 10, 5: 11}


def key_color(k, light=False):
    import colorsys
    pc, minor = textdoc.key_pc(k)
    pos = (FIFTHS[pc] - FIFTHS[3]) % 12        # 主调 E♭ 大调为 0
    if minor:
        pos = (pos - 3) % 12                    # 小调按关系大调的位置
    hue = (38 + pos * 30) % 360 / 360.0
    lv = 0.56 if not minor else 0.40
    sat = 0.55 if not minor else 0.45
    if light:
        lv += 0.12
    r, g, b = colorsys.hls_to_rgb(hue, lv, sat)
    return (int(r * 255), int(g * 255), int(b * 255))


# ---------------- 画面 ----------------
class Renderer:
    def __init__(self, doc, tl, scale=1.0):
        R.S = scale
        self.doc = doc; self.tl = tl
        self.W, self.H = s(1920), s(1080)
        self.bars = load_bars()
        # 左侧谱面区域
        self.crop = self._common_crop()
        cx0, cy0, cx1, cy1 = self.crop
        self.sc_h = self.H - s(28)
        self.sc_scale = self.sc_h / (cy1 - cy0)
        self.sc_w = int(round((cx1 - cx0) * self.sc_scale))
        self.sc_x = s(22); self.sc_y = s(14)
        self.px = self.sc_x + self.sc_w + s(30)          # 右侧面板左边
        self.pw = self.W - self.px - s(26)
        self.page_cache = {}
        self.sections = sorted(doc.sections, key=lambda x: x.start)
        self._static = None
        self.entry_cache = {}
        self._lane_items = None
        self.red_cache = {}
        self.lane_y = s(196); self.lane_h = s(170)
        self.feed_y = s(400); self.feed_h = s(565)
        self.form_y = s(1004)

    # ---- 谱页 ----
    def _page_gray(self, p):
        """谱页灰度图；各页尺寸略有不同，统一贴到同样大小的白底上（左上对齐）"""
        g = Image.open(os.path.join(DESKEW, f"p{p:03d}.png")).convert("L")
        W, H = self._page_size
        if g.size != (W, H):
            c = Image.new("L", (W, H), 255); c.paste(g, (0, 0)); g = c
        return g

    def _common_crop(self):
        sizes = [Image.open(os.path.join(DESKEW, f"p{p:03d}.png")).size for p in range(SCORE_FIRST, SCORE_LAST + 1)]
        self._page_size = (max(w for w, h in sizes), max(h for w, h in sizes))
        W, H = self._page_size
        xs0, ys0, xs1, ys1 = [], [], [], []
        for p in range(SCORE_FIRST, SCORE_LAST + 1):
            a = np.array(self._page_gray(p).reduce(4)) < 128
            rows = np.where(a.sum(1) > 3)[0]; cols = np.where(a.sum(0) > 3)[0]
            ys0.append(rows[0]); ys1.append(rows[-1]); xs0.append(cols[0]); xs1.append(cols[-1])
        m = 6
        x0 = max(0, int(np.percentile(xs0, 20)) * 4 - m * 4); x1 = min(W, int(np.percentile(xs1, 80)) * 4 + m * 4)
        y0 = max(0, int(np.percentile(ys0, 10)) * 4 - m * 4); y1 = min(H, int(np.percentile(ys1, 90)) * 4 + m * 4)
        return (x0, y0, x1, y1)

    def page_img(self, p):
        if p not in self.page_cache:
            g = self._page_gray(p).crop(self.crop)
            g = g.resize((self.sc_w, self.sc_h), Image.LANCZOS)
            a = np.asarray(g, np.float32)[..., None] / 255.0
            rgb = np.array(INK, np.float32) + (np.array(PAPER, np.float32) - np.array(INK, np.float32)) * a
            self.page_cache[p] = Image.fromarray(rgb.astype(np.uint8), "RGB")
            if len(self.page_cache) > 6:
                self.page_cache.pop(next(iter(self.page_cache)))
        return self.page_cache[p]

    def to_screen(self, x, y):
        return (self.sc_x + (x - self.crop[0]) * self.sc_scale, self.sc_y + (y - self.crop[1]) * self.sc_scale)

    # ---- 静态背景 ----
    def static_bg(self):
        if self._static is None:
            img = Image.new("RGB", (self.W, self.H), BG)
            d = ImageDraw.Draw(img)
            # 纸张阴影
            sh = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
            ds = ImageDraw.Draw(sh)
            ds.rectangle([self.sc_x + s(4), self.sc_y + s(6), self.sc_x + self.sc_w + s(4), self.sc_y + self.sc_h + s(6)],
                         fill=(0, 0, 0, 150))
            sh = sh.filter(ImageFilter.GaussianBlur(s(8)))
            img.paste(sh, (0, 0), sh)
            self._static = img
        return self._static

    # ---- 右上：标题与段落 ----
    def section_at(self, bar):
        cur = None
        for sec in self.sections:
            if bar >= sec.start:
                cur = sec
        return cur

    def draw_header(self, img, bar):
        d = ImageDraw.Draw(img)
        x = self.px
        d.text((x, s(46)), TITLE, font=font("serif_m", 20), fill=TXT3, anchor="ls")
        d.text((x + self.pw, s(46)), SUBTITLE, font=font("serif_r", 18), fill=TXT3, anchor="rs")
        sec = self.section_at(bar)
        b = self.doc.bars.get(bar)
        key = textdoc.key_display(b.key if b else textdoc.HOME_KEY)
        if sec:
            title = textdoc.pretty_notes(sec.title)
            info = f"{key}　{textdoc.bar_label(sec.start, sec.end)}"
            _m = ImageDraw.Draw(Image.new("RGB", (8, 8)))          # 只量宽度
            iw = draw_acc_text(_m, (0, s(40)), info, "serif_m", 20, TXT2)
            tsz = 34
            while tsz > 22 and draw_acc_text(_m, (0, s(40)), title, "serif_b", tsz, TXT, bold_acc=True) + s(26) + iw > self.pw:
                tsz -= 2                                            # 标题太长：缩小字号，不让右边的小节范围出界
            tw = draw_acc_text(d, (x, s(104)), title, "serif_b", tsz, TXT, bold_acc=True)
            draw_acc_text(d, (x + tw + s(26), s(104)), info, "serif_m", 20, TXT2)
            if sec.intro:
                r = Rich(sec.intro, 20, TXT2, "serif_r", 1.5)
                r.layout(self.pw)
                r.lines = r.lines[:2]
                r.draw(img, x, s(118))

    # ---- 和弦走带 ----
    # 走带按顺序排列和弦（不按时间比例），当前和弦固定在"现在"的位置，换和弦时整条平滑左移。
    def lane_items(self):
        if self._lane_items is None:
            items = []
            for n in sorted(self.doc.bars):
                b = self.doc.bars[n]
                if n not in self.tl.start:
                    continue
                for i, c in enumerate(b.chords):
                    t0 = self.tl.beat_time(n, c.beat)
                    t1 = self.tl.beat_time(n, b.chords[i + 1].beat) if i + 1 < len(b.chords) else self.tl.bar_end(n)
                    items.append(dict(bar=n, t0=t0, t1=t1, roman=textdoc.simplify_roman(c.roman),
                                      name=chord_name_display(textdoc.simplify_name(c.name)),
                                      func=textdoc.chord_function(c.roman, c.func),
                                      first=(i == 0), keychange=(i == 0 and b.key_changed and n > textdoc.FIRST_BAR), key=b.key))
            # 相同的和弦（级数与和弦名都相同）跨拍、跨小节连续出现时合并成一项
            merged = []
            for it in items:
                if merged and merged[-1]["roman"] == it["roman"] and merged[-1]["name"] == it["name"] \
                        and not it["keychange"]:
                    merged[-1]["t1"] = it["t1"]
                    merged[-1]["last_bar"] = it["bar"]
                    continue
                it["last_bar"] = it["bar"]
                it["first"] = True if (not merged or merged[-1]["bar"] != it["bar"]) else it["first"]
                merged.append(it)
            items = merged
            x = 0.0
            fn = font("sans_r", 18); fa = font("acc", 20)
            for it in items:
                spr, _ = roman_sprite(it["roman"], 44, TXT)
                nw = sum((fa if k == "acc" else fn).getlength(t) for k, t in runs_of_word(it["name"]))
                lab = str(textdoc.part_bar(it["bar"])[1]) + (("　" + textdoc.key_display(it["key"])) if it["keychange"] else "")
                lw = font("sans_r", 16).getlength(lab) if it["first"] else 0
                it["x"] = x
                x += max(spr.width, nw, lw) + s(40)
            self._lane_items = items
            self._lane_t0 = [it["t0"] for it in items]
        return self._lane_items

    def draw_lane(self, img, t, bar):
        items = self.lane_items()
        if not items or t < self.tl.start.get(textdoc.FIRST_BAR, 0) - 0.05:
            return
        x0 = self.px; y0 = self.lane_y; w = self.pw; h = self.lane_h
        lane = Image.new("RGBA", (w, h), BG + (255,))
        d = ImageDraw.Draw(lane)
        play = int(w * LANE_PLAY)
        k = max(0, int(np.searchsorted(self._lane_t0, t, side="right")) - 1)
        p = min(1.0, max(0.0, (t - items[k]["t0"]) / 0.35))
        p = 1 - (1 - p) ** 3
        xprev = items[k - 1]["x"] if k > 0 else items[k]["x"]
        off = xprev + (items[k]["x"] - xprev) * p
        for i in range(max(0, k - 12), min(len(items), k + 14)):
            it = items[i]
            xx = play + it["x"] - off
            if xx > w or xx < -s(300):
                continue
            past = i < k or t >= it["t1"]
            cur = (i == k) and t < it["t1"]
            col = AMBER if cur else (TXT3 if past else TXT2)
            if it["first"]:
                pb = lambda n_: textdoc.part_bar(n_)[1]
                lab = str(pb(it["bar"])) if it["last_bar"] == it["bar"] else f"{pb(it['bar'])}–{pb(it['last_bar'])}"
                if it["keychange"]:
                    lab += "　" + textdoc.key_display(it["key"])
                draw_acc_text(d, (xx, s(22)), lab, "sans_r", 16,
                              TXT2 if it["bar"] <= bar <= it["last_bar"] else TXT3)
            spr, base = roman_sprite(it["roman"], 44, col)
            lane.alpha_composite(spr, (int(xx), int(s(86) - base)))
            if it["name"]:
                draw_acc_text(d, (xx + s(1), s(116)), it["name"], "sans_r", 18, col if not past else TXT3)
            if it.get("func"):
                fc = FUNC_COL.get(it["func"].strip("()").rstrip("D") or "D", TXT2)
                if past:
                    fc = tuple(int(v * 0.55 + b * 0.45) for v, b in zip(fc, BG))
                d.text((xx + s(1), s(146)), it["func"], font=font("serif_sb", 20), fill=fc, anchor="ls")
        fade = np.ones(w, np.float32)
        fl, fr = s(120), s(90)
        fade[:fl] = np.linspace(0.0, 1, fl); fade[-fr:] = np.linspace(1, 0.0, fr)
        arr = np.asarray(lane).copy()
        bgc = np.array(BG, np.float32)
        arr[..., :3] = (bgc + (arr[..., :3].astype(np.float32) - bgc) * fade[None, :, None]).astype(np.uint8)
        img.paste(Image.fromarray(arr[..., :3], "RGB"), (x0, y0))

    # ---- 逐小节说明 ----
    def entry_text(self, b):
        if b is None:
            return ""
        t = b.fields.get("说明", "")
        if not t:
            t = "".join(b.fields.get(k, "") for k in ("和声", "声部", "视角"))
        return t

    def groups(self):
        """说明文字的分组：有"说明"的小节开始一组，后面没有说明的小节并入这一组（和声没变就不重述）。"""
        if getattr(self, "_groups", None) is None:
            gs = []
            starts = {sec.start for sec in self.doc.sections}
            for n in sorted(self.doc.bars):
                b = self.doc.bars[n]
                if not gs or self.entry_text(b) or n in starts:     # 段落开头另起一组，不和上一段连在一起
                    gs.append([n, n])
                else:
                    gs[-1][1] = n
            self._groups = gs
            self._group_of = {}
            for i, (a, z) in enumerate(gs):
                for n in range(a, z + 1):
                    self._group_of[n] = i
        return self._groups

    def entry(self, n):
        """n 是组的起始小节。"""
        if n in self.entry_cache:
            return self.entry_cache[n]
        b = self.doc.bars.get(n)
        w = self.pw
        hf = font("serif_sb", 24)
        z = self.groups()[self._group_of[n]][1]
        label = textdoc.bar_label(n, z if z > n else None)
        parts = []
        head = Image.new("RGBA", (w, s(40)), (0, 0, 0, 0))
        dh = ImageDraw.Draw(head)
        dh.text((0, s(30)), label, font=hf, fill=AMBER, anchor="ls")
        if b and b.fields.get("标记"):
            mk = Rich(b.fields["标记"], 19, TXT3, "serif_r", 1.3)
            mk.layout(w - hf.getlength(label) - s(28))
            mk.lines = mk.lines[:1]
            mk.draw(head, int(hf.getlength(label) + s(24)), s(5))
        parts.append(head)
        txt = self.entry_text(b)
        if txt:
            r = Rich(txt, 27, TXT, "serif_m", 1.55)
            r.layout(w)
            im = Image.new("RGBA", (w, r.height + s(6)), (0, 0, 0, 0)); r.draw(im, 0, 0)
            parts.append(im)
        hgt = sum(p.height for p in parts) + s(8) * (len(parts) - 1)
        out = Image.new("RGBA", (w, hgt), (0, 0, 0, 0))
        yy = 0
        for p in parts:
            out.alpha_composite(p, (0, yy)); yy += p.height + s(8)
        self.entry_cache[n] = out
        return out

    def reduction_for(self, bar):
        for (a, b, fn) in self.doc.reductions:
            if a <= bar <= b:
                key = (a, b, fn)
                if key not in self.red_cache:
                    import reduction
                    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "缩谱", fn)
                    self.red_cache[key] = reduction.render(path, a, int(self.pw * 0.97), TXT2)
                return key, self.red_cache[key]
        return None, None

    def draw_reduction(self, box, t, bar, key, red):
        im, bars, x_at, bottom = red
        a, b, fn = key
        x0 = s(4); y0 = s(6)
        # 当前小节浅色底
        if bar in bars:
            m0, m1 = bars[bar]
            sh = Image.new("RGBA", (int(m1 - m0), int(bottom + s(8))), (255, 255, 255, 18))
            box.alpha_composite(sh, (int(x0 + m0), y0))
        box.alpha_composite(im, (x0, y0))
        d = ImageDraw.Draw(box)
        ly = y0 + bottom + s(58)
        last_right = -1e9
        prev_r = None
        for n in range(a, b + 1):
            bb = self.doc.bars.get(n)
            if not bb or n not in self.tl.start:
                continue
            for i, c in enumerate(bb.chords):
                t0 = self.tl.beat_time(n, c.beat)
                t1 = self.tl.beat_time(n, bb.chords[i + 1].beat) if i + 1 < len(bb.chords) else self.tl.bar_end(n)
                cur = t0 <= t < t1
                col = AMBER if cur else (TXT2 if t < t0 else TXT3)
                rr = textdoc.simplify_roman(c.roman)
                if prev_r == rr:
                    continue
                prev_r = rr
                spr, base = roman_sprite(rr, 27, col, bold=False)
                lx = max(x0 + x_at(n, c.beat) - s(2), last_right + s(10))
                box.alpha_composite(spr, (int(lx), int(ly - base)))
                fn_ = textdoc.chord_function(c.roman, c.func)
                if fn_:
                    fc = FUNC_COL.get(fn_.strip("()").rstrip("D") or "D", TXT2)
                    d.text((lx + s(1), ly + s(32)), fn_, font=font("serif_sb", 18), fill=fc, anchor="ls")
                last_right = lx + spr.width
        return int(ly + s(44))

    def draw_feed(self, img, t, bar):
        x0 = self.px; y0 = self.feed_y; h = self.feed_h; w = self.pw
        box = Image.new("RGBA", (w, h), BG + (255,))
        if t < self.tl.start.get(textdoc.FIRST_BAR, 0) - 0.05:
            self.draw_title_card(box)
        else:
            top = 0
            gs = self.groups()
            gi = self._group_of.get(bar, 0)
            g0 = gs[gi][0]
            t_bar = self.tl.start[g0]
            e = min(1.0, max(0.0, (t - t_bar) / 0.45))
            e = 1 - (1 - e) ** 3
            entries = [gs[j][0] for j in range(gi, max(-1, gi - 4), -1)]
            ims = [self.entry(b) for b in entries]
            gap = s(44)
            y = top - (1 - e) * (ims[0].height + gap)
            alphas = [e, 0.34 + (1 - e) * 0.66, 0.15 + (1 - e) * 0.19, 0.15 * (1 - e)]
            for k, im in enumerate(ims):
                if y > h:
                    break
                a = alphas[min(k, 3)]
                imm = im
                if a < 0.999:
                    imm = im.copy(); imm.putalpha(im.getchannel("A").point(lambda v, a=a: int(v * a)))
                if y + im.height > top:
                    if y < top:
                        cut = int(top - y)
                        imm = imm.crop((0, cut, imm.width, imm.height))
                        box.alpha_composite(imm, (0, int(top)))
                    else:
                        box.alpha_composite(imm, (0, int(y)))
                y += im.height + gap
            fh = s(90)
            arr = np.asarray(box).copy()
            ramp = np.linspace(1, 0, fh, dtype=np.float32)[:, None, None]
            bgc = np.array(BG, np.float32)
            arr[h - fh:, :, :3] = (bgc + (arr[h - fh:, :, :3].astype(np.float32) - bgc) * ramp).astype(np.uint8)
            box = Image.fromarray(arr, "RGBA")
        img.paste(box.convert("RGB"), (x0, y0))

    def draw_title_card(self, box):
        d = ImageDraw.Draw(box)
        w, h = box.size
        d.text((0, s(90)), TITLE_CARD, font=font("serif_b", 40), fill=TXT, anchor="ls")
        d.text((0, s(140)), SUBTITLE, font=font("serif_m", 26), fill=TXT2, anchor="ls")
        d.text((0, s(220)), "逐小节和声分析", font=font("serif_sb", 30), fill=AMBER, anchor="ls")
        d.text((0, s(290)), PERFORMER, font=font("serif_r", 22), fill=TXT2, anchor="ls")
        d.text((0, s(328)), SCORE_TITLE, font=font("serif_r", 19), fill=TXT3,
               anchor="ls")

    # ---- 左侧谱面 ----
    def draw_score(self, img, t, bar):
        if getattr(self, "_score_bar", None) == bar:
            img.paste(self._score_img, (self.sc_x, self.sc_y))
            return
        r = self.bars[bar]
        page = self.page_img(r["page"]).copy()
        ov = Image.new("RGBA", page.size, (0, 0, 0, 0))
        do = ImageDraw.Draw(ov)
        def P(x, y):
            return ((x - self.crop[0]) * self.sc_scale, (y - self.crop[1]) * self.sc_scale)
        pad = 26
        do.rectangle([P(r["x0"] + 2, r["y0"] - pad), P(r["x1"] - 1, r["y1"] + pad)], fill=SHADE)
        page = Image.alpha_composite(page.convert("RGBA"), ov).convert("RGB")
        self._score_bar, self._score_img = bar, page
        img.paste(page, (self.sc_x, self.sc_y))

    # ---- 右下角：全曲曲式与调性进度条 ----
    def form_layout(self):
        if getattr(self, "_form", None) is None:
            T0 = self.tl.start.get(textdoc.FIRST_BAR, 0.0); T1 = self.tl.end_time
            X = lambda tt: self.px + (tt - T0) / (T1 - T0) * self.pw
            segs = []
            for a, b, lab in (self.doc.form or [(sec.start, sec.end, sec.title) for sec in self.sections]):
                if a in self.tl.start:
                    segs.append((X(self.tl.start[a]), X(self.tl.bar_end(b) if b in self.tl.start else T1), a, b, lab))
            keys = []
            for n in self.tl.bars:
                bk = self.doc.bars.get(n)
                k = bk.key if bk else textdoc.HOME_KEY
                if keys and keys[-1][2] == k:
                    keys[-1][1] = X(self.tl.bar_end(n))
                else:
                    keys.append([X(self.tl.start[n]), X(self.tl.bar_end(n)), k])
            self._form = (segs, keys, X)
        return self._form

    def draw_form(self, img, t, bar):
        if t < self.tl.start.get(textdoc.FIRST_BAR, 0) - 0.05:
            return
        segs, keys, X = self.form_layout()
        d = ImageDraw.Draw(img)
        y = self.form_y
        gap = s(3)
        home = textdoc.HOME_KEY
        # 曲式段：细条，当前段用强调色，其余按已过/未到分深浅
        fl = font("serif_m", 16)
        for x0, x1, a, b, lab in segs:
            cur = a <= bar <= b
            col = AMBER if cur else (TXT3 if bar > b else LINE)
            d.rectangle([x0 + gap / 2, y + s(10), x1 - gap / 2, y + s(15)], fill=col)
            tag = lab if fl.getlength(lab) < (x1 - x0) - s(6) else lab.split()[0]
            if fl.getlength(tag) < (x1 - x0) - s(4):
                d.text((x0 + gap / 2, y + s(3)), tag, font=fl, fill=(AMBER if cur else TXT3), anchor="ls")
        # 调性：更细的一条；主调 D 大调用浅色，离开主调用深色，当前调用强调色
        last_r = -1e9
        for x0, x1, k in keys:
            cur = x0 <= X(t) < x1
            col = AMBER if cur else (TXT2 if k == home else (70, 76, 86))
            d.rectangle([x0, y + s(24), max(x0 + 1, x1), y + s(27)], fill=col)
            lab = (k[0].upper() if not k[0].islower() else k[0]) + k[1:].replace("#", "♯").replace("b", "♭")
            w = draw_acc_text(ImageDraw.Draw(Image.new("RGB", (1, 1))), (0, 0), lab, "sans_r", 14, TXT3)
            if x0 >= last_r + s(10) and x0 + w < self.px + self.pw:
                draw_acc_text(d, (x0, y + s(46)), lab, "sans_r", 14, AMBER if cur else TXT3)
                last_r = x0 + w
        # 播放位置
        xp = X(t)
        d.line([(xp, y + s(6)), (xp, y + s(30))], fill=TXT, width=max(1, s(2)))

    def frame(self, t):
        bar = self.tl.bar_at(t)
        img = self.static_bg().copy()
        self.draw_score(img, t, bar)
        self.draw_header(img, bar)
        key, red = self.reduction_for(bar) if t >= self.tl.start.get(textdoc.FIRST_BAR, 0) else (None, None)
        if red:
            # 有缩谱的小节：缩谱（级数标在下面）代替和弦走带，说明文字顺延到缩谱下方
            box = Image.new("RGBA", (self.pw, red[0].height + s(130)), BG + (255,))
            used = self.draw_reduction(box, t, bar, key, red)
            img.paste(box.crop((0, 0, self.pw, used)).convert("RGB"), (self.px, self.lane_y))
            fy, fh = self.feed_y, self.feed_h
            self.feed_y = self.lane_y + used + s(30); self.feed_h = self.H - self.feed_y - s(110)
            self.draw_feed(img, t, bar)
            self.feed_y, self.feed_h = fy, fh
        else:
            self.draw_lane(img, t, bar)
            self.draw_feed(img, t, bar)
        self.draw_form(img, t, bar)
        return img


PRE_ROLL = 4.0          # 音频开始前先停在片头几秒（秒）


def video_duration():
    return PRE_ROLL + MUSIC_END + VIDEO_TAIL


def _render_chunk(args):
    """子进程：渲染第 i0..i1 帧到一个只有画面的分段文件。"""
    text, times, scale, fps, i0, i1, out = args
    try:
        os.nice(15)          # 降低优先级，不和服务器上其他任务抢 CPU
    except (OSError, AttributeError):      # Windows 没有 os.nice
        pass
    doc = textdoc.parse(text)
    bs, beats, end = load_times(times)
    rd = Renderer(doc, Timeline(bs, beats, end), scale)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{rd.W}x{rd.H}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-tune", "stillimage",
           "-threads", FF_THREADS, out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(i0, i1):
        p.stdin.write(rd.frame(i / fps - PRE_ROLL).tobytes())
    p.stdin.close(); p.wait()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=float, nargs="*", help="出单帧：秒数（相对截取后的音频）")
    ap.add_argument("--text", default=HARMONY_TXT)
    ap.add_argument("--times", default=TIMES_CSV)
    ap.add_argument("--fake-times", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0, help="1 = 1920×1080；2 = 3840×2160")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="并行进程数（默认取环境变量 SV_JOBS，未设为 2：弱服务器）")
    ap.add_argument("--start", type=float, default=None, help="只渲染一段：起（秒，相对截取音频）")
    ap.add_argument("--end", type=float, default=None, help="只渲染一段：止")
    ap.add_argument("--out", default=os.path.join(OUT, OUTPUT_NAME + "_1080p.mp4"))
    ap.add_argument("--png-dir", default=os.path.join(OUT, "预览"))
    a = ap.parse_args()
    doc = textdoc.parse(a.text)
    bs, beats, end = load_times(a.times, fake=a.fake_times)
    tl = Timeline(bs, beats, end)
    if a.preview is not None:
        rd = Renderer(doc, tl, a.scale)
        os.makedirs(a.png_dir, exist_ok=True)
        for t in a.preview:
            im = rd.frame(t)
            fn = os.path.join(a.png_dir, f"预览_{t:07.2f}s.png")
            im.save(fn)
            print(fn)
        return
    render_video(a)


def render_video(a):
    import time
    from multiprocessing import Pool
    total = video_duration()
    f0 = 0 if a.start is None else int((a.start + PRE_ROLL) * a.fps)
    f1 = int(total * a.fps) if a.end is None else int((a.end + PRE_ROLL) * a.fps)
    tmp = os.path.join(MID, "render_parts")
    os.makedirs(tmp, exist_ok=True)
    for fn in os.listdir(tmp):
        os.remove(os.path.join(tmp, fn))
    # 渲染期间改文字稿不影响这一次：先把文字稿和时间表各复制一份快照给子进程用
    import shutil
    snap_text = os.path.join(tmp, "文字稿_快照.txt"); shutil.copy(a.text, snap_text)
    snap_times = os.path.join(tmp, "小节时间_快照.csv"); shutil.copy(a.times, snap_times)
    n = a.jobs * 3
    edges = np.linspace(f0, f1, n + 1).astype(int)
    jobs = [(snap_text, snap_times, a.scale, a.fps, int(edges[k]), int(edges[k + 1]), os.path.join(tmp, f"part{k:03d}.mp4"))
            for k in range(n) if edges[k + 1] > edges[k]]
    t0 = time.time()
    print(f"渲染 {f1 - f0} 帧（{(f1 - f0) / a.fps / 60:.1f} 分钟），{len(jobs)} 段，{a.jobs} 个进程", flush=True)
    with Pool(a.jobs) as pool:
        for k, out in enumerate(pool.imap(_render_chunk, jobs)):
            print(f"  {k + 1}/{len(jobs)} 段完成，已用 {(time.time() - t0) / 60:.1f} 分", flush=True)
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for j in jobs:
            f.write(f"file '{j[-1]}'\n")
    # 音频：前面加 PRE_ROLL 秒静音，末和弦之后 VIDEO_TAIL 秒内淡出
    a_start = (f0 / a.fps) - PRE_ROLL
    a_len = (f1 - f0) / a.fps
    fade_st = MUSIC_END + 0.5 - a_start + 0.0
    af = (f"adelay={int(PRE_ROLL * 1000)}|{int(PRE_ROLL * 1000)},"
          f"atrim=start={max(0.0, a_start + PRE_ROLL):.3f}:duration={a_len:.3f},asetpts=PTS-STARTPTS,"
          f"afade=t=out:st={max(0.0, MUSIC_END + PRE_ROLL - (a_start + PRE_ROLL) + 0.8):.3f}:d={VIDEO_TAIL - 1.2:.3f}")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-i", WAV, "-filter_complex", f"[1:a]{af}[aout]", "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print("写出", a.out, f"用时 {(time.time() - t0) / 60:.1f} 分")


if __name__ == "__main__":
    main()
