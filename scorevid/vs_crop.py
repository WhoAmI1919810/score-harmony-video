# 读谱用乐谱放大：python3 vs_crop.py 起小节 止小节 [倍数=2] [上=0 下=1（系统高度比例）] → 中间文件/重读图/crop.png（同一系统）
# 每小节开头按这一行谱表的谱号标出线和间的音名（不含调号、临时记号——临时记号要自己看），不印任何候选和弦。
import os, sys, csv, json
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, BARS_CSV, FONT_DIR
import textdoc
def _bar(t):
    return textdoc.PART2_BAR - 1 + int(t[3:]) if t.upper().startswith("II-") else int(t.replace("I-", ""))
a, z = _bar(sys.argv[1]), _bar(sys.argv[2])
k = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
f0 = float(sys.argv[4]) if len(sys.argv) > 5 else 0.0; f1 = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
rs = [r for r in csv.DictReader(open(BARS_CSV, encoding="utf-8")) if a <= int(r["bar"]) <= z]
p, s = int(rs[0]["page"]), int(rs[0]["system"]); rs = [r for r in rs if int(r["page"]) == p and int(r["system"]) == s]
sy = json.load(open(os.path.join(MID, "staves.json")))[str(p)][s - 1]
sp = (sy[0][-1] - sy[0][0]) / 4
Y0, Y1 = sy[0][0] - 8 * sp, sy[-1][-1] + 7 * sp
y0, y1 = int(Y0 + (Y1 - Y0) * f0), int(Y0 + (Y1 - Y0) * f1)
x0, x1 = int(rs[0]["x0"]) - 15, int(rs[-1]["x1"]) + 10
im = Image.open(os.path.join(MID, "pages_deskew", f"p{p:03d}.png")).convert("RGB").crop((x0, max(0, y0), x1, y1))
im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
c = Image.new("RGB", (im.width, im.height + 36), "white"); c.paste(im, (0, 36)); d = ImageDraw.Draw(c)
f = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 26)
for r in rs:
    bx = (int(r["x0"]) - x0) * k; d.line([(bx, 36), (bx, c.height)], fill=(110, 110, 240)); d.text((bx + 4, 2), textdoc.short_label(int(r["bar"])), fill=(40, 40, 220), font=f)
# 音高标尺：每小节开头，按这一行谱表在本小节的谱号，标出线和间的音名（不含调号变音）
LET = "CDEFGAB"
def name_at(step):              # step：相对 C4 的自然音级数
    return LET[step % 7] + str(4 + step // 7)
BOTTOM = {"treble": 2, "bass": -10}   # 最下线：高音谱号 E4（C4 起 +2），低音谱号 G2（-10）
notes = json.load(open(os.path.join(MID, "omr", f"p{p:03d}_s{s}.json"))) if os.path.exists(os.path.join(MID, "omr", f"p{p:03d}_s{s}.json")) else []
fr = ImageFont.truetype(os.path.join(FONT_DIR, "SourceHanSansCN-Bold.otf"), 13)
last = {}
for r in rs:
    b = int(r["bar"]); bx = (int(r["x0"]) - x0) * k
    for si, lines in enumerate(sy, start=1):
        cl = [n["clef"] for n in notes if n["bar"] == b and n["staff"] == si]
        clef = max(set(cl), key=cl.count) if cl else last.get(si, "treble" if si < len(sy) else "bass")
        last[si] = clef
        bot = lines[-1]; half = (lines[-1] - lines[0]) / 8
        for st in range(-6, 15):
            yy = (bot - st * half - max(0, y0)) * k + 36
            if 36 < yy < c.height:
                d.text((bx + 3, yy - 8), name_at(BOTTOM[clef] + st), fill=(230, 60, 60) if st % 2 == 0 else (240, 150, 150), font=fr)
os.makedirs(os.path.join(MID, "重读图"), exist_ok=True)
out = os.path.join(MID, "重读图", "crop.png"); c.save(out); print(out, c.size)
