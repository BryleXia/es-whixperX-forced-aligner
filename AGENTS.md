# 项目结构指南

## 源代码（根目录）
- `align_srt_routeA.py` — 方案 A 核心脚本（CTC 强制对齐）
- `align_srt_routeA_multi.py` — 方案 A 多进程并行版
- `align_srt_routeB_llm.py` — 方案 B（ASR + LLM 语义对齐）
- `align_srt_routeC_hybrid.py` — 方案 C（锚点 + CTC 混合对齐）
- `docx_to_srt.py` — docx 双列表格转 SRT（日语学院适配）
- `transcribe.py` — 课堂录音转文字
- `diagnose_routeA_debug.py` — 方案 A 诊断工具

## 数据目录（不要读取！）
以下目录包含音频/SRT 测试数据，**禁止读取**，会浪费大量 token：
- `西语/` — 西班牙语生产数据（11GB）
- `法语/` — 法语数据（空）
- `俄语测试/` — 俄语测试数据（426MB）
- `日语/` — 日语数据（344MB）
- `debug/` — 调试输出和旧脚本结果（785MB）
- `样本数据/` — 示例数据（51MB）
- `archive/` — 历史归档（577MB）

**警告：** 这些目录包含大量音频文件（.m4a, .wav, .WAV）和字幕文件（.srt），读取它们会严重浪费 token。除非用户明确要求处理某个数据目录，否则不要扫描这些目录的内容。

## Skills
- `.claude/skills/align-batch/` — 语料批处理全自动流程（WAV+SRT 整理、压缩 16k、SSH 直连 AutoDL 上传/转录/对齐/下载；SSH 不可用时降级为生成手动命令）

## 文档
- `README.md` — 完整的项目文档和使用指南（包含三套方案的原理、使用方法、实验结果）

## 语言支持
当前支持：西班牙语 (es)、法语 (fr)、俄语 (ru)、日语 (ja)

## 工作流
1. 用户调用 `/align-batch` skill 处理新数据
2. 脚本通过 `--lang` 参数切换语言
3. 生产环境在 AutoDL 服务器上运行（GPU 加速）
