"""Resume and validate the default faster-whisper model download."""

import os
import time
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ID = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
RUNTIME_ROOT = Path(os.environ.get("VOICEBRIDGE_RUNTIME_ROOT", r"D:\VoiceBridgeRuntime"))
MODEL_DIR = RUNTIME_ROOT / "models" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
REQUIRED = {
    "model.bin",
    "config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
}


def complete() -> bool:
    return all((MODEL_DIR / name).is_file() and (MODEL_DIR / name).stat().st_size > 0 for name in REQUIRED)


MODEL_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

last_error = None
for attempt in range(6):
    if complete():
        break
    try:
        print(f"Downloading Whisper model (resume attempt {attempt + 1}/6)...", flush=True)
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(MODEL_DIR),
            local_files_only=False,
            max_workers=1,
            allow_patterns=sorted(REQUIRED),
        )
    except Exception as exc:
        last_error = exc
        print(f"Download interrupted: {exc}", flush=True)
        if attempt < 5:
            time.sleep(min(30, 2 ** attempt))

if not complete():
    missing = [name for name in sorted(REQUIRED) if not (MODEL_DIR / name).is_file()]
    raise SystemExit(f"Whisper model is incomplete. Missing: {missing}. Last error: {last_error}")

print("All Whisper files are present. Loading model on CUDA...", flush=True)
from faster_whisper import WhisperModel

model = WhisperModel(str(MODEL_DIR), device="cuda", compute_type="int8")
print(f"Whisper CUDA load passed: {MODEL_DIR}", flush=True)
del model
