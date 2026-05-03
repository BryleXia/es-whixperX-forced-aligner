# 字幕强制对齐工具（多语言版）

把字幕文件的时间戳准确对齐到音频上。提供三套互补方案，覆盖不同录音质量场景。支持西班牙语、法语、俄语、日语，切换语言只需一个参数。

**作者：** BryleXia · 北京第二外国语学院欧洲学院

**脚本：**
- `align_srt_routeA.py` — 方案 A（参考文本强制对齐）
- `align_srt_routeA_multi.py` — 方案 A 多进程并行版
- `align_srt_routeB_llm.py` — 方案 B（ASR + LLM 语义对齐）
- `align_srt_routeC_hybrid.py` — 方案 C（混合对齐）
- `docx_to_srt.py` — 日语学院 docx 双列表格转 SRT（前端适配）

---

## 如何选择方案

三个方案的核心区别在于如何处理"录音和字幕文稿不一致"的问题。

**方案 A** 假设录音与文稿高度一致，直接把字幕文字送入声学对齐器，跳过语音识别。速度快，无需 API，是首选方案。

**方案 B** 假设录音存在口误、多读、漏读等偏差。它先用语音识别获取"录音里实际说了什么"，再用大语言模型做语义匹配。适合录音质量参差不齐的场景。

**方案 C** 介于两者之间。先用方案 B 获取一部分句子的时间戳作为锚点，锚点之间的空白窗口交给方案 A 精对齐。适合方案 B 无法全覆盖、但方案 A 也因文稿偏差无法独立工作的场景。

简单来说：优先试 A，口误太多用 B，B 覆盖不全用 C。

---

## 方案 A：参考文本强制对齐

### 为什么跳过语音识别

传统的做法是：先用语音识别把音频转成文字，再把识别结果和字幕做匹配。问题出在第一步——当字幕里出现语音识别模型没见过的词（比如中文人名的西语音译），识别就会出错：

| 正确写法 | 语音识别（Whisper）输出 |
|---------|----------------------|
| Lao Bao（老包） | Alien、Lab、Labao |
| Nuodeng（诺邓） | Nudon、Nodeng、Nuodong |
| A Liang（阿亮） | Alien（完全无法识别） |

既然字幕文字本来就是对的，方案 A 跳过转录环节，直接把字幕文字作为对齐目标送进声学模型。

### 工作原理

方案 A 使用 wav2vec2 的 CTC 对齐能力（通过 WhisperX 调用）。把全部字幕行拼成一段完整文本，连同音频一起交给对齐器，wav2vec2 在音频中寻找每个词的边界位置，返回词级时间戳。最后用最长公共子序列（LCS）动态规划将词级时间戳映射回每一行字幕。

整个过程不需要语音识别，因此不受"生僻词"困扰。

### 时间戳修正

在场景切换（长时间静音）的地方，CTC 对齐器有时会把句子起点放得过早。方案 A 会检测语速异常的行——同时满足以下三个条件时触发修正：

1. 语速低于 1.5 词/秒（日语：3.0 字/秒）
2. 时长超过 6 秒
3. 与前一句间隔小于 0.3 秒（被强行塞在前一句之后）

修正方式是用 Silero-VAD 定位真正的语音起点，把时间戳吸附过去。

### 未对齐行的处理

极少数无法对齐的句子（通常 1% 以内）不会给固定占位符，而是查找前后已对齐行的时间范围，按文字长度比例分配时间段。

---

## 方案 B：ASR + LLM 语义对齐

### 适用场景

当录音和文稿出现以下偏差时，方案 A 失效——因为对齐器拿着"错误的地图"去找路：

- 口误：读错了某个词
- 多读：重复读了某句话
- 漏读：跳过了某句或某个短语
- 改词：临时换了表述方式

方案 B 的思路是：先弄清楚录音里实际说了什么，再用大语言模型理解语义，把实际内容和文稿对应起来。

### 工作流程

**第一步：faster-whisper 转录。** 用语音识别获取录音的逐段时间戳。为防止幻觉循环，关闭了 `condition_on_previous_text`，并对重复段做相似度过滤。

