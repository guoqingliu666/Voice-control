"""Verify the complete Qwen3-ASR 1.7B snapshot and load it on CUDA."""

import os
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import torch
from qwen_asr import Qwen3ASRModel


RUNTIME_ROOT = Path(os.environ.get("VOICEBRIDGE_RUNTIME_ROOT", r"D:\VoiceBridgeRuntime"))
MODEL_DIR = RUNTIME_ROOT / "models" / "models--Qwen--Qwen3-ASR-1.7B"
REQUIRED_FILES = tuple(
    MODEL_DIR / name
    for name in (
        "config.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
        "model.safetensors.index.json",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
    )
)

missing = [str(item) for item in REQUIRED_FILES if not item.is_file() or item.stat().st_size == 0]
if missing:
    raise SystemExit("Qwen3-ASR snapshot is incomplete: " + ", ".join(missing))

print("Qwen3-ASR files are present. Loading 1.7B model on CUDA...", flush=True)
model = Qwen3ASRModel.from_pretrained(
    str(MODEL_DIR),
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
    device_map="cuda:0",
    max_inference_batch_size=8,
    max_new_tokens=2048,
)
print(f"Qwen3-ASR CUDA load passed: {MODEL_DIR}", flush=True)
del model
torch.cuda.empty_cache()
