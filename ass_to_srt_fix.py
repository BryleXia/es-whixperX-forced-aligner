# -*- coding: utf-8 -*-
"""把伪装成 .srt 的 Aegisub ASS 文件转成标准 SRT，供 Route A 重新对齐。"""
import os
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def ass_time_to_srt(t):
    # 0:00:00.08 -> 00:00:00,080 ; 0:01:09.01 -> 00:01:09,010
    h, m, rest = t.split(":")
    s, cs = rest.split(".")
    cs = cs.ljust(2, "0")[:2]
    ms = int(cs) * 10
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def ass_to_srt(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    idx = 1
    in_events = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("["):
            in_events = stripped == "[Events]"
            continue
        if not in_events:
            continue
        if not ln.startswith("Dialogue:"):
            continue
        body = ln[len("Dialogue:"):]
        parts = body.split(",", 9)
        if len(parts) < 10:
            continue
        start = parts[1].strip()
        end = parts[2].strip()
        text = parts[9]
        # 去掉 ASS 覆盖标签 {\an8} 等
        text = re.sub(r"\{[^}]*\}", "", text)
        # ASS 换行 \N / \n -> 空格
        text = text.replace("\\N", " ").replace("\\n", " ")
        text = text.strip()
        if not text:
            continue
        out.append(str(idx))
        out.append(f"{ass_time_to_srt(start)} --> {ass_time_to_srt(end)}")
        out.append(text)
        out.append("")
        idx += 1
    return "\n".join(out) + "\n"


BAD = [
    "es_tour_muse_0022_seg003_tgt",
    "es_tour_muse_0022_seg004_tgt",
    "es_tour_muse_0023_seg001_tgt",
    "es_tour_muse_0023_seg002_tgt",
    "es_tour_muse_0023_seg003_tgt",
    "es_tour_muse_0023_seg004_tgt",
]

SRC_DIR = r"E:\my-ai-studio\西语SRT对齐\西语\6.24\博物馆"
DST_DIR = r"E:\my-ai-studio\西语SRT对齐\西语\6.24\博物馆_16k"

if __name__ == "__main__":
    preview_only = "--apply" not in sys.argv
    for base in BAD:
        src = os.path.join(SRC_DIR, base + ".asr.qc.srt")
        dst = os.path.join(DST_DIR, base + ".asr.qc.srt")
        srt = ass_to_srt(src)
        nblocks = srt.count("-->")
        if preview_only:
            print(f"[PREVIEW] {base}: {nblocks} blocks")
            print(srt[:300])
            print("---")
        else:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(srt)
            print(f"[WROTE] {dst}  ({nblocks} blocks)")
