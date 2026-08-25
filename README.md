# Multilingual SRT Forced Aligner

A set of Python scripts that align subtitle text to audio and write timestamped SRT files.
Input: audio files and a reference SRT whose text has been verified for correctness.
Output: the same subtitle lines with per-line start/end timestamps.

The repository contains three aligners, corresponding to three different
situations:

| Script | Approach |
|---|---|
| `align_srt_routeA.py` | CTC forced alignment of the SRT text onto the audio (no ASR step) |
| `align_srt_routeA_multi.py` | Route A, run in parallel over several files |
| `align_srt_routeB_llm.py` | ASR transcription + sequence matching + LLM matching |
| `align_srt_routeC_hybrid.py` | Hybrid: Route B matches as anchors, CTC alignment around them |

The scripts are configured through module constants at the top of each file and,
for Route A, through command-line arguments.

---

## Route A — CTC forced alignment

File: `align_srt_routeA.py`

Approach: the SRT text itself is passed to WhisperX's CTC aligner
(`whisperx.align`). No speech-recognition step is involved; timestamps are
obtained directly from the acoustic alignment of the given text.

Alignment model by language (configured in `LANG_CONFIG`):

| Language | Alignment model |
|---|---|
| es | WhisperX default (torchaudio VOXPOPULI model) |
| fr | WhisperX default (torchaudio VOXPOPULI model) |
| ja | WhisperX default |
| ru | `jonatasgrosman/wav2vec2-large-xlsr-53-russian` |

Processing details (as implemented):

- Alignment unit: **words** for es/fr/ru, **characters** for ja (character
  alignments are requested from WhisperX for ja).
- Word/character timestamps are mapped back to SRT lines with an LCS dynamic
  programming pass.
- Consecutive lines that could not be matched receive timestamps interpolated
  in proportion to their text length.
- Every line is clamped to end at least 50 ms before the next line starts.
- Outlier correction pass: a line is flagged when it has at least 3 units,
  lasts at least 6 seconds, its unit rate is below 1.5 units/s (3 chars/s for
  Japanese) and the gap to the previous line is below 0.3 s. Its start is then
  moved (at least 1.5 s forward) to the first speech onset found by
  Silero-VAD. If Silero-VAD cannot be loaded, a 20 ms-frame RMS energy
  threshold is used instead.
- Audio longer than 1800 s is split into equal-time chunks, each aligned with
  the corresponding share of lines.

Inputs and outputs:

- Audio formats scanned: `.m4a`, `.mp3`, `.wav`, `.WAV`, `.flac`.
- Reference SRT: `{stem}.asr.qc.srt` next to the audio file.
- Output: `{stem}.aligned.srt`, UTF-8 with BOM, CRLF line endings.

Command line:

```
--lang        es | fr | ru | ja        (default: ru)
--audio-dir   directory with audio+SRT (default: /root)
--output-dir  output directory         (default: /root/aligned_routeA)
```

Example:

```bash
python align_srt_routeA.py --lang es --audio-dir /root --output-dir /root/aligned_routeA
```

## Route A (parallel)

File: `align_srt_routeA_multi.py`

Runs Route A over several files at once using `multiprocessing` (spawn method).
Each worker process loads its own alignment model; the core alignment logic is
imported from `align_srt_routeA.py`.

Differences from the single-file script:

- Reference SRT matching order: `{stem}_tgt.asr.qc.srt`, then
  `{stem}.asr.qc.srt`.
- Additional `--align-model` option to override the per-language default model.
- Prints a per-file summary (status, seconds per file) and an estimated
  speedup over serial processing.

Command line:

```
--lang         es | fr | ru | ja   (default: es)
--audio-dir    required
--output-dir   required
--workers      process count       (default: 5)
--align-model  optional model override
```

Example:

```bash
python align_srt_routeA_multi.py --lang es --audio-dir /root --output-dir /root/aligned_routeA --workers 5
```

## Route B — ASR + sequence matching + LLM

File: `align_srt_routeB_llm.py`

Intended for recordings whose speech deviates from the reference text
(misreadings, omissions, repetitions), where a direct forced alignment of the
reference text does not apply.

Steps, in order:

1. **Transcription**: faster-whisper, model size `large-v3`, compute type
   `float16`; VAD filter enabled (min silence 400 ms, threshold 0.3);
   temperature 0.0, beam size 5, previous-text conditioning disabled.
2. **Repeated-segment filter**: transcript segments whose normalized text
   similarity to any of the previous five segments exceeds 0.70 are removed.
