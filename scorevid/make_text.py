# -*- coding: utf-8 -*-
"""生成 文字稿.txt：
  · 和弦、调：取自 harm_auto.py 的自动结果（中间文件/harm/auto.json）；
  · 曲式、段落标题与导语、个别小节的说明：取自 数据/分析_人工.txt（人工写，小节号写成 I-46、II-120）；
  · 其余小节的说明：按"组"自动写一句（和声进行 + 终止式 / 持续低音 / 转调）。
人工文件里 [说明] 指定的小节，自动说明让位。文字稿生成后可以直接手改；
注意再次运行本脚本会覆盖 文字稿.txt（先自动备份到 中间文件/文字稿_备份_时间.txt）。
用法：python3 make_text.py"""
import os, sys, re, json, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import MID, DATA, HARMONY_TXT
import textdoc

AUTO = os.path.join(MID, "harm", "auto.json")
HUMAN = os.path.join(DATA, "分析_人工.txt")
PCN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def parse_bar(tok):
    tok = tok.strip()
    m = re.match(r"^(I{1,2})-(\d+)$", tok)
    if m:
        n = int(m.group(2))
        return n if m.group(1) == "I" else textdoc.PART2_BAR + n - 1
    return int(tok)


def parse_range(s):
    """"I-46~I-120" 或 "46-120"（连续编号）"""
    s = s.strip()
    a, b = s.split("~") if "~" in s else s.split("-")
    return parse_bar(a), parse_bar(b)