**第二步：SequenceMatcher 初筛。** 对每句文稿，在转录结果中向前滑动窗口搜索，计算字符相似度。相似度达到 0.40 的句子直接匹配成功，剩余的交给大语言模型。

**第三步：LLM 语义裁判。** 将未匹配的文稿句子和所有转录段落一起发送给大语言模型（Qwen3.6-plus）。模型理解口误、重复、近义替换等语义关系后，给出每句文稿对应哪些转录段落。这是字符匹配做不到的——它知道"朗读者把 X 读成 Y"不意味着两句无关，而是同一内容的不同表达。

此方案在北京博物馆语料库项目中经过验证（日语 212 句，LLM 解决了汉字与假名跨书写系统的匹配问题），迁移到西语后解决的是口误导致的文本不一致问题。

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `SM_HIGH_CONF` | 0.40 | SequenceMatcher 置信度阈值 |
| `LLM_BATCH` | 8 | 每批发给 LLM 的句子数 |
| `HALL_SIM` | 0.70 | 幻觉段过滤相似度阈值 |

---

## 方案 C：混合对齐

### 思路

方案 C 不需要方案 B 100% 覆盖——只要一部分句子能成功对齐，就可以作为锚点。锚点之间的空白窗口交给方案 A 的 CTC 对齐器精对齐，兼顾两者的优势：

- 锚点句子：直接使用方案 B 的时间戳，跳过 CTC
- 空白窗口：在锚点划定的时间边界内，用 CTC 精对齐
- 如果方案 B 完全失败：整段音频退化为纯方案 A

### 适用场景

- 方案 B 覆盖率中等（50%–80%），有足够锚点但不够全覆盖
- 方案 A 因文稿偏差无法独立工作，但方案 B 也不能处理所有句子
- 需要词级精度（锚点保留了方案 B 的时间，空白区获得方案 A 的 CTC 精度）

---

## 多语言支持

三个方案均已支持多语言。方案 A / C 使用 wav2vec2 对齐模型，方案 B 使用 faster-whisper 语音识别：

| 语言代码 | 语言 | 对齐模型 | 对齐粒度 | 语音识别模型 |
|---------|------|---------|---------|------------|
| `es` | 西班牙语 | WhisperX 默认 wav2vec2 | 词级 | faster-whisper large-v3 |
| `fr` | 法语 | WhisperX 默认 wav2vec2 | 词级 | faster-whisper large-v3 |
| `ru` | 俄语 | `jonatasgrosman/wav2vec2-large-xlsr-53-russian` | 词级 | faster-whisper large-v3 |
| `ja` | 日语 | WhisperX 默认 wav2vec2 | 字符级 | faster-whisper large-v3 |

**日语特殊处理：** 日语不使用空格分词，方案 A 对日语采用字符级对齐——将文本拆为汉字/假名/外文字符序列，用 SequenceMatcher 做字符级 LCS 匹配。语速异常检测的阈值也从"词/秒"切换为"字/秒"。

**输入格式：** 字幕需为 UTF-8 编码的 SRT 格式，法语、俄语、日语的 Unicode 字符会自动归一化处理。

---

## 方案 A 并行版

生产环境中每次任务通常包含多个音频-SRT 对。原脚本串行处理，GPU 利用率低（wav2vec2 约 1.2GB 显存，RTX 5090 的 32GB 大量闲置）。

并行版（`align_srt_routeA_multi.py`）每个子进程独立加载模型，多个文件同时处理：

```
进程1: [加载 wav2vec2] → 处理 seg001
进程2: [加载 wav2vec2] → 处理 seg002
进程3: [加载 wav2vec2] → 处理 seg003
...                               （5 × 1.2GB ≈ 6GB，显存充足）
```

- 5 个文件并行，总耗时接近最慢单个文件的耗时，加速比约 4–5x
- 自动匹配两种 SRT 命名：`*_tgt.asr.qc.srt`（生产格式）和 `*.asr.qc.srt`（原格式）
- 对齐逻辑全部复用 `align_srt_routeA.py`，无重复代码

