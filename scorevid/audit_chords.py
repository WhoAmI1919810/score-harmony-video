# -*- coding: utf-8 -*-
"""人工和弦 vs 读谱音：找两类可疑处
  A 换了和弦，但这一段谱上没有新音、或新起的音全在前一个和弦里（音没变却标了换和弦）
  B 和弦音在这一段（含延续下来的音）里出现不到一半，或谱上的音大半不在和弦里
读谱音来自人声缩谱 OMR（中间文件/omr），有误读，所以只是"可疑"，要对谱确认。
用法：python3 audit_chords.py [起小节 止小节] → 打印 + 中间文件/和弦排查.csv"""
import os, sys, json, glob, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID
import textdoc
from make_text import load_chords

notes = []
for fn in sorted(glob.glob(os.path.join(MID, "omr", "p*_s*.json"))):
    notes += json.load(open(fn, encoding="utf-8"))
by_bar = {}
for n in notes:
    by_bar.setdefault(n["bar"], []).append(n)
ch = load_chords()
a = int(sys.argv[1]) if len(sys.argv) > 2 else 1
z = int(sys.argv[2]) if len(sys.argv) > 2 else 99999

# 展开成和弦段：(小节, 起 pos, 止 pos, 级数, 和弦名)
segs = []
for b in sorted(ch):
    cs = ch[b]["chords"]
    for i, c in enumerate(cs):
        p0 = (c[0] - 1) / 4
        p1 = (cs[i + 1][0] - 1) / 4 if i + 1 < len(cs) else 1.0
        segs.append((b, p0, p1, c[1], c[2]))


def onsets(b, p0, p1):
    return [n for n in by_bar.get(b, []) if p0 - 0.04 <= n["pos"] < p1 - 0.04 or (p0 == 0 and n["pos"] < 0)]


out = []
prev = None; prev_pcs = set(); prev_notes = []
for b, p0, p1, rn, name in segs:
    ns = onsets(b, p0, p1)
    pcs, bass = textdoc.chord_pcs(name) if rn not in ("—", "-") else ([], None)
    pcs = set(pcs)
    on = {n["midi"] % 12 for n in ns}
    lab = textdoc.bar_label(b) if hasattr(textdoc, "bar_label") else str(b)
    if a <= b <= z and rn not in ("—", "-") and prev and prev[3] not in ("—", "-"):
        changed = (prev[3], prev[4]) != (rn, name)
        if changed and (not ns or (on and on <= prev_pcs and not on <= pcs)):
            out.append((b, p0, "A 音没变却换和弦", f"{prev[3]} {prev[4]} → {rn} {name}", " ".join(sorted({n['name'] for n in ns})) or "（无新音）"))
        if changed and ns and on <= prev_pcs and on <= pcs and len(on) >= 2 and prev_pcs != pcs and not (pcs - prev_pcs) & on:
            out.append((b, p0, "A 新音都是两个和弦的共同音", f"{prev[3]} {prev[4]} → {rn} {name}", " ".join(sorted({n['name'] for n in ns}))))
    if a <= b <= z and pcs:
        pool = on | (prev_pcs_notes if not ns else set())
        if pool:
            hit = len(pcs & pool) / len(pcs)
            outside = len(pool - pcs) / len(pool)
            if hit < 0.5 or outside > 0.5:
                out.append((b, p0, "B 和弦音与谱上的音不符", f"{rn} {name}", " ".join(sorted({n['name'] for n in ns})) + f"（和弦音命中 {hit:.0%}，和弦外 {outside:.0%}）"))
    prev = (b, p0, p1, rn, name)
    prev_pcs = pcs if pcs else prev_pcs
    prev_pcs_notes = on if ns else (prev_pcs_notes if 'prev_pcs_notes' in dir() else set())

with open(os.path.join(MID, "和弦排查.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["小节", "显示", "位置", "类别", "和弦", "谱上新起的音"])
    for r in out:
        w.writerow([r[0], textdoc.bar_label(r[0]), f"{r[1] * 4 + 1:g}", r[2], r[3], r[4]])
from collections import Counter
print(Counter(r[2] for r in out))
for r in out:
    if a <= r[0] <= z:
        print(textdoc.bar_label(r[0]), f"拍{r[1] * 4 + 1:g}", r[2], "|", r[3], "|", r[4])
