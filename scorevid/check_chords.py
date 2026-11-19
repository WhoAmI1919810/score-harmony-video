# 校验 数据/和弦_人工.txt：级数推出的根音、和弦性质 与 和弦名是否一致。python3 check_chords.py [起小节]
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textdoc
from make_text import load_chords
MAJ = {"I": 0, "II": 2, "III": 4, "IV": 5, "V": 7, "VI": 9, "VII": 11}
MINR = {"I": 0, "II": 2, "III": 3, "IV": 5, "V": 7, "VI": 8, "VII": 10}   # 小调：III、VI、VII 用自然小调


def deg_pc(num, acc, kpc, minor):
    up = num.upper()
    base = (MINR if minor else MAJ)[up]
    if minor and up == "VII" and num == "vii":
        base = 11            # 小调 vii° 是导音
    if acc:
        # 带变音记号时一律相对大调音级（♭VI、♭III、♭VII、♯iv）
        base = MAJ[up] + acc.count("♭") * -1 + acc.count("b") * -1 + acc.count("♯") + acc.count("#")
    return (kpc + base) % 12


def root_of(roman, kpc, minor):
    p = textdoc.roman_parts(roman)
    if not p:
        return None
    if p["num"] in ("Ger",):
        return (kpc + 8) % 12
    if p["num"] == "N":
        return (kpc + 1) % 12
    if p["sec"]:                       # 可以多层：V7/V/V = （V/V）的 V
        tpc = root_of(p["sec"], kpc, minor)
        q = textdoc.roman_parts(p["sec"])
        return deg_pc(p["num"], p["acc"], tpc, q["num"].islower())
    return deg_pc(p["num"], p["acc"], kpc, minor)


start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
bad = 0
for b, v in sorted(load_chords().items()):
    if b < start or not v["key"] or v["key"] in ("—", "-"):
        continue
    kpc, kmin = textdoc.key_pc(v["key"])
    for c in v["chords"]:
        if c[1] in ("—", "-"):
            continue
        m = re.match(r"^([A-G][#bx]*)", c[2])
        if not m:
            print(b, "和弦名读不出", c); bad += 1; continue
        r = root_of(c[1], kpc, kmin)
        if r is None or r != textdoc.note_pc(m.group(1)):
            print(textdoc.bar_label(b) if hasattr(textdoc, "bar_label") else b, v["key"], c[1], c[2]); bad += 1
print("不一致", bad)