---

## 使用指南

### 1. 安装依赖

```bash
# 方案 A 依赖
pip install whisperx silero-vad num2words imageio-ffmpeg

# 方案 B / C 额外依赖
pip install faster-whisper openai
```

### 2. 准备文件

三套方案共享相同的输入格式，支持 `.m4a`、`.mp3`、`.wav`、`.flac` 音频格式。

**格式一（原格式）：**

```
/root/
├── seg001.m4a
├── seg001.asr.qc.srt
├── seg002.mp3
├── seg002.asr.qc.srt
└── ...
```

**格式二（生产格式）：**

```
/root/
├── es_tour_serv_0004_seg001.m4a
├── es_tour_serv_0004_seg001_tgt.asr.qc.srt
├── es_tour_serv_0004_seg002.m4a
├── es_tour_serv_0004_seg002_tgt.asr.qc.srt
└── ...
```

### 3. 运行

**方案 A（推荐首选）：**

```bash
# 默认俄语
python align_srt_routeA.py

# 切换语言
python align_srt_routeA.py --lang es
python align_srt_routeA.py --lang fr
python align_srt_routeA.py --lang ja

# 自定义目录
python align_srt_routeA.py --lang ru --audio-dir /root/audio --output-dir /root/output
python align_srt_routeA.py --lang ja --audio-dir /root/audio --output-dir /root/output
```

输出目录：`/root/aligned_routeA/`

**方案 A 并行版（多个文件时推荐）：**

```bash
# 5 个进程同时跑
python align_srt_routeA_multi.py --lang es --audio-dir /root/input --output-dir /root/aligned_routeA --workers 5

# 调整并行数
python align_srt_routeA_multi.py --lang ru --audio-dir /root/audio --output-dir /root/output --workers 3

# 日语（字符级对齐）
python align_srt_routeA_multi.py --lang ja --audio-dir /root/input --output-dir /root/aligned_routeA --workers 5
```

运行结束自动打印加速比。

**方案 B（口误较多时使用）：**

```bash
# 需先设置 LLM API Key
export LLM_API_KEY="your-key-here"

python align_srt_routeB_llm.py
```

输出目录：`/root/aligned_routeB/`

**方案 C（混合场景）：**

```bash
# 需先设置 LLM API Key
export LLM_API_KEY="your-key-here"

python align_srt_routeC_hybrid.py
```

输出目录：`/root/aligned_routeC/`

**课堂录音转文字：**

```bash
# 将录音转为纯文字稿
python transcribe.py recording1.aac recording2.aac

# 指定输出目录
python transcribe.py recording1.aac --output-dir /root/transcripts
```

---

## docx 转 SRT（日语学院适配）

日语学院的译文常以 **Word 双列表格** 形式提供（第一列中文原文，第二列日文译文），与对齐脚本所需的 SRT 格式不兼容。

### 表格格式要求

| 列 | 内容 |
|---|---|
| 第一列 | 中文原文 |
| 第二列 | 日文译文（需提取的目标文本） |

- 每个单元格内可包含多个自然段落，以换行分隔。
- 脚本自动跳过表头行。

### 自动模糊匹配音频

docx 文件名（如 `zh-ja_tour_muse_0020_seg001.docx`）与音频文件名（如 `ja_tour_muse_0020_seg001_tgt.wav`）常不一致。脚本会自动扫描同目录音频，用模糊匹配确定最佳 SRT 文件名，确保对齐脚本能正确配对。

### 使用示例

```bash
# 基本用法（音频与 docx 同目录）
python docx_to_srt.py --input-dir /root/日语/muse-raw20.21 --output-dir /root/日语/muse-raw20.21

# 指定独立音频目录
python docx_to_srt.py --input-dir /root/docx --output-dir /root/srt --audio-dir /root/audio
```

输出文件名示例：
- `zh-ja_tour_muse_0020_seg001.docx` → `ja_tour_muse_0020_seg001_tgt.asr.qc.srt`

### 完整日语工作流

