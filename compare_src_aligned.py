# -*- coding: utf-8 -*-
"""逐块对比源 SRT 与 Route A 对齐结果的文本，找出漏句/串句/错位。"""
import sys
import io
import re
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SRC_DIR = r"E:\my-ai-studio\西语SRT对齐\西语\6.24\博物馆_16k"
ALN_DIR = r"E:\my-ai-studio\西语SRT对齐\博物馆_16k\aligned_routeA"


def parse_srt(path):
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    blocks = re.split(r"\n\s*\n", txt.strip())
    out = []
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        tidx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if tidx is None:
            continue
        text = " ".join(lines[tidx + 1:]).strip()
        out.append(text)
    return out


def main():
    bases = sys.argv[1:] or [
        "es_tour_muse_0023_seg001_tgt",
        "es_tour_muse_0023_seg002_tgt",
    ]
    for base in bases:
        src = parse_srt(os.path.join(SRC_DIR, base + ".asr.qc.srt"))
        aln = parse_srt(os.path.join(ALN_DIR, base + ".aligned.srt"))
        print(f"=== {base} ===")
        print(f"源SRT块数: {len(src)}   对齐后块数: {len(aln)}")
        mism = 0
        for i in range(max(len(src), len(aln))):
            s = src[i] if i < len(src) else "<无>"
            a = aln[i] if i < len(aln) else "<无>"
            if s != a:
                mism += 1
                if mism <= 8:
                    print(f"  [块{i+1}不一致]")
                    print(f"    源: {s[:100]}")
                    print(f"    齐: {a[:100]}")
        print(f"  不一致块数: {mism}")
        print()


if __name__ == "__main__":
    main()
