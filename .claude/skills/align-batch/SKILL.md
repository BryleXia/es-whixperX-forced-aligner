---
name: align-batch
description: 处理用户给的本地 WAV+SRT 语料目录：扫描命名问题、规范化文件名、压缩音频到 16k 单声道、生成 AutoDL 上传/对齐/打包命令。当用户提到对齐批处理、上传服务器前的语料准备、或直接给一个含 wav/srt 的本地目录路径时使用。支持「无 SRT 先转录」分支：目录里只有 WAV 没有 SRT 时，额外生成 WhisperX 转录命令，转录后再交给 Route A 精对齐。
---

# align-batch：语料批处理半自动流程

用户会给你一个包含 WAV+SRT 文件的本地目录，你需要完成以下步骤：

> **流程分支：** 目录里每个 WAV 都有配对 SRT → 走标准流程（Step 1→4）。目录里**只有 WAV 没有 SRT** → 走「先转录再对齐」分支（Step 1 扫描后进入 Step 1.5，转录命令并入 Step 4）。两种分支的本地预处理（重命名/压缩）完全一样，区别只在 Step 4 多一条 WhisperX 转录指令。

## Step 0：解压 zip 文件（如果有）

扫描用户指定目录，如果存在 `.zip` 文件：
1. 用 Python `zipfile` 模块解压到同级目录
2. 解压完成后，对每个解压出的子文件夹继续执行后续步骤
3. 如果目录里没有 zip 文件，直接进入 Step 1

## Step 1：扫描目录，列出问题

读取用户指定目录下的所有文件，检查以下命名问题：

1. **WAV 文件名有多余空格**（如 `*_tgt .wav`）→ 需去掉空格
2. **WAV 扩展名大写**（如 `*.WAV`）→ 需改为小写 `.wav`
3. **SRT 下划线误用**（如 `*_tgt_asr.qc.srt`）→ 需改为 `*_tgt.asr.qc.srt`
4. **编号不一致**（如 `00013` vs `0013`）→ WAV 和 SRT 的编号必须匹配，向用户确认正确编号
5. **WAV/SRT 配对缺失** → 列出找不到配对的文件
6. **WAV/SRT 前缀不一致**（如 WAV 是 `es_econ_0002_*` 但 SRT 是 `es_conf_econ_0002_*`）→ 统一为与 WAV 一致的前缀

同时检查 WAV 音频参数（采样率、声道数、比特率），如果不是 16kHz 单声道，报告给用户并建议压缩。

**注意：meta.json 里的 `sample_rate` 字段经常不可信**（实测出现过标 16kHz 实际是 48kHz 立体声）。必须用 Python `wave` 模块读 WAV 头实测，不要信 meta.json。

把发现的问题逐条报告给用户，等用户确认后再执行重命名和压缩。

## Step 1.5：判断是否走「先转录」分支

统计 WAV 和 SRT 的配对情况：

- **每个 WAV 都有配对 SRT** → 标准流程，直接跳到 Step 2
- **目录里只有 WAV，没有任何 SRT**（或部分 WAV 缺 SRT）→ 走「先转录再对齐」分支：
  1. 明确告诉用户：「检测到 N 个 WAV 没有参考 SRT，Route A 需要正确文本才能对齐，需先用 WhisperX 跑出初稿 SRT（文本来自 ASR、时间戳暂不精确），再交给 Route A 精对齐」
  2. 本地预处理（重命名/压缩）照常走 Step 2、Step 3
  3. Step 4 的服务器命令里，在 Route A 对齐之前插入 WhisperX 转录步骤（见 Step 4 的转录分支）

这条分支不影响本地流程，只是 Step 4 多一条转录指令。转录和精对齐都在服务器上做，本地无需准备 SRT。

## Step 2：执行重命名

用 `mv` 命令修复所有命名问题，然后用 `ls` 验证结果，展示最终的 WAV-SRT 配对清单。

## Step 3：音频压缩（如果需要）

whisperx.load_audio() 内部用 FFmpeg 强制重采样到 16kHz 单声道，48kHz 双声道数据在进入模型前就被丢弃，上传高码率音频完全浪费带宽。

如果 WAV 不是 16kHz/1ch/16bit，则执行压缩：