```bash
# Step 1: docx → SRT
python docx_to_srt.py --input-dir /root/日语/muse-raw20.21 --output-dir /root/日语/muse-raw20.21

# Step 2: SRT + 音频 → 对齐（5 进程并行）
python align_srt_routeA_multi.py --lang ja --audio-dir /root/日语/muse-raw20.21 --output-dir /root/日语/muse-raw20.21/aligned --workers 5
```

每段录音输出一个 `.txt` 文件，根据静音间隔自动分段。

### 4. 工作流建议

1. 优先用方案 A——不需 API、速度最快、对齐质量已验证
2. 文件多时用并行版——`align_srt_routeA_multi.py`，约 4–5x 加速
3. 发现口误/漏读/多读时，切换方案 B——LLM 能理解语义偏差
4. 方案 B 覆盖不全时用方案 C——锚点 + CTC 混合，兼顾容错和精度

---

## 与其他工具的对比

| 工具 | 需要发音词典 | 需要 ASR | 口误处理 | 单段时长限制 |
|------|:----------:|:-------:|:-------:|:----------:|
| MFA（Montreal Forced Aligner） | 是 | 否 | 需手动 | 无 |
| WhisperX 标准流程 | 否 | 是 | 差 | 无 |
| **本方案 A** | 否 | 否 | 不适用 | 无 |
| **本方案 B** | 否 | 是 | LLM 语义裁判 | 无 |
| **本方案 C** | 否 | 是 + 否 | 锚点 + CTC 混合 | 无 |

---

## 实验结果

### 方案 A

| 语言 | 测试规模 | 出错数 | 错误率 |
|------|---------|--------|--------|
| 西班牙语（旧方案：Whisper 转录 + 模糊匹配） | 237 句 | 9 句 | 3.8% |
| 西班牙语（方案 A，无时间戳修正） | 390 句 | 3 句 | 0.8% |
| 西班牙语（方案 A，含时间戳修正） | 390 句 | 0 句 | 0% |
| 俄语（方案 A） | 1028 词 | 12 词 | 1.2% |

测试在 5 段纪录片音频（约 56 分钟）上完成，经人工逐句审听验证。

### 方案 B

在北京博物馆语料库项目（日语 212 句）中验证：

| 方法 | 对齐数 | 成功率 |
|------|--------|--------|
| 仅 SequenceMatcher | 148 / 212 | ~70% |
| SequenceMatcher + LLM | 207 / 212 | 97.6% |

失败的 5 句属于 Whisper 将相邻句子合并转录、边界无法确定的极端情况。

---

## 服务器环境（AutoDL）

```bash
# HF 镜像源（每次新开终端需重新设置）
export HF_ENDPOINT=https://hf-mirror.com

# 模型缓存路径
HF_HOME=/root/autodl-tmp/huggingface
TORCH_HOME=/root/autodl-tmp/torch
```

已缓存模型：
- `wav2vec2-large-xlsr-53-russian`（约 1.26GB，safetensors 格式）
- `faster-whisper large-v3`
- `Silero-VAD`

---

## 局限性

- **方案 A** 依赖文稿与录音高度一致，出现口误、漏句时无法自动纠正，应切换方案 B 或 C
- **方案 B** 依赖大语言模型 API，需要网络连接和 API 费用，且 LLM 裁判并非 100% 可靠，建议人工抽检
- **方案 C** 的效果取决于方案 B 的锚点覆盖率，若 B 完全失败则退化为纯方案 A
- **日语和俄语** 的精度可能略低于西班牙语和法语（日语用字符级策略，俄语用社区模型），建议对齐后抽检

---

## 参考文献

- Bain et al. (2023). *WhisperX: Time-Accurate Speech Transcription of Long-Form Audio.* Interspeech 2023.
- Baevski et al. (2020). *wav2vec 2.0: A Framework for Self-Supervised Learning of Speech Representations.* NeurIPS 2020.
- Conneau et al. (2020). *Unsupervised Cross-lingual Representation Learning at Scale.* ACL 2020.
- McAuliffe et al. (2017). *Montreal Forced Aligner: Trainable Text-Speech Alignment Using Kaldi.* Interspeech 2017.
