"""Resume and validate the Qwen3-TTS Base model used for voice cloning."""

import os
import time
from pathlib import Path

# The Xet transport can remain connected without writing data on some Windows
# proxy setups. Force the regular HTTPS downloader, which supports resuming.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

from huggingface_hub import snapshot_download


REPO_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
RUNTIME_ROOT = Path(os.environ.get("VOICEBRIDGE_RUNTIME_ROOT", r"D:\VoiceBridgeRuntime"))
MODEL_DIR = RUNTIME_ROOT / "models" / "models--Qwen--Qwen3-TTS-12Hz-1.7B-Base"
MODEL_FILE = MODEL_DIR / "model.safetensors"
SPEECH_TOKENIZER_FILE = MODEL_DIR / "speech_tokenizer" / "model.safetensors"
REQUIRED_FILES = tuple(
    MODEL_DIR / relative_path
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
)


MODEL_DIR.mkdir(parents=True, exist_ok=True)

last_error = None
for attempt in range(6):
    if all(item.is_file() and item.stat().st_size > 0 for item in REQUIRED_FILES):
        break
    try:
        print(f"Downloading Qwen3-TTS Base (resume attempt {attempt + 1}/6)...", flush=True)
        missing_patterns = [
            item.relative_to(MODEL_DIR).as_posix()
            for item in REQUIRED_FILES
            if not item.is_file() or item.stat().st_size == 0
        ]
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(MODEL_DIR),
            local_files_only=False,
            max_workers=1,
            allow_patterns=missing_patterns,
            ignore_patterns=["*.md", ".git*"],
        )
    except Exception as exc:
        last_error = exc
        print(f"Download interrupted: {exc}", flush=True)
        if attempt < 5:
            time.sleep(min(30, 2 ** attempt))

missing = [str(item) for item in REQUIRED_FILES if not item.is_file() or item.stat().st_size == 0]
if missing:
    raise SystemExit(f"Qwen3-TTS model is incomplete: {', '.join(missing)}. Last error: {last_error}")

print("Qwen3-TTS files are present. Loading model on CUDA...", flush=True)
import torch
from qwen_tts import Qwen3TTSModel

model = Qwen3TTSModel.from_pretrained(
    str(MODEL_DIR),
    device_map="cuda:0",
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
    attn_implementation=None,
)
print(f"Qwen3-TTS CUDA load passed: {MODEL_DIR}", flush=True)
del model
torch.cuda.empty_cache()