1. 在目录同级创建输出文件夹，命名规则：原目录名去掉空格，加上 `_16k` 后缀（如 `经济0013 0014` → `经济0013_0014_16k`）
2. 用 Python（scipy + numpy）将所有 WAV 转为 16kHz 单声道 16bit：
   ```python
   import scipy.io.wavfile as wavfile
   import numpy as np
   # 读取 → 双声道取均值 → 重采样到16kHz → 写入
   sr, data = wavfile.read(inp)
   if data.ndim == 2:
       data = data.mean(axis=1).astype(np.int16)
   if sr != 16000:
       ratio = 16000 / sr
       new_len = int(len(data) * ratio)
       data = np.interp(
           np.linspace(0, len(data)-1, new_len),
           np.arange(len(data)),
           data
       ).astype(np.int16)
   wavfile.write(out, 16000, data)
   ```
3. 将 SRT 文件也复制到输出文件夹
4. 报告压缩结果：原总大小 → 压缩后总大小，压缩比例

注意：
- 用户机器可能没有 ffmpeg，优先用 scipy/numpy 方案
- Python 路径：`E:/apps/PYTHON 3.13.5/python.exe`
- 保留原始文件不动，压缩后的文件放在新目录

## Step 4：生成服务器命令

用户确认文件准备好后，根据文件数量生成完整的命令序列：

### 上传提示
提醒用户将**压缩后的目录**（带 `_16k` 后缀的）上传到服务器。

### 转录分支（仅 Step 1.5 判定走「先转录」时执行）

如果目录原本没有 SRT，先在服务器上用 WhisperX 跑出参考 SRT，再做 Route A 对齐。

**先设 HF 环境（每次新终端，单行）：**

```
export HF_ENDPOINT=https://hf-mirror.com && export HF_HOME=/root/autodl-tmp/huggingface && export TORCH_HOME=/root/autodl-tmp/torch && export HF_HUB_OFFLINE=1
```

**WhisperX 转录（large-v3 已缓存，输出 SRT）：**

单文件：
```
whisperx /root/<目录>/<文件名>.wav --model large-v3 --language es --output_format srt --output_dir /root/<目录>/
```

多文件（一次性把所有 wav 列在后面）：
```
whisperx /root/<目录>/<文件1>.wav /root/<目录>/<文件2>.wav --model large-v3 --language es --output_format srt --output_dir /root/<目录>/
```

`--language` 跟着 `--lang` 走（es/fr/ru/ja）。

**重命名为 Route A 识别格式（`*.asr.qc.srt`）：**

```
for f in /root/<目录>/*.srt; do mv "$f" "${f%.srt}.asr.qc.srt"; done
```

转录完成后，目录里每个 wav 都有了配对的 `*.asr.qc.srt`，接着走下面的 Route A 对齐。

### 运行对齐
```
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python align_srt_routeA_multi.py --lang es --audio-dir <服务器目录路径> --output-dir <服务器目录路径>/aligned_routeA --workers <文件数>
```

参数说明：
- `--lang`：默认 `es`（西语），如果用户说是法语/俄语/日语则切换
- `--audio-dir`：服务器上音频+SRT 所在目录
- `--output-dir`：输出目录
- `--workers`：等于音频文件数量（但不超过4）

### 打包结果
```
cd <服务器目录路径的父目录> && zip -r aligned_routeA.zip aligned_routeA/
```

## 注意事项

- 脚本 `align_srt_routeA_multi.py` 的 `find_srt_for_audio()` 支持两种 SRT 命名格式：`*_tgt.asr.qc.srt` 和 `*.asr.qc.srt`，WAV 文件名必须精确匹配才能配对
- 不要自作主张执行重命名或压缩，先报告问题等用户确认
- workers 数量建议不超过 4（wav2vec2 每个进程约 15-20GB 显存）
- **OOM 恢复**：如果部分文件因 CUDA out of memory 失败，用 `--workers 1` 重跑失败文件即可，已成功的结果会被覆盖但不会丢失
- 如果根目录有其他无关音频，建议用户放到子目录避免误处理
- AutoDL 服务器每次新终端需先设置 HF 镜像：`export HF_ENDPOINT=https://hf-mirror.com`
- **WhisperX 转录必须加离线环境变量**：`HF_HOME=/root/autodl-tmp/huggingface` + `HF_HUB_OFFLINE=1`，否则会因网络拉模型报 `LocalEntryNotFoundError`（即使镜像已设也不够）
- **先转录分支的产物是「文本对、时间戳不准」的 SRT**，正好喂给 Route A 做精对齐——Route A 不在乎初稿时间戳，只用文本。转录和精对齐的角色分工：WhisperX 出文本，wav2vec2 出精确时间戳
- **服务器指令永远不要换行**，每条命令必须是完整的单行，方便用户直接复制粘贴
