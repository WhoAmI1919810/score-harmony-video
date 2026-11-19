# -*- coding: utf-8 -*-
"""读用户在"请帮我标音"网页导出的 标音结果.json，按条目打印用户的标注（小节、位置、音名、文字），供改和弦时逐条对照。
用法：python3 import_doubt.py 标音结果.json"""
import sys, json
v = json.load(open(sys.argv[1], encoding="utf-8"))
for it in v["items"]:
    if not (it.get("bars") or it.get("marks") or it.get("comment") or it.get("status") == "fine"):
        continue
    print(f"== {it['title']}  状态：{ {'fine': '读法没问题', 'seen': '看过'}.get(it.get('status'), it.get('status'))}")
    for k, t in it.get("bars", {}).items():
        print(f"   小节 {k}：{t}")
    for m in sorted(it.get("marks", []), key=lambda m: (m["bar"], m["x"], -m["y"])):
        print(f"   {m['lab']}  ({m['view']} p{m['page']} x={m['x']:.0f} y={m['y']:.0f})  {m['note']}")
    if it.get("comment"):
        print("   说明：", it["comment"])
