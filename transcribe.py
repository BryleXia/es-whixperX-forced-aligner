"""
transcribe.py — 课堂录音转文字稿

用法：
    python transcribe.py recording1.aac recording2.aac
    python transcribe.py recording1.aac --output-dir /root/transcripts
    python transcribe.py recording1.aac --model-path /root/autodl-tmp/.../faster-whisper-large-v3/snapshots/xxx

输出：每个音频对应一个 .txt 纯文字稿
"""

import argparse
import os
import sys
from pathlib import Path

# ─── 环境配置（与 routeB/routeC 一致）───────────────────────────────────────
os.environ.setdefault("HF_HOME",    "/root/autodl-tmp/huggingface")
os.environ.setdefault("TORCH_HOME", "/root/autodl-tmp/torch")

# ─── 可调参数 ────────────────────────────────────────────────────────────────
LANGUAGE             = "es"        # 西班牙语
DEVICE               = "cuda"
WHISPER_MODEL_SIZE   = "large-v3"
WHISPER_COMPUTE_TYPE = "float16"

# 段落分割阈值：两段之间静音超过此值（秒）则换行
PARAGRAPH_GAP_SEC = 2.0


def load_model(model_path: str):
    from faster_whisper import WhisperModel
    if model_path:
        model = WhisperModel(model_path, device=DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
        print(f"  模型加载完成（{model_path}）")
    else:
        model = WhisperModel(WHISPER_MODEL_SIZE, device=DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
        print(f"  模型加载完成（{WHISPER_MODEL_SIZE}）")
    return model


def transcribe(model, audio_path: str) -> list:
    """返回 segment 列表，每个元素为 {"text": str, "start": float, "end": float}"""
    segs_raw, info = model.transcribe(
        audio_path,
        language=LANGUAGE,
        word_timestamps=False,             # 纯文字稿不需要词级时间戳
        condition_on_previous_text=False,  # 防止幻觉循环
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400, threshold=0.3),
        temperature=0.0,
        beam_size=5,
    )
    segs = [{"text": s.text.strip(), "start": s.start, "end": s.end}
            for s in segs_raw if s.text.strip()]
    print(f"  转录完成：{len(segs)} 段，时长 {info.duration:.1f} 秒")
    return segs


def segments_to_text(segs: list, gap_sec: float = PARAGRAPH_GAP_SEC) -> str:
    """
    把 segment 列表拼成纯文字稿。
    相邻两段间隔 < gap_sec → 同一行（空格连接）
    相邻两段间隔 ≥ gap_sec → 换行（视为自然停顿）
    """
    if not segs:
        return ""

    lines = []
    current_line_parts = [segs[0]["text"]]

    for prev, cur in zip(segs, segs[1:]):
        gap = cur["start"] - prev["end"]
        if gap >= gap_sec:
            lines.append(" ".join(current_line_parts))
            current_line_parts = [cur["text"]]
        else:
            current_line_parts.append(cur["text"])

    lines.append(" ".join(current_line_parts))
    return "\n".join(lines)


def process_file(model, audio_path: Path, output_dir: Path):
    print(f"\n处理：{audio_path.name}")
    segs = transcribe(model, str(audio_path))
    text = segments_to_text(segs)

    out_path = output_dir / (audio_path.stem + ".txt")
    out_path.write_text(text, encoding="utf-8")
    print(f"  已保存：{out_path}")


def main():
    parser = argparse.ArgumentParser(description="西班牙语课堂录音转文字稿")
    parser.add_argument("audio_files", nargs="+", help="音频文件路径（支持 .aac .mp3 .wav .flac 等）")
    parser.add_argument("--output-dir", default="/root/transcripts", help="输出目录（默认 /root/transcripts）")
    parser.add_argument("--model-path", default="", help="faster-whisper 模型路径（留空则自动查找）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_paths = [Path(p) for p in args.audio_files]
    missing = [p for p in audio_paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"错误：找不到文件 {p}", file=sys.stderr)
        sys.exit(1)

    print("加载 faster-whisper 模型...")
    model = load_model(args.model_path)

    for audio_path in audio_paths:
        process_file(model, audio_path, output_dir)

    print(f"\n全部完成。文字稿保存在：{output_dir}")


if __name__ == "__main__":
    main()
