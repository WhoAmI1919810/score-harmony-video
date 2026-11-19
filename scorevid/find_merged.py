# -*- coding: utf-8 -*-
"""找被合并成一个"系统"的上下两个系统：系统内部两行谱表之间的左边距里如果有系统分隔记号 //（两条平行斜粗线），
说明这里其实是两个系统（小节识别时两个系统小节线位置一致，被当成一个合并了）。
输出：页、系统、分隔记号所在的行间（上一行谱表的序号）。
用法：python3 find_merged.py"""
import os, sys, json
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID


_TPL = None


def template():
    """系统分隔记号 // 的模板（assets/system_separator.png，取自马勒八人声缩谱；别的版本的谱子要换成自己谱上截的）"""
    global _TPL
    if _TPL is None:
        from common import TOOLKIT
        ink = np.array(Image.open(os.path.join(TOOLKIT, "assets", "system_separator.png")).convert("L")) < 128
        _TPL = ink.astype(np.float32)
    return _TPL


def separators(ink, y0, y1, x0=150, x1=420, thr=0.72):
    from scipy.signal import fftconvolve
    reg = ink[y0:y1, x0:x1].astype(np.float32)
    t = template()
    if reg.shape[0] < t.shape[0] + 2 or reg.shape[1] < t.shape[1] + 2:
        return []
    tz = t - t.mean(); tn = np.sqrt((tz ** 2).sum())
    num = fftconvolve(reg, tz[::-1, ::-1], mode="valid")
    ones = np.ones_like(t)
    s1 = fftconvolve(reg, ones, mode="valid"); s2 = fftconvolve(reg ** 2, ones, mode="valid")
    var = np.maximum(s2 - s1 ** 2 / t.size, 1e-6)
    ncc = num / (np.sqrt(var) * tn)
    j = np.unravel_index(np.argmax(ncc), ncc.shape)
    return [(int(j[0] + y0), int(j[1] + x0), float(ncc[j]))] if ncc[j] >= thr else []


def main():
    st = json.load(open(os.path.join(MID, "staves.json")))
    out = []
    for p, systems in sorted(st.items(), key=lambda kv: int(kv[0])):
        ink = np.array(Image.open(os.path.join(MID, "pages_deskew", f"p{int(p):03d}.png")).convert("L")) < 128
        for si, sy in enumerate(systems, start=1):
            for k in range(len(sy) - 1):
                y0 = sy[k][-1] + 15; y1 = sy[k + 1][0] - 10
                if y1 - y0 < 40:
                    continue
                h = separators(ink, y0, y1)
                if h:
                    out.append((int(p), si, k + 1, h[0]))
                    print(int(p), si, k + 1, h[0], flush=True)
    for o in out:
        print(f"p{o[0]} 系统{o[1]}：第 {o[2]} 行谱表之后有系统分隔记号 //（y={o[3][0]}）")
    print(len(out), "处")
    return out


if __name__ == "__main__":
    main()
