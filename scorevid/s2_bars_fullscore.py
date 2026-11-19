# -*- coding: utf-8 -*-
"""总谱的小节识别：页图放大 FULL_UPSCALE 倍（总谱谱线间距常只有 9–10 像素，放大后才认得出），校正倾斜后用 s2_bars 的同一套方法。
输出：数据/总谱小节位置.csv（bar,page,system,x0,x1,y0,y1；page = 总谱 pdf 页；坐标是 中间文件/总谱_deskew 上的像素，
即原图放大 2 倍后的坐标）、中间文件/总谱/staves.json、中间文件/总谱/bars_debug/。
人工修正写在 数据/总谱小节修正.txt（格式同 小节修正.txt，坐标用放大后的）。
用法：python3 s2_bars_fullscore.py [起页 止页]   （默认全部；只跑部分页时不写 csv，只出核对图）"""
import os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, FULL_FIRST, FULL_LAST, FULL_UPSCALE
import s2_bars as sb

SRC = os.path.join(MID, "总谱页")
OUTD = os.path.join(MID, "总谱")
DESK = os.path.join(MID, "总谱_deskew")
for d in (OUTD, DESK, os.path.join(OUTD, "bars_debug")):
    os.makedirs(d, exist_ok=True)


def deskew_fs(pno):
    cached = os.path.join(DESK, f"p{pno:03d}.png")
    if os.path.exists(cached) and "--redeskew" not in sys.argv:
        return Image.open(cached).convert("L"), (0.0, 0.0)
    im = Image.open(os.path.join(SRC, f"f{pno:03d}.png")).convert("L")
    im = im.resize((im.width * FULL_UPSCALE, im.height * FULL_UPSCALE), Image.LANCZOS)
    ink = np.array(im) < 128
    H, W = ink.shape
    ah = sb.estimate_skew(ink)
    vert = ndi.binary_opening(ink, structure=np.ones((121, 1), bool))
    av = sb.estimate_skew(vert.T)
    th, tv = np.tan(np.radians(ah)), np.tan(np.radians(av))
    out = im.transform((W, H), Image.AFFINE, (1, tv, -H / 2 * tv, th, 1, -W / 2 * th),
                       resample=Image.BICUBIC, fillcolor=255)
    out = out.point(lambda v: 0 if v < 128 else 255)
    out.save(cached, optimize=True)
    return out, (ah, av)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    p0, p1 = (int(args[0]), int(args[1])) if len(args) == 2 else (FULL_FIRST, FULL_LAST)
    sb.deskew_page = deskew_fs
    sb.DEBUG_DIR = os.path.join(OUTD, "bars_debug")
    sb.MID = OUTD
    sb.FIRST_PAGE, sb.LAST_PAGE = p0, p1
    sb.EDITS_TXT = os.path.join(DATA, "总谱小节修正.txt")
    full = (p0, p1) == (FULL_FIRST, FULL_LAST)
    sb.BARS_CSV = os.path.join(DATA, "总谱小节位置.csv") if full else os.path.join(OUTD, f"部分识别_{p0:03d}_{p1:03d}.csv")
    if not full:
        sb.MID = os.path.join(OUTD, f"part_{p0:03d}_{p1:03d}")
        os.makedirs(sb.MID, exist_ok=True)
    sys.argv = [sys.argv[0], "--force"]
    sb.main()


if __name__ == "__main__":
    main()
