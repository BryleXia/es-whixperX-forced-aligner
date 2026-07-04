import argparse
import csv
import json
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def srt_time_to_seconds(ts):
    m = TIME_RE.match(ts.strip())
    if not m:
        raise ValueError(f"bad SRT timestamp: {ts}")
    hh, mm, ss, ms = m.groups()
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms[:3].ljust(3, "0")) / 1000.0


def parse_srt(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\n+", text.strip())
    entries = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        time_idx = 1 if len(lines) > 1 and "-->" in lines[1] else 0
        if "-->" not in lines[time_idx]:
            continue
        start_raw, end_raw = [x.strip() for x in lines[time_idx].split("-->", 1)]
        body = " ".join(lines[time_idx + 1:]).strip()
        if body:
            entries.append({
                "start": srt_time_to_seconds(start_raw),
                "end": srt_time_to_seconds(end_raw),
                "text": body,
            })
    return entries


def norm_chars(text):
    text = unicodedata.normalize("NFD", text.lower())
    chars = []
    for ch in text:
        if unicodedata.category(ch) == "Mn":
            continue
        if unicodedata.category(ch)[0] in {"L", "N"}:
            chars.append(ch)
    return chars


def indexed_char_stream(entries):
    chars = []
    owners = []
    for idx, entry in enumerate(entries):
        for ch in norm_chars(entry["text"]):
            chars.append(ch)
            owners.append(idx)
    return chars, owners


def align_entries(raw_entries, ref_entries):
    if len(raw_entries) == len(ref_entries):
        return [(i, i, 1.0) for i in range(len(raw_entries))]

    raw_chars, raw_owners = indexed_char_stream(raw_entries)
    ref_chars, ref_owners = indexed_char_stream(ref_entries)
    matcher = SequenceMatcher(None, raw_chars, ref_chars, autojunk=False)
    votes = defaultdict(Counter)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            raw_idx = raw_owners[block.a + k]
            ref_idx = ref_owners[block.b + k]
            votes[raw_idx][ref_idx] += 1

    pairs = []
    for raw_idx, counter in votes.items():
        if not counter:
            continue
        ref_idx, score = counter.most_common(1)[0]
        raw_len = max(len(norm_chars(raw_entries[raw_idx]["text"])), 1)
        ref_len = max(len(norm_chars(ref_entries[ref_idx]["text"])), 1)
        coverage = min(score / raw_len, score / ref_len)
        if coverage >= 0.45:
            pairs.append((raw_idx, ref_idx, coverage))
    pairs.sort()
    return pairs


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def summarize_file(name, samples):
    abs_start = [abs(s["start_delta"]) for s in samples]
    abs_end = [abs(s["end_delta"]) for s in samples]
    all_abs = abs_start + abs_end
    if samples:
        mid = max(1, len(samples) // 2)
        first_mean = statistics.mean(s["mid_delta"] for s in samples[:mid])
        second_mean = statistics.mean(s["mid_delta"] for s in samples[mid:])
        drift_change = second_mean - first_mean
    else:
        drift_change = 0.0

    return {
        "file": name,
        "samples": len(samples),
        "start_mae": statistics.mean(abs_start) if abs_start else 0.0,
        "end_mae": statistics.mean(abs_end) if abs_end else 0.0,
        "p90_abs": percentile(all_abs, 0.90),
        "gt_0_2": sum(v > 0.2 for v in all_abs),
        "gt_0_5": sum(v > 0.5 for v in all_abs),
        "drift_change": drift_change,
    }


def classify(summary):
    if abs(summary["drift_change"]) > 0.35 and summary["gt_0_5"] >= 4:
        return "drift"
    if summary["p90_abs"] > 0.25:
        return "endpoint"
    return "mostly_ok"


def normalize_stem(name):
    stem = Path(name).stem
    stem = stem.replace(".aligned", "").replace(".asr.qc", "")
    stem = stem.replace(" ", "")
    if stem.endswith("_tgt"):
        stem = stem[:-4]
    return stem


def find_audio(raw_name, audio_dir):
    if not audio_dir:
        return None
    target = normalize_stem(raw_name)
    for path in Path(audio_dir).glob("*"):
        if path.suffix.lower() not in {".wav", ".m4a", ".mp3", ".flac"}:
            continue
        if normalize_stem(path.name) == target:
            return path
    return None


def load_wav_audio(path):
    if path is None or path.suffix.lower() != ".wav":
        return None, None, "non_wav_or_missing"
    try:
        from scipy.io import wavfile
        sr, data = wavfile.read(path)
    except Exception as exc:
        return None, None, f"wav_read_failed:{exc}"
    import numpy as np
    if data.ndim > 1:
        data = data.mean(axis=1)
    if np.issubdtype(data.dtype, np.integer):
        max_value = max(abs(np.iinfo(data.dtype).min), np.iinfo(data.dtype).max)
        data = data.astype("float32") / max_value
    else:
        data = data.astype("float32")
    return sr, data, "ok"


def build_rms_profile(audio, sr, frame_ms=20):
    import numpy as np
    frame_len = max(1, int(sr * frame_ms / 1000))
    n_frames = len(audio) // frame_len
    if n_frames <= 0:
        return {"regions": [], "rms": np.array([], dtype="float32"), "frame_dur": frame_ms / 1000.0, "duration": 0.0}
    frames = audio[:n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    floor = float(np.percentile(rms, 20))
    ref = float(np.percentile(rms, 70))
    threshold = max(floor * 1.8, ref * 0.15, 1e-5)
    regions = []
    in_region = False
    start = 0.0
    frame_dur = frame_ms / 1000.0
    for i, value in enumerate(rms):
        t = i * frame_dur
        if value >= threshold and not in_region:
            start = t
            in_region = True
        elif value < threshold and in_region:
            end = t
            if end - start >= 0.08:
                regions.append((start, end))
            in_region = False
    if in_region:
        regions.append((start, len(rms) * frame_dur))
    return {
        "regions": merge_regions(regions),
        "rms": rms,
        "frame_dur": frame_dur,
        "duration": len(audio) / sr,
    }


def merge_regions(regions, max_gap=0.12):
    merged = []
    for start, end in sorted(regions):
        if end <= start:
            continue
        if merged and start - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def nearest_region(profile, t, before=0.45, after=0.75):
    best = None
    best_dist = None
    for start, end in profile["regions"]:
        if end < t - before or start > t + after:
            continue
        dist = 0.0 if start <= t <= end else min(abs(t - start), abs(t - end))
        if best is None or dist < best_dist:
            best = (start, end)
            best_dist = dist
    return best


def rms_valley(profile, start, end):
    rms = profile["rms"]
    if len(rms) == 0 or end <= start:
        return (start + end) / 2.0
    import numpy as np
    frame_dur = profile["frame_dur"]
    lo = max(0, int(start / frame_dur))
    hi = min(len(rms), max(lo + 1, int(end / frame_dur)))
    if hi <= lo:
        return (start + end) / 2.0
    return (int(np.argmin(rms[lo:hi])) + lo) * frame_dur


def refine_with_rms(entries, profile, max_start_shift=0.45, max_end_shift=0.55,
                    pre_roll=0.08, post_roll=0.10, min_gap=0.04):
    refined = []
    duration = profile["duration"]
    for entry in entries:
        start = max(0.0, float(entry["start"]))
        end = min(duration, max(start + 0.12, float(entry["end"])))
        region = nearest_region(profile, start)
        if region:
            candidate = max(0.0, region[0] - pre_roll)
            if abs(candidate - start) <= max_start_shift and candidate < min(end, region[1] + 0.2):
                start = candidate
        region = nearest_region(profile, end, before=0.75, after=0.45)
        if region:
            candidate = min(duration, region[1] + post_roll)
            if abs(candidate - end) <= max_end_shift and candidate > max(start, region[0] - 0.2):
                end = candidate
        refined.append({**entry, "start": start, "end": max(end, start + 0.12)})

    for i in range(len(refined) - 1):
        left = refined[i]
        right = refined[i + 1]
        if left["end"] <= right["start"] - min_gap:
            continue
        lo = left["start"] + 0.12
        hi = right["end"] - 0.12
        if hi <= lo:
            split = (left["end"] + right["start"]) / 2.0
        else:
            split = rms_valley(profile, max(lo, min(left["end"], right["start"]) - 0.35), min(hi, max(left["end"], right["start"]) + 0.35))
        split = min(max(split, lo), hi)
        left["end"] = max(left["start"] + 0.12, split - min_gap / 2)
        right["start"] = min(right["end"] - 0.12, split + min_gap / 2)
    return refined


def endpoint_mae(entries, ref_entries, pairs):
    values = []
    for raw_idx, ref_idx, _coverage in pairs:
        raw = entries[raw_idx]
        ref = ref_entries[ref_idx]
        values.append(abs(raw["start"] - ref["start"]))
        values.append(abs(raw["end"] - ref["end"]))
    return statistics.mean(values) if values else math.nan


def endpoint_stats(entries, ref_entries, pairs):
    values = []
    for raw_idx, ref_idx, _coverage in pairs:
        raw = entries[raw_idx]
        ref = ref_entries[ref_idx]
        values.append(abs(raw["start"] - ref["start"]))
        values.append(abs(raw["end"] - ref["end"]))
    return {
        "mae": statistics.mean(values) if values else math.nan,
        "p90": percentile(values, 0.90) if values else math.nan,
        "gt_0_2": sum(v > 0.2 for v in values),
        "gt_0_5": sum(v > 0.5 for v in values),
        "n": len(values),
    }


def grid_search_rms(loaded_cases):
    grid = []
    for max_start_shift in [0.45, 0.65, 0.85]:
        for max_end_shift in [0.55, 0.75, 0.95]:
            for pre_roll in [0.02, 0.04, 0.08]:
                for post_roll in [0.04, 0.06, 0.10]:
                    all_values = []
                    file_deltas = []
                    for case in loaded_cases:
                        refined = refine_with_rms(
                            case["raw_entries"],
                            case["profile"],
                            max_start_shift=max_start_shift,
                            max_end_shift=max_end_shift,
                            pre_roll=pre_roll,
                            post_roll=post_roll,
                        )
                        before = endpoint_stats(case["raw_entries"], case["ref_entries"], case["pairs"])
                        after = endpoint_stats(refined, case["ref_entries"], case["pairs"])
                        file_deltas.append(before["mae"] - after["mae"])
                        for raw_idx, ref_idx, _coverage in case["pairs"]:
                            raw = refined[raw_idx]
                            ref = case["ref_entries"][ref_idx]
                            all_values.append(abs(raw["start"] - ref["start"]))
                            all_values.append(abs(raw["end"] - ref["end"]))
                    grid.append({
                        "max_start_shift": max_start_shift,
                        "max_end_shift": max_end_shift,
                        "pre_roll": pre_roll,
                        "post_roll": post_roll,
                        "mae": statistics.mean(all_values) if all_values else math.nan,
                        "p90": percentile(all_values, 0.90) if all_values else math.nan,
                        "improved_files": sum(delta > 0 for delta in file_deltas),
                        "worsened_files": sum(delta < -0.02 for delta in file_deltas),
                    })
    grid.sort(key=lambda x: (x["worsened_files"], x["p90"], x["mae"]))
    return grid


def main():
    parser = argparse.ArgumentParser(description="Diagnose Route A SRT timing errors against hand-corrected debug SRTs.")
    parser.add_argument("--raw-dir", default="debug/旧脚本跑出来的srt")
    parser.add_argument("--ref-dir", default="debug/人工校对完成的srt")
    parser.add_argument("--audio-dir", default="debug/音频")
    parser.add_argument("--out-dir", default="debug/routeA_diagnostics")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    ref_dir = Path(args.ref_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_samples = []
    summaries = []
    audio_summaries = []
    loaded_cases = []
    for raw_path in sorted(raw_dir.glob("*.srt")):
        ref_name = raw_path.name.replace(".aligned.srt", ".asr.qc.srt")
        ref_path = ref_dir / ref_name
        if not ref_path.exists():
            continue
        raw_entries = parse_srt(raw_path)
        ref_entries = parse_srt(ref_path)
        pairs = align_entries(raw_entries, ref_entries)
        audio_path = find_audio(raw_path.name, args.audio_dir)
        sr, audio, audio_status = load_wav_audio(audio_path)
        audio_summary = {
            "file": raw_path.name,
            "audio": str(audio_path) if audio_path else None,
            "status": audio_status,
        }
        if audio_status == "ok":
            profile = build_rms_profile(audio, sr)
            refined_entries = refine_with_rms(raw_entries, profile)
            loaded_cases.append({
                "file": raw_path.name,
                "raw_entries": raw_entries,
                "ref_entries": ref_entries,
                "pairs": pairs,
                "profile": profile,
            })
            audio_summary.update({
                "duration": round(profile["duration"], 3),
                "speech_regions": len(profile["regions"]),
                "before_endpoint_mae": round(endpoint_mae(raw_entries, ref_entries, pairs), 3),
                "after_rms_endpoint_mae": round(endpoint_mae(refined_entries, ref_entries, pairs), 3),
            })
        audio_summaries.append(audio_summary)

        file_samples = []
        for raw_idx, ref_idx, coverage in pairs:
            raw = raw_entries[raw_idx]
            ref = ref_entries[ref_idx]
            start_delta = raw["start"] - ref["start"]
            end_delta = raw["end"] - ref["end"]
            sample = {
                "file": raw_path.name,
                "raw_index": raw_idx + 1,
                "ref_index": ref_idx + 1,
                "coverage": round(coverage, 3),
                "chars": len(norm_chars(raw["text"])),
                "words": len(raw["text"].split()),
                "raw_duration": round(raw["end"] - raw["start"], 3),
                "ref_duration": round(ref["end"] - ref["start"], 3),
                "start_delta": round(start_delta, 3),
                "end_delta": round(end_delta, 3),
                "mid_delta": round(((raw["start"] + raw["end"]) - (ref["start"] + ref["end"])) / 2, 3),
                "raw_text": raw["text"],
                "ref_text": ref["text"],
            }
            file_samples.append(sample)
            all_samples.append(sample)
        summaries.append(summarize_file(raw_path.name, file_samples))

    for summary in summaries:
        summary["class"] = classify(summary)

    csv_path = out_dir / "routeA_error_samples.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "file", "raw_index", "ref_index", "coverage", "chars", "words",
            "raw_duration", "ref_duration", "start_delta", "end_delta", "mid_delta",
            "raw_text", "ref_text",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_samples)

    json_path = out_dir / "routeA_file_summary.json"
    json_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    audio_json_path = out_dir / "routeA_audio_rms_summary.json"
    audio_json_path.write_text(json.dumps(audio_summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    grid = grid_search_rms(loaded_cases) if loaded_cases else []
    grid_json_path = out_dir / "routeA_rms_param_grid.json"
    grid_json_path.write_text(json.dumps(grid[:20], ensure_ascii=False, indent=2), encoding="utf-8")

    class_counts = Counter(s["class"] for s in summaries)
    all_abs = [abs(s["start_delta"]) for s in all_samples] + [abs(s["end_delta"]) for s in all_samples]
    loaded_audio = [s for s in audio_summaries if s["status"] == "ok"]
    improved_audio = [
        s for s in loaded_audio
        if s.get("after_rms_endpoint_mae", 999) < s.get("before_endpoint_mae", 999)
    ]
    best_grid = grid[0] if grid else None
    report = [
        "# Route A Debug Error Report",
        "",
        f"- files compared: {len(summaries)}",
        f"- aligned subtitle samples: {len(all_samples)}",
        f"- overall endpoint MAE: {statistics.mean(all_abs):.3f}s" if all_abs else "- overall endpoint MAE: 0.000s",
        f"- overall endpoint P90: {percentile(all_abs, 0.90):.3f}s",
        f"- abs(delta) > 0.2s: {sum(v > 0.2 for v in all_abs)}",
        f"- abs(delta) > 0.5s: {sum(v > 0.5 for v in all_abs)}",
        "",
        "## Failure Classes",
        "",
    ]
    for key in ["mostly_ok", "endpoint", "drift"]:
        report.append(f"- {key}: {class_counts.get(key, 0)} files")
    report.extend([
        "",
        "## Interpretation",
        "",
        "- Drift files show a different average midpoint error between the first and second half of a file. This is a long-window CTC failure mode; input SRT timestamps are not a valid production guardrail and must not be used.",
        "- Endpoint files have localized start/end errors without a strong file-level trend. These are handled only by local audio speech-boundary snapping and silence-valley conflict splitting.",
        "- Mostly OK files are important guardrails: parameter changes should not increase their P90 or large-error counts.",
        "",
        "## Audio RMS Check",
        "",
        f"- WAV files loaded: {len(loaded_audio)} / {len(audio_summaries)}",
        f"- RMS-only boundary pass improved endpoint MAE on: {len(improved_audio)} loaded files",
        f"- best RMS grid setting: {best_grid}" if best_grid else "- best RMS grid setting: n/a",
        "- M4A/MP3 files are listed in the JSON but skipped on this machine unless an audio decoder is available.",
        "",
        "## Outputs",
        "",
        f"- sample table: `{csv_path}`",
        f"- file summary: `{json_path}`",
        f"- audio RMS summary: `{audio_json_path}`",
        f"- RMS parameter grid: `{grid_json_path}`",
    ])
    report_path = out_dir / "routeA_error_report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"Compared {len(summaries)} files, {len(all_samples)} aligned samples")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {audio_json_path}")
    print(f"Wrote {grid_json_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
