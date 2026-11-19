# -*- coding: utf-8 -*-
""""请用户标音"网页的素材：读 数据/待复核.txt，每条截出缩谱（和总谱）对应小节的图，写 中间文件/校对音站/
  index.html   页面（模板 web/标音模板.html，{{作品名}} 换成 project.json 的 short_name）
  data.json    条目：问题、小节框、现有和弦、读谱程序认出的音（可选显示）
  img/         截图（缩谱 vNNN_k.png、总谱 fNNN_k.png）
用法：python3 make_doubt_site.py
问题清单 数据/待复核.txt：每行 起小节~止小节 | 具体问题（写清楚看哪个声部、哪个记号，原样显示给用户）。
现有和弦取 数据/和弦_人工.txt，再用 数据/和弦_*.txt 里更新的稿子覆盖（按文件名排序，后读的覆盖先读的）。
用户导出的 标音结果.json 用 import_doubt.py 读。"""
import os, sys, csv, json, re, shutil
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, BARS_CSV, FULL_UPSCALE, SHORT_NAME
import glob
import textdoc
import make_text as mt

OUT = os.path.join(MID, "校对音站")
IMG = os.path.join(OUT, "img")
VS_W = 3000          # 缩谱截图不缩小（用户要看清音），网页里可切"适应宽度"
FS_W = 2400


def bar_of(tok):
    tok = tok.strip()
    return textdoc.PART2_BAR - 1 + int(tok[3:]) if tok.upper().startswith("II-") else int(tok.replace("I-", ""))


def chords_map():
    out = {}
    for p in [os.path.join(DATA, "和弦_人工.txt")] + sorted(f for f in glob.glob(os.path.join(DATA, "和弦_*.txt")) if not f.endswith("和弦_人工.txt")):
        if os.path.exists(p):
            mt.CHORDS_TXT = p
            out.update(mt.load_chords())
    return out


def quant(im):
    """灰度 4 级（控制体积），黑白扫描几乎看不出差别"""
    return im.convert("L").point(lambda v: 0 if v < 64 else 96 if v < 140 else 190 if v < 215 else 255).convert("P", palette=Image.ADAPTIVE, colors=4)


def crops(rows, pages_dir, staves, dw, maxw, prefix, idx, omr=None):
    """按 页/系统 分组截图。rows：这一条涉及的小节（小节位置.csv 的行）。dw：坐标 ÷ dw = 图上像素"""
    groups = {}
    for r in rows:
        groups.setdefault((int(r["page"]), int(r["system"])), []).append(r)
    out = []
    for k, ((p, s), rs) in enumerate(sorted(groups.items())):
        im = Image.open(os.path.join(pages_dir, f"p{p:03d}.png")).convert("L")
        x0 = min(int(r["x0"]) for r in rs) / dw; x1 = max(int(r["x1"]) for r in rs) / dw
        y0 = min(int(r["y0"]) for r in rs) / dw; y1 = max(int(r["y1"]) for r in rs) / dw
        if staves and str(p) in staves:
            sy = staves[str(p)][s - 1]; sp = (sy[0][-1] - sy[0][0]) / 4
            y0 = min(y0, sy[0][0] - 8 * sp); y1 = max(y1, sy[-1][-1] + 5.5 * sp)
        pad = 60 / dw * 2
        X0, X1 = max(0, x0 - 140 / dw * 2), min(im.width, x1 + pad)
        Y0, Y1 = max(0, y0 - pad * 0.5), min(im.height, y1 + pad * 0.3)
        c = im.crop((int(X0), int(Y0), int(X1), int(Y1)))
        f = min(1.0, maxw / c.width)
        if f < 1:
            c = c.resize((int(c.width * f), int(c.height * f)), Image.LANCZOS)
        fn = f"{prefix}{idx:03d}_{k}.png"
        quant(c).save(os.path.join(IMG, fn), optimize=True)
        boxes = [dict(bar=int(r["bar"]), lab=textdoc.short_label(int(r["bar"])),
                      x0=round((int(r["x0"]) / dw - X0) * f, 1), x1=round((int(r["x1"]) / dw - X0) * f, 1),
                      y0=round((int(r["y0"]) / dw - Y0) * f, 1), y1=round((int(r["y1"]) / dw - Y0) * f, 1)) for r in rs]
        notes = []
        if omr is not None:
            fn_o = os.path.join(MID, "omr", f"p{p:03d}_s{s}.json")
            bars = {int(r["bar"]) for r in rs}
            for n in (json.load(open(fn_o)) if os.path.exists(fn_o) else []):
                if n["bar"] in bars:
                    notes.append(dict(x=round((n["x"] - X0) * f, 1), y=round((n["y"] - Y0) * f, 1),
                                      n=(n.get("name") or "").replace("#", "♯").replace("b", "♭")))
        out.append(dict(src="img/" + fn, w=c.width, h=c.height, page=p, system=s,
                        ox=round(X0 * dw, 1), oy=round(Y0 * dw, 1), scale=round(f / dw, 6), boxes=boxes, notes=notes))
    return out


def main():
    os.makedirs(IMG, exist_ok=True)
    for fn in os.listdir(IMG):
        os.remove(os.path.join(IMG, fn))
    vs_rows = {int(r["bar"]): r for r in csv.DictReader(open(BARS_CSV, encoding="utf-8"))}
    fs_csv = os.path.join(DATA, "总谱小节位置.csv")
    fs_rows = {int(r["bar"]): r for r in csv.DictReader(open(fs_csv, encoding="utf-8"))} if os.path.exists(fs_csv) else {}
    staves = json.load(open(os.path.join(MID, "staves.json")))
    ch = chords_map()
    items = []
    for line in open(os.path.join(DATA, "待复核.txt"), encoding="utf-8"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rng, _, q = line.partition("|")
        a, _, z = rng.partition("~")
        a, z = bar_of(a), bar_of(z or a)
        i = len(items) + 1
        bars = list(range(a, z + 1))
        cur = []
        for b in bars:
            v = ch.get(b)
            cur.append(dict(bar=b, lab=textdoc.short_label(b), key=(v or {}).get("key") or "",
                            chords=" | ".join(f"{c[0]:g} {c[1]} {c[2]}".strip() for c in (v or {}).get("chords", [])) or "（没写）"))
        item = dict(id=i, a=a, z=z, title=textdoc.short_label(a) + ("" if a == z else "～" + textdoc.short_label(z)),
                    q=q.strip(), cur=cur,
                    vs=crops([vs_rows[b] for b in bars if b in vs_rows], os.path.join(MID, "pages_deskew"), staves, 1.0, VS_W, "v", i, omr=True),
                    fs=crops([fs_rows[b] for b in bars if b in fs_rows], os.path.join(MID, "总谱_deskew"), None, float(FULL_UPSCALE), FS_W, "f", i) if fs_rows else [])
        items.append(item)
        print(i, item["title"], len(item["vs"]), "张缩谱", len(item["fs"]), "张总谱", flush=True)
    json.dump(dict(items=items), open(os.path.join(OUT, "data.json"), "w", encoding="utf-8"), ensure_ascii=False)
    tpl = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "标音模板.html"), encoding="utf-8").read()
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(tpl.replace("{{作品名}}", SHORT_NAME))
    tot = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print("写出", OUT, len(items), "条，", f"{tot / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
