# -*- coding: utf-8 -*-
"""双行钢琴缩谱：Humdrum **kern → verovio → 浅色位图，并给出每个小节、每个拍位在图上的 x 坐标。
缩谱文件放在 缩谱/ 下，第一小节必须是文字稿 [缩谱] 行里写的起始小节（不含弱起）。"""
import re, io, json
import numpy as np
from PIL import Image
import verovio, cairosvg


def render(path, first_bar, width_px, color=(236, 231, 223)):
    tk = verovio.toolkit()
    tk.setOptions({"breaks": "none", "adjustPageHeight": True, "header": "none", "footer": "none", "scale": 40,
                   "pageMarginTop": 10, "pageMarginBottom": 10, "pageMarginLeft": 0, "pageMarginRight": 4,
                   "spacingStaff": 9, "mnumInterval": 0, "svgViewBox": False,
                   "spacingLinear": 0.9, "spacingNonLinear": 0.35})
    src = open(path, encoding="utf-8").read()
    # 小节线上的编号只是给人看的，不让 verovio 印小节号
    src = "\n".join("\t".join(re.sub(r"^=(\d+)", "=", tok) if tok.startswith("=") and not tok.startswith("==") else tok
                               for tok in line.split("\t")) for line in src.split("\n"))
    if not tk.loadData(src):
        raise RuntimeError("verovio 读不了 " + path)
    svg = tk.renderToSVG(1)
    tm = tk.renderToTimemap()
    if isinstance(tm, str):
        tm = json.loads(tm)
    outer_w = float(re.search(r'<svg width="([\d.]+)px"', svg).group(1))
    vb = re.search(r'class="definition-scale"[^>]*viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    k = outer_w / float(vb.group(1))
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=int(width_px))
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    zoom = width_px / outer_w
    f = k * zoom                                   # 内部坐标 → 输出像素
    a = np.asarray(im)[..., 3]
    out = Image.new("RGBA", im.size, color + (0,))
    out.putalpha(Image.fromarray(a))
    # 音符 x：每个 note 组里第一个 <use x= >
    note_x = {}
    for m in re.finditer(r'<g id="(note-[^"]+)" class="note[^"]*"[^>]*>(.*?)</g>', svg, re.S):
        u = (re.search(r'<use xlink:href="#E0[A-F0-9]{2}[^"]*" transform="translate\(([\d.]+),\s*([\d.]+)\)', m.group(2))
             or re.search(r'<use xlink:href="#E0[A-F0-9]{2}[^"]*" x="([\d.]+)" y="([\d.]+)"', m.group(2)))
        if u:
            note_x[m.group(1)] = float(u.group(1)) * f
    # 小节范围与最低谱线
    measures = []
    ys = []
    for m in re.finditer(r'<g id="measure-[^"]+" class="measure[^"]*"[^>]*>(.*?)(?=<g id="measure-|</svg>)', svg, re.S):
        xs = []
        for p in re.finditer(r'd="M([\d.]+) ([\d.]+) L([\d.]+) ([\d.]+)"', m.group(1)):
            x1, y1, x2, y2 = map(float, p.groups())
            if abs(y1 - y2) < 0.5 and x2 - x1 > 50:
                xs += [x1, x2]; ys.append(y1)
        if xs:
            measures.append((min(xs) * f, max(xs) * f))
    bars = {first_bar + i: m for i, m in enumerate(measures)}
    onsets = []
    for ev in tm:
        on = [note_x[i] for i in ev.get("on", []) if i in note_x]
        if on:
            onsets.append((float(ev["qstamp"]), min(on)))
    onsets.sort()
    bottom = max(ys) * f if ys else im.height

    def x_at(bar, beat):
        q = (bar - first_bar) * 4 + (beat - 1)
        qs = [o[0] for o in onsets]; xs = [o[1] for o in onsets]
        if not qs:
            return 0.0
        if q <= qs[0]:
            return xs[0]
        for i in range(len(qs) - 1):
            if qs[i] <= q < qs[i + 1]:
                if q == qs[i]:
                    return xs[i]
                return xs[i] + (xs[i + 1] - xs[i]) * (q - qs[i]) / (qs[i + 1] - qs[i])
        b1 = bars.get(bar)
        return xs[-1] if not b1 else min(b1[1] - 10, xs[-1] + (q - qs[-1]) * 40)

    return out, bars, x_at, bottom
