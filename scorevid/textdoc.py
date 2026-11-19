# -*- coding: utf-8 -*-
"""读取 文字稿.txt（逐小节和声分析）。格式见文字稿开头的说明。

parse(path) -> Doc
  doc.sections: [Section(start, end, title, keydesc, intro)]
  doc.bars: {bar: Bar}；Bar 有 key（已继承）、chords [Chord(beat, roman, name, pcs, bass)]、
            melody [(beat, midi)]、fields {"和声":..., "声部":..., "视角":..., "标记":...}
"""
import re
from dataclasses import dataclass, field

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
FIELD_NAMES = ["标记", "调", "和弦", "旋律", "说明", "缩谱", "和声", "声部", "视角"]
TEXT_FIELDS = ["说明"]
# 下面几项从 project.json 读（common.cfg）；单独拿 textdoc 用时退回默认值
try:
    from common import cfg as _cfg, DATA as _DATA, PART_NAMES as _PN
except Exception:                     # 没有工程目录时（例如单独测试）用默认值
    _cfg = lambda k, d=None: d; _DATA = None; _PN = ["第一部分", "第二部分"]
BEATS_PER_BAR = int(_cfg("beats_per_bar", 4))   # 名义拍数：拍号多变时统一按每小节 4 个等分位置写（1、2、3、4，可写 2.5）
PICKUP_BAR = _cfg("pickup_bar", None)           # 弱起小节号（没有就 null）
FIRST_BAR = int(_cfg("first_bar", 1))
HOME_KEY = _cfg("home_key", "C")
PART_NAMES = _PN
# 两部分的作品：小节在文件里连续编号（第一部分 1–PART2_BAR-1，第二部分从 PART2_BAR 起），显示时各自从 1 数。
# 单乐章作品没有 数据/两部分.txt，PART2_BAR = None，显示"第 n 小节"。
PART2_BAR = None
LAST_BAR = None
try:
    import os as _os
    _p = _os.path.join(_DATA, "两部分.txt")
    for _l in open(_p, encoding="utf-8"):
        _k, _v = _l.split("#")[0].split("=") if "=" in _l else (None, None)
        if _k and _k.strip() == "PART2_BAR":
            PART2_BAR = int(_v)
        if _k and _k.strip() == "LAST_BAR":
            LAST_BAR = int(_v)
except Exception:
    pass


def part_bar(n):
    """连续编号 → (部分 1/2, 该部分里的小节号)"""
    if PART2_BAR and n >= PART2_BAR:
        return 2, n - PART2_BAR + 1
    return 1, n


def bar_label(a, b=None):
    pa, na = part_bar(a)
    if not PART2_BAR:                                   # 单乐章
        if b is None or b == a:
            return f"第 {na} 小节"
        return f"第 {na}–{part_bar(b)[1]} 小节"
    pn = PART_NAMES[pa - 1]
    if b is None or b == a:
        return f"{pn} 第 {na} 小节"
    pb, nb = part_bar(b)
    if pb == pa:
        return f"{pn} 第 {na}–{nb} 小节"
    return f"{pn} 第 {na} 小节 – {PART_NAMES[pb - 1]} 第 {nb} 小节"


def short_label(n):
    """核对图用的短写：两部分作品 I-12 / II-3，单乐章 12"""
    if not PART2_BAR:
        return str(n)
    p, k = part_bar(n)
    return ("I-" if p == 1 else "II-") + str(k)


def bar_range_short(a, b):
    """标题里用的短写：第 12–40 小节"""
    pa, na = part_bar(a); pb, nb = part_bar(b)
    return f"第 {na}–{nb} 小节" if pa == pb else f"第 {na} – {PART_NAMES[1]} {nb} 小节"


@dataclass
class Chord:
    beat: float
    roman: str
    name: str
    pcs: list
    bass: int
    func: str = ""          # 手工指定的功能标记（和弦行里写 功:T / 功:S / 功:D）


@dataclass
class Bar:
    n: int
    key: str = ""
    key_changed: bool = False
    chords: list = field(default_factory=list)
    melody: list = field(default_factory=list)
    fields: dict = field(default_factory=dict)


@dataclass
class Section:
    start: int
    end: int
    title: str
    keydesc: str
    intro: str = ""


@dataclass
class Doc:
    sections: list
    bars: dict
    reductions: list = field(default_factory=list)     # [(起, 止, 文件名)]
    form: list = field(default_factory=list)           # [(起, 止, 标签)] 大的曲式段落


def acc_value(s):
    v = 0
    for ch in s:
        v += {"#": 1, "♯": 1, "b": -1, "♭": -1, "x": 2}.get(ch, 0)
    return v


