# 多语言字幕强制对齐工具

> 把字幕文件的时间戳**精确对齐**到音频上。不依赖语音识别，直接基于参考文本做声学强制对齐（CTC），西语实测 **390 句 0 错误**。

支持 **西语 / 法语 / 俄语 / 日语**，切换语言只需一个参数。

**技术栈：** WhisperX · wav2vec2（CTC 强制对齐）· Silero-VAD · Python

---

## 它能做什么

- ✅ **精确到句的时间戳**：输出标准 SRT，Aegisub 直接打开，不用人工对轴
- ✅ **生僻词不翻车**：跳过语音识别环节——字幕里出现模型没见过的词（人名、音译）也能对齐
- ✅ **口误也能救**：录音有口误/多读/漏读时，用 ASR + LLM 语义匹配兜底
- ✅ **批处理全自动**：几十个文件的目录，命名检查 → 压缩 → 上传 GPU 服务器 → 对齐 → 打包下载，一条龙（见「批处理自动化」）
- ✅ **多语言一行切换**：`--lang es` / `fr` / `ru` / `ja`

## 快速开始

```bash
# 方案 A（首选）：单文件
python align_srt_routeA.py --lang es

# 多文件并行（推荐）
python align_srt_routeA_multi.py --lang es \
    --audio-dir /path/to/input --output-dir /path/to/output --workers 4
```

输入：音频 + 参考 SRT 放在同一目录（支持 `*.asr.qc.srt` / `*_tgt.asr.qc.srt` 命名）。
输出：每个音频对应一个 `*.aligned.srt`（UTF-8 + CRLF，Aegisub 直接兼容）。

## 三套方案怎么选

| | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| 做法 | 参考文本 + CTC 强制对齐 | ASR 转录 + LLM 语义匹配 | B 成功句当锚点 + A 精对齐 |
| 适用 | **录音与文稿一致**（首选） | 口误/多读/漏读多 | B 部分成功时 |
| 速度 | 快，无 API | 慢，需 LLM API | 中等 |
| 实测 | 西语 390 句 **0 错** | 日语 212 句 **97.6%** | — |

**决策顺序：A → B → C。** 先试 A，口误太多换 B，B 覆盖不全用 C。

### 方案 A 为什么靠谱

传统流程先做语音识别再匹配字幕，一旦字幕里有模型没见过的词（如西语中的中文人名音译），识别就出错：

| 正确写法 | Whisper 识别结果 |
|---|---|
| Lao Bao（老包） | Alien、Lab、Labao |
| Nuodeng（诺邓） | Nudon、Nodeng |

方案 A 直接把**字幕文字**当对齐目标送进 wav2vec2，跳过转录环节，用 CTC 找到每个词的声学边界，再经 LCS 动态规划映射回字幕行。配合 Silero-VAD 检测场景切换，修正过早的句首时间戳。

---

## 使用的模型

对齐与转录**分工明确**，全部选用各领域顶尖的公开模型：

| 角色 | 模型 | 参数量 | 背景 |
|---|---|---|---|
| 对齐（西/法/俄） | `jonatasgrosman/wav2vec2-large-xlsr-53-spanish/french/russian` | **~3.17 亿** | XLSR-53 基座 + Common Voice 微调 |
| 对齐（日语） | `wav2vec2-base-960h`（WhisperX 默认） | 9500 万 | LibriSpeech 960h 微调 |
| 转录（无 SRT 分支） | **Whisper large-v3**（OpenAI） | **15.5 亿** | 500 万小时训练数据 |
| VAD（时间戳修正） | Silero-VAD | 轻量（ONNX） | 实时语音活动检测 |

### 对齐器：wav2vec2 XLSR-53（西/法/俄微调版）

- **基座**：`facebook/wav2vec2-large-xlsr-53` — Meta AI 2021（Interspeech 论文），**53 种语言、56,000 小时**无标注语音自监督预训练，24 层 Transformer
- **微调**：jonatasgrosman 系列在 **Common Voice** 上微调，西语 WER **8.81%**（2021 年社区最佳之一，比 Facebook 官方微调版 16.99% 好近一倍）
- 只用 16kHz 单声道音频，与项目的压缩管线完全匹配

### 转录器：Whisper large-v3（OpenAI）

仅「目录无参考 SRT」分支使用，负责出初稿文本：
- **15.5 亿参数**，2023 年 11 月发布，多语言 SOTA 之一
- 训练数据 **500 万小时**（100 万小时弱标注 + 400 万小时伪标注），相比 v2 错误率再降 10–20%

### 分工逻辑

> **Whisper 出文本，wav2vec2 出精确时间戳。** 对齐环节不依赖转录结果——字幕里出现模型没见过的生僻词（人名、音译）也照样对齐。

## 批处理自动化

`/align-batch` 是一个 Claude Code skill（`.claude/skills/align-batch/`），把整条生产流水线自动化：

```
本地目录 (WAV+SRT)
   │  ① 扫描命名问题（空格/大小写/编号/配对/前缀）
   │  ② 压缩为 16kHz 单声道（省 3-5 倍上传带宽）
   ▼
[SSH 直连 AutoDL GPU 服务器]
   │  ③ 上传  ④ （无 SRT 时 WhisperX 先转录）
   │  ⑤ Route A 精对齐  ⑥ 打包
   ▼
本地 ←── ⑦ 下载结果 zip
```

- **自动模式**：SSH 密钥配好后，上传/对齐/打包/下载全自动
- **手动模式**：无 SSH 时降级为生成可复制的单行命令
- **无 SRT 分支**：目录只有 WAV 时，先 WhisperX 转录出初稿（文本对、时间戳不准），再交 Route A 精对齐——WhisperX 出文本，wav2vec2 出时间戳

## 配套工具（tools/）

| 脚本 | 用途 |
|---|---|
| `docx_to_srt.py` | Word 双列表格（中→外）转 SRT，自动配对音频 |
| `transcribe.py` | 课堂录音转文字，按静音分段 |
| `ass_to_srt_fix.py` | Aegisub ASS → 标准 SRT |
| `to_aegisub_srt.py` | SRT → Aegisub 兼容格式（UTF-8 BOM + CRLF） |
| `check_encoding.py` | 检查 SRT 编码问题（BOM/行尾/空字节） |
| `check_ts_quality.py` | 扫描对齐结果时间戳异常 |
| `compare_src_aligned.py` | 逐块对比源 SRT 与对齐结果，找漏句/错位 |
| `diagnose_routeA_debug.py` | 方案 A 诊断工具 |

## 实验结果

### 方案 A（实测人工审听）

| 语言 | 方案 | 规模 | 错误率 |
|---|---|---|---|
| 西语 | Whisper 转录 + 模糊匹配（旧） | 237 句 | 3.8% |
| 西语 | 强制对齐，无时间戳修正 | 390 句 | 0.8% |
| 西语 | 强制对齐 + 时间戳修正 | 390 句 | **0%** |
| 俄语 | 强制对齐 | 1028 词 | 1.2% |

### 方案 B（北京博物馆语料库，日语 212 句）

| 方法 | 成功率 |
|---|---|
| 仅 SequenceMatcher | ~70% |
| SequenceMatcher + LLM | **97.6%** |

## 安装

```bash
# 方案 A
pip install whisperx silero-vad num2words imageio-ffmpeg

# 方案 B / C 额外
pip install faster-whisper openai
export LLM_API_KEY="your-key"
```

GPU 服务器（如 AutoDL）上运行效果最佳；wav2vec2 每进程约 15-20GB 显存，`--workers` 建议 ≤ 4。
