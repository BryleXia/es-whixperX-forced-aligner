---
name: align-batch
description: 处理用户给的本地 WAV+SRT 语料目录：扫描命名问题、规范化文件名、压缩音频到 16k 单声道，然后通过 SSH 直连 AutoDL 服务器自动完成上传/WhisperX 转录/Route A 对齐/打包/下载（全自动模式），或生成手动命令（手动模式）。当用户提到对齐批处理、上传服务器前的语料准备、或直接给一个含 wav/srt 的本地目录路径时使用。支持「无 SRT 先转录」分支：目录里只有 WAV 没有 SRT 时，额外用 WhisperX 转录，再交给 Route A 精对齐。
---

# align-batch：语料批处理全自动流程（SSH 直连）

用户会给你一个包含 WAV+SRT 文件的本地目录。核心流程：本地预处理（扫描/重命名/压缩）→ **SSH 直连服务器** → 上传 → 对齐 → 打包 → 下载回本地。

> **流程分支：** 目录里每个 WAV 都有配对 SRT → 标准流程（Step 1→4）。目录里**只有 WAV 没有 SRT** → 走「先转录再对齐」分支（Step 4 里在 Route A 之前插入 WhisperX 转录）。

## 执行模式选择

- **自动模式（推荐）**：SSH 已连通时，Step 4 直接代用户操作服务器，全程无需用户复制粘贴
- **手动模式**：SSH 未配置/用户明确要命令/服务器不可达时，降级为生成单行命令让用户粘贴（保留原半自动内容，见「手动模式」一节）

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
  3. Step 4 里在 Route A 对齐之前插入 WhisperX 转录步骤

这条分支不影响本地流程。转录和精对齐都在服务器上做，本地无需准备 SRT。

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

## Step 4：SSH 直连自动化（自动模式）

### 4.1 连接信息

向用户要 AutoDL 实例的 SSH 连接信息（AutoDL 控制台 → 实例详情 → SSH 指令）：
- 地址：`connect.<region>.seetacloud.com`
- 端口：如 `13920`
- 密码：仅首次配置需要（如果公钥未部署）

**检查/部署免密登录：**

```bash
# 免密测试（BatchMode=yes：不提示密码，能通说明公钥已生效）
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <端口> root@<地址> "echo PASSWORDLESS_OK"
```

不通时用 Python paramiko（本地 Python：`E:/apps/PYTHON 3.13.5/python.exe`，需 `pip install paramiko`）密码登录部署公钥：

```python
import paramiko, os
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("<地址>", port=<端口>, username="root", password="<密码>", timeout=30)
pub = open(os.path.expanduser("~/.ssh/id_ed25519.pub")).read().strip()
cmd = (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
       f"grep -qF '{pub.split()[1]}' ~/.ssh/authorized_keys || echo '{pub}' >> ~/.ssh/authorized_keys")
ssh.exec_command(cmd)
ssh.close()
```

> **安全：含密码的临时脚本用后立即删除，绝不提交 git。**

### 4.2 服务器环境检查（幂等）

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <端口> root@<地址> "ls /root/align_srt_routeA_multi.py && ls /root/miniconda3/bin/python && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"
```

- 服务器 Python 在 `/root/miniconda3/bin/python`（PATH 里没有 `python`，必须全路径）
- 对齐脚本在 `/root/align_srt_routeA_multi.py`；缺失则从本地 scp 上传
- **幂等检查：服务器 `/root/<目录>_16k/` 若已存在（含历史结果），先向用户确认是跳过还是覆盖重跑**（实测出现过目录和结果都在服务器上的情况，别重复跑）

### 4.3 上传压缩目录

```bash
scp -o BatchMode=yes -i ~/.ssh/id_ed25519 -P <端口> -r "E:\...\<目录>_16k" root@<地址>:/root/
```

### 4.4 转录分支（仅 Step 1.5 判定走「先转录」时执行）

服务器上先跑 WhisperX 出初稿 SRT（large-v3 已缓存）：

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <端口> root@<地址> "export HF_ENDPOINT=https://hf-mirror.com && export HF_HOME=/root/autodl-tmp/huggingface && export TORCH_HOME=/root/autodl-tmp/torch && export HF_HUB_OFFLINE=1 && cd /root/<目录>_16k && whisperx *.wav --model large-v3 --language <lang> --output_format srt --output_dir /root/<目录>_16k/ && for f in *.srt; do mv \"\$f\" \"\${f%.srt}.asr.qc.srt\"; done"
```

