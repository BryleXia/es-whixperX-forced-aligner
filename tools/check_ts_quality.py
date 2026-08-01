# -*- coding: utf-8 -*-
"""扫描对齐 SRT 的时间戳异常：超长块、负间隔/重叠、大静音间隔。"""
import sys
import io
import re
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ALN_DIR = r"E:\my-ai-studio\西语SRT对齐\博物馆_16k\aligned_routeA"


def to_ms(t):
    h, m, s = t.split(":")
    s, ms = s.split(",")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def parse(path):
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    blocks = re.split(r"\n\s*\n", txt.strip())
    segs = []
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        tidx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if tidx is None:
            continue
        st, en = lines[tidx].split("-->")
        st = to_ms(st.strip())
        en = to_ms(en.strip())
        text = " ".join(lines[tidx + 1:]).strip()
        segs.append((st, en, text))
    return segs


def main():
    files = sorted(f for f in os.listdir(ALN_DIR) if f.endswith(".aligned.srt"))
    print(f"{'文件':40s} | 块数 | 最长块 | 最大间隔 | 重叠/逆序")
    print("-" * 90)
    for f in files:
        segs = parse(os.path.join(ALN_DIR, f))
        if not segs:
            print(f"{f:40s} | 空!")
            continue
        max_dur = max(en - st for st, en, _ in segs)
        max_gap = 0
        overlap = 0
        for i in range(1, len(segs)):
            gap = segs[i][0] - segs[i - 1][1]
            if gap < 0:
                overlap += 1
            elif gap > max_gap:
                max_gap = gap
        flag = ""
        if max_dur > 15000:
            flag += " 超长块!"
        if overlap > 0:
            flag += " 重叠!"
        if max_gap > 5000:
            flag += " 大间隔!"
        print(f"{f.replace('.aligned.srt',''):40s} | {len(segs):4d} | {max_dur/1000:.1f}s | {max_gap/1000:.1f}s | {overlap}{flag}")


if __name__ == "__main__":
    main()
