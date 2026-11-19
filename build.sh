#!/bin/bash
# 乐谱和声分析视频：一键分步执行。在作品工程目录里运行（目录里要有 project.json），或先 export SV_PROJECT=工程目录。
#   bash <工具包>/build.sh 步骤 [步骤 ...]
# 步骤（按流程顺序；每一步做完都要按 AGENTS.md 的"验收"检查后再往下走）：
#   pages     取读谱用乐谱的页图                 s1_pages.py
#   fspages   取总谱页图（画面用总谱时）         s1_pages.py --full
#   audio     截录音、算对齐特征                 s3_audio.py
#   bars      识别读谱用乐谱的小节线             s2_bars.py --force
#   fsbars    识别总谱小节线并核对               s2_bars_fullscore.py → fs_fix.py → fs_check.py
#   omr       读谱（音符）                       omr_page.py all
#   text      统一谱号调号 → 自动和声候选 → 文字稿   double_bars → fix_clef → fix_ks → harm_auto → make_text
#   check     和声验收：自洽 + 对谱上的音        check_chords.py、audit_chords.py
#   align     自动对齐（只在用户校对前跑；之后只能在已校范围之间重排）   align_dtw.py
#   site      生成在线校对站素材                 make_checker.py → make_site.py
#   pack      本地渲染包                         make_render_pack.py
# 环境变量：SV_NICE（默认 15，0 = 不降优先级）、SV_FF_THREADS（默认 1）、SV_JOBS（默认 2）。弱服务器保持默认。
set -e
T="$(cd "$(dirname "$0")" && pwd)/scorevid"
N=""; [ "${SV_NICE:-15}" != "0" ] && command -v nice >/dev/null && N="nice -n ${SV_NICE:-15}"
run(){ echo "▶ $*"; $N python3 "$T/$@"; }
for step in "$@"; do
  case "$step" in
    pages)   run s1_pages.py ;;
    fspages) run s1_pages.py --full ;;
    audio)   run s3_audio.py ;;
    bars)    run s2_bars.py --force ;;
    fsbars)  run s2_bars_fullscore.py; run fs_fix.py --write; run fs_check.py 数据/总谱小节位置.csv ;;
    omr)     run omr_page.py all ;;
    text)    run double_bars.py; run fix_clef.py; run fix_ks.py; run harm_auto.py 1 1 >/dev/null; run make_text.py ;;
    check)   run check_chords.py; run audit_chords.py | head -40 ;;
    align)   run align_dtw.py ;;
    site)    if [ -f 中间文件/校对页/audio.mp3 ]; then run make_checker.py --data-only; else run make_checker.py; fi; run make_site.py ;;
    pack)    run make_render_pack.py ;;
    *) echo "未知步骤 $step"; exit 1 ;;
  esac
done
