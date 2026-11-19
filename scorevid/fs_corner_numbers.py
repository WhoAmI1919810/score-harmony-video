# 总谱页左上角拼图（裁得更大，适合小节号印得靠下的页）：python3 fs_corner_numbers.py 起页 止页 → 中间文件/核对图/页角_起页.png
import sys, os
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID
S = os.path.join(MID, "核对图") + os.sep; os.makedirs(S, exist_ok=True)
a, z = int(sys.argv[1]), int(sys.argv[2])
W, H = 380, 260
tiles = []
for p in range(a, z + 1):
    im = Image.open(os.path.join(MID, "总谱页", f"f{p:03d}.png")).convert("L")
    c = im.crop((80, 60, 460, 320))
    t = Image.new("L", (W, H + 30), 255); t.paste(c, (0, 30)); ImageDraw.Draw(t).text((5, 5), f"pdf {p}", fill=0)
    t = t.resize((W, H + 30))
    tiles.append(t)
cols = 5
sh = Image.new("L", (cols * (W + 6), ((len(tiles) + cols - 1) // cols) * (H + 36)), 255)
for i, t in enumerate(tiles): sh.paste(t, ((i % cols) * (W + 6), (i // cols) * (H + 36)))
sh.save(S + f"页角_{a}.png"); print(S + f"页角_{a}.png", sh.size)
