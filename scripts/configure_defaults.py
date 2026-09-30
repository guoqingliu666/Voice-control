"""Keep VoiceBridge on the locally verified GPU pipeline."""

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.environ.get("VOICEBRIDGE_RUNTIME_ROOT", PROJECT_ROOT / "upstream_pyvideotrans"))
MARKER = PROJECT_ROOT / ".voicebridge_initialized"

sys.path.insert(0, str(RUNTIME_ROOT))

from videotrans.configure.config import params, settings  # noqa: E402

recommended = {
        "source_language": "英语",
        "target_language": "简体中文",
        "translate_type": 3,
        "subtitle_type": 3,
        "tts_type": 1,
        "voice_role": "clone",
        "recogn_type": 2,
        "model_name": "1.7B",
        "is_cuda": True,
        "is_separate": True,
        "embed_bgm": True,
        "remove_noise": False,
        "enable_diariz": False,
        "fix_punc": 0,
        "stt_fix_punc": 0,
        "recogn2pass": False,
        "voice_autorate": True,
        "video_autorate": False,
        "align_sub_audio": True,
        "rephrase": 0,
        "clear_cache": True,
        "output_dir": (PROJECT_ROOT / "output").as_posix(),
    }

# Preserve the user's chosen direction after the first launch, but always repair
# model/channel selections. The UI exposes many optional providers whose models
# are not part of this deployment.
if MARKER.exists() and "--force" not in sys.argv:
    recommended.pop("source_language")
    recommended.pop("target_language")

(PROJECT_ROOT / "output").mkdir(parents=True, exist_ok=True)
params.save(recommended)
settings.save({"max_audio_speed_rate": 1.2})
MARKER.write_text("VoiceBridge defaults initialized.\n", encoding="utf-8")
print("已固定为 Qwen3-ASR 1.7B + Hy-MT2 1.8B + Qwen3-TTS 1.7B Base 固定音色流水线（最大变速 1.2 倍）。")
