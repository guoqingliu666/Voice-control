# Voice-control：本地视频翻译与配音

这是一个 Windows 桌面版/网页版工具：导入已经下载好的视频或音频，自动完成语音识别、中文/英文互译、配音和双语字幕。默认使用本地模型，支持 NVIDIA CUDA；不需要把音视频上传到第三方服务。

## 最快开始

1. 下载 Release 中的 `Voice-control-V1.0-Windows.zip`，完整解压到一个有足够空间的目录（建议 D 盘）。不要只在压缩包里直接运行。
2. 双击 `安装环境.bat`。首次安装会把程序环境放在 `D:\VoiceBridgeRuntime`，并下载 Python 依赖；这一步可能需要几十分钟和数 GB 磁盘空间。
3. 安装结束后双击 `运行自检.bat`。所有必需项目显示“通过”后，再双击 `启动桌面版.bat`。
4. 需要浏览器界面时双击 `启动网页版.bat`，然后打开 `http://127.0.0.1:7860`。
5. 在界面中选择视频，确认源语言和目标语言，点击开始。输出文件默认在解压目录的 `output` 文件夹。

## 电脑要求

- Windows 10/11 64 位。
- NVIDIA 显卡建议显存 8 GB 以上；RTX 5060 Ti 16 GB 已实测通过。没有 NVIDIA 显卡也可以运行，但速度会明显变慢。
- 至少 30 GB 可用空间；模型和缓存默认放在 `D:\VoiceBridgeModels`、`D:\VoiceBridgeCache`，不会主动写入 C 盘。
- 首次使用需要网络下载依赖和模型。后续使用可以离线运行已经下载完成的模型。

## 常见问题

**双击后提示找不到 uv**：请重新下载完整 ZIP（其中包含 `tools\uv.exe`），不要只下载源代码；也可以从 https://docs.astral.sh/uv/ 安装 uv 后重试。

**提示找不到 FFmpeg 或 SoX**：安装 FFmpeg 并把其 `bin` 目录加入 PATH；SoX 可在管理员 PowerShell 执行 `winget install --id ChrisBagwell.SoX --exact`。安装后重新打开启动脚本。

**模型尚未下载**：这是正常现象。先运行自检，再处理一段短视频，程序会自动续传缺少的模型。不要删除 `D:\VoiceBridgeModels`。

**程序窗口没有反应**：先关闭旧窗口，再运行 `运行自检.bat`；如果仍失败，请把自检窗口中从第一行到最后一行的文字保存下来。

## 目录说明

- `启动桌面版.bat`：启动 Qt 桌面界面。
- `启动网页版.bat`：启动本机浏览器界面。
- `运行自检.bat`：检查 Python、CUDA、FFmpeg、SoX、模型和关键模块。
- `upstream_pyvideotrans`：上游开源程序源代码。
- `D:\VoiceBridgeRuntime`：Python 运行环境和程序副本。
- `D:\VoiceBridgeModels`：本地模型缓存。

## 许可

本项目包含上游 pyVideoTrans 代码及多个第三方模型/库，具体许可见 `THIRD_PARTY.md`、`upstream_pyvideotrans\LICENSE` 和 `upstream_pyvideotrans\law.txt`。模型的使用须遵守各自模型仓库许可；发布视频前请确认你拥有原视频和声音的使用权。

## 已验证范围

本版本在 Windows + Python 3.10 + CUDA 12.8 + RTX 5060 Ti 上完成了桌面启动、网页版启动、关键模块导入和本地模型自检。不同显卡、驱动、网络或系统 PATH 可能需要按上面的提示补装组件。