`--language` 跟着 `--lang` 走（es/fr/ru/ja）。

### 4.5 运行 Route A 对齐

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <端口> root@<地址> "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True /root/miniconda3/bin/python /root/align_srt_routeA_multi.py --lang <lang> --audio-dir /root/<目录>_16k --output-dir /root/<目录>_16k/aligned_routeA --workers <N>"
```

参数说明：
- `--lang`：默认 `es`（西语），法语/俄语/日语则切换
- `--workers`：等于 WAV 文件数量，但不超过 4（wav2vec2 每进程约 15-20GB 显存；实测 85GB 显存的 RTX 6000D 上 4 workers 正常）
- 对齐耗时：长音频单文件约 1-2 分钟，注意 ssh 超时用后台运行 + 轮询或 `nohup ... &` + `tail` 日志

**长任务处理：** 对齐可能跑 10-30 分钟。用后台 + 轮询：
```bash
# 启动（输出到日志）
ssh ... "cd /root/<目录>_16k && nohup /root/miniconda3/bin/python /root/align_srt_routeA_multi.py --lang <lang> --audio-dir . --output-dir aligned_routeA --workers <N> > align.log 2>&1 & echo STARTED"
# 轮询进度（每 60-120s 一次）
ssh ... "grep -E 'error|Error|Traceback|已完成|失败|100%|Finished' /root/<目录>_16k/align.log | tail -5; ls /root/<目录>_16k/aligned_routeA/ | wc -l"
```

### 4.6 打包

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519 -p <端口> root@<地址> "cd /root && zip -r <目录>_16k_aligned_routeA.zip <目录>_16k/aligned_routeA/"
```

### 4.7 下载结果回本地

```bash
scp -o BatchMode=yes -i ~/.ssh/id_ed25519 -P <端口> root@<地址>:/root/<目录>_16k_aligned_routeA.zip "E:\...\<目录>_16k_aligned_routeA.zip"
```

**每一条 SSH 命令都是完整单行**（PowerShell 子进程调用注意：`encoding="utf-8", errors="replace"`，否则 Windows 默认 gbk 解码中文输出会报 UnicodeDecodeError）。

## Step 5：新实例处理

用户开新实例（克隆或新建）时：

- **必须重新发**：SSH 地址 + 端口（每次实例都不同）
- **克隆实例**：公钥自动保留（整盘复制），直接免密
- **新建实例**：公钥丢失，需要密码做一次 4.1 的公钥部署
- **一劳永逸建议**（告诉用户）：在 AutoDL 控制台 → 实例 → 安全 → SSH 密钥 里添加公钥，之后所有新建/克隆实例自动带上，用户永远只需发地址+端口
- 新实例的其他环境（脚本/模型/数据）同样需要确认：克隆的都有；新建的需重传脚本和模型（模型走 autodl-tmp 缓存）

## 手动模式（SSH 未配置/用户要命令）

保持原流程：生成完整单行命令序列让用户复制粘贴。

**上传提示**：提醒用户将**压缩后的目录**（带 `_16k` 后缀的）上传到服务器。

**HF 环境（每次新终端，单行）：**

```
export HF_ENDPOINT=https://hf-mirror.com && export HF_HOME=/root/autodl-tmp/huggingface && export TORCH_HOME=/root/autodl-tmp/torch && export HF_HUB_OFFLINE=1
```

**WhisperX 转录（仅先转录分支）：**

单文件：
```
whisperx /root/<目录>/<文件名>.wav --model large-v3 --language es --output_format srt --output_dir /root/<目录>/
```

多文件：
```
whisperx /root/<目录>/<文件1>.wav /root/<目录>/<文件2>.wav --model large-v3 --language es --output_format srt --output_dir /root/<目录>/
```

**重命名为 Route A 识别格式：**

```
for f in /root/<目录>/*.srt; do mv "$f" "${f%.srt}.asr.qc.srt"; done
```

**运行对齐：**

```
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python align_srt_routeA_multi.py --lang es --audio-dir <服务器目录路径> --output-dir <服务器目录路径>/aligned_routeA --workers <文件数>
```

**打包结果：**

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
- **服务器指令永远不要换行**，每条命令必须是完整的单行
- 服务器上可能已有同名目录/结果（历史批次），先检查再跑，别重复