3. **SequenceMatcher matching**: for each reference line, a windowed search
   (up to 80 segments ahead, accumulating at most 20 segments, capped at 3x
   the reference length). Accepted when similarity reaches 0.40; searching
   stops early at 0.85.
4. **LLM matching**: lines not matched in step 3 are sent to an LLM in
   batches of 8. The LLM is called through an OpenAI-compatible chat API
   (default base URL `https://dashscope.aliyuncs.com/compatible-mode/v1`,
   default model `qwen3.6-plus`); the API key is read from the `LLM_API_KEY`
   environment variable. The LLM is asked to return a JSON mapping of line
   number to transcript segment range.
5. Lines matched by neither step are omitted from the output.

Configuration is via module constants at the top of the file (there are no
command-line arguments). Defaults: scan directory `/root`, output directory
`/root/aligned_routeB`, reference SRT `{stem}.asr.qc.srt`, output
`{stem}.aligned.srt` (plain UTF-8, LF line endings).

Languages: es, fr, ru.

Example:

```bash
export LLM_API_KEY=...
python align_srt_routeB_llm.py
```

## Route C — hybrid (anchors + CTC)

File: `align_srt_routeC_hybrid.py`

Runs Route B's sequence-matching + LLM step to obtain **anchors** (reference
lines with timestamps), then aligns the remaining lines against the audio
with CTC inside the windows between anchors.

Block construction (as implemented):

- Anchor lines keep their Route B timestamps (block window: anchor ± 0.5 s).
- A gap between two anchors is aligned as one block, its window being the
  interval between the anchor windows; head/tail gaps are bounded by the
  audio edges.
- If no anchor is obtained, a single block covering the whole audio is used —
  equivalent to running Route A on the full file.
- Word-level DP mapping and the same outlier-correction pass as Route A
  (unit-rate threshold 1.3 units/s) are applied.

Configuration is via module constants (no command-line arguments). Defaults:
audio glob `{language}_*.{m4a|mp3|wav|flac}`, scan directory `/root`, output
`/root/aligned_routeC`, reference SRT `{stem}.asr.qc.srt`.

Languages: es, fr, ru.

Example:

```bash
export LLM_API_KEY=...
python align_srt_routeC_hybrid.py
```

## Choosing a route

| Situation | Route |
|---|---|
| The recording closely follows the reference text | A |
| Frequent misreadings, omissions, or extra words | B |
| Route B matches only part of the lines | C |

(Route B's own output ends with the same guidance: prefer Route A when the
recording and the reference text are highly consistent.)

## Requirements

- A CUDA-capable GPU; the scripts set `DEVICE = "cuda"`.
- Python dependencies by route: `whisperx` (A, C); `faster-whisper`, `openai`
  (B, C); `silero-vad` (A, C — optional, an RMS fallback is used if it cannot
  be loaded); `num2words` (A, C — optional, digits are expanded to words when
  available).
- The scripts set `HF_HOME` and `TORCH_HOME` to `/root/autodl-tmp` and default
  input/output directories under `/root`. They are written for a Linux GPU
  server; to run them on another machine, edit the constants at the top of the
  respective file.
- Audio decoding is delegated to whisperx / faster-whisper, which use ffmpeg.

## Language support

| Script | es | fr | ru | ja |
|---|---|---|---|---|
| `align_srt_routeA.py` | yes (word) | yes (word) | yes (word) | yes (char) |
| `align_srt_routeA_multi.py` | yes | yes | yes | yes |
| `align_srt_routeB_llm.py` | yes | yes | yes | no |
| `align_srt_routeC_hybrid.py` | yes | yes | yes | no |

## Output file format

| Script | Encoding / line endings |
|---|---|
| `align_srt_routeA.py`, `align_srt_routeA_multi.py` | UTF-8 with BOM, CRLF |
| `align_srt_routeB_llm.py`, `align_srt_routeC_hybrid.py` | UTF-8 without BOM, LF |

## License

This project is source-available under the terms in [LICENSE](LICENSE): the
code may be viewed and run for private, personal, non-commercial evaluation.
Any other use — including corpus construction, institutional or systematic
academic use, redistribution, and commercial use — requires the copyright
holder's prior written consent. Contact the repository owner to request
consent for a specific use.

---

# 多语言 SRT 强制对齐

一组把字幕文本对齐到音频、并输出带时间戳 SRT 文件的 Python 脚本。
输入：音频文件和一份文字已经校对过的参考 SRT。
输出：同样的字幕行，附上逐行的起止时间戳。