def note_pc(name):
    m = re.match(r"^([A-G])([#♯b♭x]*)$", name.strip())
    if not m:
        return None
    return (PC[m.group(1)] + acc_value(m.group(2))) % 12


def note_midi(s):
    m = re.match(r"^([A-G])([#♯b♭x]*)(-?\d)$", s.strip())
    if not m:
        return None
    return 12 * (int(m.group(3)) + 1) + PC[m.group(1)] + acc_value(m.group(2))


def chord_pcs(name):
    """和弦名 → (音级集合列表, 低音音级)。认不出的部分尽量忽略。"""
    name = name.strip().replace("♯", "#").replace("♭", "b").replace("（", "(").replace("）", ")")
    if not name or name in ("—", "-", "N.C.", "NC"):
        return [], None
    # 方括号：单音或空五度等非和弦，如 [F]、[F#-C#]
    if name.startswith("[") and name.endswith("]"):
        ns = [note_pc(x) for x in re.split(r"[-–]", name[1:-1]) if note_pc(x) is not None]
        return (sorted(set(ns)), ns[0]) if ns else ([], None)
    # 直接列音：Bb-D-G#（第一个音是低音）
    if re.match(r"^[A-G][#b]*([-–][A-G][#b]*)+$", name):
        ns = [note_pc(x) for x in re.split(r"[-–]", name)]
        return sorted(set(ns)), ns[0]
    main, _, bass = name.partition("/")
    m = re.match(r"^([A-G])([#b]*)(.*)$", main)
    if not m:
        return [], None
    root = (PC[m.group(1)] + acc_value(m.group(2))) % 12
    q = m.group(3).replace("(", "").replace(")", "")
    third, fifth, seventh = 4, 7, None
    ext = []
    if q.startswith(("maj7", "M7", "Δ")):
        seventh = 11; q = q[4:] if q.startswith("maj7") else q[2:] if q.startswith("M7") else q[1:]
    elif q.startswith(("m7b5", "ø")):
        third, fifth, seventh = 3, 6, 10; q = q[4:] if q.startswith("m7b5") else q[1:].lstrip("7")
    elif q.startswith(("dim7", "o7", "°7")):
        third, fifth, seventh = 3, 6, 9; q = q[4:] if q.startswith("dim7") else q[2:]
    elif q.startswith(("dim", "o", "°")):
        third, fifth = 3, 6; q = q[3:] if q.startswith("dim") else q[1:]
    elif q.startswith(("aug", "+")):
        fifth = 8; q = q[3:] if q.startswith("aug") else q[1:]
    elif q.startswith("m") and not q.startswith("maj"):
        third = 3; q = q[1:]
        if q.startswith("maj7"):
            seventh = 11; q = q[4:]
    # 余下：7 9 11 13 6 sus4 sus2 add9 b9 #11 等
    if q.startswith("7"):
        seventh = 10 if seventh is None else seventh; q = q[1:]
    elif q.startswith("9"):
        seventh = 10 if seventh is None else seventh; ext.append(2); q = q[1:]
    elif q.startswith("11"):
        seventh = 10 if seventh is None else seventh; ext += [2, 5]; q = q[2:]
    elif q.startswith("13"):
        seventh = 10 if seventh is None else seventh; ext += [2, 9]; q = q[2:]
    elif q.startswith("6"):
        ext.append(9); q = q[1:]
    for tok in re.findall(r"sus4|sus2|add\d+|[#b]\d+|\d+", q):
        if tok == "sus4":
            third = 5
        elif tok == "sus2":
            third = 2
        elif tok.startswith("add"):
            ext.append({2: 2, 9: 2, 4: 5, 11: 5, 6: 9, 13: 9}.get(int(tok[3:]), 0))
        elif tok[0] in "#b":
            n = int(tok[1:]); base = {5: 7, 9: 2, 11: 5, 13: 9}.get(n)
            if base is not None:
                if n == 5:
                    fifth = base + (1 if tok[0] == "#" else -1)
                else:
                    ext.append(base + (1 if tok[0] == "#" else -1))
        else:
            n = int(tok); base = {9: 2, 11: 5, 13: 9, 7: 10}.get(n)
            if base is not None:
                ext.append(base)
    ivs = [0, third, fifth] + ([seventh] if seventh is not None else []) + ext
    pcs = sorted(set((root + i) % 12 for i in ivs))
    b = note_pc(bass) if bass else root
    if b is None:
        b = root
    if b not in pcs:
        pcs.append(b)
    return pcs, b


