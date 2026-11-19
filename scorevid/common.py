# -*- coding: utf-8 -*-
"""公共路径与参数：全部从"作品工程目录"里的 project.json 读取，所有脚本都从这里取。

作品工程目录怎么找（按顺序）：
  1. 环境变量 SV_PROJECT
  2. 当前目录里有 project.json
  3. 本脚本上一级目录里有 project.json（本地渲染包就是这种布局：包根目录/project.json + 包根目录/脚本/）
找不到就报错。project.json 的字段见 docs/02_工程配置.md，示例见 project_template/project.json。
"""
import os, json, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.dirname(_HERE)                     # score-harmony-video/（在渲染包里是包根目录）


def _find_project():
    p = os.environ.get("SV_PROJECT")
    if p:
        return os.path.abspath(p)
    if os.path.exists(os.path.join(os.getcwd(), "project.json")):
        return os.getcwd()
    if os.path.exists(os.path.join(TOOLKIT, "project.json")):
        return TOOLKIT
    sys.exit("找不到作品工程目录：请 export SV_PROJECT=工程目录，或在工程目录里运行（目录里要有 project.json）")


PROJ = _find_project()
CFG = json.load(open(os.path.join(PROJ, "project.json"), encoding="utf-8"))


def _path(v):
    if not v:
        return None
    return v if os.path.isabs(v) else os.path.normpath(os.path.join(PROJ, v))


def cfg(key, default=None):
    """读 project.json，支持 "a.b" 取嵌套字段"""
    cur = CFG
    for k in key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


TASK = os.path.dirname(PROJ)
WORK = TASK
DATA = os.path.join(PROJ, "数据")
MID = os.path.join(PROJ, "中间文件")
OUT = os.path.join(PROJ, "输出")
PAGES_DIR = os.path.join(MID, "pages")
for d in (DATA, MID, OUT, PAGES_DIR):
    os.makedirs(d, exist_ok=True)

# ---- 读谱用的乐谱（钢琴缩谱 / 人声缩谱；读谱、自动和声、对齐都用它）----
PDF = _path(cfg("reading_score.pdf"))
FIRST_PAGE = int(cfg("reading_score.first_page", 1))
LAST_PAGE = int(cfg("reading_score.last_page", 1))
MP3 = _path(cfg("audio.source"))

BARS_CSV = os.path.join(DATA, "小节位置.csv")
TIMES_CSV = os.path.join(DATA, "小节时间.csv")
HARMONY_TXT = os.path.join(PROJ, "文字稿.txt")

# ---- 字体：工程目录/字体 → 工具包/字体 → project.json 里的 fonts_dir ----
def _font_root():
    for c in (os.path.join(PROJ, "字体"), os.path.join(TOOLKIT, "字体"), _path(cfg("fonts_dir"))):
        if c and os.path.isdir(c):
            return c
    return os.path.join(PROJ, "字体")


_FR = _font_root()
FONT_DIR = os.path.join(_FR, "source_han")
FREEFONT_DIR = os.path.join(_FR, "freefont")

# ---- 音频（所有时间都按剪辑后的 中间文件/audio/track.wav 计）----
AUDIO_TRIM = cfg("audio.trim")                       # [起, 止]（原文件秒数），null = 整个文件
AUDIO_CUTS = cfg("audio.cuts", []) or []             # [[a, b], ...]（原文件秒数）：剪掉的空白，如两部分之间的长静音
AUDIO_START = 0.0
AUDIO_END = float(cfg("audio.end", 0) or 0)          # 剪辑后音频的总长（s3_audio.py 跑完会打印）
MUSIC_START = float(cfg("audio.music_start", 0.0))
MUSIC_END = float(cfg("audio.music_end", AUDIO_END))  # 末和弦结束
PART2_START = cfg("audio.part2_start")               # 第二部分第一个音（没有第二部分就 null）
PART2_START = float(PART2_START) if PART2_START is not None else None
VIDEO_TAIL = float(cfg("video.tail", 5.0))
AUDIO_WAV = os.path.join(MID, "audio", "track.wav")
AUDIO_FLAC = os.path.join(MID, "audio", "track.flac")

# ---- 显示用的乐谱：full = 总谱（s2_bars_fullscore.py），vocal = 读谱用的那份 ----
SCORE = os.environ.get("SV_SCORE", cfg("display_score", "vocal"))
FULL_PDF = _path(cfg("full_score.pdf"))
FULL_FIRST = int(cfg("full_score.first_page", 1))
FULL_LAST = int(cfg("full_score.last_page", 1))
FULL_UPSCALE = int(cfg("full_score.upscale", 2))
if SCORE == "full":
    SCORE_BARS_CSV = os.path.join(DATA, "总谱小节位置.csv")
    SCORE_PAGES = os.path.join(MID, "总谱_deskew")
    SCORE_FIRST, SCORE_LAST = FULL_FIRST, FULL_LAST
    SCORE_TITLE = cfg("full_score.credit", "")
else:
    SCORE_BARS_CSV = BARS_CSV
    SCORE_PAGES = os.path.join(MID, "pages_deskew")
    SCORE_FIRST, SCORE_LAST = FIRST_PAGE, LAST_PAGE
    SCORE_TITLE = cfg("reading_score.credit", "")

# ---- 文字 ----
TITLE = cfg("text.title", "")                        # 画面左上角，如 "马勒 · 第八交响曲"
TITLE_CARD = cfg("text.title_card", TITLE)           # 片头大标题
SUBTITLE = cfg("text.subtitle", "")
PERFORMER = cfg("text.performer", "")
SHORT_NAME = cfg("short_name", "作品")              # 文件名用，如 "马勒8"
OUTPUT_NAME = cfg("text.output_name", SHORT_NAME + "_和声分析")
PART_NAMES = cfg("text.part_names", ["第一部分", "第二部分"])
OMR_TEMPLATES = _path(cfg("omr_templates")) or os.path.join(TOOLKIT, "assets", "omr_templates.npz")

# ---- 设备相关（按机器改，不要写死在脚本里）----
# 弱服务器（我们的真实环境：8 核无显卡、和别的任务共用）：后台任务降优先级、ffmpeg 单线程、渲染最多 2 进程。
# 环境变量覆盖：SV_NICE=0 关掉降优先级；SV_FF_THREADS=4；SV_JOBS=4。
import shutil as _sh
_nice = int(os.environ.get("SV_NICE", "15"))
NICE_CMD = ["nice", "-n", str(_nice)] if _nice and _sh.which("nice") else []
FF_THREADS = os.environ.get("SV_FF_THREADS", os.environ.get("FF_THREADS", "1"))
DEFAULT_JOBS = int(os.environ.get("SV_JOBS", "2"))
