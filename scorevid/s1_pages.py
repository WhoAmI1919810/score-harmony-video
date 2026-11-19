# -*- coding: utf-8 -*-
"""第 1 步：从 PDF 取出各页扫描图。
  python3 s1_pages.py          读谱用的乐谱（project.json 的 reading_score）→ 中间文件/pages/pNNN.png
  python3 s1_pages.py --full   总谱（full_score）→ 中间文件/总谱页/fNNN.png
IMSLP 的扫描 PDF 每页通常嵌一张黑白图：直接取原图（不重新栅格化，避免糊）；宽度超过 4000 像素的缩小一半。
如果 PDF 不是"每页一张图"（矢量排版的谱），改用 page.get_pixmap(dpi=300)。"""
import os, sys, pymupdf
from PIL import Image
from common import PDF, FIRST_PAGE, LAST_PAGE, PAGES_DIR, FULL_PDF, FULL_FIRST, FULL_LAST, MID

full = "--full" in sys.argv
src, p0, p1 = (FULL_PDF, FULL_FIRST, FULL_LAST) if full else (PDF, FIRST_PAGE, LAST_PAGE)
dst = os.path.join(MID, "总谱页") if full else PAGES_DIR
os.makedirs(dst, exist_ok=True)
doc = pymupdf.open(src)
for pno in range(p0, p1 + 1):
    out = os.path.join(dst, f"{'f' if full else 'p'}{pno:03d}.png")
    if os.path.exists(out):
        continue
    page = doc[pno - 1]
    imgs = page.get_images(full=True)
    if imgs:
        pix = pymupdf.Pixmap(doc, imgs[0][0])
        im = Image.frombytes("L" if pix.n == 1 else "RGB", (pix.width, pix.height), pix.samples).convert("L")
    else:
        pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
        im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if im.width > 4000:
        im = im.reduce(2)
    im.save(out)
print("ok", dst)