def parse_chords(s):
    out = []
    for seg in s.split("|"):
        toks = seg.split()
        if not toks:
            continue
        try:
            beat = float(toks[0])
        except ValueError:
            continue
        func = ""
        rest = []
        for t in toks[2:]:
            if t.startswith("功:") or t.startswith("功："):
                func = t[2:]
            else:
                rest.append(t)
        roman = toks[1] if len(toks) > 1 else "—"
        name = " ".join(rest)
        pcs, bass = chord_pcs(name)
        out.append(Chord(beat, roman, name, pcs, bass, func))
    out.sort(key=lambda c: c.beat)
    return out


def parse_melody(s):
    out = []
    for seg in s.split("|"):
        toks = seg.split()
        if len(toks) >= 2:
            try:
                beat = float(toks[0])
            except ValueError:
                continue
            m = note_midi(toks[1])
            if m is not None:
                out.append((beat, m))
    return out


def parse(path):
    sections, bars, reds, form = [], {}, [], []
    cur_bar = None; cur_sec = None; last_field = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("[段落]"):
                body = s[len("[段落]"):].strip()
                parts = [p.strip() for p in body.split("|")]
                rng = parts[0]
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", rng)
                a, b = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
                cur_sec = Section(a, b, parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "")
                sections.append(cur_sec)
                cur_bar = None; last_field = None
                continue
            if s.startswith("[曲式]"):
                body = s[len("[曲式]"):].strip()
                rng, _, lab = body.partition("|")
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", rng.strip())
                if m:
                    form.append((int(m.group(1)), int(m.group(2)), lab.strip()))
                continue
            if s.startswith("[缩谱]"):
                body = s[len("[缩谱]"):].strip()
                rng, _, fn = body.partition("|")
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", rng.strip())
                if m and fn.strip():
                    reds.append((int(m.group(1)), int(m.group(2)), fn.strip()))
                cur_bar = None; last_field = None
                continue
            if s.startswith("[小节]"):
                n = int(re.findall(r"-?\d+", s)[0])
                cur_bar = Bar(n)
                bars[n] = cur_bar
                last_field = None
                continue
            m = re.match(r"^(" + "|".join(FIELD_NAMES) + r")\s*[：:]\s*(.*)$", s)
            if cur_bar is not None and m:
                last_field = m.group(1)
                cur_bar.fields[last_field] = m.group(2).strip()
                continue
            if cur_bar is not None and last_field:
                cur_bar.fields[last_field] += s
                continue
            if cur_sec is not None and cur_bar is None:
                cur_sec.intro = (cur_sec.intro + s) if cur_sec.intro else s
    # 字段解析、调的继承
    key = HOME_KEY
    for n in sorted(bars):
        b = bars[n]
        k = b.fields.get("调", "").strip()
        if k:
            k = k.split()[0]
            b.key_changed = (k != key)
            key = k
        b.key = key
        b.chords = parse_chords(b.fields.get("和弦", ""))
        b.melody = parse_melody(b.fields.get("旋律", ""))
    return Doc(sections, bars, reds, form)


def bar_beats(n):
    """小节的拍数与起始拍（第 0 小节是弱起，只有第 4 拍）。"""
    if PICKUP_BAR is not None and n == PICKUP_BAR:
        return 1, 4.0
    return BEATS_PER_BAR, 1.0


# ---------- 显示用 ----------
KEY_NAME_ZH = {}


def key_display(k):
    """'D' → 'D 大调'，'f#' → '升 f 小调' 写法改为国际通行 'f♯ 小调'。"""
    if not k:
        return ""
    if k in ("—", "-"):
        return "调性不定"
    minor = k[0].islower()
    letter = k[0].upper() if not minor else k[0].lower()
    acc = k[1:].replace("#", "♯").replace("b", "♭")
    return f"{letter}{acc} {'小调' if minor else '大调'}"


def key_pc(k):
    if not k:
        return 3, False
    minor = k[0].islower()
    pc = note_pc(k[0].upper() + k[1:].replace("♯", "#").replace("♭", "b"))
    return (pc if pc is not None else 2), minor


def pretty_notes(text):
    """把正文里的 F#、Bb、C#4 等换成 ♯ ♭；直引号换成中文弯引号。"""
    parts = text.split('"')
    if len(parts) > 1:
        text = "".join(p + ("“" if i % 2 == 0 else "”") if i < len(parts) - 1 else p for i, p in enumerate(parts))
    text = re.sub(r"(?<![A-Za-z])([A-G])#(?![A-Za-z#])", r"\1♯", text)
    text = re.sub(r"(?<![A-Za-z])([A-G])##", r"\1𝄪", text)
    text = re.sub(r"(?<![A-Za-z])([A-G])b(?![A-Za-z])", r"\1♭", text)
    text = re.sub(r"(?<![A-Za-z])([A-G])bb(?![A-Za-z])", r"\1𝄫", text)
    return text