def load_human():
    form, secs, notes = [], [], {}
    cur = None
    if not os.path.exists(HUMAN):
        return form, secs, notes
    for raw in open(HUMAN, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\[(曲式|段落|说明)\]\s*(.+)$", line.strip())
        if m:
            kind, rest = m.group(1), m.group(2)
            parts = [p.strip() for p in rest.split("|")]
            if kind == "说明":
                notes[parse_bar(parts[0])] = parts[1]
                cur = None
            else:
                a, b = parse_range(parts[0])
                if kind == "曲式":
                    form.append((a, b, parts[1])); cur = None
                else:
                    cur = dict(a=a, b=b, title=parts[1], keydesc=parts[2] if len(parts) > 2 else "", intro="")
                    secs.append(cur)
            continue
        if cur is not None:
            cur["intro"] += line.strip()
    return form, secs, notes


def key_text(k):
    return textdoc.key_display(k)


def simp(r):
    return textdoc.simplify_roman(r)


def describe(bars, auto, key_changed_at_start, prev_key):
    """自动说明只写转调（调号行确定的事实）。终止式要看乐句划分，自动判断常错（句中的 V–I、转位的 I），
    一律不自动写；需要的话在 数据/分析_人工.txt 用 [说明] 人工写。"""
    key = auto[str(bars[0])]["key"]
    if key_changed_at_start and prev_key and key not in ("—", "-"):
        return textdoc.pretty_notes(f"转入 {key_text(key)}。")
    if key_changed_at_start and key in ("—", "-") and prev_key not in ("—", "-"):
        return "调中心不明确。"
    return ""


CHORDS_TXT = os.path.join(DATA, "和弦_人工.txt")


def load_chords():
    """数据/和弦_人工.txt：逐小节人工读谱的调与和弦。
       调 Eb                       之后各小节的调（大写大调，小写小调）
       I-12 | 1 V7 Bb7 | 3 I Eb    小节 | 拍 级数 和弦名 | ...（和弦名可写 Eb/G 表示低音）
       I-13 | =                    和弦同上一小节（延续）"""
    out = {}
    if not os.path.exists(CHORDS_TXT):
        return out
    key = None; prev = None
    for raw in open(CHORDS_TXT, encoding="utf-8"):
        # 注释：行首的 #，或前面有空白、后面跟空格的 #（和弦名里的升号 # 不能当注释）
        line = "" if raw.lstrip().startswith("#") else re.sub(r"\s#\s.*$", "", raw).strip()
        if not line:
            continue
        if line.startswith("调"):
            key = line[1:].strip(); continue
        parts = [x.strip() for x in line.split("|")]
        b = parse_bar(parts[0])
        if len(parts) >= 2 and parts[1] == "=":
            chords = [[1.0, prev[1], prev[2], 1.0]] if prev else []
        else:
            chords = []
            for seg in parts[1:]:
                t = seg.split()
                if len(t) >= 3:
                    chords.append([float(t[0]), t[1], " ".join(t[2:]), 1.0])
                elif len(t) == 2 and t[1] in ("—", "-"):
                    chords.append([float(t[0]), "—", "", 1.0])
        if chords:
            prev = chords[-1]
        out[b] = dict(key=key, chords=chords)
    return out


def main():
    auto = json.load(open(AUTO, encoding="utf-8"))
    for b, v in load_chords().items():          # 人工读谱的小节：调与和弦以人工为准
        if str(b) not in auto:                     # 自动读谱没有的小节（整小节休止等），人工写了就补上
            auto[str(b)] = dict(key=v["key"] or "—", chords=[])
        if str(b) in auto:
            if v["key"]:
                auto[str(b)]["key"] = v["key"]
            auto[str(b)]["chords"] = v["chords"]
            auto[str(b)]["manual"] = True
    bars = sorted(int(b) for b in auto)
    form, secs, notes = load_human()
    if not secs and textdoc.PART2_BAR:
        secs = [dict(a=bars[0], b=textdoc.PART2_BAR - 1, title=textdoc.PART_NAMES[0], keydesc="", intro=""),
                dict(a=textdoc.PART2_BAR, b=bars[-1], title=textdoc.PART_NAMES[1], keydesc="", intro="")]
    elif not secs:
        secs = [dict(a=bars[0], b=bars[-1], title="全曲", keydesc="", intro="")]
    sec_start = {s["a"]: s for s in secs}
    # 段落开头的小节用段落标题里写明的调（"E♭ 大调"、"e♭ 小调"）；"调性游移"等不改
    for s_ in secs:
        m = re.match(r"^([A-Ga-g])([♭♯b#]?)\s*(大调|小调)$", s_["keydesc"].strip())
        if m and str(s_["a"]) in auto and not auto[str(s_["a"])].get("manual"):
            L = m.group(1).upper() if m.group(3) == "大调" else m.group(1).lower()
            k_new = L + {"♭": "b", "♯": "#"}.get(m.group(2), m.group(2))
            a_ = auto[str(s_["a"])]
            if a_["key"] != k_new:
                a_["key"] = k_new
                # 级数按新调重算
                import harm_auto as harm8
                kpc, kmin = textdoc.key_pc(k_new)
                for c in a_["chords"]:
                    mm = re.match(r"^([A-G][#b]?)(.*)$", c[2])
                    if not mm:
                        continue
                    root = textdoc.note_pc(mm.group(1)); q = mm.group(2)
                    if root is not None and q in harm8.QUAL:
                        c[1], c[2] = harm8.roman_for(root, q, None, kpc, kmin)
    # 分组：段落开头、转调处、终止之后；每组最多 6 小节
    groups = []
    cur = []
    prev_key = None
    for n in bars:
        k = auto[str(n)]["key"]
        brk = (n in sec_start) or (prev_key is not None and k != prev_key) or n in notes or len(cur) >= 12
        if cur and brk:
            groups.append(cur); cur = []
        cur.append(n)
        prev_key = k
        # 终止：这一小节最后两个和弦是 V→I
        cs = [simp(c[1]) for c in auto[str(n)]["chords"]]
        if len(cs) >= 2 and cs[-2].startswith("V") and "/" not in cs[-2] and cs[-1] in ("I", "i") and len(cur) >= 2:
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    text_at = {}
    prev_key = None
    for g in groups:
        k = auto[str(g[0])]["key"]
        if g[0] in notes:
            text_at[g[0]] = notes[g[0]]
        else:
            text_at[g[0]] = describe(g, auto, prev_key is not None and k != prev_key, prev_key)
        prev_key = auto[str(g[-1])]["key"]
    if os.path.exists(HARMONY_TXT):
        shutil.copy(HARMONY_TXT, os.path.join(MID, f"文字稿_备份_{time.strftime('%m%d_%H%M%S')}.txt"))
    L = []
    from common import TITLE_CARD
    L.append(f"# {TITLE_CARD} 逐小节和声分析 · 文字稿")
    L.append("#")
    L.append("# 小节号：文件里全曲连续编号（第一部分 1–%d，第二部分从 %d 起），视频里显示为两部分各自的小节号。"
             % (textdoc.PART2_BAR - 1, textdoc.PART2_BAR))
    L.append("# 格式：[段落] 起-止 | 标题 | 调性概括（下一行起为导语）；[小节] N；字段 标记/调/和弦/说明。")
    L.append("#   和弦：\"拍位 级数 和弦名\"，用 | 分开；拍位按每小节 4 个等分位置写（1 = 小节开头，3 = 小节一半）。")
    L.append("#   说明里的级数写在花括号里：{V7}、{V7/V}。没有说明的小节并入前一组显示。")
    L.append("# 和弦与调以 数据/和弦_人工.txt（人工读谱）为准；没写的小节才用自动候选（harm_auto.py，只是草稿）。说明、段落导语为人工所写，自动说明只写转调。")
    L.append("")
    for a, b, lab in (form or []):
        L.append(f"[曲式] {a}-{b} | {lab}")
    L.append("")
    key = None
    for n in bars:
        if n in sec_start:
            s = sec_start[n]
            L.append("")
            L.append(f"[段落] {s['a']}-{s['b']} | {s['title']} | {s['keydesc']}")
            if s["intro"]:
                L.append(s["intro"])
            L.append("")
        a = auto[str(n)]
        L.append(f"[小节] {n}")
        if a["key"] != key:
            L.append(f"调：{a['key']}")
            key = a["key"]
        if a["chords"]:
            L.append("和弦：" + " | ".join(f"{c[0]:g} {c[1]} {c[2]}" for c in a["chords"]))
        if text_at.get(n):
            L.append("说明：" + text_at[n])
        L.append("")
    open(HARMONY_TXT, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("写出", HARMONY_TXT, len(bars), "小节，", len(groups), "组")


if __name__ == "__main__":
    main()