仓库内含三个对齐器，对应三种不同场景：

| 脚本 | 做法 |
|---|---|
| `align_srt_routeA.py` | 用 CTC 对 SRT 文本做强制对齐（不含语音识别步骤） |
| `align_srt_routeA_multi.py` | 路线 A 的多进程并行版本 |
| `align_srt_routeB_llm.py` | ASR 转录 + 序列匹配 + LLM 匹配 |
| `align_srt_routeC_hybrid.py` | 混合式：路线 B 匹配结果做锚点，围绕锚点做 CTC 对齐 |

路线 A 通过命令行参数配置；其余脚本通过文件顶部的模块常量配置。

---

## 路线 A — CTC 强制对齐

文件：`align_srt_routeA.py`

做法：把 SRT 文本本身交给 WhisperX 的 CTC 对齐器（`whisperx.align`）。
不经过语音识别环节，时间戳直接来自给定文本的声学对齐结果。

各语言使用的对齐模型（在 `LANG_CONFIG` 中配置）：

| 语言 | 对齐模型 |
|---|---|
| es | WhisperX 默认（torchaudio 的 VOXPOPULI 模型） |
| fr | WhisperX 默认（torchaudio 的 VOXPOPULI 模型） |
| ja | WhisperX 默认 |
| ru | `jonatasgrosman/wav2vec2-large-xlsr-53-russian` |

处理细节（与实现一致）：

- 对齐单位：es/fr/ru 按**词**，ja 按**字符**（ja 会向 WhisperX 请求字符级
  对齐结果）。
- 词/字符时间戳通过 LCS 动态规划映射回 SRT 各行。
- 连续未能匹配的行，按文字长度比例插值分配时间。
- 每行会被钳制为在下一行开始前至少 50 ms 结束。
- 异常起点修正：一个行的单位数 ≥ 3、时长 ≥ 6 秒、单位速率低于 1.5 单位/秒
  （日语 3 字符/秒），且与上一行的间隔小于 0.3 秒时被判为可疑，其起点会向后
  移动至少 1.5 秒、吸附到 Silero-VAD 检测到的第一个语音起点；Silero-VAD 加载
  失败时改用 20 ms 帧长的 RMS 能量阈值。
- 音频时长超过 1800 秒时按等时长分块，每块配对应份额的行。

输入与输出：

- 扫描的音频格式：`.m4a`、`.mp3`、`.wav`、`.WAV`、`.flac`。
- 参考 SRT：与音频同目录的 `{stem}.asr.qc.srt`。
- 输出：`{stem}.aligned.srt`，UTF-8 带 BOM，CRLF 行尾。

命令行参数：

```
--lang        可选 es/fr/ru/ja      （默认 ru）
--audio-dir   音频+SRT 所在目录     （默认 /root）
--output-dir  输出目录              （默认 /root/aligned_routeA）
```

示例：

```bash
python align_srt_routeA.py --lang es --audio-dir /root --output-dir /root/aligned_routeA
```

## 路线 A（并行版）

文件：`align_srt_routeA_multi.py`

用 `multiprocessing`（spawn 方式）同时对多个文件跑路线 A。每个子进程各自加载
对齐模型；核心对齐逻辑从 `align_srt_routeA.py` 导入。

与单文件版的不同：

- 参考 SRT 匹配顺序：先 `{stem}_tgt.asr.qc.srt`，再 `{stem}.asr.qc.srt`。
- 新增 `--align-model` 参数，可覆盖各语言的默认模型。
- 结束时打印每个文件的状态/耗时汇总，以及相对串行的估算加速比。

命令行参数：

```
--lang         语言（默认 es）
--audio-dir    必填
--output-dir   必填
--workers      并行进程数（默认 5）
--align-model  可选，覆盖默认对齐模型
```

示例：

```bash
python align_srt_routeA_multi.py --lang es --audio-dir /root --output-dir /root/aligned_routeA --workers 5
```

## 路线 B — ASR + 序列匹配 + LLM

文件：`align_srt_routeB_llm.py`

适用于朗读与参考文本不一致的录音（读错词、漏读、多读），这种情况下对参考文本
直接做强制对齐不适用。

步骤：

1. **转录**：faster-whisper，模型 `large-v3`、`float16`；开启 VAD 过滤（最短
   静音 400 ms，阈值 0.3）；温度 0.0、beam 5、关闭上下文条件化。
