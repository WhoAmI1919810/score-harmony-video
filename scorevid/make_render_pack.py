# -*- coding: utf-8 -*-
"""打包"本地渲染包"：输出/<short_name>_本地渲染包.zip
包里是渲染需要的全部东西：脚本、project.json、文字稿、数据（小节位置、小节时间）、显示用的谱页、剪辑后的录音、字体。
用户在自己电脑上解压后双击 渲染.bat（Windows）或运行 bash 渲染.sh。服务器弱时成片交给用户本地渲染。
用法：python3 make_render_pack.py"""
import os, sys, zipfile, glob, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (NICE_CMD, FF_THREADS, PROJ, MID, DATA, OUT, CFG, SHORT_NAME, OUTPUT_NAME, TITLE_CARD, SCORE, SCORE_PAGES, SCORE_BARS_CSV,
                    AUDIO_WAV, AUDIO_FLAC, FONT_DIR, FREEFONT_DIR)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = f"{SHORT_NAME}_本地渲染包"
SCRIPTS = ["common.py", "textdoc.py", "s5_render.py", "reduction.py", "import_times_only.py"]
VIDEO = f"{OUTPUT_NAME}_1080p.mp4"

BAT = rf"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo {TITLE_CARD} · 和声分析视频 · 本地渲染
echo.
where python >nul 2>nul || (echo 没找到 Python。请先安装 Python 3.10 以上（安装时勾选 Add to PATH）。& pause & exit /b 1)
if not exist ".venv_ok" (
  echo 第一次运行：安装依赖库……
  python -m pip install -r 脚本\requirements.txt || (echo 安装依赖失败 & pause & exit /b 1)
  echo ok> .venv_ok
)
if "%JOBS%"=="" set JOBS=4
if exist "小节时间.csv" (
  echo 发现根目录的 小节时间.csv，导入到 数据\小节时间.csv
  python 脚本\import_times_only.py 小节时间.csv || (pause & exit /b 1)
  move /y 小节时间.csv 输出\已导入_小节时间.csv >nul
)
python 脚本\s5_render.py --jobs %JOBS% --scale 1 --out "输出\{VIDEO}"
echo.
echo 完成。视频在 输出 文件夹。
pause
"""

SH = f"""#!/bin/bash
cd "$(dirname "$0")"
python3 -m pip install -q -r 脚本/requirements.txt
if [ -f 小节时间.csv ]; then python3 脚本/import_times_only.py 小节时间.csv && mv 小节时间.csv 输出/已导入_小节时间.csv; fi
python3 脚本/s5_render.py --jobs ${{JOBS:-4}} --scale 1 --out "输出/{VIDEO}"
"""

REQ = """numpy
Pillow
scipy
verovio
cairosvg
imageio-ffmpeg
"""

README = f"""{TITLE_CARD} · 逐小节和声分析视频 · 本地渲染包

一、准备
  1. 安装 Python 3.10 或更新版本（Windows 安装时勾选 "Add python.exe to PATH"）。
  2. 不需要另装 ffmpeg：依赖里的 imageio-ffmpeg 自带一个。已装 ffmpeg 的会优先用系统的。
  3. cairosvg 在 Windows 上需要 Cairo 运行库；没有它时只是缩谱画不出来，不影响出片。

二、出片
  1. 如果校对页导出了新的「小节时间.csv」，放在本文件夹根目录（和 渲染.bat 同一层），渲染时会自动导入（只导入时间）。
  2. 双击「渲染.bat」。第一次会自动安装依赖库。
  3. 同时渲染的进程数默认 4，可以在命令行先 set JOBS=8 再运行（CPU 核数多就多开）。
  4. 成片：输出\\{VIDEO}（1080p）。

三、只看几帧 / 只出一段
  python 脚本\\s5_render.py --preview 600 1500          （出第 600、1500 秒的单帧图到 输出\\预览）
  python 脚本\\s5_render.py --start 0 --end 120 --out 输出\\试一段.mp4

四、改文字
  文字稿.txt 可以直接改（格式写在文件开头），改完重新渲染即可。
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    zp = os.path.join(OUT, f"{SHORT_NAME}_本地渲染包.zip")
    n = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        def add(src, arc, store=False):
            nonlocal n
            z.write(src, f"{ROOT}/{arc}", compress_type=zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED)
            n += 1
        for s in SCRIPTS:
            add(os.path.join(HERE, s), f"脚本/{s}")
        cfg = dict(CFG); cfg["display_score"] = SCORE
        z.writestr(f"{ROOT}/project.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        z.writestr(f"{ROOT}/脚本/requirements.txt", REQ)
        z.writestr(f"{ROOT}/渲染.bat", BAT.replace("\n", "\r\n").encode("utf-8"))
        z.writestr(f"{ROOT}/渲染.sh", SH)
        z.writestr(f"{ROOT}/使用说明.txt", README)
        z.writestr(f"{ROOT}/输出/.keep", "")
        add(os.path.join(PROJ, "文字稿.txt"), "文字稿.txt")
        for fn in dict.fromkeys(("小节位置.csv", "小节时间.csv", "两部分.txt", "对齐锚点.csv", os.path.relpath(SCORE_BARS_CSV, DATA))):
            if os.path.exists(os.path.join(DATA, fn)):
                add(os.path.join(DATA, fn), f"数据/{fn}")
        rel = os.path.relpath(SCORE_PAGES, PROJ)
        for f in sorted(glob.glob(os.path.join(SCORE_PAGES, "p*.png"))):
            add(f, f"{rel}/{os.path.basename(f)}", store=True)
        if not os.path.exists(AUDIO_FLAC):
            subprocess.run(NICE_CMD + ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", FF_THREADS,
                            "-i", AUDIO_WAV, "-c:a", "flac", AUDIO_FLAC], check=True)
        add(AUDIO_FLAC, "中间文件/audio/track.flac", store=True)
        for fn in ("beats.csv",):
            f = os.path.join(MID, "align", fn)
            if os.path.exists(f):
                add(f, f"中间文件/align/{fn}")
        for sub, d in (("source_han", FONT_DIR), ("freefont", FREEFONT_DIR)):
            for f in sorted(glob.glob(os.path.join(d, "*"))):
                if os.path.isfile(f):
                    add(f, f"字体/{sub}/{os.path.basename(f)}", store=f.endswith(".otf"))
        for f in sorted(glob.glob(os.path.join(PROJ, "缩谱", "*"))):
            add(f, f"缩谱/{os.path.basename(f)}")
    print("写出", zp, f"{os.path.getsize(zp) / 1e6:.0f} MB，{n} 个文件")


if __name__ == "__main__":
    main()
