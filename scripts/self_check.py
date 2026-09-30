import importlib
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.environ.get("VOICEBRIDGE_RUNTIME_ROOT", PROJECT_ROOT / "upstream_pyvideotrans"))
sys.path.insert(0, str(RUNTIME_ROOT))


def ok(message: str) -> None:
    print(f"[通过] {message}")


def fail(message: str) -> None:
    print(f"[失败] {message}")
    raise SystemExit(1)


for module_name in ("torch", "qwen_asr", "qwen_tts", "PySide6"):
    try:
        importlib.import_module(module_name)
        ok(f"可导入 {module_name}")
    except Exception as exc:
        fail(f"无法导入 {module_name}: {exc}")

import torch

if not torch.cuda.is_available():
    fail("PyTorch 没有检测到 CUDA；可以用 CPU，但速度会非常慢")
ok(f"CUDA {torch.version.cuda} / {torch.cuda.get_device_name(0)}")

from videotrans import translator, tts

if translator.OPUS_MT_INDEX != 26:
    fail("OPUS-MT 渠道编号不正确")
if translator.HYMT2_INDEX != 3:
    fail("Hy-MT2 渠道编号不正确")
if tts.QWEN3LOCAL_TTS != 1:
    fail("Qwen3-TTS 渠道编号不正确")
ok("本地 Hy-MT2 1.8B 翻译渠道已注册（OPUS-MT 保留为轻量备用）")
ok("本地 Qwen3-TTS 音色克隆渠道已注册")

model_files = {
    "Hy-MT2 1.8B": [
        RUNTIME_ROOT / "models" / "models--tencent--Hy-MT2-1.8B" / relative_path
        for relative_path in (
            "config.json",
            "generation_config.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
        )
    ],
    "Qwen3-ASR 1.7B": [
        RUNTIME_ROOT / "models" / "models--Qwen--Qwen3-ASR-1.7B" / relative_path
        for relative_path in (
            "config.json",
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
            "model.safetensors.index.json",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.json",
        )
    ],
    "Qwen3-TTS 1.7B Base": [
        RUNTIME_ROOT / "models" / "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base" / relative_path
        for relative_path in (
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model.safetensors",
            "preprocessor_config.json",
            "speech_tokenizer/config.json",
            "speech_tokenizer/configuration.json",
            "speech_tokenizer/model.safetensors",
            "speech_tokenizer/preprocessor_config.json",
            "tokenizer_config.json",
            "vocab.json",
        )
    ],
}
missing_models = []
for model_name, required_files in model_files.items():
    if all(item.is_file() and item.stat().st_size > 0 for item in required_files):
        total_size = sum(item.stat().st_size for item in required_files)
        ok(f"{model_name} 权重已缓存（{total_size / 1024 ** 3:.2f} GiB）")
    else:
        missing_models.append(model_name)
        missing_files = [str(item) for item in required_files if not item.is_file() or item.stat().st_size == 0]
        print(f"[提示] {model_name} 权重尚未完整下载：{', '.join(missing_files)}")

result = subprocess.run(
    [sys.executable, "cli.py", "--help"],
    cwd=RUNTIME_ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
if result.returncode != 0:
    fail(f"CLI 自检失败：{result.stderr[-500:]}")
ok("pyVideoTrans CLI 可启动")

try:
    rubberband = subprocess.run(
        ["rubberband", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
except FileNotFoundError:
    rubberband = None
if rubberband and rubberband.returncode == 0:
    ok("Rubber Band 高质量语音时长对齐可用")
else:
    print("[提示] Rubber Band 不可用，将退回较低质量的 FFmpeg 变速。")

nvenc = subprocess.run(
    [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=size=64x64:rate=1",
        "-t", "0.1", "-c:v", "h264_nvenc", "-f", "null", "-",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
if nvenc.returncode == 0:
    ok("FFmpeg NVENC 硬件编码可用")
else:
    print("[提示] FFmpeg NVENC 当前不可用，成品视频会自动改用软件编码；CUDA 模型加速不受影响。")
if missing_models:
    print("\n自检完成。尚缺少的模型会在首次处理视频时自动续传：" + "、".join(missing_models))
else:
    print("\n自检完成。Hy-MT2 1.8B、Qwen3-ASR 1.7B 和 Qwen3-TTS 默认模型均已缓存。")