2. **重复段过滤**：与之前 5 段中任一段的归一化相似度超过 0.70 的转录段被移除。
3. **SequenceMatcher 匹配**：对每个参考行做窗口搜索（向前最多 80 段，最多合并
   20 段，累积长度上限为参考文本 3 倍），相似度达到 0.40 即采用，达到 0.85 提前
   停止搜索。
4. **LLM 匹配**：第 3 步未匹配的行以每批 8 行交给 LLM。LLM 走 OpenAI 兼容接口
   （默认地址 `https://dashscope.aliyuncs.com/compatible-mode/v1`，默认模型
   `qwen3.6-plus`），API 密钥从环境变量 `LLM_API_KEY` 读取；LLM 被要求返回
   「行号 → 转录段范围」的 JSON。
5. 两种方法都未匹配上的行不会出现在输出中。

配置在文件顶部常量中（没有命令行参数）。默认：扫描目录 `/root`，输出目录
`/root/aligned_routeB`，参考 SRT `{stem}.asr.qc.srt`，输出 `{stem}.aligned.srt`
（普通 UTF-8，LF 行尾）。

支持语言：es、fr、ru。

示例：

```bash
export LLM_API_KEY=...
python align_srt_routeB_llm.py
```

## 路线 C — 混合式（锚点 + CTC）

文件：`align_srt_routeC_hybrid.py`

先跑路线 B 的序列匹配 + LLM 流程得到**锚点**（带时间戳的已匹配行），再把其余
行放在锚点之间的窗口内用 CTC 做精对齐。

分块规则（与实现一致）：

- 锚点行直接沿用路线 B 的时间戳（块窗口取锚点 ± 0.5 秒）。
- 两个锚点之间的行作为一个块，窗口为两个锚点窗口之间的区间；文件头尾的块用音频
  边界兜底。
- 一个锚点都没有时，整个音频作为单块处理——等价于对全文件直接跑路线 A。
- 词级 DP 映射与路线 A 相同的异常起点修正（单位速率阈值 1.3 单位/秒）。

配置在常量中（无命令行参数）。默认：音频通配 `{language}_*.{m4a|mp3|wav|flac}`，
扫描目录 `/root`，输出 `/root/aligned_routeC`，参考 SRT `{stem}.asr.qc.srt`。

支持语言：es、fr、ru。

示例：

```bash
export LLM_API_KEY=...
python align_srt_routeC_hybrid.py
```

## 路线选择

| 情况 | 用哪条路线 |
|---|---|
| 录音与参考文本基本一致 | A |
| 口误、漏读、多读较多 | B |
| 路线 B 只能匹配一部分行 | C |

（路线 B 自身的输出结尾也给出同样的建议：录音与参考文本高度一致时优先用路线 A。）

## 运行要求

- 需要 CUDA GPU；脚本内固定 `DEVICE = "cuda"`。
- 按路线区分依赖：`whisperx`（A、C）；`faster-whisper`、`openai`（B、C）；
  `silero-vad`（A、C——可选，加载失败时退化为 RMS 兜底）；`num2words`
  （A、C——可选，可用时把数字展开为读法）。
- 脚本把 `HF_HOME`、`TORCH_HOME` 设为 `/root/autodl-tmp`，默认目录也在 `/root`
  下；是为 Linux GPU 服务器环境编写的，换机器运行需修改文件顶部常量。
- 音频解码由 whisperx / faster-whisper 内部完成（依赖 ffmpeg）。

## 语言支持

| 脚本 | es | fr | ru | ja |
|---|---|---|---|---|
| `align_srt_routeA.py` | 支持（按词） | 支持（按词） | 支持（按词） | 支持（按字符） |
| `align_srt_routeA_multi.py` | 支持 | 支持 | 支持 | 支持 |
| `align_srt_routeB_llm.py` | 支持 | 支持 | 支持 | 不支持 |
| `align_srt_routeC_hybrid.py` | 支持 | 支持 | 支持 | 不支持 |

## 输出文件格式

| 脚本 | 编码 / 行尾 |
|---|---|
| `align_srt_routeA.py`、`align_srt_routeA_multi.py` | UTF-8 带 BOM、CRLF |
| `align_srt_routeB_llm.py`、`align_srt_routeC_hybrid.py` | UTF-8 不带 BOM、LF |

## 许可证

本项目按 [LICENSE](LICENSE) 中的条款以「源码可见」方式发布：代码可被查看，并
可用于个人、私下、非商业的评估运行。除此之外的任何使用——包括语料库建设、机构化
或成体系的学术用途、再分发、商业用途——均需事先取得版权人的书面同意。如需就特定
用途取得同意，请联系仓库所有者。