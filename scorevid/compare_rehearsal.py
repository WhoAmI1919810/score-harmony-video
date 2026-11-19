# -*- coding: utf-8 -*-
"""比较两份谱的排练号位置（rehearsal.py 的输出）：python3 compare_rehearsal.py 已核对的.csv 新的.csv
对已核对那份的每个排练号，找新那份最近的排练号，打印小节号差。差 0 的占绝大多数时，
连续一段差同一个非零值 = 新谱在这段开头多了/少了小节；只差一两个、前后又回到 0 的多半是方框归错了小节（框在小节线附近），看 dx。"""
import sys, csv, bisect, collections
A = sorted({int(r["bar"]) for r in csv.DictReader(open(sys.argv[1], encoding="utf-8"))})
B = sorted({int(r["bar"]) for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))})
cnt = collections.Counter(); prev = None
for b in A:
    i = bisect.bisect_left(B, b)
    h = min([B[j] for j in (i - 1, i) if 0 <= j < len(B)], key=lambda x: abs(x - b))
    cnt[h - b] += 1
    if h - b != prev:
        print(f"从第 {b} 小节起：差 {h - b:+d}"); prev = h - b
print("差值分布", dict(cnt))
