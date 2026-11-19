# score-harmony-video：乐谱逐小节和声分析视频

输入：一份扫描乐谱（PDF）和一个录音。输出：逐小节和声分析视频。
- 左边是乐谱，当前小节打阴影；
- 右边是和弦走带（级数、和弦名、T/S/D）和分段说明；
- 右下角是全曲曲式与调性进度条。

这套工作流从两个真实项目里整理出来：马勒《第三交响曲》第六乐章，马勒《第八交响曲》全曲（2152 小节、80 分钟）。

**给 agent：先读 `AGENTS.md`。** 它是操作手册，包括铁律、流程、每一步的验收和出错时怎么查。

## 思路

机器先粗做，人来校，脚本做验收：

```
PDF ─s1 页图─ s2 小节线 ─(逐页对印刷小节号)─┐
                     omr 读谱 ─ 自动和弦草稿 ┤
录音 ─s3 剪辑+特征 ─ align_dtw 对齐初稿 ───┤
                                          ├─ 用户在校对站校时间轴 ─ import_checker
                     人工读和声（对总谱）─────┤
                     人工写说明 ─────────────┘
                              make_text → 文字稿 → s5_render 预览 / 出片 / 渲染包
```

自动的部分（小节线、读谱、和弦候选、对齐）都会错。真正让结果可用的是三样东西：
- **人工修正层**：修正按谱面位置写，重跑之后仍然有效；
- **校对站**：让用户高效地改时间轴；
- **验收关卡**：比如小节数逐页对上印刷编号、和弦对谱上的音。

## 依赖

- Python 3.10 及以上：numpy、Pillow、scipy、pymupdf；缩谱排版要 verovio 和 cairosvg。
- ffmpeg（或者 imageio-ffmpeg）。
- 字体：思源宋体、思源黑体（SIL OFL），FreeSerif（GPL 加字体例外）。放在 `字体/source_han/`、`字体/freefont/`。

## 目录

| 路径 | 内容 |
|---|---|
| `AGENTS.md` | 操作手册（先读） |
| `build.sh` | 分步执行：`bash build.sh pages bars audio …` |
| `scorevid/` | 全部脚本，索引见下 |
| `web/` | **时间轴校对站**、**标音网页**的模板，以及数据约定和托管注意事项（`web/README.md`） |
| `PROGRESS.md` | 马勒八实例的工作进度（做到哪、还剩什么、下一步） |
| `assets/` | 谱号、还原号模板（`omr_templates.npz`），系统分隔记号模板（`system_separator.png`） |
| `project_template/` | 新作品工程的起点 |
| `examples/mahler8/` | 真实项目的 `project.json` 和人工数据（小节修正、页首小节号、时间轴、和弦、说明），可以当格式样例和参考答案 |
| `docs/02`～`10` | 配置、数据格式、小节识别、对齐与校对、**人工读和声**、文字风格、渲染交付、踩坑记录、环境设备 |

## 脚本索引（`scorevid/`）

| 环节 | 脚本 | 作用 |
|---|---|---|
| 公共 | `common.py` | 读 `project.json`，提供路径和参数；设备参数走环境变量 |
| | `textdoc.py` | 解析文字稿；级数、和弦名、T/S/D、小节编号的显示 |
| 页图 | `s1_pages.py [--full]` | PDF → 页图 |
| 小节 | `s2_bars.py --force` | 读谱用谱子的小节线 → `数据/小节位置.csv`、`中间文件/bars_debug/` |
| | `s2_bars_fullscore.py [起页 止页]` | 总谱的小节线（先放大再去斜） |
| | `fs_fix.py [--write]` | 合并分段结果、套用 `总谱小节修正.txt`、自动并断开的系统，写 `总谱小节位置.csv` |
| | `fs_check.py` | 和 `总谱页首小节.txt` 逐页对小节数 |
| | `fs_missing.py 页…` | 找漏掉的小节线 |
| | `fs_corner_numbers.py 起页 止页` | 页角小节号拼图，人工读出来 |
| | `find_merged.py` | 找被并成一个的两个系统 |
| | `renumber.py` | 小节结构改动后，旧编号到新编号的对照 |
| 读谱 | `omr_page.py all` / `omr.py` / `notes_view.py` | 读音符（钢琴、人声缩谱） |
| | `double_bars.py` → `fix_clef.py` → `fix_ks.py` | 双小节线、谱号修正、调号统一 |
| | `rebin_omr.py` | 小节位置改了以后，把读谱结果重新分到新小节 |
| | `harm_auto.py` | 自动和弦候选（**只是草稿**） |
| 音频与对齐 | `s3_audio.py` | 截取、剪静音、算特征 |
| | `align_dtw.py` | 对齐（在已校范围之间重排） |
| | `align_lab.py` | 对齐方法评测 |
| | `align_base.py`、`align_legacy.py` | 依赖，以及旧方法（只作对照，不要用来出时间轴） |
| 校对 | `make_checker.py` → `make_site.py` | 生成在线校对站（页面模板在 `web/`） |
| | `import_checker.py 交回的.csv` | 导入用户校对的结果（含结构改动） |
| | `import_times_only.py` | 只导入时间（渲染包里用） |
| 和声 | `reread_sheets.py 起页 止页` | **不带候选和弦**的读谱图（别加 `--names`：读谱程序几乎不认还原号） |
| | `vs_crop.py 起 止 [倍数 上 下]` | 读谱用乐谱局部放大，带音高标尺 |
| | `fs_full.py 起 止 上 下` | 从总谱 PDF 原图截局部（核对临时记号用） |
| | `make_doubt_site.py`、`import_doubt.py` | 把看不清的地方做成标音网页给用户，读回结果 |
| 换总谱 | `rehearsal.py`、`compare_rehearsal.py` | 用排练号方框核对两份谱的小节编号 |
| | `vs_zoom.py 起 止` | 缩谱放大 |
| | `fs_zoom.py 起 止 [y0 y1 倍数]`、`fs_sheet.py 页` | 总谱放大核对，上方印现有和弦 |
| | `check_chords.py` | 级数和和弦名是否自洽 |
| | `audit_chords.py [起 止]` | 和弦对读谱音，找"音没变却换和弦"等可疑处 |
| 文字与出片 | `make_text.py` | `和弦_人工.txt` + `分析_人工.txt` → `文字稿.txt` |
| | `s5_render.py --preview 秒… / --start --end / 全片` | 渲染 |
| | `reduction.py` | 缩谱排版（可选） |
| | `make_render_pack.py` | 本地渲染包 |

## 现状

- 工具包里的脚本在马勒八的真实数据上跑过冒烟测试：文字稿和原工程逐字一致，预览帧正常。
- 重新识别、重新读谱、重新对齐这几步只做了导入检查，没有在新工程上从头跑过。第一次用于新作品时，请按 `AGENTS.md` 第三节逐步验收。
- 版权：录音和扫描谱不放进仓库。`examples` 里只有派生数据（小节坐标、时间、和弦标注）和下载来源。
