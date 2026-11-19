# -*- coding: utf-8 -*-
"""生成"时间轴校对页"用的素材，写到 中间文件/校对页/：
  audio.mp3        全曲录音（两部分之间的静音已缩短；单声道 64 kbps）
  pNNN.png         各页乐谱（宽 1000 像素）
  spec/sNNN.png    录音的音高谱（每张 60 秒，每秒 20 像素）
  data.json        每小节的页码、位置、当前时间、和弦，段落，响度包络
页面本身是 校对页.html（同一目录）。用法：python3 make_checker.py"""
import os, sys, csv, json, subprocess
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NICE_CMD, FF_THREADS, AUDIO_WAV, SHORT_NAME, MID, BARS_CSV, TIMES_CSV, HARMONY_TXT, AUDIO_START, MUSIC_START, MUSIC_END, FIRST_PAGE, LAST_PAGE
import textdoc

OUT = os.path.join(MID, "校对页")
os.makedirs(os.path.join(OUT, "spec"), exist_ok=True)
PW = 1000
SPEC_SEC = 60
SPEC_PPS = 20


def parse_time(v):
    t = 0.0
    for p in v.strip().split(":"):
        t = t * 60 + float(p)
    return t - AUDIO_START


def main():
    data_only = "--data-only" in sys.argv
    wav = AUDIO_WAV
    if data_only:
        return write_data()

    subprocess.run(NICE_CMD + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav, "-ac", "1",
                    "-ar", "44100", "-b:a", "64k", "-threads", FF_THREADS, os.path.join(OUT, "audio.mp3")], check=True)
    scale = PW / 2700.0
    for p in range(FIRST_PAGE, LAST_PAGE + 1):
        im = Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("L")
        im = im.resize((PW, int(round(im.height * scale))), Image.LANCZOS)
        im = im.quantize(colors=16)
        im.save(os.path.join(OUT, f"p{p:03d}.png"), optimize=True)
    f = np.load(os.path.join(MID, "audio", "features.npz"))
    P = f["pitch"].astype(np.float32)          # 每 0.1 秒一帧，MIDI 24..107
    E = f["energy"].astype(np.float32)
    lo, hi = 28 - 24, 100 - 24                 # E1..E7
    S = P[:, lo:hi + 1]
    S = S - np.percentile(S, 5)
    S = np.clip(S / np.percentile(S, 99.7), 0, 1) ** 1.4
    nfr = S.shape[0]
    fps = 10
    tiles = int(np.ceil(nfr / (SPEC_SEC * fps)))
    rows = S.shape[1]
    for k in range(tiles):
        seg = S[k * SPEC_SEC * fps:(k + 1) * SPEC_SEC * fps]
        if len(seg) < SPEC_SEC * fps:
            seg = np.vstack([seg, np.zeros((SPEC_SEC * fps - len(seg), rows), np.float32)])
        img = (seg.T[::-1] * 255).astype(np.uint8)          # 高音在上
        im = Image.fromarray(img, "L").resize((SPEC_SEC * SPEC_PPS, rows * 3), Image.BILINEAR)
        im.save(os.path.join(OUT, "spec", f"s{k:03d}.png"), optimize=True)
    write_data()


def write_data():
    scale = PW / 2700.0
    f = np.load(os.path.join(MID, "audio", "features.npz"))
    E = f["energy"].astype(np.float32)
    fps = 10
    tiles = int(np.ceil(len(f["pitch"]) / (SPEC_SEC * fps)))
    db = 20 * np.log10(E + 1e-9)
    env = np.clip(db + 70, 0, 70).round(1).tolist()
    # 第一部分音乐结束（第二部分开始前最后一个响的帧）：网页里重排第一部分最后一段时用
    from common import PART2_START
    k2 = int(PART2_START * fps)
    loud = np.where(db[:k2] > db.max() - 50)[0]
    part1_end = float((loud[-1] + 1) / fps) if len(loud) else PART2_START - 3
    # 小节
    T = {}
    C = set()
    for r in csv.DictReader(open(TIMES_CSV, encoding="utf-8-sig")):
        T[int(r["小节"])] = parse_time(r["开始"])
        if "确认" in (r.get("备注") or ""):
            C.add(int(r["小节"]))
    doc = textdoc.parse(HARMONY_TXT)
    bars = []
    for r in csv.DictReader(open(BARS_CSV, encoding="utf-8")):
        n = int(r["bar"])
        b = doc.bars.get(n)
        chords = []
        if b:
            prev = None
            for c in b.chords:
                rr = textdoc.simplify_roman(c.roman)
                if rr != prev:
                    chords.append(rr.replace("b", "♭").replace("#", "♯") if rr.startswith(("b", "#")) else rr)
                prev = rr
        bars.append(dict(n=n, p=int(r["page"]), x0=round(int(r["x0"]) * scale, 1), x1=round(int(r["x1"]) * scale, 1),
                         y0=round(int(r["y0"]) * scale, 1), y1=round(int(r["y1"]) * scale, 1),
                         t=round(T[n], 3), ch=" ".join(chords), key=(b.key if b else ""),
                         lab=("I-" if textdoc.part_bar(n)[0] == 1 else "II-") + str(textdoc.part_bar(n)[1]),
                         part=textdoc.part_bar(n)[0], c=(1 if n in C else 0)))
    secs = [dict(a=s.start, b=s.end, title=s.title) for s in doc.sections]
    data = dict(audioStart=AUDIO_START, musicStart=MUSIC_START, musicEnd=MUSIC_END, bars=bars, sections=secs,
                env=env, envFps=fps, spec=dict(sec=SPEC_SEC, pps=SPEC_PPS, tiles=tiles, lo=28, hi=100, rowPx=3),
                pageWidth=PW, pageHeight=round(3600 * PW / 2700.0, 1), scale=PW / 2700.0, part2Bar=textdoc.PART2_BAR, part1End=round(part1_end, 2),
                firstPage=FIRST_PAGE, lastPage=LAST_PAGE)
    json.dump(data, open(os.path.join(OUT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    tot = 0
    for root, _, fs in os.walk(OUT):
        for fn in fs:
            tot += os.path.getsize(os.path.join(root, fn))
    print("写出", OUT, f"{tot / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
