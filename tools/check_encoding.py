# -*- coding: utf-8 -*-
"""检查对齐 SRT 的编码/BOM/行尾/空字节，定位 Aegisub 打不开的原因。"""
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

D = r"E:\my-ai-studio\西语SRT对齐\博物馆_16k\aligned_routeA"

for f in sorted(os.listdir(D)):
    p = os.path.join(D, f)
    with open(p, "rb") as fh:
        raw = fh.read()
    if raw[:3] == b"\xef\xbb\xbf":
        bom = "UTF-8 BOM"
    elif raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        bom = "UTF-16 BOM"
    else:
        bom = "无BOM"
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    try:
        raw.decode("utf-8")
        enc = "UTF-8 OK"
    except Exception as e:
        enc = f"非UTF-8! {e}"
    nulls = raw.count(b"\x00")
    flag = ""
    if bom != "无BOM" or nulls > 0 or "非UTF-8" in enc:
        flag = "  <<< 异常"
    name = f.replace(".aligned.srt", "")
    print(f"{name:38s} | {bom:12s} | CRLF={crlf:4d} LF={lf:4d} | {enc:24s} | null={nulls}{flag}")