ROMAN_RE = re.compile(r"^(?P<acc>[b#♭♯]*)(?P<num>Ger|Fr|It|N|Cad|VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)"
                      r"(?P<qual>[o°øh+]?)(?P<fig>[0-9]*)(?P<rest>[^/]*)(?:/(?P<sec>.+))?$")


def roman_parts(r):
    """'V65/V' → dict(acc='', num='V', qual='', figs=['6','5'], rest='', sec='V')"""
    r = r.strip()
    m = ROMAN_RE.match(r)
    if not m:
        return None
    figs = m.group("fig")
    if figs in ("65", "43", "42", "64", "53", "63", "86", "75", "97", "98"):
        figs = list(figs)
    elif figs:
        figs = [figs]
    else:
        figs = []
    qual = {"h": "ø", "o": "°"}.get(m.group("qual"), m.group("qual"))
    acc = m.group("acc").replace("b", "♭").replace("#", "♯")
    return dict(acc=acc, num=m.group("num"), qual=qual, figs=figs, rest=m.group("rest"), sec=m.group("sec"))


# ---------- 显示用的简化：转位与功能 ----------
SHOW_INVERSIONS = False      # True = 照文字稿显示全部转位数字；False = 只保留四六和弦


def simplify_roman(r):
    """V65 → V7，I6 → I，viio42 → viio7；四六和弦（I64、IV64）保留。"""
    if SHOW_INVERSIONS:
        return r
    p = roman_parts(r)
    if not p:
        return r

    def one(pp):
        figs = pp["figs"]
        if pp["num"] in ("Ger", "Fr", "It", "N"):
            figs = figs                     # 增六和弦、那不勒斯六和弦的 6 是名称的一部分
        elif figs == ["6", "4"] and pp["num"] not in ("I", "i", "IV", "iv", "V", "v"):
            figs = []                       # 只保留主、下属、属和弦的四六和弦（终止四六、持续音上的四六）
        elif figs in (["6", "5"], ["4", "3"], ["4", "2"], ["2"]):
            figs = ["7"]
        elif figs == ["6"] and pp["num"] not in ("Ger", "Fr", "It", "N"):
            figs = []
        q = {"°": "o"}.get(pp["qual"], pp["qual"])
        acc = pp["acc"].replace("♭", "b").replace("♯", "#")
        return acc + pp["num"] + q + "".join(figs) + pp["rest"]

    out = one(p)
    if p["sec"]:                       # 可以多层：V7/V/V
        out += "/" + simplify_roman(p["sec"])
    return out


def simplify_name(name):
    """A7/C# → A7（低音是和弦音时去掉转位）；Eb/D 这类低音不在和弦里的保留。"""
    if SHOW_INVERSIONS or not name or "/" not in name or name.startswith("["):
        return name
    main, _, bass = name.partition("/")
    pcs, root = chord_pcs(main)
    b = note_pc(bass.replace("♯", "#").replace("♭", "b"))
    return main if (b is not None and b in pcs) else name


def chord_function(roman, override=None):
    """功能标记：T / S / D，副属和弦 DD（V 的属）或 (D)。"""
    if override:
        return override
    p = roman_parts(roman)
    if not p or roman.strip() in ("—", "-"):
        return ""
    if p["sec"]:
        if p["num"] not in ("V", "vii", "VII"):
            return "S"                      # 如 ii7/IV：下属方向的和弦
        q = roman_parts(p["sec"])
        if q and q["num"] in ("V", "v") and not q["acc"] and not q["sec"]:
            return "DD"
        return "(D)"
    num, acc, figs = p["num"], p["acc"], p["figs"]
    if num in ("I", "i") and not acc:
        return "D" if figs == ["6", "4"] else "T"
    if num in ("iii", "III", "vi", "VI") and not acc:
        return "T"
    if num in ("ii", "II", "IV", "iv", "N", "Ger", "Fr", "It") or (num == "II" and acc):
        return "S"
    if acc and num in ("II", "VI", "VII", "III"):
        return "T" if num == "III" else "S"
    if num in ("V", "v", "vii", "VII"):
        return "D"
    return ""


def simplify_text(text):
    """正文里 {…} 级数同样简化，并把简化后相邻重复的级数合并（{V7}–{V7} → {V7}）。"""
    if SHOW_INVERSIONS:
        return text
    t = re.sub(r"\{([^}]+)\}", lambda m: "{" + simplify_roman(m.group(1)) + "}", text)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"\{([^}]+)\}–\{\1\}", r"{\1}", t)
    return t
