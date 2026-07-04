# -*- coding: utf-8 -*-
"""把对齐 SRT 转成 Aegisub 最兼容的格式：UTF-8 带 BOM + CRLF 行尾。"""
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SRC = r"E:\my-ai-studio\西语SRT对齐\博物馆_16k\aligned_routeA"
DST = r"E:\my-ai-studio\西语SRT对齐\博物馆_16k\aligned_routeA_aegisub"
os.makedirs(DST, exist_ok=True)

BOM = b"\xef\xbb\xbf"
n = 0
for f in sorted(os.listdir(SRC)):
    if not f.endswith(".aligned.srt"):
        continue
    with open(os.path.join(SRC, f), "r", encoding="utf-8") as fh:
        txt = fh.read()
    # 统一换行为 CRLF
    txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    if not txt.endswith("\r\n"):
        txt += "\r\n"
    with open(os.path.join(DST, f), "wb") as fh:
        fh.write(BOM + txt.encode("utf-8"))
    n += 1
    print(f"[OK] {f}")

print(f"\n完成 {n} 个文件 -> {DST}")
