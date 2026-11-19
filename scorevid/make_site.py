# -*- coding: utf-8 -*-
"""生成在线校对站（静态目录，发布成临时网站）：中间文件/校对站/
素材取自 中间文件/校对页/（make_checker.py 生成；谱页、录音、音高谱不变时用 --data-only 只重写 data.json），
页面用 web/校对站模板.html（说明见 web/README.md）。网站里没有本地存储，改动要导出 CSV。
用法：python3 make_checker.py --data-only && python3 make_site.py"""
import os, sys, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NICE_CMD, FF_THREADS, AUDIO_WAV, SHORT_NAME, MID

SRC = os.path.join(MID, "校对页")
DST = os.path.join(MID, "校对站")


def link(a, b):
    if os.path.exists(b):
        os.remove(b)
    try:
        os.link(a, b)
    except OSError:
        shutil.copy(a, b)


def write_align_data():
    """网页里重排小节用的数据（和 align_dtw.py 同一种代价）：
       feats.bin  每 0.2 秒一帧：84 维音高谱 + 12 维色度（各自归一化），uint8
       tpl.bin    每小节 4 个名义拍：84 维读谱音高模板 + 12 维色度模板，uint8，顺序同 data.json 的 bars"""
    import json, csv
    import numpy as np
    import align_lab as L
    from common import BARS_CSV
    F = L.load_feats(0.2)
    Xp = L.audio_vecs(F, "pitch"); Xc = L.audio_vecs(F, "chroma")
    feats = np.concatenate([Xp, Xc], 1)
    bars = sorted({int(r["bar"]) for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))})
    Tp, idx = L.templates(bars, "pitch"); Tc, _ = L.templates(bars, "chroma")
    tpl = np.concatenate([Tp, Tc], 1)
    q = lambda a: np.clip(np.round(a * 255), 0, 255).astype(np.uint8)
    q(feats).tofile(os.path.join(DST, "feats.bin"))
    q(tpl).tofile(os.path.join(DST, "tpl.bin"))
    json.dump(dict(fr=0.2, frames=len(feats), dimP=84, dimC=12, beatsPerBar=L.NB, bars=len(bars), wPitch=0.7),
              open(os.path.join(DST, "align.json"), "w"))
    print("对齐数据：", feats.shape, tpl.shape)


def main():
    # 临时网站每个网页最多 50 MiB：谱页压成 4 级灰度，录音 40 kbps 单声道
    os.makedirs(os.path.join(DST, "spec"), exist_ok=True)
    from PIL import Image
    from common import FIRST_PAGE, LAST_PAGE
    for p in range(FIRST_PAGE, LAST_PAGE + 1):
        out = os.path.join(DST, f"p{p:03d}.png")
        if os.path.exists(out) and os.stat(out).st_nlink == 1 and "--redo" not in sys.argv:
            continue
        if os.path.exists(out):
            os.remove(out)
        im = Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("L")
        im = im.resize((1000, round(im.height * 1000 / im.width)), Image.LANCZOS).quantize(colors=4)
        im.save(out, optimize=True)
    aud = os.path.join(DST, "audio.mp3")
    if not os.path.exists(aud) or os.stat(aud).st_nlink > 1 or "--redo" in sys.argv:
        if os.path.exists(aud):
            os.remove(aud)
        import subprocess
        subprocess.run(NICE_CMD + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", FF_THREADS,
                        "-i", AUDIO_WAV, "-ac", "1", "-ar", "22050", "-b:a", "40k", aud], check=True)
    for f in glob.glob(os.path.join(SRC, "spec", "*.png")):
        link(f, os.path.join(DST, "spec", os.path.basename(f)))
    shutil.copy(os.path.join(SRC, "data.json"), os.path.join(DST, "data.json"))
    write_align_data()
    tpl = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "校对站模板.html"), encoding="utf-8").read()
    open(os.path.join(DST, "index.html"), "w", encoding="utf-8").write(tpl.replace("{{作品名}}", SHORT_NAME))
    tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DST) for f in fs)
    print("写出", DST, f"{tot / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
