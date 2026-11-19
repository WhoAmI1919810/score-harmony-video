# -*- coding: utf-8 -*-
"""总谱原分辨率局部放大（从 PDF 原图截，最清楚）：python3 fs_full.py 起小节 止小节 上 下 [宽=1900] [谱号串]
谱号串（可选）：裁出范围内从上到下每行谱表的谱号，t 高音 b 低音 a 中音 n 次中音 x 跳过；给了就在每小节开头标出每条线的音名（不含调号），
  数一下打印的"谱表 N 行"和你给的串是否对得上，对不上说明有谱表没认出来（被连线、符尾挡住），换个上下范围再试。
  移调乐器（圆号 F、单簧管 B/A、小号 F 等）标的是记谱音，要自己换算成实际音。
宽：输出宽度；一两个小节时会放大到最多 2.5 倍，五线间距够大，临时记号、加线才看得清（马勒八的经验：一次最多截 2~3 个小节）。
起止须在同一页同一系统；上、下是系统高度的比例（0 = 系统顶，1 = 系统底），用来分段看（木管 / 铜管 / 弦乐）。
小节号写 II-n 或连续编号。→ 中间文件/总谱读谱/full.png
用它核对临时记号：还原号、重升重降，扫描缩小后的页图上常看不清。读音时对照调号、上下文，五线位置手算容易差一格。"""
import os, sys, csv, pymupdf
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FONT_DIR, FULL_PDF, FULL_UPSCALE
import textdoc
bar = lambda t: textdoc.PART2_BAR - 1 + int(t[3:]) if t.upper().startswith("II-") else int(t.replace("I-", ""))
a, z = bar(sys.argv[1]), bar(sys.argv[2]); f0, f1 = float(sys.argv[3]), float(sys.argv[4])
W = int(sys.argv[5]) if len(sys.argv) > 5 else 1900
rows = [r for r in csv.DictReader(open(os.path.join(DATA, "总谱小节位置.csv"), encoding="utf-8")) if a <= int(r["bar"]) <= z]
p, s = int(rows[0]["page"]), int(rows[0]["system"]); rows = [r for r in rows if int(r["page"]) == p and int(r["system"]) == s]
d = pymupdf.open(FULL_PDF)
pix = pymupdf.Pixmap(d, d[p - 1].get_images(full=True)[0][0])
im = Image.frombytes("L" if pix.n == 1 else "RGB", (pix.width, pix.height), pix.samples).convert("L")
ref = Image.open(os.path.join(MID, "总谱页", f"f{p:03d}.png")).size[0]          # s1_pages 取出的页图宽
k0 = im.width / ref / FULL_UPSCALE                                              # 小节坐标 → PDF 原图像素
X = lambda v: int(v * k0)
Y0, Y1 = X(int(rows[0]["y0"])) - 120, X(int(rows[0]["y1"])) + 80
y0, y1 = int(Y0 + (Y1 - Y0) * f0), int(Y0 + (Y1 - Y0) * f1)
x0 = max(0, X(int(rows[0]["x0"])) - 300); x1 = X(int(rows[-1]["x1"])) + 20
c = im.crop((x0, max(0, y0), x1, min(im.height, y1))).convert("RGB")
clefs = sys.argv[6] if len(sys.argv) > 6 else ""
staves = []
if clefs:                                   # 找五线：水平投影的峰，五条等距为一组
    import numpy as np
    g = np.array(c.convert("L")) < 128
    prof = g[:, int(g.shape[1] * 0.1):].mean(1)
    pk = [y for y in range(1, len(prof) - 1) if prof[y] > 0.3 and prof[y] >= prof[y - 1] and prof[y] >= prof[y + 1]]
    lines = []
    for y in pk:
        if not lines or y - lines[-1] > 3:
            lines.append(y)
    i = 0
    while i + 4 < len(lines):
        grp = lines[i:i + 5]; dd = np.diff(grp)
        if dd.max() - dd.min() <= max(4, dd.mean() * 0.25) and 15 < dd.mean() < 60:
            staves.append(grp); i += 5
        else:
            i += 1
k = min(2.5, W / c.width); c = c.resize((int(c.width * k), int(c.height * k)), Image.LANCZOS)
can = Image.new("RGB", (c.width, c.height + 36), "white"); can.paste(c, (0, 36)); dr = ImageDraw.Draw(can)
fb = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 26)
for r in rows:
    bx = (X(int(r["x0"])) - x0) * k
    dr.line([(bx, 36), (bx, can.height)], fill=(120, 120, 245)); dr.text((bx + 4, 2), textdoc.short_label(int(r["bar"])), fill=(40, 40, 220), font=fb)
LET = "CDEFGAB"
BOT = {"t": 2, "b": -10, "a": -4, "n": -6}      # 最下线相对 C4 的自然音级：高音 E4，低音 G2，中音 F3，次中音 D3
for si, st in enumerate(staves):
    cl = clefs[si] if si < len(clefs) else "x"
    if cl not in BOT:
        continue
    half = (st[-1] - st[0]) / 8
    fr = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), max(12, int(half * k * 1.5)))
    for r in rows:
        bx = (X(int(r["x0"])) - x0) * k
        for step in range(-4, 13, 2):            # 只标线（含上下两条加线），间自己推
            yy = (st[-1] - step * half) * k + 36
            n = BOT[cl] + step
            dr.text((bx + 3, yy - max(7, half * k * 0.9)), LET[n % 7] + str(4 + n // 7), fill=(225, 50, 50), font=fr)
if clefs:
    print("谱表", len(staves), "行（给了", len(clefs), "个谱号）")
os.makedirs(os.path.join(MID, "总谱读谱"), exist_ok=True)
out = os.path.join(MID, "总谱读谱", "full.png"); can.save(out); print(out, can.size, "pdf 页", p)
